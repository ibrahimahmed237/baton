"""The shapes of a Codex rollout: reading them strictly, and building them for a write.

Everything a writer needs to know about a rollout line lives here, so the
format has one home (shapes from spike/m0_append.py and spike/m0_create.py).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Sequence
from uuid import uuid4

from ...domain.model import REPLY, TOOL_CALL, TOOL_RESULT, TOOL_TEXT, Turn

# Top-level record types Codex is known to write. A rollout holding another one
# was written by a version nobody has checked.
KNOWN_RECORD_TYPES = frozenset({"session_meta", "response_item", "event_msg", "turn_context", "compacted"})

# Task events that open and close a turn in Codex's own chat view.
TASK_OPEN = "task_started"
TASK_CLOSE = ("task_complete", "turn_aborted")


def stamp(moment: datetime) -> str:
    """A record timestamp as Codex writes it: UTC with milliseconds."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def epoch_ms(at: str, fallback: datetime) -> int:
    """Milliseconds since 1970 of an ISO time, or of the fallback when the time is empty or unreadable."""
    try:
        moment = datetime.fromisoformat(at.replace("Z", "+00:00"))
    except ValueError:
        moment = fallback
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return int(moment.timestamp() * 1000)


def serialize(records: Sequence[dict]) -> bytes:
    """Records as newline-terminated JSON lines."""
    return "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records).encode()


def parse_strict(raw: bytes) -> list[dict]:
    """Every record of a rollout, or ValueError when any line is damaged, unfinished or of an unknown type."""
    if raw and not raw.endswith(b"\n"):
        raise ValueError("unfinished last line")
    records = []
    for line in raw.decode("utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if not isinstance(record, dict) or record.get("type") not in KNOWN_RECORD_TYPES:
            raise ValueError("unknown record")
        if not isinstance(record.get('payload'), dict):
            raise ValueError('payload')
        ordinal = record.get('ordinal')
        if not isinstance(ordinal, int) or isinstance(ordinal, bool) or ordinal < 0:
            raise ValueError('ordinal')
        if records and ordinal <= records[-1]['ordinal']:
            raise ValueError('ordinal_order')
        records.append(record)
    return records


def next_ordinal(records: Sequence[dict]) -> int:
    """The ordinal after the highest one in the rollout."""
    return max((r["ordinal"] for r in records if isinstance(r.get("ordinal"), int)), default=-1) + 1


def message_ids(records: Sequence[dict]) -> set[str]:
    """The IDs the rollout's response items already carry."""
    return {r["payload"]["id"] for r in records
            if r.get("type") == "response_item" and isinstance(r.get("payload"), dict) and r["payload"].get("id")}


def records_from_end(path: Path, budget: int | None = None, chunk: int = 1 << 18) -> Iterator[dict]:
    """Parsed records, newest first, read from the end of the file in blocks.

    Lines that do not parse (a line Codex is still writing) are skipped. With a
    budget the walk stops after about that many bytes.
    """
    with path.open("rb") as fh:
        size = fh.seek(0, os.SEEK_END)
        position, carry, floor = size, b"", 0 if budget is None else max(0, size - budget)
        while position > 0:
            start = max(0, position - chunk)
            fh.seek(start)
            lines = (fh.read(position - start) + carry).split(b"\n")
            if start > 0:
                carry, lines = lines[0], lines[1:]
            else:
                carry = b""
            for line in reversed(lines):
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if isinstance(record, dict):
                    yield record
            position = start
            if start <= floor and budget is not None:
                return


class _Sequence:
    """Numbers records one after the other, as Codex numbers its own."""

    def __init__(self, first_ordinal: int, now: datetime):
        self.records: list[dict] = []
        self.ordinal = first_ordinal
        self.now = now

    def add(self, at: str, kind: str, payload: dict, **extra: object) -> None:
        marks = dict(extra)
        if kind == "response_item" and not at:
            # A time the source chat did not have is not invented on read-back.
            marks["batonAtUnknown"] = True
        self.records.append({"timestamp": at or stamp(self.now), "ordinal": self.ordinal,
                             "type": kind, "payload": payload, **marks})
        self.ordinal += 1


def _item_id() -> str:
    return "baton-" + uuid4().hex[:12]


def turn_records(turns: Sequence[Turn], thread_id: str, first_ordinal: int, now: datetime) -> list[dict]:
    """Records for finished turns, in the shape Codex writes for its own imports.

    Codex builds the chat view from the task and item events and the agent's
    context from the response items, so a turn needs both.
    """
    out = _Sequence(first_ordinal, now)
    for turn in turns:
        turn_id = "baton-turn-" + uuid4().hex[:12]
        started = turn.prompt.at or stamp(now)
        started_ms = epoch_ms(started, now)

        def item(at: str, body: dict) -> None:
            out.add(at, "event_msg", {"type": "item_completed", "thread_id": thread_id, "turn_id": turn_id,
                                      "completed_at_ms": epoch_ms(at or started, now), "item": body})

        out.add(started, "event_msg", {"type": TASK_OPEN, "turn_id": turn_id, "started_at": started_ms // 1000,
                                       "model_context_window": None, "collaboration_mode_kind": "default"})
        item(started, {"type": "UserMessage", "id": _item_id(),
                       "content": [{"type": "text", "text": turn.prompt.text, "text_elements": []}]})
        out.add(turn.prompt.at, "response_item", {"type": "message", "role": "user", "id": turn.prompt.id,
                                                  "content": [{"type": "input_text", "text": turn.prompt.text}]})
        for message in turn.messages:
            if message.kind in (REPLY, TOOL_TEXT):
                item(message.at, {"type": "AgentMessage", "id": _item_id(),
                                  "content": [{"type": "Text", "text": message.text}]})
                marks = {"batonMessageKind": TOOL_TEXT} if message.kind == TOOL_TEXT else {}
                out.add(message.at, "response_item", {"type": "message", "role": "assistant", "id": message.id,
                                                      "content": [{"type": "output_text", "text": message.text}]}, **marks)
            elif message.kind == TOOL_CALL:
                marks = {} if message.call_id else {"batonOriginalCallId": ""}
                out.add(message.at, "response_item", {
                    "type": "function_call", "id": message.id, "name": message.tool or "tool",
                    "arguments": json.dumps(message.tool_input, ensure_ascii=False),
                    "call_id": message.call_id or message.id}, **marks)
            elif message.kind == TOOL_RESULT:
                out.add(message.at, "response_item", {"type": "function_call_output", "id": message.id,
                                                      "call_id": message.call_id, "output": message.text})
            else:
                raise ValueError(message.kind)
        ended = turn.ended_at or started
        out.add(ended, "event_msg", {"type": "task_complete", "turn_id": turn_id,
                                     "last_agent_message": turn.reply_text or None,
                                     "started_at": started_ms // 1000, "completed_at": epoch_ms(ended, now) // 1000})
    return out.records


def session_meta_record(thread_id: str, folder: str, now: datetime, cli_version: str,
                        base_instructions: object) -> dict:
    """The first record of a rollout Baton creates."""
    payload = {"session_id": thread_id, "id": thread_id, "timestamp": stamp(now), "cwd": folder,
               "originator": "Codex Desktop", "cli_version": cli_version, "source": "vscode",
               "thread_source": "user", "model_provider": "openai", "history_mode": "paginated",
               "context_window": {"window_id": str(uuid4())}}
    if base_instructions:
        payload["base_instructions"] = base_instructions
    return {"timestamp": stamp(now), "ordinal": 0, "type": "session_meta", "payload": payload}
