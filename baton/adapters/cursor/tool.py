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
from ...domain.errors import NotAvailable
from ...ports.tool import FormatCheck
from .state import CursorState
from .writer import CursorWriter


class ScopedLocator(CursorLocator):
    """Keep sidebar metadata public while guarding native content."""

    def __init__(self, root, require_chat):
        super().__init__(root)
        self.require_chat = require_chat

    def data(self, ident):
        self.require_chat(ident)
        return super().data(ident)

    def bubbles(self, ident, data=None):
        self.require_chat(ident)
        return super().bubbles(ident, data)

    def transcript(self, ident):
        self.require_chat(ident)
        return super().transcript(ident)


class ScopedWriter(CursorWriter):
    def _check(self, chat_id=None):
        if chat_id is not None:
            self.adapter.require_chat(chat_id)
        return super()._check(chat_id)


class ScopedState(CursorState):
    def format_version(self, chat_id=None):
        if not self.adapter.command_scoped:
            return super().format_version(chat_id)
        if chat_id is not None:
            self.adapter.require_chat(chat_id)
            return super().format_version(chat_id)
        checks = [super(ScopedState, self).format_version(ident)
                  for ident in sorted(self.adapter.allowed_chat_ids)]
        return next((check for check in checks if not check.known),
                    checks[0] if checks else FormatCheck(True, '18'))


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
        # Direct fixture adapters retain their native observation behavior. Wiring
        # binds a command scope before any production content observation.
        self.command_scoped = False
        self.locator = ScopedLocator(self.root, self.require_content)
        self.rollback_locator = CursorLocator(rollback_root if rollback_root is not None
                                               else self.root / ".baton/rollback/cursor")
        self.hooks = CursorHooks(self, hook_commands, hook_entrypoints_available, project_root, baton_command)
        self.state = ScopedState(self)
        self.reader = CursorReader(self)
        self.writer = ScopedWriter(self)
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

    def require_chat(self, chat_id):
        if chat_id not in self.allowed_chat_ids:
            failure = NotAvailable()
            failure.values = {'tool': self.name, 'reason_note': 'scope.chats_only'}
            raise failure

    def require_content(self, chat_id):
        """Guard content once production wiring has bound a command scope."""
        if self.command_scoped:
            self.require_chat(chat_id)

    def scope_chats(self, chat_ids):
        """Bind command IDs without treating sidebar enumeration as permission."""
        ids = frozenset(chat_ids)
        if any(not valid_id(ident) for ident in ids):
            raise ValueError('chat_scope')
        self.command_scoped = True
        created = self.allowed_chat_ids - self.original_chat_ids
        self.original_chat_ids = ids
        self.allowed_chat_ids = set(ids | created)
        for path in self.writer.receipts.glob('*.json'):
            try:
                manifest = json.loads(self.rollback_locator.inside(path).read_text())
                if (manifest.get('tool') == self.name and manifest.get('kind') == 'create' and
                        manifest['data'].get('scope') == sorted(ids) and valid_id(manifest.get('chat_id'))):
                    self.allowed_chat_ids.add(manifest['chat_id'])
            except (OSError, ValueError, KeyError, TypeError):
                continue

    @classmethod
    def on_this_machine(cls, root, **options):
        if options.get("rollback_root") is None:
            raise ValueError("rollback_root_required")
        adapter = cls(root, **{'process': SystemProcess(), 'command': subprocess.run, **options})
        adapter.scope_chats(adapter.original_chat_ids)
        return adapter
