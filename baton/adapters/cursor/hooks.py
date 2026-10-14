"""Cursor hooks.json entries and native beforeSubmitPrompt output."""
import shlex
from pathlib import Path
from .locator import CursorLocator
import json

from ...ports.tool import SetupFinding
from ...domain.errors import NotAvailable
from .writer import save_json


class CursorHooks:
    global_location_verified = False
    install_requires_closed_app = True

    def install_project(self, path):
        from pathlib import Path
        return str(Path(path).parents[1])

    def install_path(self, scope, project):
        from pathlib import Path
        return Path(project) / '.cursor/hooks.json' if scope == 'project' else self.adapter.root / '.cursor/hooks.json'

    install_defaults = {'version': 1, 'hooks': {}}
    install_nested = False
    install_next_note = 'setup.restart_hooks'

    def install_entries(self, executable):
        import shlex
        commands = {'beforeSubmitPrompt': shlex.quote(executable) + ' catch-up --tool cursor',
                    'stop': shlex.quote(executable) + ' notify --tool cursor'}
        return {event: {'command': command} for event, command in commands.items()}

    def use_install_path(self, path):
        path = Path(path)
        self._install_path = path
        if path.parts[-2:] != ('.cursor', 'hooks.json'):
            raise NotAvailable()
        self.project = CursorLocator(path.parents[1])

    def use_installed_command(self, executable):
        entries = self.install_entries(executable)
        self.commands = {event: entry['command'] for event, entry in entries.items()}

    def __init__(self, adapter, hook_commands=None, entrypoints_available=None,
                 project_root=None, baton_command='baton'):
        self.adapter = adapter
        command = shlex.quote(str(adapter.root / '.local/bin/baton') if baton_command == 'baton' else baton_command)
        self.commands = hook_commands or {
            'beforeSubmitPrompt': command + ' catch-up --tool cursor',
            'stop': command + ' notify --tool cursor'}
        self.entrypoints_available = entrypoints_available or (lambda: False)
        self.project = CursorLocator(project_root) if project_root is not None else None

    @property
    def path(self):
        if hasattr(self, '_install_path'): return self._install_path
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
