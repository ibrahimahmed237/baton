#!/usr/bin/env python3
"""M0b spike: create a Cursor chat from outside, and remove it again.

Throwaway code. Cursor keeps what a chat displays (one record per message) apart
from what its agent knows (an encoded state that points at encrypted blobs).
Only the first can be written from outside. This clones the display records of
an existing throwaway chat under a new ID with new text and an empty agent
state, to see whether the app lists it and shows the messages.

Run only while Cursor is closed. `remove` deletes exactly the rows `create` added.

    m0b_cursor_create.py create --like CHAT_ID --codeword W
    m0b_cursor_create.py append --chat CHAT_ID --codeword W   # one more turn in an existing chat
    m0b_cursor_create.py insert --chat CHAT_ID --before-last-turn --codeword W   # place a turn before the newest one
    m0b_cursor_create.py cut --chat CHAT_ID --keep-turns N                        # take the chat back to N turns
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


def do_append(args):
    """Add one question and answer to the display records of a chat whose agent already has a state.

    The agent's state is left as it is, so this shows whether Cursor notices
    that the chat displays more than its agent was given.
    """
    if running():
        sys.exit("Cursor is running; it keeps chats in memory and would write over this. Quit Cursor first.")
    db = sqlite3.connect(DB, timeout=20)

    def get(key):
        return json.loads(db.execute("select value from cursorDiskKV where key=?", (key,)).fetchone()[0])

    data = get("composerData:" + args.chat)
    heads = data["fullConversationHeadersOnly"]
    user_head = [h for h in heads if h["type"] == 1][-1]
    reply_head = [h for h in heads if h["type"] == 2 and h.get("grouping", {}).get("hasText")][-1]
    now = int(time.time() * 1000)
    texts = ["[Baton spike: this turn was added from outside the app] Remember this codeword: %s." % args.codeword,
             "Noted. The codeword is %s." % args.codeword]
    rows = {}
    for head, text, at in zip((user_head, reply_head), texts, (now, now + 2000)):
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(at / 1000))
        bubble = dict(get("bubbleId:%s:%s" % (args.chat, head["bubbleId"])), bubbleId=str(uuid.uuid4()),
                      text=text, createdAt=stamp)
        bubble.pop("checkpointId", None)
        if "richText" in bubble:
            bubble["richText"] = rich_text(text)
        rows["bubbleId:%s:%s" % (args.chat, bubble["bubbleId"])] = bubble
        heads.append(dict(head, bubbleId=bubble["bubbleId"], createdAt=stamp,
                          grouping=dict(head.get("grouping", {}), textPreview=text[:80])))
    data["lastUpdatedAt"] = now + 2000
    with db:
        for key, row in rows.items():
            db.execute("insert into cursorDiskKV(key, value) values(?,?)", (key, json.dumps(row)))
        db.execute("insert into cursorDiskKV(key, value) values(?,?)", ("composerData:" + args.chat, json.dumps(data)))
    db.close()
    base.journal({"side": "cursor", "kind": "append", "chat": args.chat, "keys": list(rows)})
    print(json.dumps({"appended": True, "chat": args.chat, "messages_now": len(heads)}))


def _turn_starts(heads):
    return [i for i, head in enumerate(heads) if head["type"] == 1]


def do_insert(args):
    """Place a question and answer before the chat's newest turn: 'attach now, show later'."""
    if running():
        sys.exit("Cursor is running; it keeps chats in memory and would write over this. Quit Cursor first.")
    db = sqlite3.connect(DB, timeout=20)

    def get(key):
        return json.loads(db.execute("select value from cursorDiskKV where key=?", (key,)).fetchone()[0])

    data = get("composerData:" + args.chat)
    heads = data["fullConversationHeadersOnly"]
    at_index = _turn_starts(heads)[-1]
    user_head = heads[at_index]
    reply_head = [h for h in heads if h["type"] == 2 and h.get("grouping", {}).get("hasText")][-1]
    now = int(time.time() * 1000)
    texts = ["[Baton spike: this turn was placed before your last message, from outside] Remember this codeword: %s."
             % args.codeword, "Noted. The codeword is %s." % args.codeword]
    rows, new_heads = {}, []
    for head, text, at in zip((user_head, reply_head), texts, (now, now + 1)):
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(at / 1000))
        bubble = dict(get("bubbleId:%s:%s" % (args.chat, head["bubbleId"])), bubbleId=str(uuid.uuid4()),
                      text=text, createdAt=stamp)
        bubble.pop("checkpointId", None)
        if "richText" in bubble:
            bubble["richText"] = rich_text(text)
        rows["bubbleId:%s:%s" % (args.chat, bubble["bubbleId"])] = bubble
        new_heads.append(dict(head, bubbleId=bubble["bubbleId"], createdAt=stamp,
                              grouping=dict(head.get("grouping", {}), textPreview=text[:80])))
    data["fullConversationHeadersOnly"] = heads[:at_index] + new_heads + heads[at_index:]
    with db:
        for key, row in rows.items():
            db.execute("insert into cursorDiskKV(key, value) values(?,?)", (key, json.dumps(row)))
        db.execute("insert into cursorDiskKV(key, value) values(?,?)", ("composerData:" + args.chat, json.dumps(data)))
    db.close()
    base.journal({"side": "cursor", "kind": "insert", "chat": args.chat, "keys": list(rows)})
    print(json.dumps({"inserted": True, "chat": args.chat, "position": at_index, "messages_now": len(heads) + 2}))


def do_cut(args):
    """Take a chat back to its first N turns in the display records, saving what is removed."""
    if running():
        sys.exit("Cursor is running; it keeps chats in memory and would write over this. Quit Cursor first.")
    db = sqlite3.connect(DB, timeout=20)
    data = json.loads(db.execute("select value from cursorDiskKV where key=?",
                                 ("composerData:" + args.chat,)).fetchone()[0])
    heads = data["fullConversationHeadersOnly"]
    starts = _turn_starts(heads)
    if len(starts) <= args.keep_turns:
        sys.exit("the chat has %d turns; nothing to cut" % len(starts))
    gone = heads[starts[args.keep_turns]:]
    keys = ["bubbleId:%s:%s" % (args.chat, head["bubbleId"]) for head in gone]
    saved = {key: db.execute("select value from cursorDiskKV where key=?", (key,)).fetchone()[0] for key in keys}
    keep_path = os.path.join(base.WORK, "backup", "cursor-cut-%d.json" % int(time.time()))
    os.makedirs(os.path.dirname(keep_path), exist_ok=True)
    with open(keep_path, "w") as fh:
        json.dump({"heads": gone, "bubbles": {k: (v.decode() if isinstance(v, bytes) else v) for k, v in saved.items()}}, fh)
    data["fullConversationHeadersOnly"] = heads[:starts[args.keep_turns]]
    with db:
        for key in keys:
            db.execute("delete from cursorDiskKV where key=?", (key,))
        db.execute("insert into cursorDiskKV(key, value) values(?,?)", ("composerData:" + args.chat, json.dumps(data)))
    db.close()
    base.journal({"side": "cursor", "kind": "cut", "chat": args.chat, "saved": keep_path})
    print(json.dumps({"cut": True, "chat": args.chat, "kept_turns": args.keep_turns, "removed_messages": len(gone)}))


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
    a = sub.add_parser("append")
    a.add_argument("--chat", required=True)
    a.add_argument("--codeword", required=True)
    a.set_defaults(fn=do_append)
    i = sub.add_parser("insert")
    i.add_argument("--chat", required=True)
    i.add_argument("--before-last-turn", action="store_true", required=True)
    i.add_argument("--codeword", required=True)
    i.set_defaults(fn=do_insert)
    k = sub.add_parser("cut")
    k.add_argument("--chat", required=True)
    k.add_argument("--keep-turns", type=int, required=True)
    k.set_defaults(fn=do_cut)
    r = sub.add_parser("remove")
    r.set_defaults(fn=do_remove)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
