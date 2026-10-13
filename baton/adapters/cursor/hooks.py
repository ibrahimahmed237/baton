"""Cursor hooks.json entries and native beforeSubmitPrompt output."""
import shlex
from .locator import CursorLocator
import json

from ...ports.tool import SetupFinding
from ...domain.errors import NotAvailable
from .writer import save_json


class CursorHooks:
    def __init__(self, adapter, hook_commands=None, entrypoints_available=None,
                 project_root=None, baton_command='baton'):
        self.adapter = adapter
        command = shlex.quote(baton_command)
        self.commands = hook_commands or {
            'beforeSubmitPrompt': command + ' catch-up --tool cursor',
            'stop': command + ' notify --tool cursor'}
        self.entrypoints_available = entrypoints_available or (lambda: False)
        self.project = CursorLocator(project_root) if project_root is not None else None

    @property
    def path(self):
        if self.project is None:
            raise NotAvailable()
        return self.project.inside(self.project.root / '.cursor/hooks.json')

    def _read(self):
        return json.loads(self.path.read_text()) if self.path.exists() else {'version': 1, 'hooks': {}}

    def check(self):
        try:
            hooks = self._read().get('hooks', {})
            installed = all(any(entry.get('command') == command for entry in hooks.get(event, []))
                            for event, command in self.commands.items())
        except (OSError, ValueError, AttributeError, TypeError, NotAvailable):
            installed = False
        ready = installed and self.entrypoints_available()
        return SetupFinding('hooks', ready, '' if ready else 'setup.hooks',
                            {'tool': 'cursor', 'need': 'none', 'installed': installed})

    def install(self):
        if not self.entrypoints_available():
            return self.check()
        settings = self._read()
        hooks = settings.setdefault('hooks', {})
        for event, command in self.commands.items():
            entries = hooks.setdefault(event, [])
            if not any(e.get('command') == command for e in entries):
                entries.append({'command': command})
        save_json(self.path, settings)
        return self.check()

    def uninstall(self):
        if not self.path.exists():
            return
        settings = self._read()
        hooks = settings.get('hooks', {})
        for event, command in self.commands.items():
            if event in hooks:
                hooks[event] = [entry for entry in hooks[event] if entry.get('command') != command]
                if not hooks[event]:
                    del hooks[event]
        save_json(self.path, settings)

    def attach_reply(self, text, notice):
        context = '\n'.join(part for part in (notice, text) if part)
        output = {'continue': True}
        if context:
            output['additional_context'] = context
        return json.dumps(output)

    def turn_end_reply(self):
        return '{}'
