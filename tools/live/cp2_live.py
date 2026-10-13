#!/usr/bin/env python3
"""CP2 live run: one small, guarded step at a time against a throwaway Claude or Codex chat.

This script is run by hand by the reviewer. Nothing in the test suite runs it against a real home.
It is not part of the `baton` package; it only uses the package's adapters.

Safety rules, all enforced here before any step starts:
  * the chat must be named exactly "Baton test (safe to delete)" (the rename step's way back needs
    "Baton test renamed (safe to delete)") and must belong to this repository's folder;
  * the Codex adapter is built with that one chat id as its whole scope; the Claude adapter's locator
    is narrowed to that one chat's sidebar entry;
  * without --yes-write every step is a dry run: it reads the chat's metadata, prints what it would
    read and write and where the backup goes, and writes nothing;
  * every write goes through the adapter, except `restore`, which puts back its own backup;
  * before every write the chat's files are copied under the backup folder and verified;
  * an unexpected exception is printed, nothing more is written and the exit code is 1.

Exit codes: 0 step done, 2 refused (guard, held chat, adapter refusal) or result not as expected, 1 unexpected error.
Each step prints one JSON object per chat on one line. It never contains chat text: only counts,
record types, sizes, hashes and paths.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import sqlite3
import stat
import sys
import tempfile
import traceback
import uuid
from contextlib import closing
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from baton.adapters.claude import ClaudeAdapter  # noqa: E402
from baton.adapters.claude.locator import ClaudeLocator  # noqa: E402
from baton.adapters.codex import CodexAdapter  # noqa: E402
from baton.adapters.codex.coordination import NativeCoordination  # noqa: E402
from baton.domain.errors import BatonError, ChatHeld  # noqa: E402
from baton.domain.model import PROMPT, REPLY, Message, Turn  # noqa: E402
from baton.ports.tool import WriteReceipt  # noqa: E402

TITLE = "Baton test (safe to delete)"
RENAMED = "Baton test renamed (safe to delete)"
STEPS = ("inspect", "refuse-held", "add", "take-back", "rename", "rename-back", "restore")
BACKUP_BASE = Path(".baton-spike") / "backup"
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")
_SAFE_TYPE = re.compile(r"^[A-Za-z0-9_./-]{1,60}$")
_SNAPSHOT = re.compile(r"^(\d{2,})-([a-z-]+)$")

Factory = Callable[[str, Path, str, bool], Any]


class Refused(Exception):
    """A step that stopped on purpose before or instead of writing; `result` is what gets printed."""

    def __init__(self, reason: str, **details: Any):
        super().__init__(reason)
        self.result = {"ok": False, "refused": reason, **details}


# -- small file helpers ----------------------------------------------------------------------


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_private(path: Path, data: bytes) -> None:
    """Create a new 0600 file with these bytes, flushed to disk."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    fsync_directory(path.parent)


def replace_bytes(path: Path, data: bytes) -> None:
    """Atomically replace a file with these bytes, keeping its permissions."""
    mode = stat.S_IMODE(path.stat().st_mode)
    descriptor, temporary = tempfile.mkstemp(prefix=".baton-restore-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
        fsync_directory(path.parent)
    finally:
        Path(temporary).unlink(missing_ok=True)


def private_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, indent=1).encode()


# -- record types (never text) ---------------------------------------------------------------


def _label(value: Any) -> str | None:
    return value if isinstance(value, str) and _SAFE_TYPE.fullmatch(value) else None


def count_record_types(path: Path) -> dict[str, int]:
    """Count the record kinds of a JSONL chat file: `type` and, where there is one, `payload.type` or `subtype`."""
    counts: dict[str, int] = {}
    with path.open("rb") as stream:
        for line in stream:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except ValueError:
                key = "(unparsable line)"
            else:
                if not isinstance(record, dict):
                    key = "(not an object)"
                else:
                    key = _label(record.get("type")) or "(no type)"
                    payload = record.get("payload")
                    inner = (payload.get("type") if isinstance(payload, dict) else None) or record.get("subtype")
                    if _label(inner):
                        key += "/" + inner
            counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


# -- the two tools ---------------------------------------------------------------------------


class _OneChatLocator(ClaudeLocator):
    """The Claude locator seeing only one sidebar entry, so the adapter's format check reads one chat."""

    def __init__(self, root: Path, sidebar_id: str):
        super().__init__(root)
        self.only = sidebar_id

    def entries(self):
        for path, entry in super().entries():
            if entry["sessionId"] == self.only:
                yield path, entry


def default_factory(tool: str, home: Path, chat_id: str, injected: bool) -> Any:
    """The real adapter for the real home; for an injected home (tests) an inert one with no process control."""
    if tool == "codex":
        if injected:
            return CodexAdapter(home, allowed_chat_ids=(chat_id,), coordination=NativeCoordination())
        return CodexAdapter.on_this_machine(home, allowed_chat_ids=(chat_id,))
    adapter = ClaudeAdapter(home) if injected else ClaudeAdapter.on_this_machine(home)
    adapter.locator = _OneChatLocator(adapter.root, chat_id)
    return adapter


class Target:
    """One chat of one tool, seen through its adapter."""

    tool = ""

    def __init__(self, adapter: Any, chat_id: str):
        self.adapter = adapter
        self.chat_id = chat_id

    def ref(self):
        return self.adapter.locator.resolve(self.chat_id)

    def condition(self):
        return self.adapter.state.condition(self.chat_id)

    def files(self) -> dict[str, Path]:
        raise NotImplementedError

    def row(self) -> dict[str, Any] | None:
        return None

    def reads(self) -> list[str]:
        raise NotImplementedError

    def writes(self, step: str) -> list[str]:
        raise NotImplementedError

    def extras(self) -> dict[str, Any]:
        return {}

    def name(self) -> str:
        return self.adapter.locator.name(self.chat_id)

    def record_file(self) -> Path:
        return next(iter(self.files().values()))


class CodexTarget(Target):
    tool = "codex"

    def files(self) -> dict[str, Path]:
        return {"rollout": self.adapter.locator.rollout_path(self.chat_id)}

    def row(self) -> dict[str, Any]:
        row = self.adapter.locator.row(self.chat_id)
        if any(isinstance(value, (bytes, bytearray)) for value in row.values()):
            raise Refused("row_not_json", detail="the thread row has a binary column; it cannot be backed up as JSON")
        return row

    def reads(self) -> list[str]:
        locator = self.adapter.locator
        return ["thread row %s in %s" % (self.chat_id, locator.state_db),
                "rollout file of the thread (metadata and record types)",
                "index offset in %s" % locator.history_db,
                "lock file %s" % (locator.locks / (self.chat_id + ".lock"))]

    def writes(self, step: str) -> list[str]:
        locator = self.adapter.locator
        what = {"add": "append one turn to the rollout file and update the thread row",
                "take-back": "cut the rollout back and put the thread row back",
                "rename": "title and name in the thread row",
                "rename-back": "title and name in the thread row",
                "restore": "rollout file bytes and thread row from the backup",
                "refuse-held": "nothing (the adapter must refuse)"}[step]
        found = [what, "intent file under %s" % (self.adapter.root / ".baton-rollback")]
        if step in ("add", "take-back", "rename", "rename-back"):
            found.append("temporary lock file %s only if it does not exist (removed afterwards)"
                         % (locator.locks / (self.chat_id + ".lock")))
        return found

    def extras(self) -> dict[str, Any]:
        return {"index_offset": self.adapter.state.index.read_offset(self.chat_id),
                "rollout_size": self.record_file().stat().st_size}

    def restore_row(self, saved: dict[str, Any]) -> None:
        """Put a saved thread row back in one transaction (restore from our own backup only)."""
        columns = [column for column in saved if column != "id"]
        sets = ", ".join("%s = ?" % column for column in columns)
        with closing(sqlite3.connect(self.adapter.locator.state_db, timeout=5, isolation_level=None)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                cursor = connection.execute("UPDATE threads SET %s WHERE id = ?" % sets,
                                            [*(saved[c] for c in columns), self.chat_id])
                if cursor.rowcount != 1:
                    raise RuntimeError("the thread row to restore was not found exactly once")
                connection.execute("COMMIT")
            except BaseException:
                connection.execute("ROLLBACK")
                raise


class ClaudeTarget(Target):
    tool = "claude"

    def files(self) -> dict[str, Path]:
        return {"session": self.adapter.locator.session_path(self.chat_id),
                "sidebar": self.adapter.locator.entry(self.chat_id)[0]}

    def reads(self) -> list[str]:
        return ["sidebar entry of the chat (title, folder, session id)",
                "session file of the chat (metadata and record types)",
                "session registry %s (who holds the chat)" % (self.adapter.root / ".claude" / "sessions")]

    def writes(self, step: str) -> list[str]:
        what = {"add": "append one turn to the session file",
                "take-back": "put the session file and sidebar entry back",
                "rename": "title in the sidebar entry (the adapter refuses while the Claude app runs)",
                "rename-back": "title in the sidebar entry (the adapter refuses while the Claude app runs)",
                "restore": "session file and sidebar entry from the backup",
                "refuse-held": "nothing (the adapter must refuse)"}[step]
        return [what, "intent file under %s" % (self.adapter.root / ".baton-rollback")]


def make_target(tool: str, adapter: Any, chat_id: str) -> Target:
    return (CodexTarget if tool == "codex" else ClaudeTarget)(adapter, chat_id)


def resolve_claude_chat(home: Path, given: str) -> str:
    """The sidebar id for a sidebar id or a session id: exactly one sidebar entry must match."""
    matches = {entry["sessionId"] for _, entry in ClaudeLocator(home).entries()
               if given in (entry["sessionId"], entry.get("cliSessionId"))}
    if len(matches) != 1:
        raise Refused("claude_chat_not_found_exactly_once", matches=len(matches))
    return matches.pop()


# -- backups ---------------------------------------------------------------------------------


class Snapshot:
    """One verified copy of a chat's files taken just before a write: `<root>/<tool>-<chat>/NN-<step>/`."""

    def __init__(self, directory: Path):
        self.directory = directory
        self.meta: dict[str, Any] = json.loads((directory / "meta.json").read_text())

    @property
    def step(self) -> str:
        return self.meta["step"]

    def backup_bytes(self, role: str) -> bytes:
        return (self.directory / self.meta["files"][role]["backup"]).read_bytes()

    def saved_row(self) -> dict[str, Any] | None:
        return json.loads((self.directory / "row.json").read_text()) if self.meta.get("row") else None

    @staticmethod
    def take(target: Target, root: Path, step: str, now: datetime) -> "Snapshot":
        """Copy the files (and the Codex thread row) and check the copies before anything is written."""
        parent = private_directory(root / ("%s-%s" % (target.tool, target.chat_id)))
        numbers = [int(m.group(1)) for child in parent.iterdir() if (m := _SNAPSHOT.match(child.name))]
        directory = parent / ("%02d-%s" % (max(numbers, default=0) + 1, step))
        directory.mkdir(mode=0o700)
        files: dict[str, Any] = {}
        for role, path in target.files().items():
            before = path.read_bytes()
            backup = "%s.bak" % role
            write_private(directory / backup, before)
            if (directory / backup).read_bytes() != before or path.read_bytes() != before:
                raise RuntimeError("the %s changed while it was being copied" % role)
            files[role] = {"path": str(path), "sha256": sha256(before), "size": len(before), "backup": backup}
        row = target.row()
        if row is not None:
            write_private(directory / "row.json", json_bytes(row))
        meta = {"step": step, "tool": target.tool, "chat": target.chat_id, "files": files, "row": row is not None,
                "created_at": now.isoformat(timespec="seconds")}
        write_private(directory / "meta.json", json_bytes(meta))
        return Snapshot(directory)


def snapshots(root: Path, tool: str, chat_id: str) -> list[Snapshot]:
    """Every snapshot of this chat under a backup root, oldest first."""
    parent = root / ("%s-%s" % (tool, chat_id))
    if not parent.is_dir():
        return []
    ordered = sorted((child for child in parent.iterdir() if _SNAPSHOT.match(child.name) and (child / "meta.json").is_file()),
                     key=lambda child: child.name)
    return [Snapshot(child) for child in ordered]


def backup_root_for(ctx: "Context", tool: str, chat_id: str, creating: bool) -> Path:
    """`--backup-dir`; else a new timestamped folder (writing steps) or the newest existing one with this chat's snapshots."""
    if ctx.args.backup_dir:
        return Path(ctx.args.backup_dir)
    base = ctx.repo / BACKUP_BASE
    if creating:
        return base / ctx.now().strftime("%Y%m%dT%H%M%SZ")
    for candidate in sorted((child for child in base.iterdir() if child.is_dir()), reverse=True) if base.is_dir() else []:
        if snapshots(candidate, tool, chat_id):
            return candidate
    raise Refused("no_backup_found", looked_in=str(base))


# -- the context and the guards --------------------------------------------------------------


class Context:
    def __init__(self, args: argparse.Namespace, factory: Factory, now: Callable[[], datetime]):
        self.args = args
        self.factory = factory
        self.now = now
        self.repo = Path(args.repo).resolve() if args.repo else REPO
        self.home = Path(args.home).resolve() if args.home else Path.home()
        self.injected = args.home is not None
        self.step: str = args.step
        self.writing = bool(args.yes_write)

    @property
    def dry_run(self) -> bool:
        return self.step != "inspect" and not self.writing


def same_folder(folder: str, repo: Path) -> bool:
    return bool(folder) and Path(folder).resolve() == repo.resolve()


def guard(ctx: Context, target: Target) -> dict[str, Any]:
    """Refuse unless the chat has the throwaway title for this step and lives in this repository's folder."""
    allowed = {"rename-back": {RENAMED}, "inspect": {TITLE, RENAMED}, "restore": {TITLE, RENAMED}}.get(ctx.step, {TITLE})
    try:
        ref = target.ref()
    except KeyError:
        raise Refused("chat_not_found") from None
    result = {"title_ok": ref.name in allowed, "folder_ok": same_folder(ref.folder, ctx.repo)}
    if not all(result.values()):
        # Never print the real title or folder: they belong to a chat that is not a test chat.
        raise Refused("guard", **result)
    return result


def require_idle(target: Target) -> Any:
    """The chat exists, is readable by the checked format, and is neither held nor replying."""
    condition = target.condition()
    problems = [name for name, bad in (("not_found", not condition.exists), ("held", condition.open),
                                       ("replying", condition.replying), ("format_unknown", not condition.format_known)) if bad]
    if problems:
        raise Refused("not_idle", problems=problems)
    return condition


def plan(ctx: Context, target: Target, root: Path | None, extra: tuple[str, ...] | list[str] = ()) -> dict[str, Any]:
    return {"ok": True, "dry_run": True, "would_read": target.reads(), "would_write": [*target.writes(ctx.step), *extra],
            "backup_to": str(root) if root else None, "run_again_with": "--yes-write"}


# -- the steps -------------------------------------------------------------------------------


def step_inspect(ctx: Context, target: Target) -> dict[str, Any]:
    condition = target.condition()
    format_check = target.adapter.state.format_version()
    turns = target.adapter.reader.read(target.chat_id) if condition.exists else []
    path = target.record_file()
    result = {"format_known": bool(format_check.known), "format_version": str(format_check.version),
              "held": condition.open, "replying": condition.replying, "app_running": condition.app_running,
              "turn_count": len(turns), "file_size": path.stat().st_size,
              "record_types": count_record_types(path), **target.extras()}
    return {"ok": True, **result}


def new_turn(now: datetime, codeword: str) -> Turn:
    at = now.isoformat(timespec="seconds").replace("+00:00", "Z")
    return Turn(Message(str(uuid.uuid4()), PROMPT, "Baton live test turn " + codeword, at),
                (Message(str(uuid.uuid4()), REPLY, "Acknowledged " + codeword, at),))


def file_hashes(target: Target) -> dict[str, str]:
    return {role: sha256(path.read_bytes()) for role, path in target.files().items()}


def step_refuse_held(ctx: Context, target: Target) -> dict[str, Any]:
    """Needs a chat the app really holds. Tries one add and expects ChatHeld; checks nothing changed."""
    condition = target.condition()
    if not condition.exists or not condition.open:
        raise Refused("chat_is_not_held", detail="open the chat in the app first; nothing was attempted")
    root = backup_root_for(ctx, target.tool, target.chat_id, creating=True)
    if ctx.dry_run:
        return plan(ctx, target, root, ["a dummy add that must be refused as held"])
    snapshot = Snapshot.take(target, root, "refuse-held", ctx.now())
    before = file_hashes(target)
    refused_with = None
    try:
        target.adapter.writer.prepare(target.chat_id, "add")
        target.adapter.writer.add(target.chat_id, [new_turn(ctx.now(), "refused-" + secrets.token_hex(3))])
    except BatonError as error:
        refused_with = type(error).__name__
    unchanged = file_hashes(target) == before
    ok = refused_with == ChatHeld.__name__ and unchanged
    return {"ok": ok, "refused_with": refused_with, "files_unchanged": unchanged, "backup": str(snapshot.directory),
            **({} if unchanged else {"next": "run the restore step"})}


def step_add(ctx: Context, target: Target) -> dict[str, Any]:
    require_idle(target)
    root = backup_root_for(ctx, target.tool, target.chat_id, creating=True)
    if ctx.dry_run:
        return plan(ctx, target, root, ["backup first: copies of the chat's files (and the thread row for Codex)"])
    adapter, chat_id = target.adapter, target.chat_id
    snapshot = Snapshot.take(target, root, "add", ctx.now())
    codeword = "%s-%s" % (secrets.choice(("amber", "birch", "cedar", "dune", "ember", "fjord")), secrets.token_hex(2))
    turn = new_turn(ctx.now(), codeword)
    turns_before = adapter.reader.read(chat_id)
    bytes_before = {role: snapshot.backup_bytes(role) for role in snapshot.meta["files"]}
    adapter.writer.prepare(chat_id, "add")
    written = adapter.writer.add(chat_id, [turn])
    write_private(snapshot.directory / "add-receipt.json", json_bytes(asdict(written.receipt)))
    turns_after = adapter.reader.read(chat_id)
    main_role = next(iter(bytes_before))
    bytes_after = target.files()[main_role].read_bytes()
    checks = {"one_more_turn": len(turns_after) == len(turns_before) + 1,
              "earlier_turns_equal": turns_after[:len(turns_before)] == turns_before,
              "prompt_read_back": bool(turns_after) and turns_after[-1].prompt.text == turn.prompt.text,
              "reply_read_back": bool(turns_after) and turns_after[-1].reply_text == turn.messages[0].text,
              "old_bytes_are_a_prefix": bytes_after.startswith(bytes_before[main_role])}
    return {"ok": all(checks.values()), "codeword": codeword, "checks": checks, "turns_before": len(turns_before),
            "turns_after": len(turns_after), "size_before": len(bytes_before[main_role]), "size_after": len(bytes_after),
            "backup": str(snapshot.directory), **target.extras()}


def step_take_back(ctx: Context, target: Target) -> dict[str, Any]:
    root = backup_root_for(ctx, target.tool, target.chat_id, creating=False)
    candidates = [s for s in snapshots(root, target.tool, target.chat_id)
                  if s.step == "add" and (s.directory / "add-receipt.json").is_file()
                  and not (s.directory / "taken-back.json").exists()]
    if not candidates:
        raise Refused("no_add_to_take_back", looked_in=str(root))
    snapshot = candidates[-1]
    require_idle(target)
    if ctx.dry_run:
        return plan(ctx, target, root, ["compare the files with the backup %s afterwards" % snapshot.directory])
    data = json.loads((snapshot.directory / "add-receipt.json").read_text())
    target.adapter.writer.take_back(WriteReceipt(data["tool"], data["chat_id"], data["kind"], data["data"]))
    write_private(snapshot.directory / "taken-back.json", json_bytes({"at": ctx.now().isoformat(timespec="seconds")}))
    checks = {role: sha256(path.read_bytes()) == snapshot.meta["files"][role]["sha256"]
              for role, path in target.files().items()}
    if snapshot.meta.get("row"):
        checks["thread_row"] = target.row() == snapshot.saved_row()
    return {"ok": all(checks.values()), "bytes_equal_to_backup": checks, "backup": str(snapshot.directory), **target.extras()}


def step_rename(ctx: Context, target: Target, new_name: str) -> dict[str, Any]:
    require_idle(target)
    root = backup_root_for(ctx, target.tool, target.chat_id, creating=True)
    if ctx.dry_run:
        return plan(ctx, target, root, ["new name: " + new_name])
    snapshot = Snapshot.take(target, root, ctx.step, ctx.now())
    target.adapter.writer.prepare(target.chat_id, "rename")
    written = target.adapter.writer.rename(target.chat_id, new_name)
    write_private(snapshot.directory / "rename-receipt.json", json_bytes(asdict(written.receipt)))
    name = target.name()
    return {"ok": name == new_name, "name_read_back_matches": name == new_name, "backup": str(snapshot.directory)}


def step_restore(ctx: Context, target: Target) -> dict[str, Any]:
    root = backup_root_for(ctx, target.tool, target.chat_id, creating=False)
    found = snapshots(root, target.tool, target.chat_id)
    if not found:
        raise Refused("no_backup_found", looked_in=str(root))
    snapshot = found[0]
    require_idle(target)
    if ctx.dry_run:
        return plan(ctx, target, root, ["backup used (the oldest in the folder): %s" % snapshot.directory])
    return restore_locked(ctx, target, snapshot)


def restore_locked(ctx: Context, target: Target, snapshot: Snapshot) -> dict[str, Any]:
    """Put the backup back, holding Codex's thread lock while doing it, then compare with the backup."""
    adapter = target.adapter
    if target.tool == "codex":
        coordination = adapter.coordination
        if coordination is None:
            raise Refused("no_lock_protocol")
        try:
            with coordination.exclusive(adapter.locator, target.chat_id) as lease:
                changed = apply_backup(target, snapshot, lease.check)
        except ChatHeld:
            raise Refused("not_idle", problems=["held"]) from None
    else:
        changed = apply_backup(target, snapshot, lambda: None)
    checks = {role: sha256(path.read_bytes()) == snapshot.meta["files"][role]["sha256"]
              for role, path in target.files().items()}
    if snapshot.meta.get("row"):
        checks["thread_row"] = target.row() == snapshot.saved_row()
    result = {"ok": all(checks.values()), "restored": changed, "bytes_equal_to_backup": checks, "backup": str(snapshot.directory),
              **target.extras()}
    offset = result.get("index_offset")
    if target.tool == "codex" and isinstance(offset, int) and offset > snapshot.meta["files"]["rollout"]["size"]:
        result["warning"] = "codex_index_is_past_the_restored_file"
    return result


def apply_backup(target: Target, snapshot: Snapshot, recheck: Callable[[], None]) -> list[str]:
    """Replace each file whose bytes differ from the backup; Codex's row last. Returns what was replaced."""
    condition = target.condition()
    if condition.replying or (target.tool == "claude" and condition.open):
        raise Refused("not_idle", problems=["held" if condition.open else "replying"])
    changed: list[str] = []
    for role, path in target.files().items():
        saved = snapshot.backup_bytes(role)
        if path.read_bytes() == saved:
            continue
        if role == "sidebar" and condition.app_running:
            raise Refused("app_running_and_sidebar_differs", detail="quit the Claude app first; nothing was written")
        recheck()
        replace_bytes(path, saved)
        changed.append(role)
    saved_row = snapshot.saved_row()
    if saved_row is not None and target.row() != saved_row:
        recheck()
        target.restore_row(saved_row)
        changed.append("thread_row")
    return changed


def run_step(ctx: Context, target: Target) -> dict[str, Any]:
    step = ctx.step
    if step == "inspect":
        return step_inspect(ctx, target)
    if step == "refuse-held":
        return step_refuse_held(ctx, target)
    if step == "add":
        return step_add(ctx, target)
    if step == "take-back":
        return step_take_back(ctx, target)
    if step == "rename":
        return step_rename(ctx, target, RENAMED)
    if step == "rename-back":
        return step_rename(ctx, target, TITLE)
    return step_restore(ctx, target)


# -- entry point -----------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--codex-chat", metavar="THREAD_ID", help="id of the throwaway Codex thread")
    parser.add_argument("--claude-chat", metavar="SESSION_ID", help="id of the throwaway Claude chat (sidebar id or session id)")
    parser.add_argument("--step", required=True, choices=STEPS)
    parser.add_argument("--backup-dir", help="backup folder (default: .baton-spike/backup/<timestamp>/ in the repository; "
                                             "take-back and restore default to the newest one holding this chat)")
    parser.add_argument("--yes-write", action="store_true", help="really write; without it every writing step is a dry run")
    parser.add_argument("--home", help="home folder to use instead of the real one (for tests)")
    parser.add_argument("--repo", help="repository folder the chat must belong to (default: this repository)")
    return parser


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def main(argv: list[str] | None = None, *, adapter_factory: Factory | None = None,
         now: Callable[[], datetime] | None = None, stdout=None, stderr=None) -> int:
    out, err = stdout or sys.stdout, stderr or sys.stderr
    args = build_parser().parse_args(argv)
    if not (args.codex_chat or args.claude_chat):
        build_parser().error("give --codex-chat and/or --claude-chat")
    ctx = Context(args, adapter_factory or default_factory, now or _utc_now)
    wanted = [(tool, chat) for tool, chat in (("codex", args.codex_chat), ("claude", args.claude_chat)) if chat]
    try:
        for tool, given in wanted:
            header = {"step": ctx.step, "tool": tool}
            try:
                if not _SAFE_ID.fullmatch(given):
                    raise Refused("chat_id_not_allowed")
                chat_id = resolve_claude_chat(ctx.home, given) if tool == "claude" else given
                target = make_target(tool, ctx.factory(tool, ctx.home, chat_id, ctx.injected), chat_id)
                header["chat"] = chat_id
                result = {**header, **guard_then_run(ctx, target)}
            except Refused as stop:
                result = {**header, **stop.result}
            except BatonError as error:
                result = {**header, "ok": False, "refused": "adapter", "error": type(error).__name__}
            print(json.dumps(result, sort_keys=True), file=out, flush=True)
            if not result.get("ok", False):
                return 2
    except Exception as error:  # noqa: BLE001 - last resort: say what happened, write nothing more
        traceback.print_exc(file=err)
        print(json.dumps({"step": ctx.step, "ok": False, "unexpected_error": "%s: %s" % (type(error).__name__, error),
                          "note": "nothing more was written; backups are under the backup folder"}), file=out, flush=True)
        return 1
    return 0


def guard_then_run(ctx: Context, target: Target) -> dict[str, Any]:
    guard_result = guard(ctx, target)
    result = run_step(ctx, target)
    return {"guard": guard_result, **result}


if __name__ == "__main__":
    sys.exit(main())
