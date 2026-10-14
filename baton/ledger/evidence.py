"""Canonical observations and offer claims on the owning Ledger connection."""
from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from ..domain.model import Message, Turn, turn_extends


class EvidenceRecords:
    """Retain source baselines without upgrading old rows into verified history."""

    def _record_evidence(self, turn_id: int, turn: Turn, verified: bool,
                         complete: bool = True) -> bool:
        """Save an observation; return whether its metadata has a verified basis."""
        payload = asdict(turn)
        row = self.db.execute('select * from turn_evidence where turn_id=?', (turn_id,)).fetchone()
        if row is None:
            self.db.execute('insert into turn_evidence values(?,?,?,?)',
                            (turn_id, json.dumps(payload), int(verified), int(complete)))
            return verified
        if row['complete']:
            return False
        before = json.loads(row['payload'])
        # Only append to an unfinished observation. Rewrites remain detectable,
        # and a legacy observation never acquires historical verification.
        previous = Turn(Message(**before['prompt']), tuple(Message(**m) for m in before['messages']))
        if turn_extends(previous, turn):
            self.db.execute('update turn_evidence set payload=?,complete=? where turn_id=?',
                            (json.dumps(payload), int(complete), turn_id))
            return bool(row['verified'])
        return False

    def turn_evidence(self, link_id: int) -> dict[int, dict[str, Any]]:
        """Read canonical content and the provenance of each retained baseline."""
        result = {}
        for row in self.db.execute('select e.* from turn_evidence e join turns t on t.id=e.turn_id'
                                   ' where t.link_id=?', (link_id,)):
            payload = json.loads(row['payload'])
            turn = Turn(Message(**payload['prompt']), tuple(Message(**m) for m in payload['messages']))
            result[row['turn_id']] = {'turn': turn, 'verified': bool(row['verified']),
                                      'complete': bool(row['complete'])}
        return result

    def claim_limit_offer(self, key: str, at: str) -> bool:
        """Persist one atomic offer claim across independent processes."""
        with self.db:
            cursor = self.db.execute('insert into limit_offers(key,offered_at) values(?,?)'
                                     ' on conflict(key) do nothing', (key, at))
        return cursor.rowcount == 1
