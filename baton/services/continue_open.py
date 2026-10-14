"""Service-owned opening, sync-before-open and immediate record receipts."""
from dataclasses import dataclass
from hashlib import sha256
import json

from ..domain.errors import BatonError, ChatChanged, LinkPaused, NotAvailable
from ..ports.tool import AppControl
from .marks import Marks
from .noteformat import NoteRef


class PausedAction(LinkPaused):
    """A paused link must be resumed before this mutation."""
    note_id = 'action.paused'


@dataclass(frozen=True)
class ContinuePlan:
    plan_id: str
    link_id: int
    destination: str
    delivery: object
    opening: dict


class ContinueOpen:
    """Use injected delivery and AppControl ports; never open after a hold or failure."""
    def __init__(self, store, adapters, applier=None):
        self.store, self.adapters, self.applier = store, adapters, applier

    def opening(self, tool, chat_id):
        if tool not in self.adapters:
            raise NotAvailable()
        adapter = self.adapters[tool]
        try:
            ref = adapter.locator.resolve(chat_id)
        except KeyError:
            raise NotAvailable() from None
        if not adapter.state.condition(ref.id).exists:
            raise NotAvailable()
        exact = adapter.facts.opens_at_chat
        return {'tool': tool, 'chat_id': ref.id, 'folder': ref.folder,
                'opened': 'chat' if exact else 'folder',
                'note': NoteRef('open.chat' if exact else 'open.folder', {'tool': tool, 'title': ref.name})}

    def execute_open(self, outcome):
        """Execute the exact opening already prepared and disclosed to the caller."""
        self._open(outcome)
        return outcome

    def open(self, tool, chat_id):
        return self.execute_open(self.opening(tool, chat_id))

    def _open(self, outcome):
        # Refresh identity, folder and capability immediately before AppControl.
        fresh = self.opening(outcome['tool'], outcome['chat_id'])
        if fresh != outcome:
            raise ChatChanged()
        app: AppControl = self.adapters[outcome['tool']].app
        app.open(outcome['chat_id'] if outcome['opened'] == 'chat' else None, outcome['folder'])

    def plan(self, link_id, destination):
        link = self.store.get_link(link_id)
        if link.removed_at or destination not in link.sides:
            raise NotAvailable()
        if link.paused:
            raise PausedAction()
        self.applier.refresh(link_id)
        delivery = self.applier.preview(link_id)
        delivery = self.applier.prepare(link_id, [s for s in delivery.steps if s.side == destination],
            {s: v['chat_id'] for s, v in delivery.snapshots.items()}, delivery.decision_needed)
        opening = self.opening(destination, link.chat(destination))
        fingerprint = sha256(json.dumps([delivery.plan_id, opening], sort_keys=True).encode()).hexdigest()
        return ContinuePlan('p_' + fingerprint, link_id, destination, delivery, opening)

    def apply(self, plan):
        if self.plan(plan.link_id, plan.destination) != plan:
            raise ChatChanged()
        if plan.delivery.decision_needed:
            return {'applied': False, 'opened': False, 'notes': (NoteRef('merge.decision_needed', {}),)}
        if any(s.action in ('hold', 'attach') for s in plan.delivery.steps):
            return {'applied': False, 'opened': False, 'notes': (NoteRef('continue.waiting', {}),)}
        try:
            result = self.applier.apply(plan.delivery)
        except BatonError:
            return {'applied': False, 'opened': False, 'notes': (NoteRef('continue.failed', {}),)}
        if not result.applied or any(s.action in ('hold', 'attach') for s in result.completed):
            return {'applied': False, 'opened': False, 'notes': (NoteRef('continue.failed', {}),)}
        link = self.store.get_link(plan.link_id)
        if link.paused or link.removed_at or link.chat(plan.destination) != plan.opening['chat_id']:
            return {'applied': False, 'opened': False, 'notes': (NoteRef('continue.waiting', {}),)}
        self._open(plan.opening)
        return {'applied': True, 'opened': True, 'notes': (plan.opening['note'],)}


class RecordActions:
    """Validate immediate record targets and supply their future-behavior notes."""
    def __init__(self, store, clock):
        self.store, self.marks = store, Marks(store, clock)

    def link(self, action, link_id):
        try:
            link = getattr(self.marks, action)(link_id)
        except KeyError:
            raise NotAvailable() from None
        return link, (NoteRef('pause.unchanged' if link.paused else 'resume.unchanged', {}),)

    def turn(self, action, turn_id):
        try:
            turn = getattr(self.marks, action)(turn_id)
        except KeyError:
            raise NotAvailable() from None
        ident = {'keep': 'keep.unchanged', 'send': 'send.unchanged',
                 'pin': 'pin.unchanged', 'unpin': 'unpin.unchanged'}[action]
        link_id, _ = self.marks._find(turn_id)
        other, = self.store.get_link(link_id).others(turn.origin)
        return turn, (NoteRef(ident, {'tool': turn.origin, 'other_tool': other}),)
