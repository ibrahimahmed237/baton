"""Private CLI storage and exclusion between commands sharing a ledger."""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import stat


def private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        if os.fstat(descriptor).st_uid != os.getuid():
            raise PermissionError("storage_owner")
        os.fchmod(descriptor, 0o700)
    finally:
        os.close(descriptor)


def private_file(directory: int, name: str) -> int:
    descriptor = os.open(name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=directory)
    try:
        info = os.fstat(descriptor)
        if info.st_uid != os.getuid() or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise PermissionError("storage_file")
        os.fchmod(descriptor, 0o600)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


@contextmanager
def command_lock(root: Path):
    """Hold across recovery, planning and writing; the OS releases it on exit/crash."""
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    descriptor = None
    try:
        if os.fstat(directory).st_uid != os.getuid():
            raise PermissionError("storage_owner")
        descriptor = private_file(directory, "command.lock")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield directory
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(directory)
