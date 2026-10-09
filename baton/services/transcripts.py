"""Immutable private history snapshots behind briefs."""
from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path
import stat
import tempfile
from typing import Protocol


class TranscriptStore(Protocol):
    def save(self, link_id: int, text: str) -> str:
        """Publish a content-addressed snapshot; never replace earlier content."""
        ...


    def verify(self, path: str, digest: str) -> None:
        """Refuse changed or outside transcript content before native creation."""
        ...


class FolderTranscripts:
    """Durably publish mode-0600 snapshots inside a private directory."""
    def __init__(self, folder: Path):
        self.folder = folder

    def save(self, link_id: int, text: str) -> str:
        """Publish one durable snapshot without overwriting earlier content."""
        data = text.encode('utf-8')
        digest = sha256(data).hexdigest()
        self.folder.mkdir(parents=True, mode=0o700, exist_ok=True)
        info = self.folder.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError('transcript_directory')
        os.chmod(self.folder, 0o700)
        path = self.folder / f'link-{int(link_id)}-{digest}.md'
        descriptor, temporary = tempfile.mkstemp(prefix='.brief-', dir=self.folder)
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
                with os.fdopen(descriptor, 'rb') as stream:
                    current = os.fstat(stream.fileno())
                    if (not stat.S_ISREG(current.st_mode) or current.st_uid != os.getuid()
                            or current.st_nlink != 1 or stat.S_IMODE(current.st_mode) != 0o600
                            or stream.read() != data):
                        raise ValueError('transcript_identity')
            directory = os.open(self.folder, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            os.unlink(temporary)
        return str(path)

    def verify(self, path: str, digest: str) -> None:
        """Verify the owned snapshot has the approved content and private mode."""
        target = Path(path)
        if target.parent != self.folder or target.name != Path(path).name:
            raise ValueError('transcript_scope')
        descriptor = os.open(target, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1
                    or sha256(stream.read()).hexdigest() != digest):
                raise ValueError('transcript_changed')
