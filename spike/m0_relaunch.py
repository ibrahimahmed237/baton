#!/usr/bin/env python3
"""M0 spike: relaunch Claude from outside, and check two things on the way.

Throwaway code. Two checks could not be run from inside a Claude chat, because
both need the app closed and opened again:

- after a chat's file was cut back, does the chat view follow the file?
- does a chat renamed while the app is closed keep the new name?

It is also the first run of the order Baton's own relaunch will use
(docs/features/link-actions.md, A6): wait until no chat is replying, quit the
app, change what has to change while it is closed, open it again.

    m0_relaunch.py start --rename LOCAL_ID --title T --look LOCAL_ID [--look ...] --return-to LOCAL_ID

`start` detaches and returns at once; the work happens after the chat that
started it has finished replying. Results go to .baton-spike/relaunch/.
"""
import argparse
import glob
import json
import os
import shutil
import signal
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import m0_append as base  # noqa: E402

APP = "/Applications/Claude.app/Contents/MacOS/Claude"
REGISTRY = os.path.expanduser("~/.claude/sessions")
ENTRIES = os.path.expanduser("~/Library/Application Support/Claude/claude-code-sessions")
OUT = os.path.join(base.WORK, "relaunch")
LINK = "claude://claude.ai/epitaxy/%s"


def app_pid():
    listing = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True).stdout
    for line in listing.splitlines():
        pid, _, command = line.strip().partition(" ")
        if command.strip() == APP:
            return int(pid)
    return None


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def chats():
    """The chats Claude has a process for, with their state."""
    found = []
    for path in glob.glob(os.path.join(REGISTRY, "*.json")):
        try:
            with open(path) as fh:
                entry = json.load(fh)
        except (OSError, ValueError):
            continue
        if alive(entry.get("pid", -1)):
            found.append(entry)
    return found


def wait_until(condition, seconds, steady=1):
    """True once `condition` has held for `steady` checks in a row, one second apart."""
    held = 0
    for _ in range(seconds):
        held = held + 1 if condition() else 0
        if held >= steady:
            return True
        time.sleep(1)
    return False


def entry_file(local_id):
    found = glob.glob(os.path.join(ENTRIES, "*", "*", local_id + ".json"))
    return found[0] if found else None


def title_of(local_id):
    with open(entry_file(local_id)) as fh:
        return json.load(fh).get("title")


def save(result):
    with open(os.path.join(OUT, "result.json"), "w") as fh:
        json.dump(result, fh, indent=1)


def run(args):
    result = {"started": base.now_iso(), "steps": []}

    def step(name, **detail):
        result["steps"].append(dict(step=name, at=base.now_iso(), **detail))
        save(result)

    if not wait_until(lambda: all(chat.get("status") != "busy" for chat in chats()), 900, steady=8):
        return step("gave up: a chat was still replying after 15 minutes")
    pid = app_pid()
    if pid is None:
        return step("gave up: Claude is not running")
    step("no chat is replying", chats=[(chat.get("sessionId"), chat.get("status")) for chat in chats()])

    os.kill(pid, signal.SIGTERM)
    if not wait_until(lambda: not alive(pid) and not chats(), 60):
        return step("gave up: Claude did not quit within a minute; nothing was changed")
    step("Claude has quit")

    if args.rename:
        path = entry_file(args.rename)
        shutil.copy2(path, os.path.join(OUT, os.path.basename(path) + ".before"))
        with open(path) as fh:
            entry = json.load(fh)
        before, entry["title"] = entry.get("title"), args.title
        with open(path, "w") as fh:
            json.dump(entry, fh)
        step("renamed while closed", chat=args.rename, before=before, after=args.title)

    subprocess.run(["open", "-a", "Claude"])
    wait_until(lambda: app_pid() is not None, 60)
    time.sleep(25)
    if args.rename:
        step("name 25 seconds after start", title=title_of(args.rename))

    for index, local_id in enumerate(args.look):
        subprocess.run(["open", LINK % local_id])
        time.sleep(10)
        shot = os.path.join(OUT, "view-%d.jpg" % index)
        taken = subprocess.run(["screencapture", "-x", "-t", "jpg", shot], capture_output=True, text=True)
        step("opened chat", chat=local_id, screenshot=shot if taken.returncode == 0 else taken.stderr.strip())

    if args.rename:
        step("name at the end", title=title_of(args.rename))
    if args.return_to:
        subprocess.run(["open", LINK % args.return_to])
    step("done")


def start(args):
    os.makedirs(OUT, exist_ok=True)
    if os.fork():
        print("started; Claude will be relaunched once no chat is replying. Results: %s" % OUT)
        return
    os.setsid()
    if os.fork():
        os._exit(0)
    log = os.open(os.path.join(OUT, "log.txt"), os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
    for fd in (0, 1, 2):
        os.dup2(log if fd else os.open(os.devnull, os.O_RDONLY), fd)
    try:
        run(args)
    except Exception as error:  # the log is the only place this can be seen
        print("failed: %r" % error, flush=True)
    os._exit(0)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start")
    s.add_argument("--rename", help="sidebar ID of the chat to rename while Claude is closed")
    s.add_argument("--title", default="Baton renamed while closed")
    s.add_argument("--look", action="append", default=[], help="sidebar ID of a chat to open and capture")
    s.add_argument("--return-to", help="sidebar ID of the chat to end on")
    s.set_defaults(fn=start)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
