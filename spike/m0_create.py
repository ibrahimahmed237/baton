#!/usr/bin/env python3
"""M0 spike: create a brand-new chat on one side, written entirely from outside the app.

Throwaway code. Linking a chat means creating its twin on the other side, so
this checks that each app accepts a chat it did not create itself
(docs/DESIGN.md section 9). The new chat holds one turn with a codeword.

Only new files and one new database row are written; nothing existing is
changed. Everything created is listed in the journal so `remove` can delete
exactly those things and nothing else.

    m0_create.py claude --codeword WORD [--title TEXT] [--cwd DIR]
    m0_create.py codex  --codeword WORD [--title TEXT] [--cwd DIR]
    m0_create.py remove
"""
import argparse
import datetime
import glob
import json
import os
import re
import sqlite3
import sys
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import m0_append as base  # noqa: E402

HOME = base.HOME
CLAUDE_PROJECTS = os.path.join(HOME, ".claude", "projects")
CLAUDE_SIDEBAR_ROOT = os.path.join(HOME, "Library", "Application Support", "Claude", "claude-code-sessions")
CODEX_SESSIONS = os.path.join(HOME, ".codex", "sessions")


def texts(codeword):
    return ("[Baton spike: this chat was created from outside the app] Remember this codeword: %s." % codeword,
            "Noted. The codeword is %s." % codeword)


# ---------------------------------------------------------------- Claude

def claude_sidebar_dir():
    """The account folder the desktop app is using: the one with the newest sidebar entry."""
    best, newest = None, -1
    for d in glob.glob(os.path.join(CLAUDE_SIDEBAR_ROOT, "*", "*")):
        stamps = [os.path.getmtime(f) for f in glob.glob(os.path.join(d, "local_*.json"))]
        if stamps and max(stamps) > newest:
            best, newest = d, max(stamps)
    return best


def claude_version(project_dir):
    """The Claude Code version that last wrote a chat in this project."""
    files = sorted(glob.glob(os.path.join(project_dir, "*.jsonl")), key=os.path.getmtime, reverse=True)
    for f in files[:5]:
        for rec in reversed(base.read_jsonl(f)):
            if rec.get("version"):
                return rec["version"]
    return "2.1.284"


def do_claude(args):
    sidebar = claude_sidebar_dir()
    if not sidebar:
        sys.exit("no Claude desktop sidebar folder found")
    project_dir = os.path.join(CLAUDE_PROJECTS, re.sub(r"[^A-Za-z0-9]", "-", args.cwd))
    sid, local_id = str(uuid.uuid4()), "local_" + str(uuid.uuid4())
    path = os.path.join(project_dir, sid + ".jsonl")
    entry_path = os.path.join(sidebar, local_id + ".json")
    prompt, reply = texts(args.codeword)
    stamp, ms = base.now_iso(), int(time.time() * 1000)
    envelope = {"isSidechain": False, "userType": "external", "entrypoint": "claude-desktop", "cwd": args.cwd,
                "sessionId": sid, "version": claude_version(project_dir), "gitBranch": "HEAD"}
    user = dict(envelope, parentUuid=None, uuid=str(uuid.uuid4()), promptId=str(uuid.uuid4()), type="user",
                timestamp=stamp, message={"role": "user", "content": prompt}, permissionMode="default",
                origin={"kind": "human"}, promptSource="sdk", turnOrigin="human",
                turnPosition={"promptIndex": 1, "turnIndex": 1})
    assistant = dict(envelope, parentUuid=user["uuid"], uuid=str(uuid.uuid4()), type="assistant", timestamp=stamp,
                     message={"id": "msg_baton_" + uuid.uuid4().hex[:20], "type": "message", "role": "assistant",
                              "model": "codex", "content": [{"type": "text", "text": reply}],
                              "stop_reason": "end_turn", "stop_sequence": None,
                              "usage": {"input_tokens": 0, "output_tokens": 0}})
    title = {"type": "custom-title", "customTitle": args.title, "sessionId": sid}
    entry = {"sessionId": local_id, "cliSessionId": sid, "cwd": args.cwd, "originCwd": args.cwd,
             "lastFocusedAt": ms, "createdAt": ms, "lastActivityAt": ms, "isArchived": False,
             "title": args.title, "titleSource": "auto", "permissionMode": "default", "completedTurns": 1,
             "titleTurn": 0, "bridgeSessionIds": [], "alwaysAllowedReasons": [], "sessionPermissionUpdates": [],
             "spawnSeed": {}}
    if os.path.exists(path) or os.path.exists(entry_path):
        sys.exit("refusing to overwrite an existing file")

    base.journal({"side": "claude", "created": [path, entry_path], "session": sid, "local": local_id})
    os.makedirs(project_dir, exist_ok=True)
    with open(path, "x") as fh:
        fh.write(base.serialize([user, assistant, title]))
    with open(entry_path, "x") as fh:
        json.dump(entry, fh, indent=1)
    print(json.dumps({"created": True, "session": sid, "sidebar_id": local_id, "file": path,
                      "sidebar_entry": entry_path, "link": "claude://claude.ai/epitaxy/" + local_id}, indent=1))


# ---------------------------------------------------------------- Codex

def codex_defaults():
    """Settings and base instructions of the newest thread the user started, so the new one behaves like it."""
    db = sqlite3.connect("file:%s?mode=ro" % base.CODEX_DB, uri=True, timeout=5)
    rows = db.execute("""select rollout_path, sandbox_policy, approval_mode, model, reasoning_effort, cli_version
                         from threads where thread_source='user' and rollout_path!='' order by updated_at desc limit 5""").fetchall()
    db.close()
    for rollout, sandbox, approval, model, effort, version in rows:
        try:
            with open(rollout, errors="replace") as fh:
                meta = (json.loads(fh.readline()) or {}).get("payload") or {}
        except (OSError, ValueError):
            continue
        if meta.get("base_instructions"):
            return {"sandbox_policy": sandbox, "approval_mode": approval, "model": model, "reasoning_effort": effort,
                    "cli_version": version or meta.get("cli_version") or "", "base_instructions": meta["base_instructions"]}
    sys.exit("no existing Codex thread to copy settings from")


def do_codex(args):
    d = codex_defaults()
    tid = str(uuid.uuid4())
    local = datetime.datetime.now()
    out_dir = os.path.join(CODEX_SESSIONS, local.strftime("%Y"), local.strftime("%m"), local.strftime("%d"))
    path = os.path.join(out_dir, "rollout-%s-%s.jsonl" % (local.strftime("%Y-%m-%dT%H-%M-%S"), tid))
    if os.path.exists(path):
        sys.exit("refusing to overwrite an existing file")
    prompt, reply = texts(args.codeword)
    stamp, ms = base.now_iso(), int(time.time() * 1000)
    meta = {"timestamp": stamp, "ordinal": 0, "type": "session_meta", "payload": {
        "session_id": tid, "id": tid, "timestamp": stamp, "cwd": args.cwd, "originator": "Codex Desktop",
        "cli_version": d["cli_version"], "source": "vscode", "thread_source": "user", "model_provider": "openai",
        "history_mode": "paginated", "context_window": {"window_id": str(uuid.uuid4())},
        "base_instructions": d["base_instructions"]}}
    text = base.serialize([meta] + base.codex_turn(tid, 1, prompt, reply))

    dest = base.backup([], sqlite_paths=[base.CODEX_DB])
    base.journal({"side": "codex", "created": [path], "thread": tid, "backup": dest})
    os.makedirs(out_dir, exist_ok=True)
    with open(path, "x") as fh:
        fh.write(text)
    if len(base.read_jsonl(path)) != text.count("\n"):
        os.remove(path)
        sys.exit("the new rollout did not read back cleanly; removed it")
    try:
        rw = sqlite3.connect(base.CODEX_DB, timeout=10)
        rw.execute("""insert into threads (id, rollout_path, created_at, updated_at, source, model_provider, cwd, title,
                        sandbox_policy, approval_mode, tokens_used, has_user_event, archived, cli_version,
                        first_user_message, model, reasoning_effort, created_at_ms, updated_at_ms, thread_source,
                        preview, recency_at, recency_at_ms, history_mode, name, is_pinned, originator)
                      values (?,?,?,?,?,?,?,?,?,?,0,0,0,?,?,?,?,?,?,?,?,?,?,?,?,0,?)""",
                   (tid, path, ms // 1000, ms // 1000, "vscode", "openai", args.cwd, args.title, d["sandbox_policy"],
                    d["approval_mode"], d["cli_version"], prompt, d["model"], d["reasoning_effort"], ms, ms, "user",
                    prompt[:200], ms // 1000, ms, "paginated", args.title, "Codex Desktop"))
        rw.commit()
        rw.close()
    except sqlite3.Error as err:
        os.remove(path)  # the file is useless to Codex without its row
        sys.exit("could not add the thread to Codex's database (%s); removed the new rollout" % err)
    print(json.dumps({"created": True, "thread": tid, "file": path, "link": "codex://threads/" + tid,
                      "backup": dest}, indent=1))


# ---------------------------------------------------------------- remove

def do_remove(_args):
    if not os.path.exists(base.JOURNAL):
        sys.exit("nothing journaled")
    entries = base.read_jsonl(base.JOURNAL)
    for entry in entries:
        if "created" not in entry or entry.get("removed"):
            continue
        for path in entry["created"]:
            if os.path.exists(path):
                os.remove(path)
                print("removed", path)
        if entry["side"] == "codex":
            rw = sqlite3.connect(base.CODEX_DB, timeout=10)
            rw.execute("delete from threads where id=? and originator='Codex Desktop' and name=title", (entry["thread"],))
            rw.commit()
            rw.close()
            print("removed thread row", entry["thread"])
        entry["removed"] = base.now_iso()
    with open(base.JOURNAL, "w") as fh:
        for entry in entries:
            fh.write(json.dumps(entry) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (("claude", do_claude), ("codex", do_codex)):
        p = sub.add_parser(name)
        p.add_argument("--codeword", required=True)
        p.add_argument("--title", default="Baton created chat")
        p.add_argument("--cwd", default=base.ROOT)
        p.set_defaults(fn=fn)
    r = sub.add_parser("remove")
    r.set_defaults(fn=do_remove)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
