"""Atomic undo and restoration of link identities, states and write receipts."""
from __future__ import annotations

from dataclasses import asdict
import json
from typing import Sequence

from ..domain.errors import AlreadyLinked, ChatChanged
from ..domain.link import ADDED, ATTACHED, KEPT_BACK, SHOWN, SKIPPED, WAITING, WRITTEN_HERE


class UndoRecords:
    """Keep an undo event and its verified writes in the owning transaction."""

    def complete_undo(self, link_id: int, expected: dict, writes: Sequence[dict],
                      at: str, detail: dict) -> int:
        """Commit verified undo or restore writes and pause the link atomically."""
        link = self.get_link(link_id)
        current = {'link': asdict(link), 'turns': [asdict(t) for t in self.turns(link_id)],
                   'history': [asdict(e) for e in self.history(link_id)],
                   'local_ids': {s: self.local_ids(link_id, s) for s in link.sides}}
        if expected != current:
            raise ChatChanged()
        kind = detail['operation']
        if kind not in ('undo', 'restore') or len({w['side'] for w in writes}) != len(writes):
            raise ValueError('undo_shape')
        ids = {t.id for t in self.turns(link_id)}
        for write in writes:
            side = write['side']
            if (side not in link.sides or not set(write['states']).issubset(ids) or
                    not set(write['states'].values()).issubset({ADDED, ATTACHED, KEPT_BACK, SHOWN, SKIPPED, WAITING, WRITTEN_HERE}) or
                    not set(write['local_ids']).issubset(set(write['states']))):
                raise ValueError('undo_side')
            linked = self.link_for(side, write['chat_id'])
            if linked and linked.id != link_id:
                raise AlreadyLinked(side, linked)
            if write.get('entry_id') is not None:
                entry = self.journal_entry(write['entry_id'])
                receipt = write['receipt']
                if (entry['state'] != 'begun' or entry['link_id'] != link_id or
                        (entry['tool'], entry['chat_id'], entry['action']) !=
                        (receipt['tool'], receipt['chat_id'], receipt['kind']) or
                        (receipt['tool'], receipt['chat_id']) != (side, write['chat_id'])):
                    raise ValueError('undo_receipt')
        detail = dict(detail, writes=list(writes))
        with self.db:
            event = self._event(link_id, at, kind, detail=detail,
                                turn_ids=sorted({i for w in writes for i in w['states']}))
            for write in writes:
                side = write['side']
                self.db.execute('update link_chats set chat=?,active=1 where link_id=? and tool=?',
                                (write['chat_id'], link_id, side))
                for ident, state in write['states'].items():
                    self.db.execute('update turn_states set state=?,local_id=?,event_id=? where turn_id=? and side=?',
                                    (state, write['local_ids'].get(ident, ''), event, ident, side))
                    if ident in write.get('origin_ids', {}):
                        self.db.execute('update turns set origin_id=? where id=? and origin=?',
                                        (write['origin_ids'][ident], ident, side))
                if write.get('entry_id') is not None:
                    if write['receipt']['kind'] == 'create':
                        self._record_copy(write['receipt'], at)
                    self.db.execute("update journal set state='committed',ended_at=?,post_receipt=? where id=?",
                                    (at, json.dumps(write['receipt']), write['entry_id']))
            if detail.get('order'):
                for seq, ident in enumerate(detail['order'], 1):
                    self.db.execute('update turns set seq=? where id=? and link_id=?', (seq, ident, link_id))
            self.db.execute('update links set paused=1,removed_at=null where id=?', (link_id,))
        return event
