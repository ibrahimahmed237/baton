"""Merge owned hook entries without modifying unrelated project settings."""
import json
import importlib.util
from ...ports.tool import SetupFinding
from ..setup_files import checked

class ClaudeHooks:
    """Manage owned hook settings and native prompt-hook output."""
    global_location_verified = False
    install_requires_closed_app = True

    def install_project(self, path):
        from pathlib import Path
        return str(Path(path).parents[1])

    def install_path(self, scope, project):
        from pathlib import Path
        return Path(project) / '.claude/settings.local.json' if scope == 'project' else self.adapter.root / '.claude/settings.json'


    install_defaults = {}
    install_nested = True
    install_next_note = 'setup.no_hook_step'

    def install_entries(self, executable):
        import shlex
        commands = {'UserPromptSubmit': shlex.quote(executable) + ' catch-up --tool claude',
                    'Stop': shlex.quote(executable) + ' notify --tool claude'}
        return {event: {'hooks': [{'type': 'command', 'command': command}]} for event, command in commands.items()}

    def use_install_path(self, path):
        from pathlib import Path
        self._install_path = checked(path)

    def use_installed_command(self, executable):
        entries = self.install_entries(executable)
        self.commands = {event: entry['hooks'][0]['command'] for event, entry in entries.items()}

    def __init__(self, adapter, hook_commands=None, entrypoints_available=None):
        self.adapter = adapter
        self.commands = hook_commands or {}
        if not hook_commands:
            self.use_installed_command(str(adapter.root / '.local/bin/baton'))
        self.entrypoints_available = entrypoints_available or self._available
    @staticmethod
    def _available():
        try:
            return all(importlib.util.find_spec(name) is not None for name in
                ('baton.hooks.prompt', 'baton.hooks.turn_end'))
        except (ModuleNotFoundError, ValueError): return False
    @property
    def path(self):
        """Return the settings path confined to the adapter root."""
        if hasattr(self, '_install_path'): return self._install_path
        return self.adapter.locator.inside(checked(self.adapter.root / '.claude/settings.json'))
    def _read(self):
        if not self.path.exists(): return {}
        result = json.loads(self.path.read_text())
        if not isinstance(result, dict): raise ValueError('invalid settings')
        return result
    def check(self):
        """Report whether the owned hook entries and entry points are ready."""
        try:
            settings = self._read(); hooks = settings.get('hooks', {})
            ok = all({'hooks': [{'type': 'command', 'command': command}]} in hooks.get(event, [])
                     for event, command in self.commands.items())
        except (OSError, ValueError, TypeError, AttributeError): ok = False
        ok = ok and self.entrypoints_available()
        return SetupFinding('hooks', ok, '' if ok else 'setup.hooks', {'need': 'none', 'tool': 'claude'})
    def install(self):
        """Add owned hook entries without replacing unrelated settings."""
        if not self.entrypoints_available(): return self.check()
        settings = self._read(); hooks = settings.setdefault('hooks', {})
        for event, command in self.commands.items():
            entries = hooks.setdefault(event, [])
            if not any(any(h.get('command') == command for h in e.get('hooks', [])) for e in entries):
                entries.append({'hooks': [{'type': 'command', 'command': command}]})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(settings, indent=2))
        return self.check()
    def uninstall(self):
        """Remove only the hook entries owned by Baton."""
        settings = self._read()
        for event, command in self.commands.items():
            entries = settings.get('hooks', {}).get(event, [])
            for entry in entries:
                entry['hooks'] = [h for h in entry.get('hooks', []) if h.get('command') != command]
            if event in settings.get('hooks', {}): settings['hooks'][event] = [e for e in entries if e.get('hooks')]
        if self.path.exists(): self.path.write_text(json.dumps(settings, indent=2))
    def attach_reply(self, text, notice):
        """Encode native additional context and an optional notice."""
        result = {'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit', 'additionalContext': text}}
        if notice is not None: result['systemMessage'] = notice
        return json.dumps(result)
    def turn_end_reply(self):
        """Return the native empty turn-end hook response."""
        return ''
