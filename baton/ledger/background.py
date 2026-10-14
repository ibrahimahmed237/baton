"""Retention and reviewed-answer attachments owned by background jobs."""
from __future__ import annotations

import json
from typing import Sequence
from datetime import datetime

BACKGROUND_SCHEMA = """
create table if not exists background_resources(
 job text not null, kind text not null, ident text not null,
 primary key(job,kind,ident)
);
create table if not exists reviewed_answers(
 id text primary key, tool text not null, chat text not null,
 expires_at text not null, payload text not null, message_id text
);
"""


class BackgroundRecords:
    """Keep cleanup and prompt receipts on the same durable connection."""
    def own_background_resources(self, job: str, resources: Sequence[tuple[str, str]]) -> None:
        """Register records created by this job for bounded retention."""
        with self.db:
            self.db.executemany('insert or ignore into background_resources values(?,?,?)',
                                [(job, kind, ident) for kind, ident in resources])

    def _configure_background_cleanup(self, handlers) -> None:
        """Inject deletion of external resources belonging to this connection."""
        self._background_cleanup = handlers

    def cleanup_background(self, at: str) -> None:
        """Remove expired background payloads, preserving canonical brief artifacts."""
        expired = []
        for row in self.db.execute('select id,payload from brief_artifacts'):
            value = json.loads(row['payload'])
            if not row['id'].startswith('j_') or 'expires_at' not in value or 'kind' not in value or 'request' not in value:
                continue
            state = self.brief_cache_get(row['id']) or {}
            if datetime.fromisoformat(at) >= datetime.fromisoformat(state.get('expires_at', value['expires_at'])):
                expired.append(row['id'])
        expired.extend(row[0] for row in self.db.execute(
            'select distinct job from background_resources where job not in (select id from brief_artifacts)'))
        protected = {row[0] for row in self.db.execute('select artifact_id from brief_coverage')}
        # Historical brief artifacts are also required by undo/restore.
        def references(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key == 'artifact_id' and isinstance(item, str):
                        protected.add(item)
                    references(item)
            elif isinstance(value, list):
                for item in value: references(item)
        for row in self.db.execute('select detail from events'):
            references(json.loads(row[0]))
        with self.db:
            for job in expired:
                resources = list(self.db.execute('select kind,ident from background_resources where job=? order by kind', (job,)))
                for kind, ident in resources:
                    if self.db.execute('select 1 from background_resources where kind=? and ident=? and job!=?', (kind, ident, job)).fetchone():
                        self.db.execute('delete from background_resources where job=? and kind=? and ident=?', (job, kind, ident))
                        continue
                    if kind == 'artifact' and ident in protected:
                        self.db.execute('delete from background_resources where job=? and kind=? and ident=?', (job, kind, ident))
                        continue
                    if kind in ('cli_plan', 'transcript'):
                        if kind == 'transcript':
                            path = json.loads(ident)['path']
                            retained = any(json.loads(row[0]).get('transcript_path') == path
                                for row in self.db.execute('select payload from brief_artifacts'))
                            if retained:
                                self.db.execute('delete from background_resources where job=? and kind=? and ident=?', (job, kind, ident))
                                continue
                        handler = getattr(self, '_background_cleanup', {}).get(kind)
                        if handler is None:
                            continue
                        handler(ident)
                        self.db.execute('delete from background_resources where job=? and kind=? and ident=?', (job, kind, ident))
                        continue
                    table, column = {'artifact': ('brief_artifacts', 'id'), 'plan': ('brief_plans', 'id'),
                                     'cache': ('brief_cache', 'key')}[kind]
                    self.db.execute(f'delete from {table} where {column}=?', (ident,))
                    self.db.execute('delete from background_resources where job=? and kind=? and ident=?', (job, kind, ident))
                self.db.execute('delete from brief_artifacts where id in (?,?)', (job, job + '_result'))
                self.db.execute('delete from brief_cache where key=?', (job,))
            self.db.execute('delete from reviewed_answers where expires_at<=?', (at,))

    def queue_reviewed_answer(self, ident: str, tool: str, chat: str, expires_at: str, payload: dict) -> None:
        """Persist a confirmed answer once without modifying native history."""
        with self.db:
            self.db.execute('insert or ignore into reviewed_answers(id,tool,chat,expires_at,payload) values(?,?,?,?,?)',
                            (ident, tool, chat, expires_at, json.dumps(payload, sort_keys=True)))

    def reviewed_answers(self, tool: str, chat: str) -> list[dict]:
        """Return pending confirmed answers addressed only to this chat."""
        return [dict(row, payload=json.loads(row['payload'])) for row in self.db.execute(
            'select * from reviewed_answers where tool=? and chat=? and message_id is null order by rowid', (tool, chat))]

    def consume_reviewed_answers(self, idents: Sequence[str], message_id: str) -> None:
        """Keep a durable prompt receipt so retries never attach twice."""
        with self.db:
            self.db.executemany('update reviewed_answers set message_id=?,payload=? where id=? and message_id is null',
                                [(message_id, '{}', ident) for ident in idents])

    def set_background_owner(self, job: str | None) -> None:
        """Scope writes on this connection to the job that owns their retention."""
        self._background_owner = job

    def _own_background_record(self, kind, ident):
        job = getattr(self, '_background_owner', None)
        if not job:
            return
        table, column = {'artifact': ('brief_artifacts', 'id'), 'plan': ('brief_plans', 'id'),
                         'cache': ('brief_cache', 'key')}[kind]
        existing = self.db.execute(f'select 1 from {table} where {column}=?', (ident,)).fetchone()
        owned = self.db.execute('select 1 from background_resources where kind=? and ident=?', (kind, ident)).fetchone()
        if not existing or owned:
            self.db.execute('insert or ignore into background_resources values(?,?,?)', (job, kind, ident))
