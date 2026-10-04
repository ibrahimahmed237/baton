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

from . import ledger, status
from .ledger import LedgerTurn, Link
from .status import SideCondition

# What happens to a side's waiting turns.
ADD = "add"                              # the chat is closed: added as normal messages
ADD_AFTER_RELEASE = "add_after_release"  # open but idle: its process is closed, then added; shown after a relaunch
ATTACH = "attach"                        # open: attached to the user's next message there
HOLD = "hold"                            # nothing is done now; the reason says why

# Ways to order a merge (merge.md, M3 to M6).
BY_TIME = "by_time"
DONT_REORDER = "dont_reorder"

# What a merge means for one side's chat (M5).
KEEPS_CHAT = "keeps_chat"
MERGED_COPY = "merged_copy"


@dataclass(frozen=True)
class Step:
    side: str
    action: str
    turns: tuple[LedgerTurn, ...]
    reason: str = ""


@dataclass(frozen=True)
class Plan:
    steps: dict[str, Step]  # only sides that have waiting turns
    decision_needed: bool

    @property
    def writes_anything(self) -> bool:
        return any(step.action in (ADD, ADD_AFTER_RELEASE) for step in self.steps.values())


class OrderNotAllowed(Exception):
    """The order moves one app's own turns past each other, or is not the same set of turns."""


def plan_sync(link: Link, turns: Sequence[LedgerTurn],
              conditions: Mapping[str, SideCondition] | None = None,
              add_when_idle: Collection[str] = ()) -> Plan:
    """`add_when_idle` names the sides whose tool can release one idle chat and
    where the user chose to have turns added automatically."""
    conditions = conditions or {}
    current = status.link_status(link, turns, conditions)
    steps = {}
    for side, side_status in current.sides.items():
        waiting = tuple(turn for turn in turns if turn.states.get(side) == ledger.WAITING)
        if not waiting:
            continue
        reason = side_status.waiting_reason
        if reason == status.NOT_SYNCED_YET:
            steps[side] = Step(side, ADD, waiting)
        elif reason == status.CHAT_OPEN:
            idle = not conditions.get(side, SideCondition()).replying
            release = idle and side in add_when_idle and link.mode == ledger.FULL_COPY
            steps[side] = Step(side, ADD_AFTER_RELEASE if release else ATTACH, waiting, reason)
        else:
            steps[side] = Step(side, HOLD, waiting, reason)
    return Plan(steps, current.decision_needed)


# Merging, when both sides have turns the other never received.

def unsynced(turns: Sequence[LedgerTurn]) -> list[LedgerTurn]:
    """Turns some side is still waiting for, in conversation order."""
    return [turn for turn in turns if ledger.WAITING in turn.states.values()]


def last_shared(turns: Sequence[LedgerTurn]) -> LedgerTurn | None:
    """The last turn every side has, before the first unsynced one (M2)."""
    shared = None
    for turn in turns:
        if ledger.WAITING in turn.states.values():
            break
        if all(state in ledger.AGENT_HAS for state in turn.states.values()):
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
        raise ValueError("no unsynced turns were written in %s" % preset)
    return sorted(pending, key=lambda turn: (turn.origin != preset, turn.seq))


def check_order(turns: Sequence[LedgerTurn], order: Sequence[LedgerTurn]) -> None:
    """Raise unless `order` is the unsynced turns with each app's own turns in their own order (M4)."""
    pending = unsynced(turns)
    if sorted(turn.id for turn in order) != sorted(turn.id for turn in pending):
        raise OrderNotAllowed("the order has to hold exactly the turns that are not synced yet")
    for side in {turn.origin for turn in pending}:
        own = [turn.id for turn in pending if turn.origin == side]
        if [turn.id for turn in order if turn.origin == side] != own:
            raise OrderNotAllowed(
                "turns written in %s stay in the order they were written; only turns from"
                " different apps can pass each other" % side)


def move(turns: Sequence[LedgerTurn], order: Sequence[LedgerTurn], turn_id: int, position: int) -> list[LedgerTurn]:
    """Move one turn to a position in the order; refused if it passes a turn of its own app."""
    moved = [turn for turn in order if turn.id == turn_id]
    if not moved:
        raise OrderNotAllowed("turn %d is not among the turns being merged" % turn_id)
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
    return [turn for turn in unsynced(turns) if turn.origin != keep and turn.states.get(keep) == ledger.WAITING]
