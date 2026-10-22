"""Find Codex chats: the `threads` table of its state database and the rollout file each row names."""
from __future__ import annotations

import json
import sqlite3
from ...ports.budget import sqlite_timeout
import stat
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ...domain.errors import NotAvailable
from ...ports.tool import ChatRef


def iso_from_ms(milliseconds: Any) -> str:
    """An ISO UTC time from milliseconds since 1970; empty when the value is not a number."""
    if not isinstance(milliseconds, (int, float)):
        return ""
    return datetime.fromtimestamp(milliseconds / 1000, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class CodexLocator:
    """Resolve chat ids to their thread rows and rollout files under one root (the home folder)."""

    def __init__(self, root, scope):
        self.root = Path(root).resolve()
        self.scope = scope
        self._writer_connection = None

    # -- where things are -------------------------------------------------

    @property
    def home(self) -> Path:
        """Codex's own folder."""
        return self.scope.checked_path(self.root / ".codex")

    @property
    def state_db(self) -> Path:
        """The database that lists threads."""
        return self._database_path("state_5.sqlite")

    @property
    def history_db(self) -> Path:
        """Codex's projection of rollouts, which remembers how far it has read."""
        return self._database_path("thread_history_1.sqlite")

    def _database_path(self, name: str) -> Path:
        path = self.scope.checked_path(self.home / name)
        for suffix in ('-wal', '-shm', '-journal'):
            self.scope.checked_path(Path(str(path) + suffix))
        return path

    @property
    def locks(self) -> Path:
        """One lock file per thread that is loaded."""
        return self.scope.checked_path(self.home / "thread-writer-locks")

    @property
    def sessions(self) -> Path:
        """Where rollout files are kept, one folder per day."""
        return self.scope.checked_path(self.home / "sessions")

    def inside(self, path) -> Path:
        """The resolved path, refused when it leaves the root."""
        resolved = self.scope.checked_path(Path(path))
        if not resolved.is_relative_to(self.root):
            raise ValueError("outside adapter root")
        return resolved

    def new_rollout_path(self, thread_id: str, moment: datetime) -> Path:
        """Where Codex would put the rollout of a thread started now (local time, as Codex names it)."""
        local = moment.astimezone()
        folder = self.sessions / local.strftime("%Y") / local.strftime("%m") / local.strftime("%d")
        name = "rollout-%s-%s.jsonl" % (local.strftime("%Y-%m-%dT%H-%M-%S"), thread_id)
        return self.inside(folder / name)

    # -- the threads table ------------------------------------------------

    def read_rows(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        """Read only exact ID-bound row queries, checking scope before SQL access."""
        expected_many = 'SELECT * FROM threads WHERE id IN (' + ','.join('?' for _ in params) + ')'
        if not params or sql not in (expected_many, 'SELECT * FROM threads WHERE id = ?'):
            raise NotAvailable()
        if sql == 'SELECT * FROM threads WHERE id = ?' and len(params) != 1:
            raise NotAvailable()
        for ident in params:
            self.scope.require(ident)
        if self._writer_connection is not None:
            return [dict(row) for row in self._writer_connection.execute(sql, params)]
        if not self.state_db.exists():
            return []
        with closing(sqlite3.connect(self.state_db.as_uri() + "?mode=ro", uri=True, timeout=sqlite_timeout())) as connection:
            connection.row_factory = sqlite3.Row
            return [dict(row) for row in connection.execute(sql, params)]

    def row(self, chat_id: str) -> dict[str, Any]:
        """The thread row of a chat, with every column the table has."""
        self.scope.require(chat_id)
        rows = self.read_rows("SELECT * FROM threads WHERE id = ?", (chat_id,))
        if not rows:
            raise KeyError(chat_id)
        return rows[0]

    def rollout_path(self, chat_id: str) -> Path:
        """The rollout file of a chat; KeyError when there is no such chat or its file is gone."""
        path = self.rollout_of(self.row(chat_id))
        if path is None or not path.is_file():
            raise KeyError(chat_id)
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise KeyError(chat_id)
        with path.open('rb') as stream:
            try:
                meta = json.loads(stream.readline())
            except (ValueError, UnicodeError):
                raise KeyError(chat_id) from None
        if (not isinstance(meta, dict) or meta.get('type') != 'session_meta' or
                not isinstance(meta.get('payload'), dict) or
                meta['payload'].get('id', meta['payload'].get('session_id')) != chat_id):
            raise KeyError(chat_id)
        return path

    def rollout_of(self, row: dict[str, Any]) -> Path | None:
        """The rollout path a thread row names, confined to the root; None when the row names none or one outside."""
        self.scope.require(row["id"])
        raw = row.get("rollout_path") or ""
        if not raw:
            return None
        path = Path(raw)
        try:
            raw_path = path if path.is_absolute() else self.home / path
            resolved = self.inside(raw_path)
            if (resolved != raw_path.absolute() or not resolved.is_relative_to(self.sessions) or
                    not resolved.name.endswith('-' + row['id'] + '.jsonl')):
                return None
            return resolved
        except (ValueError, NotAvailable):
            return None

    @staticmethod
    def is_chat(row: dict[str, Any]) -> bool:
        """A thread the user could have started, not an archived one or a sub-agent's."""
        if row.get("archived") or not row.get("rollout_path"):
            return False
        if row.get("thread_source") == "subagent" or row.get("agent_role"):
            return False
        return "subagent" not in (row.get("source") or "")

    def _ref(self, row: dict[str, Any]) -> ChatRef:
        updated = row.get("updated_at_ms")
        if updated is None and isinstance(row.get("updated_at"), (int, float)):
            updated = row["updated_at"] * 1000
        return ChatRef(row["id"], row.get("name") or row.get("title") or "", row.get("cwd") or "", iso_from_ms(updated))

    def scoped_rows(self) -> list[dict[str, Any]]:
        """Read row metadata only for IDs explicitly authorized in this adapter."""
        ids = sorted(self.scope.original | self.scope.created)
        if not ids:
            return []
        return self.read_rows('SELECT * FROM threads WHERE id IN (' + ','.join('?' for _ in ids) + ')', tuple(ids))

    def chats(self) -> list[ChatRef]:
        """Discover metadata across scopes without reading or authorizing native content."""
        if not self.state_db.exists():
            return []
        with closing(sqlite3.connect(self.state_db.as_uri() + "?mode=ro", uri=True, timeout=sqlite_timeout())) as connection:
            connection.row_factory = sqlite3.Row
            columns = {row['name'] for row in connection.execute('PRAGMA table_info(threads)')}
            metadata = ('id', 'name', 'title', 'cwd', 'updated_at_ms', 'updated_at', 'archived')
            selected = ', '.join(column for column in metadata if column in columns)
            filters = ['COALESCE(archived, 0) = 0']
            # Filter native classification in SQL; do not return private row fields.
            for column, clause in (
                    ('thread_source', "COALESCE(thread_source, '') != 'subagent'"),
                    ('agent_role', "COALESCE(agent_role, '') = ''"),
                    ('source', "instr(COALESCE(source, ''), 'subagent') = 0")):
                if column in columns:
                    filters.append(clause)
            rows = connection.execute('SELECT ' + selected + ' FROM threads WHERE ' + ' AND '.join(filters))
            refs = [self._ref(dict(row)) for row in rows]
        refs.sort(key=lambda ref: ref.id)
        refs.sort(key=lambda ref: ref.updated_at, reverse=True)
        return refs

    def resolve(self, chat_id: str) -> ChatRef:
        """The reference of one chat. A Codex chat keeps its id, so nothing is followed."""
        self.rollout_path(chat_id)
        return self._ref(self.row(chat_id))

    def name(self, chat_id: str) -> str:
        """The name Codex shows: the name the user gave, else the title."""
        return self.resolve(chat_id).name
