"""Durable single-use brief approvals and atomic native transitions."""
from __future__ import annotations

from dataclasses import asdict
import json

from ..domain.errors import AlreadyLinked, ChatChanged
from ..domain.link import SUMMARIZED, ADDED, SHOWN, KEPT_BACK, SKIPPED
from ..domain.model import Turn, Message


def decode_turn(value):
    """Decode one retained canonical turn from its persisted payload."""
    return Turn(Message(**value["prompt"]), tuple(Message(**m) for m in value["messages"]))


class BriefRecords:
    """Share Ledger's connection so coverage cannot outlive its write receipt."""
    def save_brief_plan(self, ident: str, stage: str, payload: dict) -> None:
        """Persist one exact stage approval before returning its token."""
        with self.db:
            self.db.execute('insert into brief_plans(id,stage,payload) values(?,?,?)',
                            (ident, stage, json.dumps(payload, sort_keys=True)))

    def brief_plan(self, ident: str) -> dict:
        """Read the persisted stage, payload and consumption state."""
        row = self.db.execute('select * from brief_plans where id=?', (ident,)).fetchone()
        if row is None:
            raise ChatChanged()
        return dict(row, payload=json.loads(row['payload']))

    def consume_brief_plan(self, ident: str, stage: str) -> dict:
        """Atomically consume one matching stage approval exactly once."""
        with self.db:
            changed = self.db.execute('update brief_plans set consumed=1 where id=? and stage=? and consumed=0',
                                      (ident, stage))
            if changed.rowcount != 1:
                raise ChatChanged()
            return self.brief_plan(ident)['payload']

    def save_brief_artifact(self, ident: str, payload: dict) -> None:
        """Persist immutable generated content, refusing changed identity reuse."""
        encoded = json.dumps(payload, sort_keys=True)
        with self.db:
            self.db.execute('insert or ignore into brief_artifacts(id,payload) values(?,?)', (ident, encoded))
            if self.db.execute('select payload from brief_artifacts where id=?', (ident,)).fetchone()[0] != encoded:
                raise ChatChanged()

    def brief_artifact(self, ident: str) -> dict:
        """Read the immutable artifact required for native creation."""
        row = self.db.execute('select payload from brief_artifacts where id=?', (ident,)).fetchone()
        if row is None:
            raise ChatChanged()
        return json.loads(row[0])

    def brief_cache_get(self, key: str) -> dict | None:
        """Read the summary cached for a privacy-bound writer input."""
        row = self.db.execute('select payload from brief_cache where key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def brief_cache_put(self, key: str, payload: dict) -> None:
        """Replace only the cache for one privacy-bound writer input."""
        with self.db:
            self.db.execute('insert into brief_cache(key,payload) values(?,?) on conflict(key) do update set payload=excluded.payload',
                            (key, json.dumps(payload, sort_keys=True)))

    def summary_coverage(self, link_id: int, side: str, chat_id: str | None = None) -> dict | None:
        """Read coverage belonging to the selected or current native chat."""
        chat_id = chat_id or self.get_link(link_id).chat(side)
        row = self.db.execute('select * from brief_coverage where link_id=? and side=? and chat_id=?',
                              (link_id, side, chat_id)).fetchone()
        if row is None:
            return None
        ids = json.loads(row['turn_ids'])
        return {'artifact_id': row['artifact_id'], 'chat_id': row['chat_id'],
                'opening_id': row['opening_id'], 'opening_fingerprint': row['opening_fingerprint'], 'turn_ids': ids, 'through_turn_id': ids[-1] if ids else None}

    def archived_brief_origins(self, link_id: int) -> dict:
        """Read missing origins only through active sanctioned summary coverage."""
        # Only a currently active, explicitly recorded brief replacement permits
        # absent originating content; moving elsewhere cannot license a fallback.
        result = {}
        for side in self.get_link(link_id).sides:
            coverage = self.summary_coverage(link_id, side)
            if coverage is None:
                continue
            artifact = self.brief_artifact(coverage['artifact_id'])
            prior_chat = artifact['request']['chats'].get(side)
            if prior_chat is None:
                continue
            for row in self.db.execute('select turn_id,payload from brief_origins where link_id=? and origin_chat=?',
                                        (link_id, prior_chat)):
                result[row['turn_id']] = decode_turn(json.loads(row['payload']))
        return result

    @staticmethod
    def _opening_fingerprint(artifact):
        # Canonical public content is encoded independently of native IDs.
        from hashlib import sha256
        from ..domain.model import PROMPT
        value = json.dumps([(PROMPT, artifact['text'])], ensure_ascii=False, separators=(',', ':'))
        return sha256(value.encode()).hexdigest()

    def complete_brief(self, link_id: int, side: str, chat_id: str, artifact_id: str,
                       opening_id: str, original_ids: list[int], local_ids: list[str], state: str,
                       entry_id: int, receipt: dict, expected: dict, at: str, after_snapshot: dict) -> int:
        """Move the link, coverage, archived sources, history and receipt together."""
        self.db.execute('begin immediate')
        with self.db:
            self._creation_entry(entry_id, receipt, link_id)
            link = self.get_link(link_id)
            current = {'link': asdict(link), 'turns': [asdict(t) for t in self.turns(link_id)],
                       'history': [asdict(e) for e in self.history(link_id)],
                       'local_ids': {s: self.local_ids(link_id, s) for s in link.sides}}
            if json.loads(json.dumps(current)) != expected or link.removed_at or link.paused:
                raise ChatChanged()
            if (side not in link.sides or receipt['tool'] != side or receipt['chat_id'] != chat_id
                    or state not in (SHOWN, ADDED) or len(original_ids) != len(local_ids)
                    or len(set(local_ids)) != len(local_ids) or not opening_id or opening_id in local_ids):
                raise ValueError('brief_receipt')
            if self.link_for(side, chat_id):
                raise AlreadyLinked(side, self.link_for(side, chat_id))
            artifact = self.brief_artifact(artifact_id)
            covered = artifact['covered_ids']
            if (original_ids != artifact['original_ids'] or artifact['request']['kind'] != 'existing'
                    or artifact['request']['link_id'] != link_id or artifact['request']['to'] != side
                    or artifact['request']['record'] != expected):
                raise ValueError('brief_originals')
            rows = self.turns(link_id)
            eligible = {r.id for r in rows if r.states[side] not in (KEPT_BACK, SKIPPED)}
            if set(covered) != eligible or len(covered) != len(set(covered)):
                raise ChatChanged()
            detail = {'artifact_id': artifact_id, 'before': expected,
                      'before_chats': artifact['request']['snapshots'],
                      'from': link.chat(side), 'to': chat_id,
                      'covered_ids': covered, 'original_ids': original_ids,
                      'opening_id': opening_id, 'after_chats': {side: after_snapshot},
                      'writes': [{'side': side, 'action': 'create', 'chat_id': chat_id, 'turn_ids': covered}]}
            event = self._event(link_id, at, 'brief', side, detail, covered)
            evidence = self.turn_evidence(link_id)
            for row in rows:
                if row.origin == side:
                    value = evidence.get(row.id)
                    if value is None or not value['verified'] or not value['complete']:
                        raise ChatChanged()
                    self.db.execute('insert or ignore into brief_origins(link_id,turn_id,origin_chat,payload) values(?,?,?,?)',
                                    (link_id, row.id, link.chat(side), json.dumps(asdict(value['turn']), sort_keys=True)))
                if row.id in covered:
                    self.db.execute('update turn_states set state=?,local_id=?,event_id=? where turn_id=? and side=?',
                                    (SUMMARIZED, '', event, row.id, side))
            for ident, local_id in zip(original_ids, local_ids):
                self.db.execute('update turn_states set state=?,local_id=?,event_id=? where turn_id=? and side=?',
                                (state, local_id, event, ident, side))
                self.db.execute('update turns set origin_id=? where id=? and origin=?', (local_id, ident, side))
            self.db.execute('update link_chats set chat=? where link_id=? and tool=?', (chat_id, link_id, side))
            self.db.execute("update links set mode='brief' where id=?", (link_id,))
            for seq, value in enumerate(artifact['request']['rows'], 1):
                self.db.execute('update turns set seq=? where id=? and link_id=?', (seq, value['id'], link_id))
            self.db.execute('insert into brief_coverage(link_id,side,chat_id,artifact_id,opening_id,turn_ids,opening_fingerprint) values(?,?,?,?,?,?,?)',
                            (link_id, side, chat_id, artifact_id, opening_id, json.dumps(covered), self._opening_fingerprint(artifact)))
            self._record_copy(receipt, at)
            self.db.execute("update journal set state='committed',ended_at=?,post_receipt=? where id=?",
                            (at, json.dumps(receipt), entry_id))
            return event

    def complete_brief_link(self, request: dict, chat_id: str, artifact_id: str,
                            opening_id: str, original_ids: list[int], local_ids: list[str], state: str,
                            entry_id: int, receipt: dict, at: str, after_snapshot: dict) -> tuple[int, int]:
        """Create initial canonical history and summary baseline in one transaction."""
        self.db.execute('begin immediate')
        with self.db:
            self._creation_entry(entry_id, receipt)
            artifact = self.brief_artifact(artifact_id)
            side = request['to']
            if (artifact['request'] != request or request['kind'] != 'new_link'
                    or original_ids != artifact['original_ids'] or receipt['tool'] != side
                    or receipt['chat_id'] != chat_id or len(original_ids) != len(local_ids)
                    or len(set(local_ids)) != len(local_ids) or opening_id in local_ids
                    or state not in (SHOWN, ADDED)
                    or [asdict(link) for link in self.links()] != request['records']):
                raise ChatChanged()
            source, source_chat = next(iter(request['chats'].items()))
            expected_record = request.get('replace_record')
            if expected_record:
                old_id = request['replace_link_id']
                old = self.get_link(old_id)
                current_record = {'link': asdict(old), 'turns': [asdict(t) for t in self.turns(old_id)],
                                  'history': [asdict(e) for e in self.history(old_id)],
                                  'local_ids': {s: self.local_ids(old_id, s) for s in old.sides}}
                if json.loads(json.dumps(current_record)) != expected_record:
                    raise ChatChanged()
            replacing = request['replace_link_id']
            owner = self.link_for(source, source_chat)
            if owner and owner.id != replacing:
                raise AlreadyLinked(source, owner)
            if self.link_for(side, chat_id):
                raise AlreadyLinked(side, self.link_for(side, chat_id))
            if replacing is not None:
                self.db.execute('update links set removed_at=? where id=?', (at, replacing))
                self.db.execute('update link_chats set active=0 where link_id=?', (replacing,))
                self._event(replacing, at, 'link_removed')
            cur = self.db.execute("insert into links(mode,created_at) values('brief',?)", (at,))
            link_id = cur.lastrowid
            self.db.executemany('insert into link_chats(link_id,tool,chat) values(?,?,?)',
                                [(link_id, source, source_chat), (link_id, side, chat_id)])
            mapped = {}
            from ..domain.link import WRITTEN_HERE
            from .records import _size
            for seq, value in enumerate(request['rows'], 1):
                turn = decode_turn(request['content'][str(value['id'])])
                cur = self.db.execute('insert into turns(link_id,seq,origin,origin_id,started_at,ended_at,first_line,size,pinned) values(?,?,?,?,?,?,?,?,?)',
                                      (link_id, seq, source, turn.id, turn.started_at, turn.ended_at,
                                       value['first_line'], _size(turn), int(value['pinned'])))
                ident = cur.lastrowid
                mapped[value['id']] = ident
                self._record_evidence(ident, turn, verified=True, complete=True)
                self.db.executemany('insert into turn_states(turn_id,side,state,local_id) values(?,?,?,?)',
                                    [(ident, source, value['states'][source],
                                      turn.id if value['states'][source] in (WRITTEN_HERE, SHOWN, ADDED) else ''),
                                     (ident, side, SUMMARIZED if value['id'] in artifact['covered_ids'] else value['states'][side], '')])
            source_coverage = request.get('source_coverage')
            if source_coverage:
                source_ids = [mapped[ident] for ident in source_coverage['turn_ids'] if ident in mapped]
                self.db.execute('insert into brief_coverage(link_id,side,chat_id,artifact_id,opening_id,turn_ids,opening_fingerprint) values(?,?,?,?,?,?,?)',
                                (link_id, source, source_chat, artifact_id, source_coverage['opening_id'], json.dumps(source_ids), source_coverage['opening_fingerprint']))
                for value in request['rows']:
                    payload = request['content'][str(value['id'])]
                    self.db.execute('insert into brief_origins(link_id,turn_id,origin_chat,payload) values(?,?,?,?)',
                                    (link_id, mapped[value['id']], source_chat, json.dumps(payload, sort_keys=True)))
            covered = [mapped[ident] for ident in artifact['covered_ids']]
            event = self._event(link_id, at, 'brief', side,
                                {'artifact_id': artifact_id, 'initial': True, 'opening_id': opening_id,
                                 'to': chat_id, 'after_chats': {side: after_snapshot}}, covered)
            for ident, local in zip(original_ids, local_ids):
                self.db.execute('update turn_states set state=?,local_id=?,event_id=? where turn_id=? and side=?',
                                (state, local, event, mapped[ident], side))
            self.db.execute('insert into brief_coverage(link_id,side,chat_id,artifact_id,opening_id,turn_ids,opening_fingerprint) values(?,?,?,?,?,?,?)',
                            (link_id, side, chat_id, artifact_id, opening_id, json.dumps(covered), self._opening_fingerprint(artifact)))
            self._record_copy(receipt, at)
            self.db.execute("update journal set state='committed',link_id=?,ended_at=?,post_receipt=? where id=?",
                            (link_id, at, json.dumps(receipt), entry_id))
            return link_id, event
