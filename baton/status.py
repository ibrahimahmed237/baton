"""Where each side of a link stands, worked out from the ledger.

Answers the questions of docs/features/sync-status.md (R1 to R4): how many turns
this side's agent has, how many its chat shows, what is waiting and why, and
what happens on the next message there. Nothing here reads or writes a chat; the
caller says what condition each chat is in.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from . import ledger
from .ledger import LedgerTurn, Link

# Why turns are waiting on a side (R4), most important first.
SIDE_MISSING = "side_missing"
PAUSED = "paused"
DECISION_NEEDED = "decision_needed"
HOOKS_NOT_READY = "hooks_not_ready"
CHAT_OPEN = "chat_open"
NOT_SYNCED_YET = "not_synced_yet"

_CHARS_PER_TOKEN = 4


@dataclass(frozen=True)
class SideCondition:
    """What is true of one side's chat right now."""
    exists: bool = True
    open: bool = False
    hooks_ready: bool = True


@dataclass(frozen=True)
class SideStatus:
    side: str
    total: int            # turns in the conversation
    agent_has: int
    chat_shows: int
    added: int            # known to the agent, shown after a relaunch
    attached: int         # known to the agent, never shown
    waiting: int
    kept_elsewhere: int   # kept back where they were written; never coming here
    skipped: int
    synced_up_to: LedgerTurn | None
    waiting_reason: str   # '' when nothing is waiting
    attached_on_next_message: int
    attached_tokens: int  # rough size of what the next message carries

    @property
    def in_sync(self) -> bool:
        return self.waiting == 0


@dataclass(frozen=True)
class LinkStatus:
    sides: dict[str, SideStatus]
    paused: bool
    decision_needed: bool

    @property
    def in_sync(self) -> bool:
        """Every agent has every turn. A side can be in sync and show fewer turns."""
        return all(status.in_sync for status in self.sides.values())

    def side(self, side: str) -> SideStatus:
        return self.sides[side]


def link_status(link: Link, turns: Sequence[LedgerTurn],
                conditions: Mapping[str, SideCondition] | None = None) -> LinkStatus:
    conditions = conditions or {}
    in_conflict = _in_conflict(turns)
    sides = {side: _side_status(link, turns, side, conditions.get(side, SideCondition()), side in in_conflict)
             for side in link.sides}
    return LinkStatus(sides, link.paused, bool(in_conflict))


def _in_conflict(turns: Sequence[LedgerTurn]) -> set[str]:
    """Sides that each have a turn the other is waiting for: the user has to decide the order."""
    waits = {(turn.origin, side) for turn in turns
             for side, state in turn.states.items() if state == ledger.WAITING}
    return {side for origin, side in waits if (side, origin) in waits}


def _side_status(link: Link, turns: Sequence[LedgerTurn], side: str,
                 condition: SideCondition, conflict: bool) -> SideStatus:
    def count(*states: str) -> int:
        return sum(1 for turn in turns if turn.states.get(side) in states)

    waiting = [turn for turn in turns if turn.states.get(side) == ledger.WAITING]
    reason = _waiting_reason(link, condition, conflict) if waiting else ""
    carried = waiting if reason == CHAT_OPEN else []
    return SideStatus(
        side=side,
        total=len(turns),
        agent_has=count(*ledger.AGENT_HAS),
        chat_shows=count(*ledger.CHAT_SHOWS),
        added=count(ledger.ADDED),
        attached=count(ledger.ATTACHED),
        waiting=len(waiting),
        kept_elsewhere=count(ledger.KEPT_BACK),
        skipped=count(ledger.SKIPPED),
        synced_up_to=_synced_up_to(turns, side),
        waiting_reason=reason,
        attached_on_next_message=len(carried),
        attached_tokens=sum(turn.size for turn in carried) // _CHARS_PER_TOKEN,
    )


def _waiting_reason(link: Link, condition: SideCondition, conflict: bool) -> str:
    if not condition.exists:
        return SIDE_MISSING
    if link.paused:
        return PAUSED
    if conflict:
        return DECISION_NEEDED
    if condition.open:
        return CHAT_OPEN if condition.hooks_ready else HOOKS_NOT_READY
    return NOT_SYNCED_YET


def _synced_up_to(turns: Sequence[LedgerTurn], side: str) -> LedgerTurn | None:
    """The last turn this side's agent has before the first one it is waiting for (R2)."""
    last = None
    for turn in turns:
        state = turn.states.get(side)
        if state == ledger.WAITING:
            break
        if state in ledger.AGENT_HAS:
            last = turn
    return last
