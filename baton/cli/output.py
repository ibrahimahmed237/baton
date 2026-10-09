"""Results and errors as the shared objects of docs/plan/CONTRACT.md.

Every function returns plain dicts and lists ready for `json.dumps`. Words for
the user come from the note catalogue only; this module never writes a sentence
of its own.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Iterable, Mapping, Sequence

from ..domain.conditions import SideCondition
from ..domain.errors import BatonError
from ..domain.link import LedgerTurn
from ..domain.model import Message
from ..notes.catalogue import CATALOGUE
from ..ports.tool import ChatRef, Usage
from ..services.status import SideStatus
from .tools import LABELS, label

logger = logging.getLogger(__name__)

# What the user is told about a crash or a refusal that has no note of its own.
UNEXPECTED = "error.unexpected"

# The same rough estimate services.status uses to size what a message carries.
CHARS_PER_TOKEN = 4

# Note ids whose {tool} is a tool call's name, not a coding app (CONTRACT.md, F2).
_NOT_APP_LABELS = ("mapping.",)


# Notes

def note(note_id: str, values: Mapping[str, Any] | None = None, *, lenient: bool = False) -> dict[str, Any]:
    """Render a catalogue note; values naming a coding app are replaced by its display label.

    Raises KeyError for an unknown id or a missing value, unless `lenient`, which
    fills a missing value with nothing.
    """
    values = app_labels(note_id, values or {})
    definition = CATALOGUE[note_id]
    if not lenient:
        return definition.to_dict(values)
    blanks = {name: "" for name in definition.fields if name not in values}
    return {**definition.to_dict({**blanks, **values}), "values": dict(values)}


def app_labels(note_id: str, values: Mapping[str, Any]) -> dict[str, Any]:
    """Replace tool ids in `tool`, `other_tool`, `first_tool` ... by the display label."""
    if note_id.startswith(_NOT_APP_LABELS):
        return dict(values)
    return {key: LABELS.get(value, value) if _names_a_tool(key, value) else value
            for key, value in values.items()}


def _names_a_tool(key: str, value: Any) -> bool:
    return (key == "tool" or key.endswith("_tool")) and isinstance(value, str)


def note_list(items: Iterable[tuple[str, Mapping[str, Any]] | str]) -> list[dict[str, Any]]:
    """Render a list of note ids, or (id, values) pairs."""
    result = []
    for item in items:
        note_id, values = (item, None) if isinstance(item, str) else item
        result.append(note(note_id, values))
    return result


# Shared objects

def chat(tool: str, chat_id: str, name: str, folder: str, updated_at: str,
         linked: bool = False, link_id: int | None = None) -> dict[str, Any]:
    """Chat: one chat in one tool. A missing chat is built from its last known name."""
    return {"tool": tool, "tool_label": label(tool), "id": chat_id, "name": name, "folder": folder,
            "updated_at": updated_at, "linked": linked, "link_id": link_id}


def chat_from_ref(tool: str, ref: ChatRef, linked: bool = False, link_id: int | None = None) -> dict[str, Any]:
    """Chat for a chat a locator found."""
    return chat(tool, ref.id, ref.name, ref.folder, ref.updated_at, linked, link_id)


def side_condition(value: SideCondition) -> dict[str, Any]:
    """Side.condition, with the additive CP1 fields."""
    return {"exists": value.exists, "open": value.open, "replying": value.replying,
            "hooks_ready": value.hooks_ready, "app_running": value.app_running,
            "app_started_at": value.app_started_at, "format_known": value.format_known}


def message(value: Message) -> dict[str, Any]:
    """One entry of Turn.messages. A tool name is given for tool calls and results only."""
    result = {"kind": value.kind, "text": value.text}
    if value.tool:
        result["tool"] = value.tool
    return result


def turn(value: LedgerTurn, messages: Sequence[Message] | None = None) -> dict[str, Any]:
    """Turn: one turn of a linked conversation. `messages` only when the caller asked for them."""
    result: dict[str, Any] = {
        "id": value.id, "seq": value.seq, "origin": value.origin, "first_line": value.first_line,
        "started_at": value.started_at, "ended_at": value.ended_at or None,
        "tokens": value.size // CHARS_PER_TOKEN, "pinned": value.pinned, "states": dict(value.states)}
    if messages is not None:
        result["messages"] = [message(item) for item in messages]
    return result


def side_usage(value: Usage) -> dict[str, Any]:
    """Side.usage: tokens in use, the size if known, the percent, and the limit if one was hit."""
    percent = round(value.tokens * 100 / value.size, 1) if value.size else None
    return {"tokens": value.tokens, "size": value.size, "percent": percent,
            "limit": {"resets_at": value.limit_resets_at} if value.limit_reached else None}


def since_you_left(turns: int, files: int, commands: int, since: str) -> dict[str, Any]:
    """Side.since_you_left."""
    return {"turns": turns, "files": files, "commands": commands, "since": since}


def next_message(status: SideStatus) -> dict[str, int]:
    """Side.next_message: what the next message in that chat would carry."""
    return {"turns": status.attached_on_next_message, "tokens": status.attached_tokens}


def side(status: SideStatus, *, chat_info: Mapping[str, Any], condition: SideCondition,
         usage: Mapping[str, Any], since: Mapping[str, Any] | None = None,
         notes: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
    """Side: where one side of a link stands."""
    return {
        "tool": status.side, "tool_label": label(status.side), "chat": dict(chat_info),
        "condition": side_condition(condition),
        "total": status.total, "agent_has": status.agent_has, "chat_shows": status.chat_shows,
        "added": status.added, "attached": status.attached, "waiting": status.waiting,
        "kept_elsewhere": status.kept_elsewhere, "skipped": status.skipped,
        "synced_up_to": turn(status.synced_up_to) if status.synced_up_to else None,
        "waiting_reason": status.waiting_reason or None,
        "next_message": next_message(status), "usage": dict(usage),
        "since_you_left": dict(since) if since else None,
        "notes": [dict(item) for item in notes]}


def step(tool: str, action: str, turn_ids: Iterable[int], *, reason: str = "",
         needs: Iterable[str] = (), notes: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
    """Step: what a plan does to one side."""
    return {"tool": tool, "tool_label": label(tool), "action": action, "turns": list(turn_ids),
            "reason": reason, "needs": list(needs), "notes": [dict(item) for item in notes]}


def plan(plan_id: str, link_id: int | None, steps: Sequence[Mapping[str, Any]], *,
         decision_needed: bool = False, notes: Sequence[Mapping[str, Any]] = (),
         applied: bool = False, **extra: Any) -> dict[str, Any]:
    """Plan: what an action would do. `extra` adds a command's own fields (removes, brief ...)."""
    return {"plan_id": plan_id, "applied": applied, "link_id": link_id,
            "steps": [dict(item) for item in steps], "decision_needed": decision_needed,
            "notes": [dict(item) for item in notes], **extra}


# Errors

def snake_case(name: str) -> str:
    """ChatChanged -> chat_changed."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def error(failure: BatonError, values: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The error object for an expected refusal: its kind and the note that explains it.

    A refusal with no catalogue note gets the plain `error.unexpected` note; what
    the exception said goes to the log, never to the user.
    """
    shown = {**getattr(failure, "values", {}), **(values or {})}
    if getattr(failure, "side", None):
        shown.setdefault("tool", failure.side)
    try:
        explained = note(failure.note_id, shown, lenient=True)
    except KeyError:
        logger.warning("no note for %s (%r): %s", type(failure).__name__, failure.note_id, failure)
        explained = note(UNEXPECTED)
    return {"error": {"kind": snake_case(type(failure).__name__), "note": explained}}


def internal_error(failure: BaseException) -> dict[str, Any]:
    """The error object for a crash: the plain note only. The details are logged by the caller."""
    return {"error": {"kind": "internal", "note": note(UNEXPECTED)}}


def usage_error(message_text: str) -> dict[str, Any]:
    """The error object for a command line that could not be understood."""
    return {"error": {"kind": "usage", "message": message_text}}
