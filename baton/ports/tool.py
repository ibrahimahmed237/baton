"""Small interfaces implemented by a chat tool."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, Sequence, runtime_checkable

from ..domain.capabilities import Capabilities
from ..domain.conditions import SideCondition
from ..domain.model import Turn


@dataclass(frozen=True)
class ChatRef:
    """A chat's identity and location."""
    id: str
    name: str
    folder: str
    updated_at: str


@dataclass(frozen=True)
class Usage:
    """Context usage and the current limit."""
    tokens: int
    size: int | None
    limit_reached: bool
    limit_resets_at: str | None


@dataclass(frozen=True)
class FormatCheck:
    """Whether the observed format is supported."""
    known: bool
    version: str


@dataclass(frozen=True)
class WriteReceipt:
    """The information needed to undo one write."""
    tool: str
    chat_id: str
    kind: str
    data: dict[str, Any]


@dataclass(frozen=True)
class WriteResult:
    """A written chat, its turn ids and its undo receipt."""
    chat_id: str
    local_ids: tuple[str, ...]
    receipt: WriteReceipt


@dataclass(frozen=True)
class SetupFinding:
    """One setup check and the values for its note."""
    id: str
    ok: bool
    note_id: str
    values: dict[str, Any]


@runtime_checkable
class ChatLocator(Protocol):
    """ChatLocator interface for a chat tool."""
    def chats(self) -> list[ChatRef]: ...
    def resolve(self, chat_id: str) -> ChatRef: ...
    def name(self, chat_id: str) -> str: ...

@runtime_checkable
class ChatReader(Protocol):
    """ChatReader interface for a chat tool."""
    def read(self, chat_id: str) -> list[Turn]: ...
    def files_changed(self, turn: Turn) -> list[str]: ...
    def usage(self, chat_id: str) -> Usage: ...

@runtime_checkable
class ChatState(Protocol):
    """ChatState interface for a chat tool."""
    def condition(self, chat_id: str) -> SideCondition: ...
    def format_version(self) -> FormatCheck: ...

@runtime_checkable
class ChatWriter(Protocol):
    """ChatWriter interface for a chat tool."""
    def prepare(self, chat_id: str | None, kind: str) -> WriteReceipt: ...
    def create(self, turns: Sequence[Turn], name: str, folder: str) -> WriteResult: ...
    def add(self, chat_id: str, turns: Sequence[Turn]) -> WriteResult: ...
    def place(self, chat_id: str, turns: Sequence[Turn], before_local_id: str) -> WriteResult: ...
    def cut(self, chat_id: str, keep_through_local_id: str) -> WriteResult:
        """Keep through a turn; an empty identity keeps no turns."""
        ...
    def restore(self, receipt: WriteReceipt) -> WriteResult:
        """Restore an unchanged saved cut with a fresh reversible receipt."""
        ...
    def rename(self, chat_id: str, name: str) -> WriteResult: ...
    def take_back(self, receipt: WriteReceipt) -> None: ...

@runtime_checkable
class HookSupport(Protocol):
    """HookSupport interface for a chat tool."""
    def install(self) -> SetupFinding: ...
    def uninstall(self) -> None: ...
    def check(self) -> SetupFinding: ...
    def attach_reply(self, text: str, notice: str | None) -> str: ...
    def turn_end_reply(self) -> str: ...

@runtime_checkable
class BackgroundRunner(Protocol):
    """BackgroundRunner interface for a chat tool."""
    def available(self) -> SetupFinding: ...
    def ask(self, prompt: str, folder: str, read_only: bool = True) -> str: ...

@runtime_checkable
class AppControl(Protocol):
    """AppControl interface for a chat tool."""
    def running(self) -> bool: ...
    def close(self) -> None: ...
    def open(self, chat_id: str | None, folder: str | None) -> None: ...
    def release(self, chat_id: str) -> None: ...

@runtime_checkable
class ToolAdapter(Protocol):
    """ToolAdapter interface for a chat tool."""
    name: str
    facts: Capabilities
    locator: ChatLocator; reader: ChatReader; state: ChatState; writer: ChatWriter
    hooks: HookSupport; runner: BackgroundRunner | None; app: AppControl
