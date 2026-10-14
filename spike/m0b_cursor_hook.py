#!/usr/bin/env python3
"""M0b spike: a test hook for the Cursor app.

Throwaway code. Two questions: does Cursor tell a hook which chat a prompt and a
finished reply belong to, and can a hook give the agent extra text?

Every call is logged to .baton-spike/cursor-hook-log.jsonl. Text is offered in
two places, each with its own codeword, so the answer shows which one works:

- when a chat starts: PLUM-2
- when a prompt containing "hook test" is sent: LIME-8

Registered for this folder only, in .cursor/hooks.json.
"""
import json
import os
import sys
import time

LOG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".baton-spike", "cursor-hook-log.jsonl")


def main():
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except ValueError:
        payload = {"unparsed": raw[:2000]}
    payload.pop("user_email", None)
    event = payload.get("hook_event_name") or (sys.argv[1] if len(sys.argv) > 1 else "")

    reply = {}
    if event == "sessionStart":
        reply = {"continue": True,
                 "additional_context": "<baton-catch-up>Baton spike, given at chat start. The codeword is PLUM-2.</baton-catch-up>"}
    elif event == "beforeSubmitPrompt":
        reply = {"continue": True}
        if "hook test" in str(payload.get("prompt", "")).lower():
            reply["additional_context"] = ("<baton-catch-up>Baton spike, given with this prompt. "
                                           "The codeword is LIME-8.</baton-catch-up>")

    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a") as fh:
        fh.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "event": event,
                             "payload": payload, "reply": reply}) + "\n")
    print(json.dumps(reply))


if __name__ == "__main__":
    main()
