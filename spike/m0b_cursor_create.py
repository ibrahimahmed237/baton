#!/usr/bin/env python3
"""M0b spike: create a Cursor chat from outside, and remove it again.

Throwaway code. Cursor keeps what a chat displays (one record per message) apart
from what its agent knows (an encoded state that points at encrypted blobs).
Only the first can be written from outside. This clones the display records of
an existing throwaway chat under a new ID with new text and an empty agent
state, to see whether the app lists it and shows the messages.

Run only while Cursor is closed. `remove` deletes exactly the rows `create` added.

    m0b_cursor_create.py create --like CHAT_ID --codeword W
    m0b_cursor_create.py remove
"""
import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import m0_append as base  # noqa: E402

DB = os.path.expanduser("~/Library/Application Support/Cursor/User/globalStorage/state.vscdb")
NAME = "Baton test (safe to delete)"


def running():
    listing = subprocess.run(["ps", "-axo", "command="], capture_output=True, text=True).stdout
    return "/Applications/Cursor.app/Contents/MacOS/Cursor" in (line.strip() for line in listing.splitlines())


def rich_text(text):
    leaf = {"detail": 0, "format": 0, "mode": "normal", "style": "", "text": text, "type": "text", "version": 1}
    paragraph = {"children": [leaf], "direction": "ltr", "format": "", "indent": 0, "type": "paragraph", "version": 1}
    return json.dumps({"root": {"children": [paragraph], "direction": "ltr", "format": "", "indent": 0,
                                "type": "root", "version": 1}})


def do_create(args):
    if running():
        sys.exit("Cursor is running; it keeps chats in memory and would write over this. Quit Cursor first.")
    db = sqlite3.connect(DB, timeout=20)

    def get(key):
        return json.loads(db.execute("select value from cursorDiskKV where key=?", (key,)).fetchone()[0])

    data = get("composerData:" + args.like)
    header = db.execute("select * from composerHeaders where composerId=?", (args.like,)).fetchone()
    heads = data["fullConversationHeadersOnly"]
    sources = [get("bubbleId:%s:%s" % (args.like, heads[0]["bubbleId"])),
               get("bubbleId:%s:%s" % (args.like, heads[-1]["bubbleId"]))]
    empty = db.execute("select value from cursorDiskKV where key like 'composerData:%'"
                       " and value like '%\"fullConversationHeadersOnly\":[]%' limit 1").fetchone()
    empty_state = json.loads(empty[0]).get("conversationState", "~") if empty else "~"

    new, now = str(uuid.uuid4()), int(time.time() * 1000)
    texts = ["[Baton spike: this chat was created from outside the app] Remember this codeword: %s." % args.codeword,
             "Noted. The codeword is %s." % args.codeword]
    rows, new_heads = {}, []
    for source, head, text, at in zip(sources, (heads[0], heads[-1]), texts, (now, now + 2000)):
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(at / 1000))
        bubble = dict(source, bubbleId=str(uuid.uuid4()), text=text, createdAt=stamp)
        bubble.pop("checkpointId", None)
        if "richText" in bubble:
            bubble["richText"] = rich_text(text)
        rows["bubbleId:%s:%s" % (new, bubble["bubbleId"])] = bubble
        grouping = dict(head.get("grouping", {}), textPreview=text[:80])
        new_heads.append(dict(head, bubbleId=bubble["bubbleId"], createdAt=stamp, grouping=grouping))
    data.update(composerId=new, name=NAME, createdAt=now, lastUpdatedAt=now + 2000,
                fullConversationHeadersOnly=new_heads, conversationState=empty_state,
                latestChatGenerationUUID=None, generatingBubbleIds=[], subtitle=texts[1][:60])
    for key in ("contextTokensUsed", "contextUsagePercent"):
        if key in data:
            data[key] = 0
    rows["composerData:" + new] = data
    value = dict(json.loads(header[8]), composerId=new, name=NAME, createdAt=now, lastUpdatedAt=now + 2000,
                 subtitle=texts[1][:60])
    with db:
        for key, row in rows.items():
            db.execute("insert into cursorDiskKV(key, value) values(?,?)", (key, json.dumps(row)))
        db.execute("insert into composerHeaders values(?,?,?,?,?,?,?,?,?,?)",
                   (new, header[1], now, now + 2000, 0, 0, now + 2000, None, json.dumps(value), header[9]))
    db.close()
    base.journal({"side": "cursor", "kind": "create", "chat": new, "keys": list(rows)})
    print(json.dumps({"created": True, "chat": new, "rows": len(rows) + 1}))


def do_remove(_args):
    if running():
        sys.exit("Cursor is running; quit it first.")
    entries = base.read_jsonl(base.JOURNAL)
    db = sqlite3.connect(DB, timeout=20)
    for entry in entries:
        if entry.get("side") != "cursor" or entry.get("kind") != "create" or entry.get("removed"):
            continue
        with db:
            # Also what Cursor itself added for this chat after it was created.
            db.execute("delete from cursorDiskKV where key like ?", ("%" + entry["chat"] + "%",))
            db.execute("delete from composerHeaders where composerId=?", (entry["chat"],))
        entry["removed"] = base.now_iso()
        print("removed", entry["chat"])
    db.close()
    with open(base.JOURNAL, "w") as fh:
        for entry in entries:
            fh.write(json.dumps(entry) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create")
    c.add_argument("--like", required=True, help="ID of an existing throwaway chat to copy the record shapes from")
    c.add_argument("--codeword", required=True)
    c.set_defaults(fn=do_create)
    r = sub.add_parser("remove")
    r.set_defaults(fn=do_remove)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
