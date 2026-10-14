"""How full each side's agent is, and whether it has reached a usage limit.

Answers working-across W1, W3, W5 and W6. The numbers come from the reader's
`Usage`; this module never guesses a context size or a reset time the tool did
not record (see the "no estimates" non-goal of that spec).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timezone, tzinfo
from typing import Any, Mapping

from ..ports.clock import Clock
from ..ports.tool import ChatReader, Usage
from .noteformat import NoteRef, clock_time, count, day_of, parse_time

# W6: above this share of the context the tool will soon summarise the chat itself.
NEARLY_FULL_PERCENT = 80


@dataclass(frozen=True)
class ContextUse:
    """Tokens in use, and their share of the context only when the size is known."""
    tokens: int
    size: int | None
    percent: int | None
    nearly_full: bool


@dataclass(frozen=True)
class LimitState:
    """What the tool recorded about a usage limit at the end of the latest turn."""
    reached: bool
    resets_at: str | None
    available_again: bool  # a reset time was given and has passed

    @property
    def blocking(self) -> bool:
        """Whether the tool still cannot be asked: reached, and not known to be over."""
        return self.reached and not self.available_again


@dataclass(frozen=True)
class SideUsage:
    """One side's context use and limit, with the notes that say so."""
    side: str
    context: ContextUse
    limit: LimitState
    notes: tuple[NoteRef, ...]

    def as_contract(self) -> dict[str, Any]:
        """The `usage` object of CONTRACT.md; size, percent and limit are null when not known."""
        return {"tokens": self.context.tokens, "size": self.context.size,
                "percent": self.context.percent,
                "limit": {"resets_at": self.limit.resets_at} if self.limit.blocking else None}


def context_use(usage: Usage) -> ContextUse:
    """Work out the share of the context in use. No size, no percentage (V6)."""
    tokens = max(usage.tokens, 0)
    size = usage.size if usage.size and usage.size > 0 else None
    # Rounded half up in integers, so 82.0 never shows as 81 through a float.
    percent = (tokens * 200 + size) // (2 * size) if size else None
    nearly_full = size is not None and tokens * 100 > size * NEARLY_FULL_PERCENT
    return ContextUse(tokens, size, percent, nearly_full)


def limit_state(usage: Usage, now: str) -> LimitState:
    """Read the limit. "Available again" is only ever claimed from a reset time that has passed."""
    if not usage.limit_reached:
        return LimitState(False, None, False)
    reset = parse_time(usage.limit_resets_at)
    current = parse_time(now)
    resets_at = usage.limit_resets_at if reset else None
    return LimitState(True, resets_at, bool(reset and current and current >= reset))


class UsageService:
    """Report usage per side from the readers; stateless between calls."""

    def __init__(self, readers: Mapping[str, ChatReader], clock: Clock, tz: tzinfo = timezone.utc):
        self.readers, self.clock, self.tz = readers, clock, tz

    def limit(self, side: str, chat_id: str) -> LimitState:
        """The limit state of one side's chat."""
        return limit_state(self.readers[side].usage(chat_id), self.clock.now())

    def side(self, side: str, chat_id: str, other: str | None = None) -> SideUsage:
        """Usage and limit of one side. `other` is the tool to suggest continuing in, if any."""
        usage = self.readers[side].usage(chat_id)
        now = self.clock.now()
        context, limit = context_use(usage), limit_state(usage, now)
        return SideUsage(side, context, limit, tuple(self._notes(side, other, context, limit)))

    def _notes(self, side: str, other: str | None, context: ContextUse, limit: LimitState):
        if limit.blocking:
            yield NoteRef("limit.reached", {"tool": side})
            if limit.resets_at:
                yield NoteRef("limit.available_at", {"tool": side, "time": self._time(limit.resets_at)})
        elif limit.reached:
            yield NoteRef("limit.available", {"tool": side})
        if not context.tokens:
            return
        if context.size is None:
            yield NoteRef("context.in_use_no_size", {"tokens": count(context.tokens)})
            return
        yield NoteRef("context.in_use", {"tokens": count(context.tokens), "percent": context.percent,
                                         "size": count(context.size)})
        if context.nearly_full:
            if other:
                yield NoteRef("context.nearly_full", {"tool": side, "other_tool": other})
            else:
                yield NoteRef("context.nearly_full_alone", {"tool": side})

    def _time(self, value: str) -> str:
        return clock_time(value, self.tz, day_of(self.clock.now(), self.tz))
