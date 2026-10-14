"""Immediate record-only actions; native chats are never changed."""
from ..domain.errors import NotAvailable
from ..ports.clock import Clock
from ..ports.store import RecordStore
from ..domain.link import AGENT_HAS, KEPT_BACK
from .noteformat import NoteRef


class Marks:
    """Change per-turn and per-link marks in the record store."""
    def __init__(self, store: RecordStore, clock: Clock):
        """Use injected store, adapters and timing ports."""
        self.store, self.clock = store, clock

    def _find(self, turn_id, link_id=None):
        links = [self.store.get_link(link_id)] if link_id is not None else self.store.links()
        for link in links:
            if not link.removed_at:
                for turn in self.store.turns(link.id):
                    if turn.id == turn_id:
                        return link.id, turn
        raise KeyError(turn_id)

    def _mark(self, turn_id, action, link_id=None):
        link_id, _ = self._find(turn_id, link_id)
        action(link_id, turn_id)
        return self._find(turn_id, link_id)[1]

    def keep(self, turn_id, link_id=None):
        """Keep an undelivered turn on its originating side."""
        return self._mark(turn_id, lambda link, turn: self.store.keep_back(link, turn, self.clock.now()), link_id)

    def send(self, turn_id, link_id=None):
        """Make a kept turn waiting again without writing a chat."""
        return self._mark(turn_id, lambda link, turn: self.store.send_after_all(link, turn, self.clock.now()), link_id)

    send_after_all = send

    def pin(self, turn_id, link_id=None):
        """Pin a turn without changing native content."""
        return self._mark(turn_id, lambda link, turn: self.store.set_pinned(link, turn, True), link_id)

    def unpin(self, turn_id, link_id=None):
        """Remove a turn pin without changing native content."""
        return self._mark(turn_id, lambda link, turn: self.store.set_pinned(link, turn, False), link_id)

    def pinned(self, link_id):
        """List pinned turns in conversation order."""
        return [turn for turn in self.store.turns(link_id) if turn.pinned]

    def status_notes(self, link_id, side):
        """Disclose kept gaps once a later turn has reached that agent (W13)."""
        rows = self.store.turns(link_id)
        gaps = [turn for turn in rows if turn.states.get(side) == KEPT_BACK and
                any(later.seq > turn.seq and later.states.get(side) in AGENT_HAS for later in rows)]
        return (NoteRef('keep.missing_turns', {'tool': side, 'n': len(gaps)}),) if gaps else ()

    def _pause(self, link_id, paused):
        if self.store.get_link(link_id).removed_at:
            raise NotAvailable()
        self.store.set_paused(link_id, paused, self.clock.now())
        return self.store.get_link(link_id)

    def pause(self, link_id):
        """Stop delivery for one link while retaining waiting turns."""
        return self._pause(link_id, True)

    def resume(self, link_id):
        """Resume a link under the ordinary delivery and conflict rules."""
        return self._pause(link_id, False)
