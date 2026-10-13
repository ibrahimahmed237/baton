"""Read OpenCode messages and parts into public turns."""
import json

from ...domain.model import Message, Turn, PROMPT, REPLY, TOOL_CALL, TOOL_RESULT
from ...ports.tool import Usage
from .locator import iso


class OpenCodeReader:
    """Discard synthetic context and reasoning; retain native tool activity."""

    def __init__(self, adapter):
        self.adapter = adapter

    def rows(self, chat_id):
        """Read one consistent snapshot of a chat's native rows."""
        self.adapter.locator.row(chat_id)
        with self.adapter.locator.connect() as db:
            db.execute("BEGIN")
            messages = [dict(r) for r in db.execute("SELECT * FROM message WHERE session_id=? ORDER BY time_created,id", (chat_id,))]
            parts = [dict(r) for r in db.execute("SELECT * FROM part WHERE session_id=? ORDER BY time_created,id", (chat_id,))]
        return messages, parts

    def read(self, chat_id):
        """Group by native parent IDs, ordering turns by user-row creation time.

        An appended Baton turn follows the user turn currently being answered,
        even when that native reply adds messages or parts after Baton's rows.
        Public timestamps may preserve source history; native user-row times
        determine placement in this chat. Orphan assistants start no turn.
        """
        rows, parts = self.rows(chat_id)
        turns = {}
        content_by_message = {}
        for part in parts:
            native = json.loads(part["data"])
            # SQLite's foreign key owns the part, even if its JSON has no ID.
            content_by_message.setdefault(part["message_id"], []).append((part, native))
        for row in rows:
            data = json.loads(row["data"])
            content = content_by_message.get(row["id"], [])
            content = [(p, d) for p, d in content if not d.get("synthetic") and not d.get("ignored")]
            if data.get("role") == "user":
                text = "\n".join(d.get("text", "") for _, d in content if d.get("type") == "text")
                if not text:
                    continue
                prompt = Message(**data["baton"]) if "baton" in data else Message(row["id"], PROMPT, text, iso(data.get("batonRowTime", row["time_created"])))
                turns[row["id"]] = Turn(prompt)
        for row in rows:
            data = json.loads(row["data"])
            parent = data.get("parentID")
            content = [(p, d) for p, d in content_by_message.get(row["id"], [])
                       if not d.get("synthetic") and not d.get("ignored")]
            if data.get("role") == "assistant" and parent in turns:
                activity = []
                for part, native in content:
                    kind = native.get("type")
                    if kind not in ("text", "tool"):
                        continue
                    if "baton" in native:
                        activity.append(Message(**native["baton"]))
                    elif kind == "text":
                        activity.append(Message(part["id"], REPLY, native.get("text", ""), iso(native.get("batonRowTime", part["time_created"]))))
                    else:
                        state = native.get("state", {})
                        call = native.get("callID", part["id"])
                        activity.append(Message(part["id"], TOOL_CALL, at=iso(native.get("batonRowTime", part["time_created"])),
                                                tool=native.get("tool", ""), tool_input=state.get("input", {}), call_id=call))
                        if state.get("status") in ("completed", "error"):
                            activity.append(Message(part["id"] + "#result", TOOL_RESULT,
                                                    state.get("output", state.get("error", "")),
                                                    iso(state.get("time", {}).get("end", native.get("batonRowUpdated", part["time_updated"]))),
                                                    call_id=call, is_error=state["status"] == "error"))
                turns[parent] = Turn(turns[parent].prompt, (*turns[parent].messages, *activity))
        return list(turns.values())

    def usage(self, chat_id):
        """Report the newest native assistant usage, preserving it across Baton writes."""
        rows, _ = self.rows(chat_id)
        reply = next((json.loads(r["data"]) for r in reversed(rows) if json.loads(r["data"]).get("role") == "assistant"
                      and not json.loads(r["data"]).get("batonWritten")), {})
        counts = reply.get("tokens", {})
        total = counts.get("total")
        if total is None:
            total = sum(counts.get(k, 0) for k in ("input", "output", "reasoning")) + sum(counts.get("cache", {}).values())
        error = reply.get("error") or {}
        error = error if isinstance(error, dict) else {}
        detail = error.get("data", error) if isinstance(error, dict) else {}
        limited = detail.get("statusCode", detail.get("status")) in (429, "429") or error.get("name") == "RateLimitError"
        return Usage(int(total), None, limited, None)

    def files_changed(self, turn):
        """Use the native user's summary diffs, falling back to mapped write calls."""
        scoped = self.adapter.allowed_chat_ids | self.adapter.writer.created
        with self.adapter.locator.connect() as db:
            row = db.execute("SELECT data FROM message WHERE id=? AND session_id IN (%s)" %
                             (",".join("?" for _ in scoped) or "NULL"), (turn.id, *sorted(scoped))).fetchone()
            if row is None and scoped:
                row = db.execute("SELECT data FROM message WHERE json_extract(data,'$.baton.id')=? AND session_id IN (%s)" %
                                 ",".join("?" for _ in scoped), (turn.id, *sorted(scoped))).fetchone()
        if row:
            return sorted({d["file"] for d in json.loads(row["data"]).get("summary", {}).get("diffs", []) if d.get("file")})
        return sorted({m.tool_input.get("filePath", m.tool_input.get("path")) for m in turn.messages
                       if m.kind == TOOL_CALL and m.tool in ("write", "edit") and isinstance(m.tool_input, dict)
                       and (m.tool_input.get("filePath") or m.tool_input.get("path"))})

    def commands_run(self, turn):
        """Count native bash or shell calls, excluding their results."""
        return sum(m.kind == TOOL_CALL and m.tool in ("bash", "shell") for m in turn.messages)
