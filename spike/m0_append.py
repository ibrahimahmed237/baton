#!/usr/bin/env python3
"""M0 spike: append one synthetic turn to a real Claude Code or Codex chat.

Throwaway code. It exists to answer questions about the real desktop apps
(docs/DESIGN.md, section 9) before the engine is written. Run it only against
chats created for testing.

Every write is preceded by a backup of the touched files and a journal entry
holding the file's size, so `undo` can cut the file back.

    m0_append.py claude --session ID --codeword WORD [--allow-open]
    m0_append.py codex  --thread ID  --codeword WORD [--wait-released SECONDS]
    m0_append.py undo
"""
import argparse
import datetime
import fcntl
import glob
import json
import os
import shutil
import sqlite3
import sys
import time
import uuid

HOME = os.path.expanduser("~")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(ROOT, ".baton-spike")
JOURNAL = os.path.join(WORK, "journal.jsonl")
CODEX_DB = os.path.join(HOME, ".codex", "state_5.sqlite")
CODEX_LOCKS = os.path.join(HOME, ".codex", "thread-writer-locks")


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def read_jsonl(path):
    out = []
    with open(path, errors="replace") as fh:
        for line in fh:
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


def backup(paths, sqlite_paths=()):
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = os.path.join(WORK, "backup", stamp)
    os.makedirs(dest, exist_ok=True)
    for p in paths:
        shutil.copy2(p, os.path.join(dest, os.path.basename(p)))
    for p in sqlite_paths:
        src = sqlite3.connect("file:%s?mode=ro" % p, uri=True)
        dst = sqlite3.connect(os.path.join(dest, os.path.basename(p)))
        src.backup(dst)
        dst.close()
        src.close()
    return dest


def journal(entry):
    os.makedirs(WORK, exist_ok=True)
    entry["at"] = now_iso()
    with open(JOURNAL, "a") as fh:
        fh.write(json.dumps(entry) + "\n")


def serialize(records):
    return "".join(json.dumps(rec, ensure_ascii=False) + "\n" for rec in records)


def append_text(path, text):
    with open(path, "a") as fh:
        fh.write(text)


# ---------------------------------------------------------------- Claude

def claude_session_file(session_id):
    hits = glob.glob(os.path.join(HOME, ".claude", "projects", "*", session_id + ".jsonl"))
    if len(hits) != 1:
        sys.exit("expected exactly one file for session %s, found %d" % (session_id, len(hits)))
    return hits[0]


def claude_live_process(session_id):
    """The registry entry of a running process that holds this session, if any."""
    for f in glob.glob(os.path.join(HOME, ".claude", "sessions", "*.json")):
        try:
            entry = json.load(open(f))
        except (ValueError, OSError):
            continue
        if entry.get("sessionId") != session_id:
            continue
        try:
            os.kill(int(entry.get("pid", 0)), 0)
        except (OSError, ValueError):
            continue
        return entry
    return None


def is_human_prompt(rec):
    if rec.get("type") != "user" or rec.get("isMeta"):
        return False
    content = (rec.get("message") or {}).get("content")
    if isinstance(content, str):
        return bool(content.strip())
    return isinstance(content, list) and not any(
        isinstance(b, dict) and b.get("type") == "tool_result" for b in content)


def do_claude(args):
    path = claude_session_file(args.session)
    live = claude_live_process(args.session)
    if live and not args.allow_open:
        sys.exit("session is held by a live process (pid %s, %s); pass --allow-open to test that case"
                 % (live.get("pid"), live.get("status")))
    recs = read_jsonl(path)
    prompts = [r for r in recs if is_human_prompt(r)]
    with_uuid = [r for r in recs if r.get("uuid")]
    if not prompts or not with_uuid:
        sys.exit("no prompt to use as a template in %s" % path)
    template, leaf = prompts[-1], with_uuid[-1]["uuid"]
    stamp = now_iso()

    user = dict(template)
    user.update({
        "parentUuid": leaf, "uuid": str(uuid.uuid4()), "promptId": str(uuid.uuid4()), "timestamp": stamp,
        "message": {"role": "user", "content":
                    "[Baton spike: this turn was appended from outside the app] Remember this codeword: %s." % args.codeword},
    })
    if isinstance(template.get("turnPosition"), dict):
        user["turnPosition"] = {"promptIndex": template["turnPosition"].get("promptIndex", 0) + 1, "turnIndex": 1}

    envelope = {k: template[k] for k in ("isSidechain", "userType", "entrypoint", "cwd", "sessionId", "version", "gitBranch")
                if k in template}
    assistant = dict(envelope)
    assistant.update({
        "parentUuid": user["uuid"], "uuid": str(uuid.uuid4()), "timestamp": stamp, "type": "assistant",
        "message": {"id": "msg_baton_" + uuid.uuid4().hex[:20], "type": "message", "role": "assistant", "model": "codex",
                    "content": [{"type": "text", "text": "Noted. The codeword is %s." % args.codeword}],
                    "stop_reason": "end_turn", "stop_sequence": None,
                    "usage": {"input_tokens": 0, "output_tokens": 0}},
    })

    size = os.path.getsize(path)
    text = serialize([user, assistant])
    dest = backup([path])
    journal({"side": "claude", "path": path, "size_before": size, "size_after": size + len(text.encode()),
             "backup": dest, "held_by_live_process": bool(live), "leaf_before": leaf,
             "wrote": [user["uuid"], assistant["uuid"]]})
    append_text(path, text)
    print(json.dumps({"appended_to": path, "size_before": size, "size_after": os.path.getsize(path),
                      "held_by_live_process": bool(live), "process_status": (live or {}).get("status"),
                      "parent": leaf, "backup": dest}, indent=1))


# ---------------------------------------------------------------- Codex

def codex_lock_held(thread_id):
    """True while a Codex writer holds the thread. The lock file exists only while the thread is loaded."""
    path = os.path.join(CODEX_LOCKS, thread_id + ".lock")
    if not os.path.exists(path):
        return False
    fd = os.open(path, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    except OSError:
        return True
    finally:
        os.close(fd)


def do_codex(args):
    db = sqlite3.connect("file:%s?mode=ro" % CODEX_DB, uri=True, timeout=5)
    row = db.execute("select rollout_path, updated_at, updated_at_ms, recency_at, recency_at_ms from threads where id=?",
                     (args.thread,)).fetchone()
    db.close()
    if not row or not os.path.exists(row[0]):
        sys.exit("thread %s not found" % args.thread)
    path = row[0]

    waited, deadline = 0, time.time() + args.wait_released
    while codex_lock_held(args.thread):
        if time.time() >= deadline:
            print(json.dumps({"appended": False, "reason": "thread still held by Codex", "waited_seconds": waited}))
            sys.exit(3)
        time.sleep(5)
        waited += 5

    recs = read_jsonl(path)
    ordinal = max((r["ordinal"] for r in recs if isinstance(r.get("ordinal"), int)), default=-1) + 1
    stamp, ms = now_iso(), int(time.time() * 1000)
    turn = "baton-turn-" + uuid.uuid4().hex[:12]
    prompt = "[Baton spike: this turn was appended from outside the app] Remember this codeword: %s." % args.codeword
    reply = "Noted. The codeword is %s." % args.codeword
    payloads = [
        ("event_msg", {"type": "task_started", "turn_id": turn, "started_at": ms // 1000,
                       "model_context_window": None, "collaboration_mode_kind": "default"}),
        ("event_msg", {"type": "item_completed", "thread_id": args.thread, "turn_id": turn, "completed_at_ms": ms,
                       "item": {"type": "UserMessage", "id": "baton-" + uuid.uuid4().hex[:12],
                                "content": [{"type": "text", "text": prompt, "text_elements": []}]}}),
        ("response_item", {"type": "message", "role": "user", "content": [{"type": "input_text", "text": prompt}]}),
        ("event_msg", {"type": "item_completed", "thread_id": args.thread, "turn_id": turn, "completed_at_ms": ms,
                       "item": {"type": "AgentMessage", "id": "baton-" + uuid.uuid4().hex[:12],
                                "content": [{"type": "Text", "text": reply}]}}),
        ("response_item", {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": reply}]}),
        ("event_msg", {"type": "task_complete", "turn_id": turn, "last_agent_message": reply,
                       "started_at": ms // 1000, "completed_at": ms // 1000}),
    ]
    records = [{"timestamp": stamp, "ordinal": ordinal + i, "type": t, "payload": p} for i, (t, p) in enumerate(payloads)]

    size = os.path.getsize(path)
    text = serialize(records)
    dest = backup([path], sqlite_paths=[CODEX_DB])
    journal({"side": "codex", "path": path, "size_before": size, "size_after": size + len(text.encode()),
             "backup": dest, "thread": args.thread,
             "threads_row_before": {"updated_at": row[1], "updated_at_ms": row[2], "recency_at": row[3], "recency_at_ms": row[4]},
             "first_ordinal": ordinal, "waited_seconds": waited})
    append_text(path, text)
    rw = sqlite3.connect(CODEX_DB, timeout=10)
    rw.execute("update threads set updated_at=?, updated_at_ms=?, recency_at=?, recency_at_ms=? where id=?",
               (ms // 1000, ms, ms // 1000, ms, args.thread))
    rw.commit()
    rw.close()
    print(json.dumps({"appended": True, "appended_to": path, "size_before": size, "size_after": os.path.getsize(path),
                      "first_ordinal": ordinal, "waited_seconds": waited, "backup": dest}, indent=1))


# ---------------------------------------------------------------- undo

def do_undo(_args):
    if not os.path.exists(JOURNAL):
        sys.exit("nothing journaled")
    entries = read_jsonl(JOURNAL)
    for entry in reversed(entries):
        if entry.get("undone"):
            continue
        # Cutting back is only safe while the appended turn is still the end of the file.
        # Once the app has written after it, truncating would delete real turns.
        if os.path.getsize(entry["path"]) != entry.get("size_after"):
            print("skipped %s: the file changed after this append, cutting it back would remove later turns"
                  % entry["path"])
            continue
        with open(entry["path"], "r+") as fh:
            fh.truncate(entry["size_before"])
        if entry["side"] == "codex":
            before = entry["threads_row_before"]
            rw = sqlite3.connect(CODEX_DB, timeout=10)
            rw.execute("update threads set updated_at=?, updated_at_ms=?, recency_at=?, recency_at_ms=? where id=?",
                       (before["updated_at"], before["updated_at_ms"], before["recency_at"], before["recency_at_ms"],
                        entry["thread"]))
            rw.commit()
            rw.close()
        entry["undone"] = now_iso()
        print("cut %s back to %d bytes" % (entry["path"], entry["size_before"]))
    with open(JOURNAL, "w") as fh:
        for entry in entries:
            fh.write(json.dumps(entry) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("claude")
    c.add_argument("--session", required=True)
    c.add_argument("--codeword", required=True)
    c.add_argument("--allow-open", action="store_true", help="write even though a live process holds the session")
    c.set_defaults(fn=do_claude)
    x = sub.add_parser("codex")
    x.add_argument("--thread", required=True)
    x.add_argument("--codeword", required=True)
    x.add_argument("--wait-released", type=int, default=0, help="seconds to wait for Codex to release the thread")
    x.set_defaults(fn=do_codex)
    u = sub.add_parser("undo")
    u.set_defaults(fn=do_undo)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
