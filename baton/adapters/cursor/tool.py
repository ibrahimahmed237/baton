"""Compose the Cursor app adapter with explicit writes and inert defaults."""
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess

from .app import CursorApp, InertProcess, SystemProcess
from .facts import FACTS
from .hooks import CursorHooks
from .locator import CursorLocator, valid_id
from .reader import CursorReader
from .runner import CursorRunner, InertRunner
from .state import CursorState
from .writer import CursorWriter


class CursorAdapter:
    name = 'cursor'
    facts = FACTS

    def __init__(self, root, *, process=None, command=None, now=None,
                 allowed_chat_ids=(), hook_commands=None, hook_entrypoints_available=None,
                 rollback_root=None, project_root=None, baton_command="baton"):
        self.root = Path(root).resolve()
        self.process = process if process is not None else InertProcess()
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.original_chat_ids = frozenset(allowed_chat_ids)
        if any(not valid_id(i) for i in self.original_chat_ids):
            raise ValueError('chat_scope')
        self.allowed_chat_ids = set(self.original_chat_ids)
        self.locator = CursorLocator(self.root)
        self.rollback_locator = CursorLocator(rollback_root if rollback_root is not None
                                               else self.root / ".baton/rollback/cursor")
        self.hooks = CursorHooks(self, hook_commands, hook_entrypoints_available, project_root, baton_command)
        self.state = CursorState(self)
        self.reader = CursorReader(self)
        self.writer = CursorWriter(self)
        for path in self.writer.receipts.glob('*.json'):
            try:
                manifest = json.loads(self.rollback_locator.inside(path).read_text())
                if (manifest.get('tool') == 'cursor' and manifest.get('kind') == 'create' and
                        manifest['data'].get('scope') == sorted(self.original_chat_ids) and
                        valid_id(manifest.get('chat_id'))):
                    self.allowed_chat_ids.add(manifest['chat_id'])
            except (OSError, ValueError, KeyError, TypeError):
                continue
        self.runner = CursorRunner(command) if command is not None else InertRunner()
        self.app = CursorApp(self)

    @classmethod
    def on_this_machine(cls, root, **options):
        if options.get("rollback_root") is None:
            raise ValueError("rollback_root_required")
        return cls(root, **{'process': SystemProcess(), 'command': subprocess.run, **options})
