"""What is true of a Codex chat right now: held, replying, readable by the checked format."""
from __future__ import annotations

import fcntl
import sqlite3
from contextlib import closing
from pathlib import Path

from ...domain.conditions import SideCondition
from ...ports.tool import FormatCheck
from .facts import SCHEMA_VERSION
from .records import KNOWN_RECORD_TYPES, TASK_CLOSE, TASK_OPEN, records_from_end, parse_strict

# Columns of `threads` that the writer reads or sets (spike/m0_create.py). All must exist.
REQUIRED_COLUMNS = frozenset({
    "id", "rollout_path", "created_at", "updated_at", "source", "model_provider", "cwd", "title",
    "sandbox_policy", "approval_mode", "tokens_used", "has_user_event", "archived", "cli_version",
    "first_user_message", "model", "reasoning_effort", "created_at_ms", "updated_at_ms", "thread_source",
    "preview", "recency_at", "recency_at_ms", "history_mode", "name", "is_pinned", "originator",
})
_HOW_MANY_NEWEST_ROLLOUTS = 3
_TAIL_BYTES = 1 << 20


class HistoryIndex:
    """How far Codex's chat view has read into a rollout (`thread_history_1.sqlite`)."""

    TABLE = "thread_history_projection_state"

    def __init__(self, locator):
        self.locator = locator

    def read_offset(self, thread_id: str) -> int | None:
        """The byte offset Codex has read up to; 0 when it has not read the thread; None when this cannot be told."""
        self.locator.scope.require(thread_id)
        path = self.locator.history_db
        if not path.exists():
            return None
        try:
            with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)) as connection:
                columns = [row[1] for row in connection.execute("PRAGMA table_info(%s)" % self.TABLE)]
                id_column, offset_column = "thread_id", "next_rollout_byte_offset"
                if set(columns) != {"thread_id", "next_rollout_byte_offset", "next_rollout_ordinal"}:
                    return None
                row = connection.execute("SELECT %s,next_rollout_ordinal FROM %s WHERE %s = ?" % (offset_column, self.TABLE, id_column),
                                         (thread_id,)).fetchone()
        except sqlite3.Error:
            return None
        if row is None:
            return 0
        return row[0] if all(isinstance(value, int) and value >= 0 for value in row) else None


class CodexState:
    """Report who holds a chat, whether it is replying, and whether Baton may write to the format."""

    def __init__(self, adapter):
        self.adapter = adapter
        self.index = HistoryIndex(adapter.locator)
        self._scanned: dict[str, tuple[tuple[int, int], bool]] = {}

    # -- holder -----------------------------------------------------------

    def _lock_path(self, chat_id: str) -> Path | None:
        if not chat_id or Path(chat_id).name != chat_id:
            return None
        return self.adapter.scope.checked_path(self.adapter.locator.locks / (chat_id + ".lock"))

    def held(self, chat_id: str) -> bool:
        """True while Codex has the thread loaded: its lock file exists and cannot be locked by us.

        A missing lock file means the thread is released (docs/SPIKE-M0.md).
        """
        path = self._lock_path(chat_id)
        if path is None or not path.exists():
            return False
        try:
            descriptor = path.open("rb")
        except OSError:
            return True
        with descriptor:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except OSError:
                return True
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        return False

    def held_chats(self) -> list[str]:
        """Ids of every thread Codex has loaded."""
        locks = self.adapter.locator.locks
        if not locks.is_dir():
            return []
        return sorted(path.stem for path in locks.glob("*.lock") if self.held(path.stem))

    # -- replying ---------------------------------------------------------

    def replying(self, chat_id: str) -> bool:
        """True when a task has started without a completion after it, whether or not the chat looks held.

        Hold detection is not yet verified on the real app, so it cannot be what
        decides that nothing is being answered. A task that crashed and never
        finished in a closed chat therefore also counts, and Baton refuses to
        write to it (decision owed after the live run).
        """
        try:
            path = self.adapter.locator.rollout_path(chat_id)
        except KeyError:
            return False
        return self.unfinished_task(path)

    def replying_chats(self) -> list[str]:
        """Ids of every chat in this adapter's scope with an unfinished task, held or not."""
        scope = self.adapter.scope
        return [ident for ident in sorted(scope.original | scope.created) if self.replying(ident)]

    @staticmethod
    def unfinished_task(path: Path) -> bool:
        """True when the newest task event of the rollout is a start."""
        for record in records_from_end(path):
            payload = record.get("payload") or {}
            if record.get("type") != "event_msg":
                continue
            if payload.get("type") == TASK_OPEN:
                return True
            if payload.get("type") in TASK_CLOSE:
                return False
        return False

    # -- condition and format ---------------------------------------------

    def condition(self, chat_id: str) -> SideCondition:
        """Existence, holder, reply, hook and launch evidence for a chat."""
        process = self.adapter.process
        try:
            self.adapter.locator.rollout_path(chat_id)
        except KeyError:
            return SideCondition(exists=False, app_running=process.running())
        held = self.held(chat_id)
        return SideCondition(
            exists=True, open=held, replying=self.replying(chat_id),
            hooks_ready=self.adapter.hooks.check().ok, app_running=process.running(),
            app_started_at=process.started_at(), format_known=self.target_format(chat_id).known)

    def _threads_columns_ok(self) -> bool:
        locator = self.adapter.locator
        with closing(sqlite3.connect(locator.state_db.as_uri() + "?mode=ro", uri=True, timeout=5)) as connection:
            info = connection.execute("PRAGMA table_info(threads)").fetchall()
        names = {row[1] for row in info}
        if not REQUIRED_COLUMNS <= names:
            return False
        # A column Codex added that must be given a value would make Baton's insert fail.
        return not any(row[3] and row[4] is None and not row[5] and row[1] not in REQUIRED_COLUMNS for row in info)

    def _rollout_ok(self, path: Path) -> bool:
        """True when the recent records of a rollout are all of the known types (a line still being written is ignored)."""
        try:
            stat = path.stat()
        except OSError:
            return True
        signature = (stat.st_size, stat.st_mtime_ns)
        cached = self._scanned.get(str(path))
        if cached is None or cached[0] != signature:
            known = all(record.get("type") in KNOWN_RECORD_TYPES
                        for record in records_from_end(path, budget=_TAIL_BYTES))
            cached = self._scanned[str(path)] = (signature, known)
        return cached[1]

    def format_version(self) -> FormatCheck:
        """Known when the threads columns are the checked ones and the newest rollouts hold known record types."""
        locator = self.adapter.locator
        if not locator.state_db.exists():
            return FormatCheck(True, SCHEMA_VERSION)
        try:
            if not self._threads_columns_ok():
                return FormatCheck(False, "schema")
            newest = locator.scoped_rows()
        except (sqlite3.Error, OSError):
            return FormatCheck(False, "unreadable")
        for row in newest:
            try:
                path = locator.rollout_path(row['id'])
            except (KeyError, OSError):
                return FormatCheck(False, 'identity')
            if not self._rollout_ok(path):
                return FormatCheck(False, 'records')
        return FormatCheck(True, SCHEMA_VERSION)

    def target_format(self, chat_id: str) -> FormatCheck:
        """Validate the entire particular target before any native mutation."""
        self.adapter.scope.require(chat_id)
        if not self.format_version().known:
            return FormatCheck(False, 'schema')
        try:
            path = self.adapter.locator.rollout_path(chat_id)
            records = parse_strict(path.read_bytes())
            if not records or records[0].get('type') != 'session_meta':
                return FormatCheck(False, 'session')
            meta = records[0]['payload']
            if meta.get('id', meta.get('session_id')) != chat_id:
                return FormatCheck(False, 'identity')
        except (OSError, ValueError, TypeError, KeyError):
            return FormatCheck(False, 'records')
        return FormatCheck(True, SCHEMA_VERSION)
