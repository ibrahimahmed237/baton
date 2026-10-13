"""Ask Codex in the background: a separate, unsaved, read-only run of the CLI bundled in the ChatGPT app."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable

from ...domain.errors import NotAvailable
from ...ports.tool import SetupFinding

BUNDLED_CLI = "/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex"
_TIMEOUT_SECONDS = 120


class InertRunner:
    """The runner when no launcher is passed in: never available, never starts a process."""

    def available(self) -> SetupFinding:
        """Never available."""
        return SetupFinding("runner", False, "setup.runner", {"tool": "codex"})

    def ask(self, prompt: str, folder: str, read_only: bool = True) -> str:
        """Nothing can be asked."""
        raise NotAvailable()


class CodexRunner:
    """Build the command line and hand it to an injected launcher; never resumes a linked thread."""

    def __init__(self, command: Callable | None = None, binary: str = BUNDLED_CLI):
        self.command = command or subprocess.run
        self.binary = binary

    def _run(self, args: list[str], folder: str | None = None):
        return self.command(args, cwd=folder, capture_output=True, text=True, timeout=_TIMEOUT_SECONDS)

    def available(self) -> SetupFinding:
        """Whether the bundled CLI exists and is signed in with the app's login."""
        try:
            ok = Path(self.binary).is_file() and self._run([self.binary, "login", "status"]).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            ok = False
        return SetupFinding("runner", ok, "" if ok else "setup.runner", {"tool": "codex"})

    def ask(self, prompt: str, folder: str, read_only: bool = True) -> str:
        """Run one ephemeral read-only question; leaves no thread and no rollout behind."""
        if not read_only or not self.available().ok:
            raise NotAvailable()
        result = self._run([self.binary, "exec", "--ephemeral", "-s", "read-only", "--", prompt], folder)
        if result.returncode:
            raise NotAvailable()
        return result.stdout
