"""File-level hook installation boundaries, independent of any coding tool."""
from dataclasses import dataclass
from typing import Protocol
from ..domain.errors import BatonError


class InstallRefused(BatonError):
    note_id = 'setup.install_refused'


class ProjectRequired(BatonError):
    note_id = 'setup.project_required'


class UnsafeProject(BatonError):
    note_id = 'setup.unsafe_project'


class CommandMissing(BatonError):
    note_id = 'setup.command_missing'


@dataclass(frozen=True)
class HookChange:
    path: str
    before: str | None
    after: str | None
    entries: object


class InstallFiles(Protocol):
    @property
    def root(self): ...
    @property
    def coordination_verified(self) -> bool: ...
    def project_path(self, project: str) -> str: ...
    def command_available(self, executable: str) -> bool: ...
    def record_source(self, tool: str) -> str | None: ...
    def recorded(self, tool: str) -> dict | None: ...
    def prepare(self, hooks, executable: str, removing: bool) -> HookChange: ...
    def details(self, tool: str, executable: str, change: HookChange, removing: bool) -> list[dict]: ...
    def apply(self, tool: str, executable: str, change: HookChange, removing: bool, record_before: dict | None = None, record_source: str | None = None, before_write=None) -> list[str]: ...


class GlobalUnverified(BatonError):
    note_id = 'setup.global_unverified'


class WritersUnverified(BatonError):
    note_id = 'setup.writers_unverified'


class InstallAppRunning(BatonError):
    note_id = "setup.install_app_running"
