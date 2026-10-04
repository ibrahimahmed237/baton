"""Read a Codex chat (a rollout file) into turns.

A rollout is a plain sequence of records. The conversation the agent has is in
its `response_item` records; the rest drives Codex's own chat view. Codex also
writes text of its own as user messages (environment, instructions, app state),
which are not prompts.
"""
from __future__ import annotations

import json

from .model import PROMPT, REPLY, TOOL_CALL, TOOL_RESULT, Message, Turn

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
        kind, at = payload.get("type"), record.get("timestamp", "")
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
                messages.append(Message(id=ident, kind=REPLY, text=text, at=at))
        elif kind in _TOOL_CALLS:
            messages.append(Message(id=ident, kind=TOOL_CALL, at=at, tool=payload.get("name") or kind,
                                    tool_input=_tool_input(payload), call_id=payload.get("call_id", "")))
        elif kind in _TOOL_RESULTS:
            messages.append(Message(id=ident, kind=TOOL_RESULT, at=at, call_id=payload.get("call_id", ""),
                                    text=_result_text(payload.get("output", payload.get("tools")))))
    if prompt is not None:
        turns.append(Turn(prompt, tuple(messages)))
    return turns


def read_chat(path: str) -> list[Turn]:
    return turns_from_records(read_records(path))
