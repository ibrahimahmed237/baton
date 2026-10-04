#!/usr/bin/env python3
"""M0b spike: create a throwaway OpenCode chat from outside, and remove it again.

Throwaway code. OpenCode keeps every chat in one database. Its own command is
damaged on the target Mac and its local server asks for a password, so the only
way in from outside is the database itself. This adds one chat with one finished
question and answer, in the shapes OpenCode writes, to see whether the app lists
it, shows the turn, and whether its agent knows it.

The whole database is copied first. `remove` deletes exactly the rows `create`
added.

    m0b_opencode.py create --codeword FIG-3 [--cwd DIR] [--title T]
    m0b_opencode.py append --codeword PEAR-1     # one more turn in the chat `create` made
    m0b_opencode.py cut --keep-turns 1           # take the chat back to its first N turns
    m0b_opencode.py remove
"""
import argparse
import json
import os
import random
import sqlite3
import string
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import m0_append as base  # noqa: E402

DB = os.path.expanduser("~/.local/share/opencode/opencode.db")
_MASK = (1 << 48) - 1
_ALPHABET = string.digits + string.ascii_uppercase + string.ascii_lowercase
_counter = 0


def new_id(prefix, at_ms, descending=False):
    """OpenCode's IDs: a prefix, 48 bits of time and counter as hex, then 14 random characters.

    Chats count down, so the newest sorts first; messages and parts count up.
    """
    global _counter
    _counter += 1
    value = at_ms * 0x1000 + _counter
    if descending:
        value = ~value
    return "%s_%012x%s" % (prefix, value & _MASK, "".join(random.choice(_ALPHABET) for _ in range(14)))


def do_create(args):
    cwd = os.path.abspath(args.cwd)
    root = subprocess.run(["git", "-C", cwd, "rev-list", "--max-parents=0", "HEAD"],
                          capture_output=True, text=True).stdout.split()
    if not root:
        sys.exit("%s is not a git folder; OpenCode names a project by its first commit" % cwd)
    project_id = root[0]

    backup_dir = os.path.join(base.WORK, "backup", "opencode-%d" % int(time.time()))
    os.makedirs(backup_dir)
    source = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    copy = sqlite3.connect(os.path.join(backup_dir, "opencode.db"))
    source.backup(copy)
    copy.close()

    source.row_factory = sqlite3.Row
    model = json.loads(source.execute(
        "select data from message where json_extract(data,'$.role')='user' order by time_created desc limit 1"
    ).fetchone()["data"])["model"]
    model = {"providerID": model["providerID"], "modelID": model["modelID"]}
    had_project = source.execute("select 1 from project where id=?", (project_id,)).fetchone() is not None
    source.close()

    now = int(time.time() * 1000)
    session_id = new_id("ses", now, descending=True)
    user_id, assistant_id = new_id("msg", now + 1), new_id("msg", now + 2000)
    zero = {"total": 0, "input": 0, "output": 0, "reasoning": 0, "cache": {"write": 0, "read": 0}}
    messages = [
        (user_id, now + 1, {"role": "user", "time": {"created": now + 1}, "agent": "build", "model": model,
                            "summary": {"diffs": []}}),
        (assistant_id, now + 2000, {"parentID": user_id, "role": "assistant", "mode": "build", "agent": "build",
                                    "path": {"cwd": cwd, "root": cwd}, "cost": 0, "tokens": zero,
                                    "modelID": model["modelID"], "providerID": model["providerID"],
                                    "time": {"created": now + 2000, "completed": now + 3000}, "finish": "stop"}),
    ]
    parts = [
        (new_id("prt", now + 1), user_id, now + 1,
         {"type": "text", "text": "[Baton spike: this turn was added from outside the app] "
                                  "Remember this codeword: %s." % args.codeword}),
        (new_id("prt", now + 2000), assistant_id, now + 2000, {"type": "step-start"}),
        (new_id("prt", now + 2100), assistant_id, now + 2100,
         {"type": "text", "text": "Noted. The codeword is %s." % args.codeword,
          "time": {"start": now + 2100, "end": now + 2900}}),
        (new_id("prt", now + 3000), assistant_id, now + 3000,
         {"type": "step-finish", "reason": "stop", "tokens": zero, "cost": 0}),
    ]

    db = sqlite3.connect(DB, timeout=10)
    with db:
        if not had_project:
            db.execute("insert into project(id, worktree, vcs, time_created, time_updated, sandboxes)"
                       " values(?,?,?,?,?,?)", (project_id, cwd, "git", now, now, "[]"))
            db.execute("insert into project_directory(project_id, directory, time_created) values(?,?,?)",
                       (project_id, cwd, now))
        db.execute(
            "insert into session(id, project_id, slug, directory, title, version, summary_additions,"
            " summary_deletions, summary_files, time_created, time_updated, path, cost, tokens_input,"
            " tokens_output, tokens_reasoning, tokens_cache_read, tokens_cache_write)"
            " values(?,?,?,?,?,?,0,0,0,?,?,'',0,0,0,0,0,0)",
            (session_id, project_id, "baton-spike", cwd, args.title, "local", now, now + 3000))
        for message_id, at, data in messages:
            db.execute("insert into message(id, session_id, time_created, time_updated, data) values(?,?,?,?,?)",
                       (message_id, session_id, at, at, json.dumps(data)))
        for part_id, message_id, at, data in parts:
            db.execute("insert into part(id, message_id, session_id, time_created, time_updated, data)"
                       " values(?,?,?,?,?,?)", (part_id, message_id, session_id, at, at, json.dumps(data)))
    broken = db.execute("pragma foreign_key_check").fetchall()
    db.close()

    base.journal({"side": "opencode", "kind": "create", "session": session_id, "project": project_id,
                  "project_added": not had_project, "cwd": cwd, "backup": backup_dir})
    print(json.dumps({"created": True, "session": session_id, "project": project_id,
                      "project_added": not had_project, "backup": backup_dir,
                      "foreign_key_problems": len(broken)}, indent=1))


def do_append(args):
    """Add one finished question and answer to the test chat, whether or not the app has it on screen."""
    entry = [e for e in base.read_jsonl(base.JOURNAL)
             if e.get("side") == "opencode" and e.get("kind") == "create" and not e.get("removed")][-1]
    session_id, cwd = entry["session"], entry["cwd"]
    db = sqlite3.connect(DB, timeout=10)
    db.row_factory = sqlite3.Row
    last = json.loads(db.execute(
        "select data from message where session_id=? and json_extract(data,'$.role')='assistant'"
        " order by time_created desc limit 1", (session_id,)).fetchone()["data"])
    model = {"providerID": last["providerID"], "modelID": last["modelID"]}
    now = int(time.time() * 1000)
    user_id, assistant_id = new_id("msg", now + 1), new_id("msg", now + 2000)
    zero = {"total": 0, "input": 0, "output": 0, "reasoning": 0, "cache": {"write": 0, "read": 0}}
    rows = [
        (user_id, now + 1, {"role": "user", "time": {"created": now + 1}, "agent": "build", "model": model,
                            "summary": {"diffs": []}},
         [{"type": "text", "text": "[Baton spike: this turn was added from outside the app] "
                                   "Remember this codeword: %s." % args.codeword}]),
        (assistant_id, now + 2000, {"parentID": user_id, "role": "assistant", "mode": "build", "agent": "build",
                                    "path": {"cwd": cwd, "root": cwd}, "cost": 0, "tokens": zero,
                                    "modelID": model["modelID"], "providerID": model["providerID"],
                                    "time": {"created": now + 2000, "completed": now + 3000}, "finish": "stop"},
         [{"type": "step-start"},
          {"type": "text", "text": "Noted. The codeword is %s." % args.codeword,
           "time": {"start": now + 2100, "end": now + 2900}},
          {"type": "step-finish", "reason": "stop", "tokens": zero, "cost": 0}]),
    ]
    with db:
        for message_id, at, data, parts in rows:
            db.execute("insert into message(id, session_id, time_created, time_updated, data) values(?,?,?,?,?)",
                       (message_id, session_id, at, at, json.dumps(data)))
            for offset, part in enumerate(parts):
                db.execute("insert into part(id, message_id, session_id, time_created, time_updated, data)"
                           " values(?,?,?,?,?,?)",
                           (new_id("prt", at + offset), message_id, session_id, at + offset, at + offset,
                            json.dumps(part)))
        db.execute("update session set time_updated=? where id=?", (now + 3000, session_id))
    db.close()
    base.journal({"side": "opencode", "kind": "append", "session": session_id, "messages": [user_id, assistant_id]})
    print(json.dumps({"appended": True, "session": session_id, "messages": [user_id, assistant_id]}))


def do_cut(args):
    """Remove every message after the first N questions and their answers, saving the removed rows."""
    entry = [e for e in base.read_jsonl(base.JOURNAL)
             if e.get("side") == "opencode" and e.get("kind") == "create" and not e.get("removed")][-1]
    session_id = entry["session"]
    db = sqlite3.connect(DB, timeout=10)
    db.row_factory = sqlite3.Row
    messages = db.execute("select * from message where session_id=? order by time_created, id", (session_id,)).fetchall()
    users = [m["id"] for m in messages if json.loads(m["data"])["role"] == "user"]
    if len(users) <= args.keep_turns:
        sys.exit("the chat has %d turns; nothing to cut" % len(users))
    first_gone = [m["id"] for m in messages].index(users[args.keep_turns])
    gone = [m["id"] for m in messages[first_gone:]]
    marks = ",".join("?" * len(gone))
    saved = {"messages": [dict(m) for m in messages[first_gone:]],
             "parts": [dict(p) for p in db.execute("select * from part where message_id in (%s)" % marks, gone)]}
    keep_path = os.path.join(base.WORK, "backup", "opencode-cut-%d.json" % int(time.time()))
    os.makedirs(os.path.dirname(keep_path), exist_ok=True)
    with open(keep_path, "w") as fh:
        json.dump(saved, fh)
    with db:
        db.execute("delete from part where message_id in (%s)" % marks, gone)
        db.execute("delete from message where id in (%s)" % marks, gone)
    db.close()
    base.journal({"side": "opencode", "kind": "cut", "session": session_id, "removed_messages": gone, "saved": keep_path})
    print(json.dumps({"cut": True, "kept_turns": args.keep_turns, "removed_messages": len(gone), "saved": keep_path}))


def do_rename(args):
    """Change the test chat's name in the database, to see whether the app shows it."""
    entry = [e for e in base.read_jsonl(base.JOURNAL)
             if e.get("side") == "opencode" and e.get("kind") == "create" and not e.get("removed")][-1]
    db = sqlite3.connect(DB, timeout=10)
    before = db.execute("select title from session where id=?", (entry["session"],)).fetchone()[0]
    with db:
        db.execute("update session set title=?, time_updated=? where id=?",
                   (args.title, int(time.time() * 1000), entry["session"]))
    db.close()
    print(json.dumps({"renamed": True, "before": before, "after": args.title}))


def do_remove(_args):
    entries = base.read_jsonl(base.JOURNAL)
    db = sqlite3.connect(DB, timeout=10)
    for entry in entries:
        if entry.get("side") != "opencode" or entry.get("kind") != "create" or entry.get("removed"):
            continue
        with db:
            for table in ("part", "message"):
                db.execute("delete from %s where session_id=?" % table, (entry["session"],))
            db.execute("delete from session where id=?", (entry["session"],))
            # The project goes only if this script added it and nothing else uses it now.
            if entry["project_added"] and not db.execute(
                    "select 1 from session where project_id=?", (entry["project"],)).fetchone():
                db.execute("delete from project_directory where project_id=?", (entry["project"],))
                db.execute("delete from project where id=?", (entry["project"],))
        entry["removed"] = base.now_iso()
        print("removed %s" % entry["session"])
    db.close()
    with open(base.JOURNAL, "w") as fh:
        for entry in entries:
            fh.write(json.dumps(entry) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create")
    c.add_argument("--codeword", required=True)
    c.add_argument("--cwd", default=os.getcwd())
    c.add_argument("--title", default="Baton test (safe to delete)")
    c.set_defaults(fn=do_create)
    a = sub.add_parser("append")
    a.add_argument("--codeword", required=True)
    a.set_defaults(fn=do_append)
    k = sub.add_parser("cut")
    k.add_argument("--keep-turns", type=int, required=True)
    k.set_defaults(fn=do_cut)
    n = sub.add_parser("rename")
    n.add_argument("--title", required=True)
    n.set_defaults(fn=do_rename)
    r = sub.add_parser("remove")
    r.set_defaults(fn=do_remove)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
