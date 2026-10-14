#!/usr/bin/env python3
"""M0 spike: cut a chat back to an earlier point, as undo will have to.

Throwaway code. Undo removes turns from the end of a chat, including anything
the app wrote after them. This checks whether each app accepts a chat that is
now shorter than what it last saw (docs/features/link-actions.md, A9).

The whole file is copied before the cut, so `restore` can put it back.

    m0_cut.py claude --session ID --keep-lines N
    m0_cut.py codex  --thread ID  --keep-ordinal K
    m0_cut.py restore
"""
import argparse
import json
import os
import shutil
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import m0_append as base  # noqa: E402


def cut(path, keep_bytes, side, ident):
    size = os.path.getsize(path)
    if not 0 < keep_bytes < size:
        sys.exit("nothing to cut: the file has %d bytes and %d would be kept" % (size, keep_bytes))
    dest = base.backup([path])
    base.journal({"side": side, "kind": "cut", "path": path, "id": ident, "size_before": size,
                  "size_after": keep_bytes, "backup_file": os.path.join(dest, os.path.basename(path))})
    with open(path, "r+") as fh:
        fh.truncate(keep_bytes)
    print(json.dumps({"cut": True, "path": path, "size_before": size, "size_after": keep_bytes,
                      "removed_bytes": size - keep_bytes, "backup": dest}, indent=1))


def do_claude(args):
    path = base.claude_session_file(args.session)
    live = base.claude_live_process(args.session)
    if live:
        sys.exit("session is held by a live process (pid %s, %s); a chat can only be cut back while closed"
                 % (live.get("pid"), live.get("status")))
    keep = 0
    with open(path, "rb") as fh:
        for _ in range(args.keep_lines):
            keep += len(fh.readline())
    cut(path, keep, "claude", args.session)


def do_codex(args):
    db = sqlite3.connect("file:%s?mode=ro" % base.CODEX_DB, uri=True, timeout=5)
    row = db.execute("select rollout_path from threads where id=?", (args.thread,)).fetchone()
    db.close()
    if not row or not os.path.exists(row[0]):
        sys.exit("thread %s not found" % args.thread)
    if base.codex_lock_held(args.thread):
        sys.exit("Codex holds this thread; a chat can only be cut back while closed")
    keep = 0
    with open(row[0], "rb") as fh:
        for line in fh:
            try:
                ordinal = json.loads(line).get("ordinal")
            except ValueError:
                ordinal = None
            if isinstance(ordinal, int) and ordinal > args.keep_ordinal:
                break
            keep += len(line)
    cut(row[0], keep, "codex", args.thread)


def do_restore(_args):
    entries = base.read_jsonl(base.JOURNAL)
    for entry in reversed(entries):
        if entry.get("kind") != "cut" or entry.get("restored"):
            continue
        # Putting the removed part back is only right while the chat still ends where the cut left it.
        if os.path.getsize(entry["path"]) != entry["size_after"]:
            print("skipped %s: the chat changed after the cut" % entry["path"])
            continue
        shutil.copy2(entry["backup_file"], entry["path"])
        entry["restored"] = base.now_iso()
        print("restored %s to %d bytes" % (entry["path"], entry["size_before"]))
    with open(base.JOURNAL, "w") as fh:
        for entry in entries:
            fh.write(json.dumps(entry) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("claude")
    c.add_argument("--session", required=True)
    c.add_argument("--keep-lines", type=int, required=True)
    c.set_defaults(fn=do_claude)
    x = sub.add_parser("codex")
    x.add_argument("--thread", required=True)
    x.add_argument("--keep-ordinal", type=int, required=True)
    x.set_defaults(fn=do_codex)
    r = sub.add_parser("restore")
    r.set_defaults(fn=do_restore)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
