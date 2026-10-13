"""Production exclusion for Codex writes: the same thread-writer lock Codex itself takes.

Measured on the real machine (docs/plan/reports/CP2-live-step-A-2026-10-13.md): Codex Desktop
holds a BSD flock on `~/.codex/thread-writer-locks/<thread id>.lock` for every loaded thread,
the file is empty and exists only while the thread is loaded, and another process cannot take
even a shared non-blocking lock on it. A thread that is not loaded has no lock file.

So Baton takes the exclusive lock itself for the length of a write. Success proves no loaded
Codex thread holds the chat; it does not prove how Codex reacts to a lock it finds taken while
it loads the chat (that is still to be measured live). Removing a lock file we created is only safe if
Codex never opens the same path while we hold it; if it does, it may end up locking a deleted file (open question).
"""
from __future__ import annotations

import errno
import fcntl
import os
import re
import stat
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from ...domain.errors import ChatChanged, ChatHeld, NotAvailable

_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")
_DIRECTORY_MODE = 0o700
_FILE_MODE = 0o600
_ATTEMPTS = 3


class _Lease:
    """Proof that this process holds the thread's lock file, re-checkable at any moment."""

    def __init__(self, path: Path, descriptor: int, created: bool):
        self.path = path
        self.descriptor = descriptor
        self.created = created
        info = os.fstat(descriptor)
        self.file_id = (info.st_dev, info.st_ino)
        directory = path.parent.lstat()
        self.directory_id = (directory.st_dev, directory.st_ino)

    def check(self) -> None:
        """Raise ChatChanged unless the lock file and its folder are still the ones locked."""
        try:
            current = self.path.lstat()
            directory = self.path.parent.lstat()
        except OSError:
            raise ChatChanged() from None
        if (not stat.S_ISREG(current.st_mode) or (current.st_dev, current.st_ino) != self.file_id
                or current.st_nlink != 1 or current.st_uid != os.getuid()
                or (directory.st_dev, directory.st_ino) != self.directory_id
                or stat.S_ISLNK(directory.st_mode)):
            raise ChatChanged()

    def remove_if_ours(self) -> None:
        """Delete the lock file when this process made it and it is still the same file."""
        if not self.created:
            return
        try:
            current = self.path.lstat()
            directory = self.path.parent.lstat()
        except OSError:
            return
        if ((current.st_dev, current.st_ino) == self.file_id and stat.S_ISREG(current.st_mode)
                and (directory.st_dev, directory.st_ino) == self.directory_id):
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass


class NativeCoordination:
    """Exclusive per-thread exclusion through Codex's own lock files.

    Same protocol as the test fixture: `exclusive(locator, chat_id)` yields a lease with `check()`.
    """

    @contextmanager
    def global_idle(self, adapter) -> Iterator[None]:
        """Not available: closing the app automatically needs a measured whole-app exclusion."""
        raise NotAvailable()
        yield  # pragma: no cover

    def _open(self, path: Path) -> tuple[int, bool]:
        """Open the lock file without following a symlink; create it (0600) when it is missing."""
        for _ in range(_ATTEMPTS):
            try:
                descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, _FILE_MODE)
                return descriptor, True
            except FileExistsError:
                pass
            except OSError as error:
                if error.errno == errno.ELOOP:
                    raise NotAvailable() from None
                raise
            try:
                return os.open(path, os.O_RDWR | os.O_NOFOLLOW), False
            except FileNotFoundError:
                continue
            except OSError as error:
                if error.errno == errno.ELOOP:
                    raise NotAvailable() from None
                raise
        raise ChatChanged()

    @contextmanager
    def exclusive(self, locator, chat_id: str) -> Iterator[_Lease]:
        """Hold the thread's lock exclusively; ChatHeld when a loaded Codex thread (or anyone) holds it."""
        if not isinstance(chat_id, str) or not _SAFE_ID.fullmatch(chat_id):
            raise NotAvailable()
        locator.scope.require(chat_id)
        # Check every folder on the way first, so a symlinked ancestor is refused before anything is created.
        path = locator.scope.checked_path(locator.locks / (chat_id + ".lock"))
        path.parent.mkdir(parents=True, mode=_DIRECTORY_MODE, exist_ok=True)
        path = locator.scope.checked_path(path)
        descriptor, created = self._open(path)
        lease = None
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                if error.errno in (errno.EWOULDBLOCK, errno.EAGAIN, errno.EACCES):
                    # Never delete a file we could not lock: its holder may have made it just now.
                    created = False
                    raise ChatHeld() from None
                raise
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                created = False
                raise NotAvailable()
            if created:
                os.fchmod(descriptor, _FILE_MODE)
            lease = _Lease(path, descriptor, created)
            lease.check()
            yield lease
        finally:
            try:
                # Remove while the lock is still held, so nobody can lock a file we are deleting.
                if lease is not None:
                    lease.remove_if_ours()
            finally:
                os.close(descriptor)
