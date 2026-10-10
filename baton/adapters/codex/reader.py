"""Read a Codex chat (a rollout file) into turns.

A rollout is a plain sequence of records. The conversation the agent has is in
its `response_item` records; the rest drives Codex's own chat view. Codex also
writes text of its own as user messages (environment, instructions, app state),
which are not prompts.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from ...domain.model import PROMPT, REPLY, TOOL_CALL, TOOL_RESULT, TOOL_TEXT, Message, Turn
from ...ports.tool import Usage
from .records import records_from_end

# Blocks Codex, its plugins or Baton put into a user message. None is typed by the user.
_INJECTED_PREFIXES = (
    "<environment_context>",
    "<permissions instructions>",
    "# AGENTS.md instructions",
    "<user_instructions>",
    "<INSTRUCTIONS>",
    "<recommended_plugins>",
    "<codex_internal_context",
    "<external_codex_apps",
    "<send_user_message",
    "<skills",
    "<app_context",
    "<turn_aborted",
    "<system_reminder",
    "<collaboration_mode",
    "<realtime",
    "<plugin",
    "<baton-catch-up>",
)
_TOOL_CALLS = ("function_call", "custom_tool_call", "tool_search_call")
_TOOL_RESULTS = ("function_call_output", "custom_tool_call_output", "tool_search_output")


def read_records(path: str) -> list[dict]:
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


def _texts(content) -> list[str]:
    if isinstance(content, str):
        return [content]
    return [b.get("text", "") for b in content or []
            if isinstance(b, dict) and b.get("type") in ("input_text", "output_text", "text")]


def prompt_text(payload: dict) -> str:
    """What the user typed in this message; empty when the whole message was put there by Codex."""
    typed = [t.strip() for t in _texts(payload.get("content")) if not t.lstrip().startswith(_INJECTED_PREFIXES)]
    return "\n".join(t for t in typed if t)


def _result_text(output) -> str:
    if isinstance(output, list):
        return "".join(_texts(output))
    if isinstance(output, dict):
        return json.dumps(output, ensure_ascii=False)
    return "" if output is None else str(output)


def _tool_input(payload: dict):
    raw = payload.get("arguments", payload.get("input"))
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except ValueError:
            return raw
    return raw


def turns_from_records(records: list[dict]) -> list[Turn]:
    turns: list[Turn] = []
    prompt, messages = None, []
    for record in records:
        if record.get("type") != "response_item":
            continue
        payload = record.get("payload") or {}
        kind = payload.get("type")
        # Baton marks a time its source chat did not have, so it reads back as empty.
        at = "" if record.get("batonAtUnknown") else record.get("timestamp", "")
        # Turns Codex imported or Baton wrote carry no ID of their own; the ordinal is unique in the file.
        ident = payload.get("id") or "ordinal-%s" % record.get("ordinal")
        if kind == "message" and payload.get("role") == "user":
            text = prompt_text(payload)
            if not text:
                continue
            if prompt is not None:
                turns.append(Turn(prompt, tuple(messages)))
            prompt, messages = Message(id=ident, kind=PROMPT, text=text, at=at), []
        elif prompt is None:
            continue
        elif kind == "message" and payload.get("role") == "assistant":
            text = "".join(_texts(payload.get("content")))
            if text.strip():
                # Baton writes flattened tool activity as ordinary assistant text and marks it.
                reply_kind = TOOL_TEXT if record.get("batonMessageKind") == TOOL_TEXT else REPLY
                messages.append(Message(id=ident, kind=reply_kind, text=text, at=at))
        elif kind in _TOOL_CALLS:
            messages.append(Message(id=ident, kind=TOOL_CALL, at=at, tool=payload.get("name") or kind,
                                    tool_input=_tool_input(payload),
                                    call_id=record.get("batonOriginalCallId", payload.get("call_id", ""))))
        elif kind in _TOOL_RESULTS:
            messages.append(Message(id=ident, kind=TOOL_RESULT, at=at, call_id=payload.get("call_id", ""),
                                    text=_result_text(payload.get("output", payload.get("tools")))))
    if prompt is not None:
        turns.append(Turn(prompt, tuple(messages)))
    return turns


def read_chat(path: str) -> list[Turn]:
    return turns_from_records(read_records(path))


def commands_run(turn: Turn) -> int:
    """Count native shell/exec calls; polling and ordinary tools are not commands."""
    names = {'shell', 'shell_command', 'exec_command'}
    return sum(message.kind == TOOL_CALL and message.tool.rsplit('.', 1)[-1] in names
               for message in turn.messages)


_PATCHED_FILE = re.compile(r"^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+?)\s*$", re.M)
_EDIT_TOOLS = ("write", "edit", "multiedit")


def _iso(seconds) -> str | None:
    if not isinstance(seconds, (int, float)):
        return None
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _limit_reset(limits: dict, now: datetime) -> str | None:
    """When the limit that was reached ends, or None when none was reached or it has ended already."""
    windows = {name: limits[name] for name in ("primary", "secondary") if isinstance(limits.get(name), dict)}
    full = [name for name, window in windows.items() if (window.get("used_percent") or 0) >= 100]
    named = limits.get("rate_limit_reached_type")
    if not full and not named:
        return None
    if not full:
        full = ["secondary" if "secondary" in str(named).lower() else "primary"]
    resets = [windows[name].get("resets_at") for name in full if name in windows]
    resets = [r for r in resets if isinstance(r, (int, float))]
    latest = max(resets, default=None)
    if latest is not None and latest <= now.timestamp():
        return None
    return _iso(latest) if latest is not None else ""


class CodexReader:
    """Read a chat through the locator: its turns, its context in use and its limit."""

    def __init__(self, adapter):
        self.adapter = adapter

    def read(self, chat_id: str) -> list[Turn]:
        """The turns of one chat."""
        return read_chat(str(self.adapter.locator.rollout_path(chat_id)))

    def usage(self, chat_id: str) -> Usage:
        """Context in use and the limit, from the last token_count events of the rollout."""
        path = self.adapter.locator.rollout_path(chat_id)
        info, limits = None, None
        for record in records_from_end(path):
            payload = record.get("payload") or {}
            if record.get("type") != "event_msg" or payload.get("type") != "token_count":
                continue
            if limits is None and isinstance(payload.get("rate_limits"), dict):
                limits = payload["rate_limits"]
            if info is None and isinstance(payload.get("info"), dict):
                info = payload["info"]
            if info is not None and limits is not None:
                break
        last = (info or {}).get("last_token_usage") or {}
        tokens = last.get("total_tokens")
        if not isinstance(tokens, int):
            tokens = sum(last.get(key) or 0 for key in ("input_tokens", "output_tokens"))
        size = (info or {}).get("model_context_window")
        reset = _limit_reset(limits or {}, self.adapter.now())
        return Usage(tokens, size if isinstance(size, int) else None, reset is not None, reset or None)

    def files_changed(self, turn: Turn) -> list[str]:
        """Paths the turn's edits touched: edit-style tool calls and apply_patch patches."""
        paths: list[str] = []

        def note(path) -> None:
            if isinstance(path, str) and path and path not in paths:
                paths.append(path)

        for message in turn.messages:
            if message.kind != TOOL_CALL:
                continue
            values = message.tool_input
            if message.tool.lower() in _EDIT_TOOLS and isinstance(values, dict):
                note(values.get("file_path") or values.get("path"))
            # apply_patch arrives either as its own tool or as the argument of a shell call.
            for text in _strings(values):
                for path in _PATCHED_FILE.findall(text) if "*** Begin Patch" in text else ():
                    note(path)
        return paths

    def commands_run(self, turn: Turn) -> int:
        """Count native shell/exec calls; polling and ordinary tools are not commands."""
        return commands_run(turn)


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)
