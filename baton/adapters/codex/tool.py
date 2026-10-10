"""The Codex adapter, wired only through an explicit root and injected controls."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .app import CodexApp, SystemProcess
from .facts import FACTS
from .hooks import CodexHooks
from .locator import CodexLocator
from .reader import CodexReader
from .runner import BUNDLED_CLI, CodexRunner
from .scope import ChatScope
from .state import CodexState
from .writer import CodexWriter


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class CodexAdapter:
    """Compose the locator, reader, state, writer, hooks, runner and app control for Codex."""

    name = "codex"
    facts = FACTS

    def __init__(self, root, *, process=None, command: Callable | None = None, binary: str = BUNDLED_CLI,
                 now: Callable[[], datetime] | None = None, hook_commands: dict[str, str] | None = None,
                 hook_entrypoints_available: Callable[[], bool] | None = None,
                 allowed_chat_ids=(), coordination=None):
        """`root` stands for the home folder: every path the adapter touches is below it."""
        self.root = Path(root).resolve()
        self.now = now or _utc_now
        self.process = process if process is not None else SystemProcess()
        self.scope = ChatScope(self.root, allowed_chat_ids)
        self.coordination = coordination
        self.locator = CodexLocator(self.root, self.scope)
        self.hooks = CodexHooks(self, hook_commands=hook_commands, entrypoints_available=hook_entrypoints_available)
        self.state = CodexState(self)
        self.reader = CodexReader(self)
        self.writer = CodexWriter(self)
        self.runner = CodexRunner(command, binary)
        self.app = CodexApp(self)
