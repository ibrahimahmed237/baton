"""Write into Codex chats: rollout file first, thread row second, every step reversible.

Every write first saves an intent manifest (fsynced) that names the state
before and after. `take_back` reads it, so a write can be undone by a new
process after a crash, and only while nothing else has touched what Baton wrote.
Codex cannot be made to forget turns, so the only way a rollout gets shorter is
the take-back of Baton's own last append, while Codex's chat view has not read
past it.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import sqlite3
import stat
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any, Sequence
from uuid import uuid4

from ...domain.errors import ChatChanged, ChatHeld, ChatReplying, NotAvailable, UnknownFormat
from ...domain.model import Turn
from ...ports.tool import WriteReceipt, WriteResult
from .records import message_ids, next_ordinal, parse_strict, serialize, session_meta_record, turn_records

logger = logging.getLogger(__name__)

KINDS = ("create", "add", "cut", "rename", "place", "restore")
# What Codex cannot do to an existing chat.
_NOT_CODEX = ("cut", "place", "restore")
_TIME_COLUMNS = ("updated_at", "updated_at_ms", "recency_at", "recency_at_ms")
_FALLBACK_SANDBOX = '{"type":"read-only"}'
_FALLBACK_APPROVAL = "on-request"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _encode(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _decode(text: str) -> bytes:
    return base64.b64decode(text)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class CodexWriter:
    """Create, add to and rename Codex chats, and take those writes back."""

    def __init__(self, adapter):
        self.adapter = adapter
        self.prepared: WriteReceipt | None = None
        self.lease = None

    # -- guards -----------------------------------------------------------

    def _check(self, chat_id: str | None = None) -> None:
        """Refuse before any change: unchecked format, no database, or a chat Codex holds or is answering in."""
        state, locator = self.adapter.state, self.adapter.locator
        if chat_id is not None:
            self.adapter.scope.require(chat_id)
        if not state.format_version().known:
            raise UnknownFormat()
        if not locator.state_db.exists():
            raise NotAvailable()
        if chat_id is None:
            return
        locator.rollout_path(chat_id)
        if not state.target_format(chat_id).known:
            raise UnknownFormat()
        if self.lease is not None:
            self.lease.check()
            return
        if state.replying(chat_id):
            raise ChatReplying()
        if state.held(chat_id):
            raise ChatHeld()

    def _intent_path(self, token: str) -> Path:
        folder = self.adapter.root / '.baton-rollback'
        if folder.is_symlink():
            raise NotAvailable()
        return self.adapter.scope.checked_path(folder / (self.adapter.scope.key + '-' + token + '.json'))

    # -- receipts ---------------------------------------------------------

    def _row_fields(self, chat_id: str, fields: Sequence[str]) -> dict[str, Any]:
        row = self.adapter.locator.row(chat_id)
        return {field: row.get(field) for field in fields}

    def prepare(self, chat_id: str | None, kind: str) -> WriteReceipt:
        """Save what a write will change, before it changes anything."""
        if kind not in KINDS or (chat_id is None) != (kind == "create"):
            raise ValueError(kind)
        if kind in _NOT_CODEX:
            raise NotAvailable()
        self._check(chat_id)
        if self.adapter.coordination is None:
            raise NotAvailable()
        token = uuid4().hex
        data: dict[str, Any] = {"prepared": True, "token": token, "intent": str(self._intent_path(token)),
                                "rollout": None, "row": {"before": None}}
        if kind == "create":
            chat_id = str(uuid4())
            self.adapter.scope.register_created(chat_id)
            path = self.adapter.locator.new_rollout_path(chat_id, self.adapter.now())
            data["rollout"] = {"path": str(path), "size": None, "sha": None}
        else:
            path = self.adapter.locator.rollout_path(chat_id)
            if kind == "add":
                raw = path.read_bytes()
                data["rollout"] = {"path": str(path), "size": len(raw), "sha": _sha(raw)}
                data["row"] = {"before": self.adapter.locator.row(chat_id)}
            else:
                data["row"] = {"before": self.adapter.locator.row(chat_id)}
                raw = path.read_bytes()
                data["target"] = {"path": str(path), "size": len(raw), "sha": _sha(raw)}
        receipt = WriteReceipt(self.adapter.name, chat_id, kind, data)
        self.prepared = receipt
        return receipt

    def _begin(self, chat_id: str | None, kind: str) -> WriteReceipt:
        receipt = self.prepared
        if receipt is None or receipt.kind != kind or (chat_id is not None and receipt.chat_id != chat_id):
            receipt = self.prepare(chat_id, kind)
        self.prepared = None
        return receipt

    # -- the operations ---------------------------------------------------

    def create(self, turns: Sequence[Turn], name: str, folder: str) -> WriteResult:
        """A new chat: rollout file, a check that it reads back, then the thread row."""
        self._check()
        receipt = self._begin(None, "create")
        now = self.adapter.now()
        template = self._template()
        records = [session_meta_record(receipt.chat_id, folder, now, template["cli_version"], template["base_instructions"])]
        records += turn_records(turns, receipt.chat_id, 1, now)
        row = self._new_row(receipt, name, folder, turns, template, now)
        with closing(sqlite3.connect(self.adapter.locator.state_db)) as connection:
            for column in connection.execute('PRAGMA table_info(threads)'):
                if column[1] not in row:
                    row[column[1]] = connection.execute('SELECT ' + column[4]).fetchone()[0] if column[4] is not None else None
        return self._publish(receipt, turns, serialize(records), {"mode": "insert", "before": None, "after": row})

    def add(self, chat_id: str, turns: Sequence[Turn]) -> WriteResult:
        """Append finished turns with the next ordinals and bump the thread's times."""
        self._check(chat_id)
        receipt = self._begin(chat_id, "add")
        try:
            records = parse_strict(self.adapter.locator.rollout_path(chat_id).read_bytes())
        except ValueError as error:
            raise UnknownFormat() from error
        ids = [m.id for t in turns for m in (t.prompt, *t.messages)]
        if len(ids) != len(set(ids)) or message_ids(records).intersection(ids):
            raise ValueError("duplicate message id")
        now = self.adapter.now()
        appended = serialize(turn_records(turns, chat_id, next_ordinal(records), now)) if turns else b""
        before = receipt.data["row"]["before"]
        if turns:
            ms = int(now.timestamp() * 1000)
            after = {**before, "updated_at": ms // 1000, "updated_at_ms": ms, "recency_at": ms // 1000, "recency_at_ms": ms}
        else:
            after = dict(before)
        return self._publish(receipt, turns, appended, {"mode": "update", "before": before, "after": after})

    def rename(self, chat_id: str, name: str) -> WriteResult:
        """Set both the title and the name of the thread; Codex shows it after a relaunch."""
        self._check(chat_id)
        receipt = self._begin(chat_id, "rename")
        row = {"mode": "update", "before": receipt.data["row"]["before"], "after": {**receipt.data["row"]["before"], "title": name, "name": name}}
        return self._publish(receipt, (), None, row)

    def place(self, chat_id: str, turns: Sequence[Turn], before_local_id: str) -> WriteResult:
        """Codex has no way to put a turn before another."""
        self._check()
        raise NotAvailable()

    def cut(self, chat_id: str, keep_through_local_id: str) -> WriteResult:
        """Codex keeps showing a rollout it has read past, so a chat is never made shorter this way.

        The one exception is `take_back` of Baton's own last append.
        """
        self._check()
        raise NotAvailable()

    def restore(self, receipt: WriteReceipt) -> WriteResult:
        """There is no cut to restore."""
        raise NotAvailable()

    # -- create helpers ---------------------------------------------------

    def _template(self) -> dict[str, Any]:
        """Settings and base instructions of the user's newest threads, so a new chat behaves like theirs."""
        locator = self.adapter.locator
        rows = [row for row in locator.scoped_rows()
                if locator.is_chat(row) and row.get("thread_source") == "user"]
        rows.sort(key=lambda row: -(row.get("updated_at_ms") or (row.get("updated_at") or 0) * 1000))
        newest = rows[0] if rows else {}
        base_instructions, meta_version = None, ""
        for row in rows[:5]:
            try:
                path = locator.rollout_path(row["id"])
                with path.open("rb") as fh:
                    meta = (json.loads(fh.readline()) or {}).get("payload") or {}
            except (OSError, ValueError, AttributeError, KeyError):
                continue
            if meta.get("base_instructions"):
                base_instructions, meta_version = meta["base_instructions"], meta.get("cli_version") or ""
                break
        return {"sandbox_policy": newest.get("sandbox_policy") or _FALLBACK_SANDBOX,
                "approval_mode": newest.get("approval_mode") or _FALLBACK_APPROVAL,
                "model": newest.get("model"), "reasoning_effort": newest.get("reasoning_effort"),
                "cli_version": newest.get("cli_version") or meta_version, "base_instructions": base_instructions}

    @staticmethod
    def _new_row(receipt: WriteReceipt, name: str, folder: str, turns: Sequence[Turn],
                 template: dict[str, Any], now) -> dict[str, Any]:
        ms = int(now.timestamp() * 1000)
        first = turns[0].prompt.text if turns else ""
        return {"id": receipt.chat_id, "rollout_path": receipt.data["rollout"]["path"],
                "created_at": ms // 1000, "updated_at": ms // 1000, "source": "vscode", "model_provider": "openai",
                "cwd": folder, "title": name, "sandbox_policy": template["sandbox_policy"],
                "approval_mode": template["approval_mode"], "tokens_used": 0, "has_user_event": 0, "archived": 0,
                "cli_version": template["cli_version"], "first_user_message": first, "model": template["model"],
                "reasoning_effort": template["reasoning_effort"], "created_at_ms": ms, "updated_at_ms": ms,
                "thread_source": "user", "preview": first[:200], "recency_at": ms // 1000, "recency_at_ms": ms,
                "history_mode": "paginated", "name": name, "is_pinned": 0, "originator": "Codex Desktop"}

    # -- publishing -------------------------------------------------------

    @contextmanager
    def _exclusive(self, chat_id: str):
        if self.adapter.coordination is None:
            raise NotAvailable()
        if self.lease is not None:
            self.lease.check()
            yield
            return
        with self.adapter.coordination.exclusive(self.adapter.locator, chat_id) as lease:
            self.lease = lease
            try:
                lease.check()
                yield
                lease.check()
            finally:
                self.lease = None

    @contextmanager
    def _transaction(self):
        locator = self.adapter.locator
        with closing(sqlite3.connect(locator.state_db, timeout=5, isolation_level=None)) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute('BEGIN IMMEDIATE')
            locator._writer_connection = connection
            try:
                yield connection
                self.lease.check()
                connection.execute('COMMIT')
            except BaseException:
                connection.execute('ROLLBACK')
                raise
            finally:
                locator._writer_connection = None

    def _publish(self, receipt: WriteReceipt, turns: Sequence[Turn], appended: bytes | None,
                 row: dict[str, Any]) -> WriteResult:
        """Hold verified exclusion through final checks, publication and recovery."""
        with self._exclusive(receipt.chat_id):
            return self._publish_locked(receipt, turns, appended, row)

    def _publish_locked(self, receipt: WriteReceipt, turns: Sequence[Turn], appended: bytes | None,
                 row: dict[str, Any]) -> WriteResult:
        """Save the intent, recheck, mutate, verify; on any failure put everything back."""
        data, locator = receipt.data, self.adapter.locator
        rollout = None if data["rollout"] is None else {**data["rollout"], "appended": _encode(appended or b"")}
        manifest = {"token": data["token"], "kind": receipt.kind, "chat_id": receipt.chat_id,
                    "rollout": rollout, "row": row, "target": data.get("target"),
                    "scope": sorted(self.adapter.scope.original)}
        intent = self._intent_path(data['token'])
        if str(intent) != data['intent']:
            raise ValueError('receipt_path')
        self._save_intent(intent, manifest)
        mutated = False
        try:
            with self._transaction():
                self._recheck(receipt, manifest)
                mutated = True
                self._mutate(manifest, [t.id for t in turns])
        except BaseException:
            if not mutated:
                intent.unlink(missing_ok=True)
                raise
            try:
                self._revert(manifest, intent)
            except (OSError, ValueError, sqlite3.Error, ChatChanged, ChatHeld, ChatReplying, NotAvailable):
                logger.exception("could not put back a failed write; the intent %s remains", intent)
            raise
        post = WriteReceipt(receipt.tool, receipt.chat_id, receipt.kind, {**data, "prepared": False})
        return WriteResult(receipt.chat_id, tuple(t.id for t in turns), post)

    @staticmethod
    def _save_intent(intent: Path, manifest: dict[str, Any]) -> None:
        intent.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        info = intent.parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise NotAvailable()
        os.chmod(intent.parent, 0o700)
        descriptor = os.open(intent, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as fh:
            json.dump(manifest, fh)
            fh.flush()
            os.fsync(fh.fileno())
        _fsync_directory(intent.parent)

    def _recheck(self, receipt: WriteReceipt, manifest: dict[str, Any]) -> None:
        """Immediately before the first change: still allowed, and still exactly as it was prepared."""
        creating = receipt.kind == "create"
        self._check(None if creating else receipt.chat_id)
        target = manifest.get("target")
        if target:
            raw = self.adapter.locator.inside(target["path"]).read_bytes()
            if len(raw) != target["size"] or _sha(raw) != target["sha"]:
                raise ChatChanged()
        spec = manifest["rollout"]
        if spec is not None:
            path = self.adapter.locator.inside(spec["path"])
            if creating:
                if path.exists():
                    raise ChatChanged()
            else:
                raw = path.read_bytes()
                if len(raw) != spec["size"] or _sha(raw) != spec["sha"]:
                    raise ChatChanged()
        if creating:
            if self._row_exists(receipt.chat_id):
                raise ChatChanged()
        elif self._row_fields(receipt.chat_id, tuple(manifest["row"]["before"])) != manifest["row"]["before"]:
            raise ChatChanged()

    def _row_exists(self, chat_id: str) -> bool:
        try:
            self.adapter.locator.row(chat_id)
        except KeyError:
            return False
        return True

    def _mutate(self, manifest: dict[str, Any], expected_ids: list[str]) -> None:
        self.lease.check()
        spec, chat_id = manifest["rollout"], manifest["chat_id"]
        if spec is not None:
            path = self.adapter.locator.inside(spec["path"])
            appended = _decode(spec["appended"])
            if spec["size"] is None:
                path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb" if spec["size"] is None else "ab") as fh:
                fh.write(appended)
                fh.flush()
                os.fsync(fh.fileno())
            _fsync_directory(path.parent)
            self._verify_rollout(path, spec, appended)
        self._write_row(manifest)
        if manifest["kind"] in ("create", "add") and expected_ids:
            read = [t.id for t in self.adapter.reader.read(chat_id)]
            if read[-len(expected_ids):] != expected_ids or (manifest["kind"] == "create" and read != expected_ids):
                raise ChatChanged()
        if manifest["kind"] == "create":
            self.adapter.locator.resolve(chat_id)

    @staticmethod
    def _verify_rollout(path: Path, spec: dict[str, Any], appended: bytes) -> None:
        """The file holds what was prepared plus what was appended, and every line parses."""
        raw = path.read_bytes()
        size = spec["size"] or 0
        if len(raw) != size + len(appended) or raw[size:] != appended:
            raise ChatChanged()
        if spec["size"] is not None and _sha(raw[:size]) != spec["sha"]:
            raise ChatChanged()
        try:
            parse_strict(raw)
        except ValueError as error:
            raise ChatChanged() from error

    def _write_row(self, manifest: dict[str, Any]) -> None:
        """Insert or update the thread row in one transaction; an update only applies to the row as it was prepared."""
        spec, chat_id = manifest["row"], manifest["chat_id"]
        self.lease.check()
        connection = self.adapter.locator._writer_connection
        if connection is None:
            raise NotAvailable()
        if spec['mode'] == 'insert':
            columns = list(spec['after'])
            cursor = connection.execute('INSERT INTO threads (%s) VALUES (%s)' %
                (', '.join(columns), ', '.join('?' * len(columns))), [spec['after'][c] for c in columns])
            if cursor.rowcount != 1:
                raise ChatChanged()
        else:
            self._update(connection, chat_id, spec['before'], spec['after'])

    @staticmethod
    def _update(connection: sqlite3.Connection, chat_id: str, expect: dict[str, Any], values: dict[str, Any]) -> None:
        sets = ", ".join("%s = ?" % column for column in values)
        guard = " AND ".join("%s IS ?" % column for column in expect)
        cursor = connection.execute("UPDATE threads SET %s WHERE id = ?%s" % (sets, " AND " + guard if guard else ""),
                                    [*values.values(), chat_id, *expect.values()])
        if cursor.rowcount != 1:
            raise ChatChanged()

    # -- taking a write back ----------------------------------------------

    def take_back(self, receipt: WriteReceipt) -> None:
        """Undo one write of this adapter, unless something else has changed what it wrote."""
        if receipt.tool != self.adapter.name:
            raise ValueError("wrong adapter")
        token = receipt.data['token']
        if not isinstance(token, str) or len(token) != 32 or any(c not in '0123456789abcdef' for c in token):
            raise ValueError('receipt_token')
        intent = self._intent_path(token)
        if str(intent) != receipt.data['intent']:
            raise ValueError('receipt_path')
        if not intent.exists():
            if receipt.data.get("prepared"):
                return
            raise ValueError("receipt consumed")
        info = intent.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
                info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600):
            raise NotAvailable()
        manifest = json.loads(intent.read_text())
        if (manifest.get("token"), manifest.get("chat_id"), manifest.get("kind")) != (receipt.data["token"], receipt.chat_id, receipt.kind):
            raise ValueError("receipt mismatch")
        stored_rollout = manifest.get('rollout')
        prepared_rollout = receipt.data.get('rollout')
        if (({key: stored_rollout.get(key) for key in ('path','size','sha')} if stored_rollout else None) != prepared_rollout or
                manifest.get('target') != receipt.data.get('target') or
                manifest.get('row', {}).get('before') != receipt.data.get('row', {}).get('before')):
            raise ValueError('receipt_manifest')
        if receipt.kind == 'create' and not self.adapter.scope.contains(receipt.chat_id):
            self.adapter.scope.recover_created(manifest, intent)
        self.adapter.scope.require(receipt.chat_id)
        self._revert(manifest, intent)

    def _rollout_state(self, spec: dict[str, Any]) -> str:
        """Where the rollout is between the prepared state and the written one."""
        path = self.adapter.locator.inside(spec["path"])
        appended, size = _decode(spec["appended"]), spec["size"]
        if not path.exists():
            return "before" if size is None else "changed"
        raw = path.read_bytes()
        if size is None:
            tail = raw
        elif len(raw) < size or _sha(raw[:size]) != spec["sha"]:
            return "changed"
        else:
            tail = raw[size:]
        if tail == appended:
            return "after"
        if size is not None and not tail:
            return "before"
        return "partial" if appended.startswith(tail) else "changed"

    def _row_state(self, manifest: dict[str, Any]) -> str:
        spec = manifest["row"]
        try:
            row = self.adapter.locator.row(manifest["chat_id"])
        except KeyError:
            return "before" if spec["mode"] == "insert" else "changed"
        if spec["mode"] == "insert":
            return "after" if row == spec["after"] else "changed"
        current = row
        if current == spec["after"]:
            return "after"
        return "before" if current == spec["before"] else "changed"

    def _revert(self, manifest: dict[str, Any], intent: Path) -> None:
        with self._exclusive(manifest['chat_id']):
            with self._transaction():
                self._revert_locked(manifest, intent)
            intent.unlink()
            _fsync_directory(intent.parent)

    def _revert_locked(self, manifest: dict[str, Any], intent: Path) -> None:
        chat_id, spec = manifest["chat_id"], manifest["rollout"]
        state = self.adapter.state
        self.adapter.scope.require(chat_id)
        self.lease.check()
        if not state._threads_columns_ok():
            raise UnknownFormat()
        target = manifest.get('target')
        if target:
            raw = self.adapter.locator.inside(target['path']).read_bytes()
            if len(raw) != target['size'] or _sha(raw) != target['sha']:
                raise ChatChanged()
        row_state = self._row_state(manifest)
        if row_state == "changed":
            raise ChatChanged()
        rollout_state = "before" if spec is None else self._rollout_state(spec)
        if "changed" in (rollout_state, row_state):
            raise ChatChanged()
        shortening = spec is not None and spec["size"] is not None and rollout_state != "before"
        if shortening and spec["appended"]:
            # Codex's chat view keeps what it has read; a shorter file would disagree with it for good.
            offset = state.index.read_offset(chat_id)
            if offset is None or offset > spec["size"]:
                raise NotAvailable()
        creating = manifest["row"]["mode"] == "insert"
        if creating and row_state == "after":
            self._remove_row(chat_id, manifest["row"]["after"])
        if not creating and row_state == 'after':
            self._update(self.adapter.locator._writer_connection, chat_id, manifest['row']['after'], manifest['row']['before'])
        if rollout_state != 'before':
            self.lease.check()
            self._remove_appended(spec)

    def _remove_row(self, chat_id: str, expected: dict) -> None:
        self.lease.check()
        guard = ' AND '.join(column + ' IS ?' for column in expected)
        cursor = self.adapter.locator._writer_connection.execute(
            'DELETE FROM threads WHERE ' + guard, list(expected.values()))
        if cursor.rowcount != 1:
            raise ChatChanged()

    def _remove_appended(self, spec: dict[str, Any]) -> None:
        path = self.adapter.locator.inside(spec["path"])
        if spec["size"] is None:
            path.unlink(missing_ok=True)
        else:
            with path.open("r+b") as fh:
                fh.truncate(spec["size"])
                fh.flush()
                os.fsync(fh.fileno())
        _fsync_directory(path.parent)
