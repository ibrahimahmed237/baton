"""Links, recorded turns, history events, and per-side states."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

CLAUDE = "claude"
CODEX = "codex"
TOOLS = (CLAUDE, CODEX)

# How a link was made (DESIGN.md, section 4).
FULL_COPY = "full_copy"
ATTACHED_HISTORY = "attached_history"
MODES = (FULL_COPY, ATTACHED_HISTORY)

# The state of one turn on one side.
WRITTEN_HERE = "written_here"
SHOWN = "shown"
ADDED = "added"  # in the chat file and known to the agent; shown after a relaunch
ATTACHED = "attached"
WAITING = "waiting"
SKIPPED = "skipped"
KEPT_BACK = "kept_back"

DELIVERED = (SHOWN, ADDED, ATTACHED)
AGENT_HAS = (WRITTEN_HERE,) + DELIVERED
CHAT_SHOWS = (WRITTEN_HERE, SHOWN)


@dataclass(frozen=True)
class Link:
    id: int
    chats: dict[str, str]  # tool -> chat
    mode: str
    paused: bool
    created_at: str
    removed_at: str = ""

    @property
    def sides(self) -> tuple[str, ...]:
        return tuple(self.chats)

    def chat(self, side: str) -> str:
        return self.chats[side]

    def others(self, side: str) -> tuple[str, ...]:
        return tuple(tool for tool in self.chats if tool != side)


@dataclass(frozen=True)
class LedgerTurn:
    id: int
    seq: int
    origin: str
    origin_id: str
    started_at: str
    ended_at: str
    first_line: str
    size: int
    pinned: bool
    states: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Event:
    id: int
    at: str
    kind: str
    side: str
    detail: dict[str, Any]
    turn_ids: tuple[int, ...] = ()
