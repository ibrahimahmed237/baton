"""Represent whole turns using target facts, without carrying private reasoning."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from typing import Sequence

from ..domain.capabilities import Capabilities
from ..domain.model import Message, Turn, PROMPT, REPLY, TOOL_CALL, TOOL_RESULT, TOOL_TEXT
from ..notes.catalogue import get


def _tool_text(message: Message, calls: dict[str, int]) -> str:
    if message.kind == TOOL_CALL:
        return get('mapping.tool_call').render({
            'n': calls[message.id], 'tool': message.tool,
            'input': json.dumps(message.tool_input, sort_keys=True, ensure_ascii=False),
            'text': message.text}).template
    return get('mapping.tool_result').render({
        'n': calls.get(message.call_id, 0), 'text': message.text,
        'is_error': json.dumps(message.is_error)}).template


def _messages(turn: Turn):
    # Only the public message kinds cross; unknown reasoning variants stay private too.
    messages = [m for m in turn.messages if m.kind in (REPLY, TOOL_CALL, TOOL_RESULT, TOOL_TEXT)]
    calls = {m.id: index for index, m in enumerate(
        (m for m in messages if m.kind == TOOL_CALL), start=1)}
    for message in messages:
        if message.kind == TOOL_RESULT and message.call_id and message.call_id not in calls:
            calls[message.call_id] = len(calls) + 1
    return messages, calls


def for_target(turn: Turn, facts: Capabilities) -> Turn:
    """Keep public messages and either real tool blocks or labelled activity text."""
    messages, calls = _messages(turn)
    mapped = []
    for message in messages:
        if message.kind in (TOOL_CALL, TOOL_RESULT) and not facts.replays_tool_calls:
            mapped.append(Message(message.id, TOOL_TEXT, _tool_text(message, calls), message.at))
        else:
            mapped.append(deepcopy(message))
    return Turn(deepcopy(turn.prompt), tuple(mapped))


def for_created_chat(turns: Sequence[Turn], facts: Capabilities) -> list[Turn]:
    """Map a new chat without changing its user's prompt."""
    return [for_target(turn, facts) for turn in turns]


def marker(source_tool: str) -> str:
    """Return separate hand-off metadata without inserting a user turn."""
    return get('history.marker').render({'tool': source_tool}).template


def title(name: str, source_tool: str, title_tag: bool = False) -> str:
    """Optionally distinguish a created chat in the tool's own title."""
    if title_tag:
        return get('history.title_tag').render({'tool': source_tool}).template + ' ' + name
    return name


def content_key(turn: Turn) -> str:
    """Match copied public content across ids, timestamps and replay representations."""
    messages, calls = _messages(turn)
    content = [(PROMPT, turn.prompt.text)]
    content.extend((TOOL_TEXT, _tool_text(m, calls)) if m.kind in (TOOL_CALL, TOOL_RESULT)
                   else (m.kind, m.text) for m in messages)
    encoded = json.dumps(content, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    return sha256(encoded).hexdigest()
