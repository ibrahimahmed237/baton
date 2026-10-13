"""Claude adapter wired exclusively through an explicit filesystem root."""
import subprocess
from pathlib import Path
from .facts import FACTS
from .locator import ClaudeLocator
from .reader import ClaudeReader
from .state import ClaudeState
from .writer import ClaudeWriter
from .hooks import ClaudeHooks
from .runner import ClaudeRunner, InertRunner
from .app import ClaudeApp, InertProcess, SystemProcess

class ClaudeAdapter:
    """Compose the native reader, writer, state and app ports.

    Without `process` and `command` the adapter is inert: it sees no app, starts no process
    and its runner is never available. Use `on_this_machine` for the real machine.
    """
    name = "claude"
    facts = FACTS
    def __init__(self, root, *, process=None, command=None, account=None, context_sizes=None, hook_commands=None, hook_entrypoints_available=None):
        self.root = Path(root).resolve()
        self.account = account
        self.context_sizes = context_sizes or {}
        self.process = process if process is not None else InertProcess()
        self.locator = ClaudeLocator(self.root)
        self.hooks = ClaudeHooks(self, hook_commands=hook_commands, entrypoints_available=hook_entrypoints_available)
        self.state = ClaudeState(self)
        self.reader = ClaudeReader(self)
        self.writer = ClaudeWriter(self)
        self.runner = ClaudeRunner(command) if command is not None else InertRunner()
        self.app = ClaudeApp(self)

    @classmethod
    def on_this_machine(cls, root, **options):
        """The adapter for the real machine: the one place that picks the real `ps`/`open`/`osascript` and CLI launcher."""
        return cls(root, **{"process": SystemProcess(), "command": subprocess.run, **options})
