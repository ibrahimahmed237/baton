"""What a sync would do, worked out before anything is written.

Two questions are answered here, both from the ledger alone:

- `plan_sync`: for each side, are its waiting turns added to the chat, attached
  to the next message, or held, and why (DESIGN.md section 4).
- the merge helpers: when both sides have turns the other never received, which
  orders are allowed and what each order means for each chat
  (docs/features/merge.md).

Nothing here reads or writes a chat. The applier carries a plan out.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Collection, Mapping, Sequence

from . import status
from ..domain import link as link_states
from ..domain.link import LedgerTurn, Link
from ..domain.conditions import SideCondition
from ..domain.capabilities import Capabilities
from ..domain.errors import OrderNotAllowed

# What happens to a side's waiting turns.
ADD = status.ADD                              # the chat is closed: added as normal messages
ADD_AFTER_RELEASE = status.ADD_AFTER_RELEASE  # open but idle: its process is closed, then added; shown after a relaunch
ATTACH = status.ATTACH                        # open: attached to the user's next message there
HOLD = status.HOLD                            # nothing is done now; the reason says why

# Ways to order a merge (merge.md, M3 to M6).
BY_TIME = "by_time"
DONT_REORDER = "dont_reorder"

# What a merge means for one side's chat (M5).
KEEPS_CHAT = "keeps_chat"
MERGED_COPY = "merged_copy"


@dataclass(frozen=True)
class Step:
    """One side’s delivery action, required visibility step and alternatives."""
    side: str
    action: str
    turns: tuple[LedgerTurn, ...]
    reason: str = ""
    needs: tuple[str, ...] = ()
    alternatives: tuple[str, ...] = ()


@dataclass(frozen=True)
class Plan:
    """A preview of delivery without changing a chat."""
    steps: dict[str, Step]  # only sides that have waiting turns
    decision_needed: bool

    @property
    def writes_anything(self) -> bool:
        """Whether applying this plan would write real messages."""
        return any(step.action in (ADD, ADD_AFTER_RELEASE) for step in self.steps.values())


def plan_sync(link: Link, turns: Sequence[LedgerTurn],
              conditions: Mapping[str, SideCondition] | None = None,
              add_when_idle: Collection[str] = (), *,
              facts: Mapping[str, Capabilities],
              initial_history_sides: Collection[str] = ()) -> Plan:
    """Choose delivery from capabilities and current state, without tool names."""
    conditions = conditions or {}
    current = status.link_status(link, turns, conditions, facts=facts, add_when_idle=add_when_idle,
                                 initial_history_sides=initial_history_sides)
    steps = {}
    for side, side_status in current.sides.items():
        waiting = tuple(turn for turn in turns if turn.states.get(side) == link_states.WAITING)
        if not waiting:
            continue
        condition = conditions.get(side, SideCondition())
        action, reason, needs, alternatives = status.delivery_choice(
            link, condition, facts[side], side_status.waiting_reason,
            side in add_when_idle, side in initial_history_sides)
        steps[side] = Step(side, action, waiting, reason, needs, alternatives)
    return Plan(steps, current.decision_needed)


# Merging, when both sides have turns the other never received.

def unsynced(turns: Sequence[LedgerTurn]) -> list[LedgerTurn]:
    """Turns some side is still waiting for, in conversation order."""
    return [turn for turn in turns if link_states.WAITING in turn.states.values()]


def last_shared(turns: Sequence[LedgerTurn]) -> LedgerTurn | None:
    """The last turn every side has, before the first unsynced one (M2)."""
    shared = None
    for turn in turns:
        if link_states.WAITING in turn.states.values():
            break
        if all(state in link_states.AGENT_HAS for state in turn.states.values()):
            shared = turn
    return shared


def merge_order(turns: Sequence[LedgerTurn], preset: str = BY_TIME) -> list[LedgerTurn]:
    """The unsynced turns in a preset order: by time, or one side's first (name the side).

    Every order keeps each app's own turns in the order they were written.
    """
    pending = unsynced(turns)
    sides = list(dict.fromkeys(turn.origin for turn in pending))
    if preset in (BY_TIME, DONT_REORDER):
        queues = [[turn for turn in pending if turn.origin == side] for side in sides]
        ordered = []
        while any(queues):
            heads = [queue for queue in queues if queue]
            queue = min(heads, key=lambda q: (q[0].started_at, q[0].seq))
            ordered.append(queue.pop(0))
        return ordered
    if preset not in sides:
        raise ValueError("no_unsynced_turns:" + preset)
    return sorted(pending, key=lambda turn: (turn.origin != preset, turn.seq))


def check_order(turns: Sequence[LedgerTurn], order: Sequence[LedgerTurn]) -> None:
    """Raise unless `order` is the unsynced turns with each app's own turns in their own order (M4)."""
    pending = unsynced(turns)
    if sorted(turn.id for turn in order) != sorted(turn.id for turn in pending):
        raise OrderNotAllowed(OrderNotAllowed.note_id)
    for side in {turn.origin for turn in pending}:
        own = [turn.id for turn in pending if turn.origin == side]
        if [turn.id for turn in order if turn.origin == side] != own:
            raise OrderNotAllowed(OrderNotAllowed.note_id)


def move(turns: Sequence[LedgerTurn], order: Sequence[LedgerTurn], turn_id: int, position: int) -> list[LedgerTurn]:
    """Move one turn to a position in the order; refused if it passes a turn of its own app."""
    moved = [turn for turn in order if turn.id == turn_id]
    if not moved:
        raise OrderNotAllowed(OrderNotAllowed.note_id)
    rest = [turn for turn in order if turn.id != turn_id]
    result = rest[:position] + moved + rest[position:]
    check_order(turns, result)
    return result


def outcome(order: Sequence[LedgerTurn], preset: str = "") -> dict[str, str]:
    """For each side, whether it keeps its chat or gets a merged copy as a new chat (M5).

    A side keeps its chat when the other side's turns all come after its own:
    they are then simply added at the end. With "don't reorder" both keep
    their chats and end up with the same turns in a different order (M6).
    """
    sides = list(dict.fromkeys(turn.origin for turn in order))
    if preset == DONT_REORDER:
        return {side: KEEPS_CHAT for side in sides}
    result = {}
    for side in sides:
        last_own = max(index for index, turn in enumerate(order) if turn.origin == side)
        first_other = min((index for index, turn in enumerate(order) if turn.origin != side), default=len(order))
        result[side] = KEEPS_CHAT if last_own < first_other else MERGED_COPY
    return result


def overlapping(order: Sequence[LedgerTurn]) -> list[tuple[LedgerTurn, LedgerTurn]]:
    """Pairs of turns from different apps that ran at the same time (M7)."""
    pairs = []
    for index, first in enumerate(order):
        for second in order[index + 1:]:
            if first.origin == second.origin or not (first.ended_at and second.ended_at):
                continue
            if first.started_at < second.ended_at and second.started_at < first.ended_at:
                pairs.append((first, second))
    return pairs


def turns_to_skip(turns: Sequence[LedgerTurn], keep: str) -> list[LedgerTurn]:
    """"Keep this side's": the other sides' unsynced turns that will stay where they were written (M9)."""
    return [turn for turn in unsynced(turns) if turn.origin != keep and turn.states.get(keep) == link_states.WAITING]
