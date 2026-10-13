"""The Codex adapter, wired only through an explicit root and injected controls."""
from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .app import CodexApp, InertProcess, SystemProcess
from .coordination import NativeCoordination
from .facts import FACTS
from .hooks import CodexHooks
from .locator import CodexLocator
from .reader import CodexReader
from .runner import BUNDLED_CLI, CodexRunner, InertRunner
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
        """`root` stands for the home folder: every path the adapter touches is below it.

        Without `process` and `command` the adapter is inert: it sees no app, starts no process
        and its runner is never available. Use `on_this_machine` for the real machine.
        """
        self.root = Path(root).resolve()
        self.now = now or _utc_now
        self.process = process if process is not None else InertProcess()
        self.scope = ChatScope(self.root, allowed_chat_ids)
        self.coordination = coordination
        self.locator = CodexLocator(self.root, self.scope)
        self.hooks = CodexHooks(self, hook_commands=hook_commands, entrypoints_available=hook_entrypoints_available)
        self.state = CodexState(self)
        self.reader = CodexReader(self)
        self.writer = CodexWriter(self)
        self.runner = CodexRunner(command, binary) if command is not None else InertRunner()
        self.app = CodexApp(self)

    @classmethod
    def on_this_machine(cls, root, **options) -> "CodexAdapter":
        """The adapter for the real machine: the one place that picks the real process control, CLI launcher and thread lock.

        Writes still need the explicit chat scope (`allowed_chat_ids`); the lock only supplies exclusion.
        """
        return cls(root, **{"process": SystemProcess(), "command": subprocess.run,
                            "coordination": NativeCoordination(), **options})
