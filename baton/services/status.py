"""Where each side of a link stands, worked out from the link_states.

Answers the questions of docs/features/sync-status.md (R1 to R4): how many turns
this side's agent has, how many its chat shows, what is waiting and why, and
what happens on the next message there. Nothing here reads or writes a chat; the
caller says what condition each chat is in.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Collection, Mapping, Sequence

from ..domain import link as link_states
from ..domain.link import Event, LedgerTurn, Link
from ..domain.capabilities import Capabilities, Visibility, WriteWindow
from ..domain.conditions import SideCondition

# Why turns are waiting on a side (R4), most important first.
SIDE_MISSING = "side_missing"
PAUSED = "paused"
DECISION_NEEDED = "decision_needed"
HOOKS_NOT_READY = "hooks_not_ready"
CHAT_OPEN = "chat_open"
NOT_SYNCED_YET = "not_synced_yet"
FORMAT_UNKNOWN = "format_unknown"

ADD = "add"
ADD_AFTER_RELEASE = "add_after_release"
ATTACH = "attach"
HOLD = "hold"

_CHARS_PER_TOKEN = 4


@dataclass(frozen=True)
class SideStatus:
    """Counts and pending delivery/visibility instructions for one chat."""
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
    shown_turn_ids: tuple[int, ...] = ()
    needs: tuple[str, ...] = ()

    @property
    def in_sync(self) -> bool:
        """Whether this agent has every available turn."""
        return self.waiting == 0


@dataclass(frozen=True)
class LinkStatus:
    """Delivery status of all linked sides."""
    sides: dict[str, SideStatus]
    paused: bool
    decision_needed: bool

    @property
    def in_sync(self) -> bool:
        """Every agent has every turn. A side can be in sync and show fewer turns."""
        return all(status.in_sync for status in self.sides.values())

    def side(self, side: str) -> SideStatus:
        """Return a single side’s status."""
        return self.sides[side]


def link_status(link: Link, turns: Sequence[LedgerTurn],
                conditions: Mapping[str, SideCondition] | None = None, *,
                facts: Mapping[str, Capabilities], history: Sequence[Event] = (),
                add_when_idle: Collection[str] = (),
                initial_history_sides: Collection[str] = ()) -> LinkStatus:
    """Compute status from facts and explicit delivery/relaunch evidence."""
    conditions = conditions or {}
    in_conflict = set() if merge_decision_applies(link, turns, history) else _in_conflict(turns)
    sides = {side: _side_status(link, turns, side, conditions.get(side, SideCondition()), side in in_conflict, facts[side], history, side in add_when_idle, side in initial_history_sides)
             for side in link.sides}
    return LinkStatus(sides, link.paused, bool(in_conflict))


def merge_decision_applies(link: Link, turns: Sequence[LedgerTurn], history: Sequence[Event]) -> bool:
    """Only the exact pending deliveries explicitly approved for these chats bypass S7."""
    merge = next((event for event in history if event.kind == 'merge'), None)
    if merge is None or merge.detail.get('chats') != link.chats:
        return False
    approved = merge.detail.get('pending', {})
    pending = {(turn.id, side) for turn in turns for side, state in turn.states.items()
               if state == link_states.WAITING}
    allowed = {(ident, side) for side, ids in approved.items() for ident in ids}
    return bool(pending) and pending.issubset(allowed)


def _in_conflict(turns: Sequence[LedgerTurn]) -> set[str]:
    """Sides that each have a turn the other is waiting for: the user has to decide the order."""
    waits = {(turn.origin, side) for turn in turns
             for side, state in turn.states.items() if state == link_states.WAITING}
    return {side for origin, side in waits if (side, origin) in waits}


def _side_status(link: Link, turns: Sequence[LedgerTurn], side: str,
                 condition: SideCondition, conflict: bool, facts: Capabilities,
                 history: Sequence[Event], automatic: bool, initial_history: bool = False) -> SideStatus:
    def count(*states: str) -> int:
        return sum(1 for turn in turns if turn.states.get(side) in states)

    waiting = [turn for turn in turns if turn.states.get(side) == link_states.WAITING]
    reason = _waiting_reason(link, condition, conflict) if waiting else ""
    # Use the planner policy so status cannot promise attachment for an add-only side.
    action, delivery_reason, _, _ = delivery_choice(link, condition, facts, reason, automatic, initial_history)
    if waiting:
        reason = NOT_SYNCED_YET if action == ADD else delivery_reason
    carried = waiting if action == ATTACH else []
    visible = visible_added_turn_ids(turns, side, facts, condition, history)
    remaining_added = count(link_states.ADDED) - len(visible)
    needs = ()
    if remaining_added:
        needs = ("reopen_chat_to_see",) if facts.added_turn_visible == Visibility.ON_REOPEN_CHAT else ("relaunch_to_see",)
    return SideStatus(
        side=side,
        total=len(turns),
        agent_has=count(*link_states.AGENT_HAS),
        chat_shows=count(*link_states.CHAT_SHOWS) + len(visible),
        added=remaining_added,
        attached=count(link_states.ATTACHED),
        waiting=len(waiting),
        kept_elsewhere=count(link_states.KEPT_BACK),
        skipped=count(link_states.SKIPPED),
        synced_up_to=_synced_up_to(turns, side),
        waiting_reason=reason,
        attached_on_next_message=len(carried),
        attached_tokens=sum(turn.size for turn in carried) // _CHARS_PER_TOKEN,
        shown_turn_ids=visible,
        needs=needs,
    )


def _waiting_reason(link: Link, condition: SideCondition, conflict: bool) -> str:
    if not condition.exists:
        return SIDE_MISSING
    if link.paused:
        return PAUSED
    if conflict:
        return DECISION_NEEDED
    if not condition.format_known and not (condition.open and condition.hooks_ready):
        return FORMAT_UNKNOWN
    if condition.open:
        return CHAT_OPEN if condition.hooks_ready else HOOKS_NOT_READY
    return NOT_SYNCED_YET


def _synced_up_to(turns: Sequence[LedgerTurn], side: str) -> LedgerTurn | None:
    """The last turn this side's agent has before the first one it is waiting for (R2)."""
    last = None
    for turn in turns:
        state = turn.states.get(side)
        if state == link_states.WAITING:
            break
        if state in link_states.AGENT_HAS:
            last = turn
    return last


def visible_added_turn_ids(turns: Sequence[LedgerTurn], side: str, facts: Capabilities,
                           condition: SideCondition, history: Sequence[Event] = ()) -> tuple[int, ...]:
    """Return added turns proven visible, never using a prompt-hook call."""
    added = [turn.id for turn in turns if turn.states.get(side) == link_states.ADDED]
    if facts.added_turn_visible == Visibility.AT_ONCE:
        return tuple(added)
    delivered = {}
    for event in sorted(history, key=lambda item: item.id):
        if event.side == side and event.kind in ("added", "twin_created", "created", "synced", "delivered", "add", "add_after_release", "create", "place"):
            for turn_id in event.turn_ids:
                delivered[turn_id] = event.at
        if event.kind == "merge":
            for write in event.detail.get("writes", ()):
                if write.get("side") == side and write.get("action") in ("add", "create"):
                    for turn_id in write.get("turn_ids", ()):
                        delivered[turn_id] = event.at
    return tuple(turn_id for turn_id in added
                 if _later(condition.app_started_at, delivered.get(turn_id, "")))


def _later(start: str, delivered: str) -> bool:
    try:
        if not start or not delivered:
            return False
        started_at = datetime.fromisoformat(start)
        delivered_at = datetime.fromisoformat(delivered)
        return bool(started_at.tzinfo and delivered_at.tzinfo) and started_at > delivered_at
    except (ValueError, TypeError):
        return False

def delivery_choice(link: Link, condition: SideCondition, facts: Capabilities,
                    reason: str, automatic: bool = False, initial_history: bool = False) -> tuple[str, str, tuple[str, ...], tuple[str, ...]]:
    """Select a safe action and note metadata for a single waiting side."""
    if reason in (SIDE_MISSING, PAUSED, DECISION_NEEDED):
        return HOLD, reason, (), ()
    if not condition.format_known:
        action = ATTACH if condition.open and condition.hooks_ready else HOLD
        return action, FORMAT_UNKNOWN, (), ()
    if initial_history:
        return (ATTACH, 'initial_history', (), ()) if condition.hooks_ready else (HOLD, HOOKS_NOT_READY, (), ())
    window = facts.write_window
    allowed = (window == WriteWindow.ANY_TIME
               or window == WriteWindow.NOT_HELD and not condition.open
               or window == WriteWindow.APP_CLOSED and not condition.app_running
               or window == WriteWindow.CLOSED_OR_RELEASED and not condition.open)
    if allowed:
        needs = ("reopen_chat_to_see",) if window == WriteWindow.ANY_TIME and condition.open else ()
        return ADD, "", needs, ()
    releasable = (window == WriteWindow.CLOSED_OR_RELEASED and condition.open
                  and not condition.replying and facts.can_release_chat
                  and link.mode == link_states.FULL_COPY)
    if releasable and automatic:
        return ADD_AFTER_RELEASE, CHAT_OPEN, ("relaunch_to_see",), ("relaunch",)
    alternatives = ("close_sync_reopen",)
    if releasable:
        alternatives += ("add_now",)
    if (condition.open or window == WriteWindow.APP_CLOSED and condition.app_running) and condition.hooks_ready:
        return ATTACH, CHAT_OPEN, (), alternatives
    return HOLD, HOOKS_NOT_READY, (), alternatives
