"""Brief plan/result data and shared sizing/fingerprint helpers."""
from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
import json
from typing import Any

from ..domain.link import KEPT_BACK, SKIPPED, LedgerTurn
from ..domain.model import Turn
from .noteformat import NoteRef
from .delivery_plan import ApplyStep

OFFLINE = "offline"
DEFAULT_RECENT_TURNS = 3
DEFAULT_THRESHOLD_TOKENS = 150000  # the brief_threshold_tokens setting
_CHARS_PER_TOKEN = 4
# Turns a tool must not get: kept in the tool they were written in, or skipped in a merge.
_NOT_FOR_THIS_TOOL = (KEPT_BACK, SKIPPED)

Pair = tuple[LedgerTurn, Turn]


@dataclass(frozen=True)
class BriefPlan:
    """A stored approval for generation or immutable native creation."""
    link_id: int | None
    side: str
    action: str
    writer: str
    text: str
    turn: Turn
    name: str
    folder: str
    tokens: int
    pinned: tuple[int, ...]
    pinned_tokens: int
    transcript_path: str
    notes: tuple[NoteRef, ...]
    plan_id: str = ''
    stage: str = 'generate'
    estimated_tokens: int = 0
    candidate_estimates: tuple[dict, ...] = ()
    artifact_id: str = ''
    summary: str = ''
    originals: tuple[Turn, ...] = ()
    needs: tuple[str, ...] = ()
    turn_ids: tuple[int, ...] = ()

    confirmation_available: bool = True

    def with_availability(self, running: bool):
        """Match native creation's manual-close policy at the creation review."""
        if self.stage != 'create' or 'app_closed' not in self.needs:
            return self
        manual = NoteRef('create.close_manually', {'tool': self.side})
        notes = self.notes if manual in self.notes else (*self.notes, manual)
        return replace(self, notes=notes, confirmation_available=not running)

    @property
    def steps(self) -> tuple[ApplyStep, ...]:
        """The explicit destination is stable through both approval stages."""
        turns = (self.turn, *self.originals) if self.stage == 'create' else ()
        return (ApplyStep(self.side, 'create', self.turn_ids, turns, needs=self.needs, name=self.name, folder=self.folder),)

    @property
    def confirmation(self):
        """Return the catalogue confirmation belonging to this stored stage."""
        if not self.confirmation_available:
            return NoteRef('plan.unavailable', {})
        return NoteRef('plan.confirm_brief_generation' if self.stage == 'generate'
                       else 'plan.confirm_brief_creation', {})

    def as_contract(self) -> dict[str, Any]:
        """Expose additive artifact and bounded cost fields for the contract."""
        return {'writer': self.writer, 'tokens': self.tokens, 'pinned': list(self.pinned),
                'estimated_tokens': self.estimated_tokens,
                'candidate_estimates': list(self.candidate_estimates),
                'artifact_id': self.artifact_id, 'text': self.text, 'summary': self.summary, 'pinned_tokens': self.pinned_tokens}


@dataclass(frozen=True)
class BriefResult:
    """Report committed native creation or its recoverable failure."""
    plan_id: str
    applied: bool
    chat_id: str = ''
    link_id: int | None = None
    event_id: int | None = None
    error: str = ''
    rollback_error: str = ''


def _fingerprint(value) -> str:
    normalized = json.loads(json.dumps(value))
    return sha256(json.dumps(normalized, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

def estimate_tokens(text: str) -> int:
    """The same rough size as everywhere else in Baton: four characters a token."""
    return len(text) // _CHARS_PER_TOKEN


