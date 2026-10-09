"""Read a Claude Code chat file into turns.

A chat file is a log of records linked by `parentUuid`. Not everything in it
is part of the conversation the agent has: a prompt can bypass earlier records
and leave them on a dead branch, and many records are bookkeeping. This reader
returns what the agent actually has, as turns.
"""
from __future__ import annotations

import json
import re

from ...domain.model import PROMPT, REPLY, TOOL_CALL, TOOL_RESULT, TOOL_TEXT, Message, Turn

# User records Claude Code writes for its own purposes. Records from current
# versions carry `origin`; this list covers older records that do not.
_NOT_A_PROMPT_PREFIXES = (
    "<command-name>",
    "<command-message>",
    "<local-command-stdout>",
    "<local-command-stderr>",
    "<local-command-caveat>",
    "<task-notification>",
    "[Request interrupted",
)
_PROMPT_ORIGINS = ("human", "peer")
_REMINDER = re.compile(r"\s*<system-reminder>.*?</system-reminder>\s*", re.S)
_ON_THE_CHAIN = ("user", "assistant", "system", "attachment")


def read_records(path: str) -> list[dict]:
    """Read JSONL records, tolerating damaged lines for read-only use."""
    records = []
    with open(path, errors="replace") as fh:
        for line in fh:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict):
                records.append(record)
    return records


def live_chain(records: list[dict]) -> list[dict]:
    """The records the agent has, oldest first.

    The newest record is the end of the conversation; following parents from
    it gives the conversation. A compaction marker has no parent but names the
    record it logically follows, so the history before it is kept too.
    """
    by_id = {}
    for record in records:
        if record.get("uuid"):
            by_id.setdefault(record["uuid"], record)
    leaf = None
    for record in reversed(records):
        if record.get("uuid") and record.get("type") in _ON_THE_CHAIN and not record.get("isSidechain"):
            leaf = record
            break
    chain, seen = [], set()
    while leaf is not None and leaf["uuid"] not in seen:
        seen.add(leaf["uuid"])
        chain.append(leaf)
        leaf = by_id.get(leaf.get("parentUuid") or leaf.get("logicalParentUuid"))
    chain.reverse()
    return chain


def _text_blocks(content) -> list[str]:
    if isinstance(content, str):
        return [content]
    return [b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text"]


def prompt_text(record: dict) -> str:
    """What the user typed, without the reminders Claude Code wraps around it."""
    blocks = [_REMINDER.sub("", block) for block in _text_blocks((record.get("message") or {}).get("content"))]
    return "\n".join(block.strip() for block in blocks if block.strip())


def is_prompt(record: dict) -> bool:
    """Distinguish real human or peer prompts from injected records."""
    if record.get("type") != "user" or record.get("isCompactSummary") or record.get("isVisibleInTranscriptOnly"):
        return False
    content = (record.get("message") or {}).get("content")
    if isinstance(content, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
        return False
    origin = record.get("origin")
    if isinstance(origin, dict) and origin.get("kind"):
        # "peer" is a message another chat sent to this one. Nobody typed it here, but the agent
        # answers it like a prompt, so the answer makes no sense to the other side without it.
        return origin["kind"] in _PROMPT_ORIGINS and bool(prompt_text(record))
    if record.get("isMeta"):
        return False
    text = prompt_text(record)
    return bool(text) and not text.startswith(_NOT_A_PROMPT_PREFIXES)


def _result_text(content) -> str:
    if isinstance(content, str):
        return content
    return "".join(b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text")


def _messages(record: dict) -> list[Message]:
    """The reply, tool-call and tool-result messages one record holds."""
    content = (record.get("message") or {}).get("content")
    if not isinstance(content, list):
        return []
    uuid, at = record.get("uuid", ""), record.get("timestamp", "")
    out = []
    for index, block in enumerate(content):
        if not isinstance(block, dict):
            continue
        # A record normally holds one block; the suffix keeps IDs unique when it holds more.
        ident = uuid if len(content) == 1 else "%s#%d" % (uuid, index)
        kind = block.get("type")
        if record["type"] == "assistant" and kind == "text" and block.get("text", "").strip():
            out.append(Message(id=ident, kind=TOOL_TEXT if record.get("batonMessageKind") == TOOL_TEXT else REPLY, text=block["text"], at=at))
        elif record["type"] == "assistant" and kind == "tool_use":
            out.append(Message(id=ident, kind=TOOL_CALL, at=at, tool=block.get("name", ""),
                               tool_input=block.get("input"), call_id=record.get("batonOriginalCallId", block.get("id", ""))))
        elif record["type"] == "user" and kind == "tool_result":
            out.append(Message(id=ident, kind=TOOL_RESULT, text=_result_text(block.get("content")), at=at,
                               call_id=block.get("tool_use_id", ""), is_error=bool(block.get("is_error"))))
    return out


def turns_from_records(records: list[dict]) -> list[Turn]:
    """Read the live public conversation as whole turns."""
    turns: list[Turn] = []
    prompt, messages = None, []
    for record in live_chain(records):
        if is_prompt(record):
            if prompt is not None:
                turns.append(Turn(prompt, tuple(messages)))
            prompt = Message(id=record["uuid"], kind=PROMPT, text=prompt_text(record), at=record.get("timestamp", ""))
            messages = []
        elif prompt is not None and record.get("type") in ("user", "assistant") and not record.get("isCompactSummary"):
            messages.extend(_messages(record))
    if prompt is not None:
        turns.append(Turn(prompt, tuple(messages)))
    return turns


def read_chat(path: str) -> list[Turn]:
    """Read public turns from one native chat file."""
    return turns_from_records(read_records(path))


class ClaudeReader:
    """Resolve stable sidebar ids, then read only the native live chain."""
    def __init__(self, adapter): self.adapter = adapter
    def read(self, chat_id):
        """Read the public turns for the current stable chat identity."""
        return read_chat(str(self.adapter.locator.session_path(chat_id)))
    def usage(self, chat_id):
        """Read the latest context usage and provider limit evidence."""
        from datetime import datetime, timezone
        from ...ports.tool import Usage
        records = live_chain(read_records(str(self.adapter.locator.session_path(chat_id))))
        tokens, size, reached, reset = 0, None, False, None
        for record in reversed(records):
            if record.get("type") != "assistant": continue
            if record.get("isApiErrorMessage"):
                quota = record.get("quotaLimits") or {}
                reached = record.get("apiErrorStatus") == 429 or record.get("error") == "rate_limit"
                if quota.get("resetsAt") is not None:
                    reset = datetime.fromtimestamp(quota["resetsAt"], timezone.utc).isoformat().replace("+00:00", "Z")
                continue
            message = record.get("message") or {}
            usage = message.get("usage")
            if isinstance(usage, dict):
                tokens = sum(usage.get(k, 0) or 0 for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens"))
                size = self.adapter.context_sizes.get(message.get("model"))
                break
        return Usage(tokens, size, reached, reset)
    def files_changed(self, turn):
        """Extract paths changed by native edit or write tool calls."""
        paths = []
        for message in turn.messages:
            if message.kind == TOOL_CALL and message.tool.lower() in ("write", "edit", "multiedit"):
                values = message.tool_input or {}
                if isinstance(values, dict):
                    path = values.get("file_path") or values.get("path")
                    if isinstance(path, str) and path not in paths: paths.append(path)
        return paths
