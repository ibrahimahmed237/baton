"""Native IDs and row snapshots for the OpenCode database."""
import base64
from dataclasses import asdict
from datetime import datetime
import itertools
import json
import secrets
import string

from ...domain.model import REPLY, TOOL_CALL, TOOL_RESULT, TOOL_TEXT

_COUNTER = itertools.count(1)
_MASK = (1 << 48) - 1


def new_id(prefix, milliseconds, descending=False):
    """Use OpenCode's time/counter prefix and fourteen-character random tail."""
    value = milliseconds * 0x1000 + next(_COUNTER)
    if descending:
        value = ~value
    tail = "".join(secrets.choice(string.digits + string.ascii_uppercase + string.ascii_lowercase) for _ in range(14))
    return "%s_%012x%s" % (prefix, value & _MASK, tail)


def milliseconds(at, fallback):
    """Use the turn's timestamp when present, otherwise the injected clock."""
    return int(datetime.fromisoformat(at.replace("Z", "+00:00")).timestamp() * 1000) if at else fallback


def pack(value):
    """Keep arbitrary SQLite blob columns JSON-safe in durable receipts."""
    if isinstance(value, bytes):
        return {"sqlite_blob": base64.b64encode(value).decode()}
    if isinstance(value, dict):
        return {k: pack(v) for k, v in value.items()}
    if isinstance(value, list):
        return [pack(v) for v in value]
    return value


def unpack(value):
    """Restore exact SQLite values from a saved receipt."""
    if isinstance(value, dict):
        if set(value) == {"sqlite_blob"}:
            return base64.b64decode(value["sqlite_blob"])
        return {k: unpack(v) for k, v in value.items()}
    if isinstance(value, list):
        return [unpack(v) for v in value]
    return value


def snapshot(db, chat_id):
    """Capture full session, message and part rows, including unknown columns."""
    row = db.execute("SELECT * FROM session WHERE id=?", (chat_id,)).fetchone()
    return pack({"session": [dict(row)] if row else [],
                 "message": [dict(r) for r in db.execute("SELECT * FROM message WHERE session_id=? ORDER BY id", (chat_id,))],
                 "part": [dict(r) for r in db.execute("SELECT * FROM part WHERE session_id=? ORDER BY id", (chat_id,))]})


def serialize_turns(turns, chat_id, folder, model, start, now, honor_times=True):
    """Build native messages and parts while retaining original message identities."""
    messages, parts = [], []
    clock = start
    zero = {"total": 0, "input": 0, "output": 0, "reasoning": 0, "cache": {"write": 0, "read": 0}}
    for turn in turns:
        clock = max(clock + 1, milliseconds(turn.started_at, now) if honor_times else clock + 1)
        user_id = new_id("msg", clock)
        diffs = [{"file": m.tool_input.get("filePath", m.tool_input.get("path"))}
                 for m in turn.messages if m.kind == TOOL_CALL and m.tool in ("write", "edit", "apply_patch")
                 and isinstance(m.tool_input, dict) and (m.tool_input.get("filePath") or m.tool_input.get("path"))]
        data = {"role": "user", "time": {"created": clock}, "agent": "build", "model": model,
                "summary": {"diffs": diffs}, "baton": asdict(turn.prompt)}
        messages.append(dict(id=user_id, session_id=chat_id, time_created=clock, time_updated=clock, data=json.dumps(data)))
        parts.append(dict(id=new_id("prt", clock), message_id=user_id, session_id=chat_id,
                          time_created=clock, time_updated=clock, data=json.dumps({"type": "text", "text": turn.prompt.text})))
        for message in turn.messages:
            clock = max(clock + 1, milliseconds(message.at, clock + 1) if honor_times else clock + 1)
            assistant_id = new_id("msg", clock)
            data = {"role": "assistant", "parentID": user_id, "mode": "build", "agent": "build",
                    "path": {"cwd": folder, "root": folder}, "cost": 0, "tokens": zero,
                    "providerID": model["providerID"], "modelID": model["modelID"],
                    "time": {"created": clock, "completed": clock}, "finish": "stop",
                    "batonWritten": True}
            if message.kind in (REPLY, TOOL_TEXT):
                part = {"type": "text", "text": message.text, "baton": asdict(message)}
            elif message.kind in (TOOL_CALL, TOOL_RESULT):
                # Native calls hold their result in state; separate Baton messages
                # retain that distinction so incomplete calls are never final replies.
                call = message.call_id or message.id
                part = {"type": "tool", "callID": call, "tool": message.tool, "baton": asdict(message),
                        "state": {"status": "completed" if message.kind == TOOL_RESULT else "pending",
                                  "input": message.tool_input or {}, "output": message.text}}
                if message.kind == TOOL_RESULT:
                    prior = next((p for p in reversed(parts) if json.loads(p["data"]).get("callID") == call), None)
                    if prior:
                        native = json.loads(prior["data"])
                        part["tool"] = native["tool"]
                        native["state"] = {"status": "error" if message.is_error else "completed",
                                           "input": native["state"]["input"], "output": message.text,
                                           "time": {"start": prior["time_created"], "end": clock}}
                        prior["data"] = json.dumps(native)
                        # Keep the public result in its original position as text,
                        # while native replay uses the completed call state above.
                    part = {"type": "text", "text": message.text, "baton": asdict(message)}
            else:
                raise ValueError(message.kind)
            messages.append(dict(id=assistant_id, session_id=chat_id, time_created=clock, time_updated=clock, data=json.dumps(data)))
            parts.append(dict(id=new_id("prt", clock), message_id=assistant_id, session_id=chat_id,
                              time_created=clock, time_updated=clock, data=json.dumps(part)))
    return messages, parts, clock
