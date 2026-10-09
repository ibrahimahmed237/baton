"""Claude adapter wired exclusively through an explicit filesystem root."""
from pathlib import Path
from .facts import FACTS
from .locator import ClaudeLocator
from .reader import ClaudeReader
from .state import ClaudeState
from .writer import ClaudeWriter
from .hooks import ClaudeHooks
from .runner import ClaudeRunner
from .app import ClaudeApp, SystemProcess

class ClaudeAdapter:
    """Compose the native reader, writer, state and app ports."""
    name = "claude"
    facts = FACTS
    def __init__(self, root, *, process=None, command=None, account=None, context_sizes=None, hook_commands=None, hook_entrypoints_available=None):
        self.root = Path(root).resolve()
        self.account = account
        self.context_sizes = context_sizes or {}
        self.process = process if process is not None else SystemProcess()
        self.locator = ClaudeLocator(self.root)
        self.hooks = ClaudeHooks(self, hook_commands=hook_commands, entrypoints_available=hook_entrypoints_available)
        self.state = ClaudeState(self)
        self.reader = ClaudeReader(self)
        self.writer = ClaudeWriter(self)
        self.runner = ClaudeRunner(command)
        self.app = ClaudeApp(self)
