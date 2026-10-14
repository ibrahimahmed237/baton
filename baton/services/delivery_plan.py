"""Immutable delivery actions and the observations a confirmation covers."""
from __future__ import annotations
from dataclasses import dataclass
from ..domain.model import Turn

@dataclass(frozen=True)
class ApplyStep:
    """A single confirmed action with its complete turn payload."""
    side: str
    action: str
    turn_ids: tuple[int, ...] = ()
    turns: tuple[Turn, ...] = ()
    reason: str = ''
    needs: tuple[str, ...] = ()
    name: str = ''
    folder: str = ''
    before_local_id: str = ''
    keep_through_local_id: str = ''
    alternatives: tuple[str, ...] = ()


@dataclass(frozen=True)
class PreparedPlan:
    """An immutable preview token and the observations it confirms."""
    plan_id: str
    link_id: int | None
    steps: tuple[ApplyStep, ...]
    snapshots: dict[str, dict]
    record: dict
    decision_needed: bool = False
