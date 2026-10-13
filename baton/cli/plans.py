"""Plans waiting for `--confirm`.

A command that would change something prints a plan and remembers how it was
asked for. A later `--confirm <plan_id>` runs in a new process, so the plan is
kept as the request that produced it: the command name and its arguments.

Each preview gets its own confirmation id (what the app is shown and sends
back). The service's plan id, which fingerprints the full state of the chats and
records, is kept next to it as the plan's `fingerprint`. To confirm, the plan is
claimed (removed, so only one process can ever carry it out), the stored request
is planned again from the chats as they are now, and the new fingerprint must be
the stored one. Anything else is refused with ChatChanged.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import stat
from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Protocol

from ..domain.errors import BatonError, ChatChanged
from ..ports.clock import Clock

class WrongPlanAction(BatonError):
    """The confirmation belongs to a different action."""
    note_id = "plan.wrong_action"


PLAN_LIFETIME = timedelta(minutes=10)
_PLAN_ID = re.compile(r"^p_[0-9A-Za-z_-]{1,128}$")
_PLAN_FILE = re.compile(r"^(p_[0-9A-Za-z_-]{1,128})\.json$")


@dataclass(frozen=True)
class StoredPlan:
    """A shown plan: its confirmation id, the state fingerprint, the request and when it was shown."""
    plan_id: str
    fingerprint: str
    command: str
    arguments: dict[str, Any]
    stored_at: str


def _valid(data: Any, plan_id: str) -> StoredPlan | None:
    """Return the plan a decoded file describes, or None unless every field is right."""
    if not isinstance(data, dict) or set(data) != {"plan_id", "fingerprint", "command", "arguments", "stored_at"}:
        return None
    if data["plan_id"] != plan_id or not isinstance(data["arguments"], dict):
        return None
    if not all(isinstance(data[key], str) for key in ("plan_id", "fingerprint", "command", "stored_at")):
        return None
    return StoredPlan(data["plan_id"], data["fingerprint"], data["command"], data["arguments"], data["stored_at"])


class PlanStore(Protocol):
    """Keeps shown plans between two runs of the command."""
    def save(self, plan: StoredPlan) -> None:
        """Keep a plan."""
        ...

    def claim(self, plan_id: str) -> StoredPlan | None:
        """Remove a plan and return it. Of any number of claims, at most one gets the plan."""
        ...

    def load(self, plan_id: str) -> StoredPlan | None:
        """Return a plan without removing it, or None when it is not kept or not valid."""
        ...

    def delete(self, plan_id: str) -> None:
        """Forget a plan; forgetting an unknown plan is not an error."""
        ...

    def all(self) -> Iterable[StoredPlan]:
        """Return every valid kept plan."""
        ...


class MemoryPlanStore:
    """Keep plans in this process, for tests."""
    def __init__(self) -> None:
        self._plans: dict[str, StoredPlan] = {}

    def save(self, plan: StoredPlan) -> None:
        """Keep a plan."""
        self._plans[plan.plan_id] = plan

    def claim(self, plan_id: str) -> StoredPlan | None:
        """Remove and return a plan."""
        return self._plans.pop(plan_id, None)

    def load(self, plan_id: str) -> StoredPlan | None:
        """Return a kept plan."""
        return self._plans.get(plan_id)

    def delete(self, plan_id: str) -> None:
        """Forget a plan."""
        self._plans.pop(plan_id, None)

    def all(self) -> list[StoredPlan]:
        """Return every kept plan."""
        return list(self._plans.values())


class FilePlanStore:
    """Keep each plan as one small JSON file in a private folder.

    The folder is ours alone (mode 0700) and may not be a symbolic link; a plan
    file that is a symbolic link is never followed. Files are written to a
    temporary name and renamed into place; a claim is a rename, which only one
    process can win.
    """
    def __init__(self, folder: Path):
        self.folder = Path(folder)

    def _open_folder(self, create: bool = False) -> int | None:
        """Open the folder without following a link; None when it is absent or not ours."""
        if create:
            self.folder.parent.mkdir(parents=True, exist_ok=True)
            with suppress(FileExistsError):
                os.mkdir(self.folder, 0o700)
        try:
            descriptor = os.open(self.folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        except OSError:
            return None
        info = os.fstat(descriptor)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            os.close(descriptor)
            return None
        if info.st_mode & 0o077:
            os.fchmod(descriptor, 0o700)
        return descriptor

    @staticmethod
    def _read(descriptor: int, name: str, plan_id: str) -> StoredPlan | None:
        try:
            handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=descriptor)
            with os.fdopen(handle) as stream:
                return _valid(json.load(stream), plan_id)
        except (OSError, ValueError):
            return None

    def save(self, plan: StoredPlan) -> None:
        """Write a plan into place, never leaving half a file behind."""
        if not _PLAN_ID.match(plan.plan_id):
            raise ValueError("not a plan id")
        descriptor = self._open_folder(create=True)
        if descriptor is None:
            raise OSError("the plans folder is missing, is a link or is not ours: %s" % self.folder)
        temporary = ".tmp-" + secrets.token_hex(8)
        try:
            handle = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=descriptor)
            try:
                with os.fdopen(handle, "w") as stream:
                    json.dump(asdict(plan), stream)
                os.rename(temporary, plan.plan_id + ".json", src_dir_fd=descriptor, dst_dir_fd=descriptor)
            except BaseException:
                with suppress(OSError):
                    os.unlink(temporary, dir_fd=descriptor)
                raise
        finally:
            os.close(descriptor)

    def claim(self, plan_id: str) -> StoredPlan | None:
        """Rename the plan's file away; the one process whose rename works gets the plan."""
        if not _PLAN_ID.match(plan_id):
            return None
        descriptor = self._open_folder()
        if descriptor is None:
            return None
        claimed = ".claimed-" + secrets.token_hex(8)
        try:
            try:
                os.rename(plan_id + ".json", claimed, src_dir_fd=descriptor, dst_dir_fd=descriptor)
            except OSError:
                return None
            try:
                return self._read(descriptor, claimed, plan_id)
            finally:
                with suppress(OSError):
                    os.unlink(claimed, dir_fd=descriptor)
        finally:
            os.close(descriptor)

    def load(self, plan_id: str) -> StoredPlan | None:
        """Read a plan; an unknown id, a bad id, a link or a damaged file is simply not kept."""
        if not _PLAN_ID.match(plan_id):
            return None
        descriptor = self._open_folder()
        if descriptor is None:
            return None
        try:
            return self._read(descriptor, plan_id + ".json", plan_id)
        finally:
            os.close(descriptor)

    def delete(self, plan_id: str) -> None:
        """Remove a plan's file (or a link standing in its place)."""
        if not _PLAN_ID.match(plan_id):
            return
        descriptor = self._open_folder()
        if descriptor is None:
            return
        try:
            with suppress(OSError):
                os.unlink(plan_id + ".json", dir_fd=descriptor)
        finally:
            os.close(descriptor)

    def all(self) -> list[StoredPlan]:
        """Read every valid plan in the folder."""
        descriptor = self._open_folder()
        if descriptor is None:
            return []
        try:
            names = [match.group(1) for match in map(_PLAN_FILE.match, os.listdir(descriptor)) if match]
            found = (self._read(descriptor, name + ".json", name) for name in names)
            return [plan for plan in found if plan is not None]
        finally:
            os.close(descriptor)


def new_confirmation_id() -> str:
    """Return an unguessable, never repeated confirmation id."""
    return "p_" + secrets.token_hex(16)


class PlanBook:
    """Remember shown plans for ten minutes and check a confirmation against the chats."""
    def __init__(self, store: PlanStore, clock: Clock, lifetime: timedelta = PLAN_LIFETIME,
                 new_id: Callable[[], str] = new_confirmation_id):
        self.store, self.clock, self.lifetime, self.new_id = store, clock, lifetime, new_id

    def remember(self, fingerprint: str, command: str, arguments: Mapping[str, Any]) -> str:
        """Keep a plan about to be shown and return the confirmation id to show with it.

        `fingerprint` is the service's plan id. Every preview gets a new
        confirmation id, so one preview can never replace or revive another.
        """
        self.purge()
        plan = StoredPlan(self.new_id(), fingerprint, command, dict(arguments), self.clock.now())
        self.store.save(plan)
        return plan.plan_id

    def confirm(self, plan_id: str, command: str,
                plan_again: Callable[[Mapping[str, Any]], str]) -> StoredPlan:
        """Claim a plan and check it still describes the chats; ChatChanged otherwise.

        The plan is used up by the claim: whatever happens next, it can not be
        confirmed again, and a second process asking for it is refused. It is
        refused when unknown, shown by another command, ten minutes old (checked
        when claimed and again after planning) or when `plan_again(arguments)`,
        the stored request planned from the chats as they are now, does not give
        the stored fingerprint.
        """
        shown = self.store.load(plan_id)
        if shown is None:
            raise ChatChanged()
        if shown.command != command:
            raise WrongPlanAction()
        plan = self.store.claim(plan_id)
        if plan is None or plan.command != command or self._expired(plan):
            raise ChatChanged()
        if plan_again(plan.arguments) != plan.fingerprint or self._expired(plan):
            raise ChatChanged()
        return plan

    def purge(self) -> None:
        """Delete every plan older than ten minutes."""
        for plan in self.store.all():
            if self._expired(plan):
                self.store.delete(plan.plan_id)

    def _expired(self, plan: StoredPlan) -> bool:
        try:
            return _utc(self.clock.now()) - _utc(plan.stored_at) >= self.lifetime
        except ValueError:
            return True


def _utc(text: str) -> datetime:
    value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
