#!/usr/bin/env python3
"""M0 spike: a test hook for the prompt and the turn-end events of both tools.

Throwaway code. It stands in for the real hooks so these can be observed in the
desktop apps (docs/DESIGN.md section 9):

  - does text returned by the prompt hook reach the agent,
  - what does each app pass to each hook (is the session ID there),
  - how is the optional notice shown to the user,
  - does the turn-end hook fire, and what output does each app accept.

On a prompt it only acts when the text contains "hook test", so ordinary chats
in this folder are left alone. At turn end it only logs. Everything it receives
is logged to .baton-spike/hook-log.jsonl.

    m0_hook.py claude|codex      (hook input arrives as JSON on stdin)
"""
import datetime
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(ROOT, ".baton-spike", "hook-log.jsonl")
TRIGGER = "hook test"

# What each side is told happened on the other side.
MISSED = {
    "claude": {"from": "Codex", "codeword": "PAPAYA-9"},
    "codex": {"from": "Claude", "codeword": "GUAVA-5"},
}


def main():
    side = sys.argv[1] if len(sys.argv) > 1 else "claude"
    raw = sys.stdin.read()
    try:
        data = json.loads(raw) if raw.strip() else {}
    except ValueError:
        data = {"unparsed": raw[:200]}
    event = data.get("hook_event_name") or ""
    prompt = data.get("prompt") or ""
    attach = event != "Stop" and TRIGGER in prompt.lower()

    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a") as fh:
        fh.write(json.dumps({
            "at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "side": side,
            "keys": sorted(data.keys()),
            "session_id": data.get("session_id"),
            "hook_event_name": event,
            "cwd": data.get("cwd"),
            "transcript_path": data.get("transcript_path"),
            "prompt_preview": prompt[:60],
            "last_assistant_message_preview": (data.get("last_assistant_message") or "")[:60],
            "stop_hook_active": data.get("stop_hook_active"),
            "attached": attach,
        }) + "\n")

    if event == "Stop":
        # Codex accepts only JSON here; Claude accepts no output at all.
        if side == "codex":
            print("{}")
        return
    if not attach:
        return
    missed = MISSED.get(side, MISSED["claude"])
    stamp = datetime.datetime.now().strftime("%H:%M")
    context = (
        "<baton-catch-up>\n"
        "Baton spike. One turn happened in %(from)s since this chat's last turn. You did not see it.\n"
        "[%(from)s, %(stamp)s] User: Remember this codeword: %(codeword)s.\n"
        "[%(from)s, %(stamp)s] Assistant: Noted. The codeword is %(codeword)s.\n"
        "</baton-catch-up>" % dict(missed, stamp=stamp)
    )
    print(json.dumps({
        "hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": context},
        "systemMessage": "Baton attached 1 turn from %s to this message (spike test)." % missed["from"],
    }))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # A test hook must never block the user's message.
        pass
