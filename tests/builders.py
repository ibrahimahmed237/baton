"""Build made-up chat records in the shapes the two tools write.

Tests use these instead of real chat files, so no real conversation is ever
stored in the repo. The shapes follow what was observed in Claude Code 2.1.28x
and Codex 0.159/0.160 (docs/SPIKE-M0.md).
"""
from __future__ import annotations

import itertools
import json

_ids = itertools.count(1)


def _uuid() -> str:
    return "id-%04d" % next(_ids)


def write_jsonl(path, records) -> str:
    with open(path, "w") as fh:
        for record in records:
            fh.write(json.dumps(record) + "\n")
    return str(path)


class ClaudeChat:
    """Appends records like Claude Code does: each new record's parent is the previous one."""

    def __init__(self):
        self.records: list[dict] = []
        self.leaf = None
        self.clock = 0

    def _add(self, record: dict, parent="__leaf__") -> dict:
        self.clock += 1
        record.setdefault("uuid", _uuid())
        record.setdefault("parentUuid", self.leaf if parent == "__leaf__" else parent)
        record.setdefault("timestamp", "2026-01-01T00:%02d:00.000Z" % self.clock)
        self.records.append(record)
        self.leaf = record["uuid"]
        return record

    def prompt(self, text, origin="human", parent="__leaf__", **extra) -> dict:
        record = {"type": "user", "message": {"role": "user", "content": text}, **extra}
        if origin:
            record["origin"] = {"kind": origin}
        return self._add(record, parent)

    def prompt_blocks(self, *texts) -> dict:
        blocks = [{"type": "text", "text": t} for t in texts]
        return self._add({"type": "user", "message": {"role": "user", "content": blocks}, "origin": {"kind": "human"}})

    def reply(self, text) -> dict:
        return self._add({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}})

    def thinking(self) -> dict:
        return self._add({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "thinking", "thinking": "..."}]}})

    def tool_call(self, name, tool_input, call_id) -> dict:
        block = {"type": "tool_use", "id": call_id, "name": name, "input": tool_input}
        return self._add({"type": "assistant", "message": {"role": "assistant", "content": [block]}})

    def tool_result(self, call_id, text, is_error=False) -> dict:
        block = {"type": "tool_result", "tool_use_id": call_id, "content": text, "is_error": is_error}
        return self._add({"type": "user", "message": {"role": "user", "content": [block]}})

    def attachment(self, kind, content="") -> dict:
        return self._add({"type": "attachment", "attachment": {"type": kind, "content": content}})

    def system(self, subtype) -> dict:
        return self._add({"type": "system", "subtype": subtype})

    def bookkeeping(self, kind) -> dict:
        """Records with no place in the conversation: titles, snapshots, queue operations."""
        record = {"type": kind}
        self.records.append(record)
        return record

    def compact(self, summary) -> dict:
        """What compaction writes: a marker with no parent that names what it follows, then the summary."""
        before = self.leaf
        self._add({"type": "system", "subtype": "compact_boundary", "logicalParentUuid": before}, parent=None)
        return self._add({"type": "user", "isCompactSummary": True, "message": {"role": "user", "content": summary}})

    def write(self, path) -> str:
        return write_jsonl(path, self.records)


class CodexChat:
    """Appends records like Codex does: a plain sequence numbered by `ordinal`."""

    def __init__(self, thread="thread-1"):
        self.thread = thread
        self.records: list[dict] = []
        self._add("session_meta", {"session_id": thread, "id": thread})

    def _add(self, kind, payload) -> dict:
        ordinal = len(self.records)
        record = {"timestamp": "2026-01-01T00:%02d:00.000Z" % ordinal, "ordinal": ordinal, "type": kind, "payload": payload}
        self.records.append(record)
        return record

    def user(self, *texts, native=True) -> dict:
        payload = {"type": "message", "role": "user", "content": [{"type": "input_text", "text": t} for t in texts]}
        if native:
            payload["id"] = _uuid()
        return self._add("response_item", payload)

    def assistant(self, text, native=True) -> dict:
        payload = {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]}
        if native:
            payload["id"] = _uuid()
        return self._add("response_item", payload)

    def developer(self, text) -> dict:
        return self._add("response_item", {"type": "message", "role": "developer", "id": _uuid(),
                                           "content": [{"type": "input_text", "text": text}]})

    def reasoning(self) -> dict:
        return self._add("response_item", {"type": "reasoning", "id": _uuid(), "encrypted_content": "x"})

    def function_call(self, name, arguments, call_id) -> dict:
        return self._add("response_item", {"type": "function_call", "id": _uuid(), "name": name,
                                           "arguments": json.dumps(arguments), "call_id": call_id})

    def function_output(self, call_id, output) -> dict:
        return self._add("response_item", {"type": "function_call_output", "id": _uuid(), "call_id": call_id, "output": output})

    def custom_call(self, name, tool_input, call_id) -> dict:
        return self._add("response_item", {"type": "custom_tool_call", "id": _uuid(), "name": name,
                                           "input": tool_input, "call_id": call_id})

    def custom_output(self, call_id, output) -> dict:
        return self._add("response_item", {"type": "custom_tool_call_output", "id": _uuid(), "call_id": call_id, "output": output})

    def event(self, kind, **fields) -> dict:
        return self._add("event_msg", dict(type=kind, **fields))

    def write(self, path) -> str:
        return write_jsonl(path, self.records)
