"""Baton's two entries in Codex's hooks.json, and what each prints.

Codex runs a hook only after the user has trusted it once (`/hooks`), per entry.
Baton reports whether that has happened and never records the trust itself.
"""
from __future__ import annotations

import importlib.util
import json
import os
import tempfile
from pathlib import Path
from typing import Callable

from ...domain.capabilities import HookNeed
from ...ports.tool import SetupFinding
from ..setup_files import checked

_EVENTS = ("UserPromptSubmit", "Stop")


class CodexHooks:
    """Install, remove and check Baton's hook entries; build what the hooks print."""
    global_location_verified = False
    install_requires_closed_app = True

    def install_project(self, path):
        from pathlib import Path
        return str(Path(path).parents[1])

    def install_path(self, scope, project):
        from pathlib import Path
        return Path(project) / '.codex/hooks.json' if scope == 'project' else self.adapter.root / '.codex/hooks.json'


    install_defaults = {}
    install_nested = True
    install_next_note = 'setup.trust_once'

    def install_entries(self, executable):
        import shlex
        commands = {'UserPromptSubmit': shlex.quote(executable) + ' catch-up --tool codex',
                    'Stop': shlex.quote(executable) + ' notify --tool codex'}
        return {event: {'hooks': [{'type': 'command', 'command': command}]} for event, command in commands.items()}

    def use_install_path(self, path):
        from pathlib import Path
        self._install_path = checked(path)

    def use_installed_command(self, executable):
        entries = self.install_entries(executable)
        self.commands = {event: entry['hooks'][0]['command'] for event, entry in entries.items()}

    def __init__(self, adapter, hook_commands: dict[str, str] | None = None,
                 entrypoints_available: Callable[[], bool] | None = None):
        self.adapter = adapter
        self.commands = hook_commands or {}
        if not hook_commands:
            self.use_installed_command(str(adapter.root / '.local/bin/baton'))
        self.entrypoints_available = entrypoints_available or self._available

    @staticmethod
    def _available() -> bool:
        try:
            return all(importlib.util.find_spec(name) is not None
                       for name in ("baton.hooks.prompt", "baton.hooks.turn_end"))
        except (ModuleNotFoundError, ValueError):
            return False

    @property
    def path(self) -> Path:
        """The user-level hooks file, confined to the adapter root."""
        if hasattr(self, '_install_path'): return self._install_path
        return self.adapter.locator.inside(self.adapter.locator.home / "hooks.json")

    def _read(self) -> dict:
        if not self.path.exists():
            return {}
        settings = json.loads(self.path.read_text())
        if not isinstance(settings, dict):
            raise ValueError("invalid hooks file")
        return settings

    def _write(self, settings: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".baton-", dir=self.path.parent)
        try:
            with os.fdopen(descriptor, "w") as fh:
                json.dump(settings, fh, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(temporary, self.path)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def _installed(self) -> bool:
        try:
            hooks = self._read().get("hooks", {})
            return all({'hooks': [{'type': 'command', 'command': command}]} in hooks.get(event, [])
                       for event, command in self.commands.items())
        except (OSError, ValueError, TypeError, AttributeError):
            return False

    def trusted(self) -> bool:
        """Read Codex's measured per-hook trust records without recreating its hash."""
        import tomllib
        try:
            config = self.adapter.locator.inside(self.adapter.locator.home / 'config.toml')
            with config.open('rb') as stream:
                state = tomllib.load(stream).get('hooks', {}).get('state', {})
            return all(isinstance(value := state.get(str(self.path) + ':' + event + ':0:0', {}).get('trusted_hash'), str)
                       and bool(value.strip()) for event in ('user_prompt_submit', 'stop'))
        except (OSError, ValueError, TypeError, AttributeError):
            return False

    def check(self) -> SetupFinding:
        """Whether the entries are installed and trusted. Never changes anything."""
        installed = self._installed() and self.entrypoints_available()
        trusted = installed and self.trusted()
        if not installed:
            note = "setup.hooks"
        elif not trusted:
            note = "setup.trust_once"
        else:
            note = ""
        values = {"need": HookNeed.TRUST_ONCE.value, "tool": "codex", "installed": installed, "trusted": trusted}
        return SetupFinding("hooks", installed and trusted, note, values)

    def install(self) -> SetupFinding:
        """Add Baton's entries without touching any other entry or setting."""
        if not self.entrypoints_available():
            return self.check()
        settings = self._read()
        hooks = settings.setdefault("hooks", {})
        for event, command in self.commands.items():
            entries = hooks.setdefault(event, [])
            if not any(h.get("command") == command for entry in entries for h in entry.get("hooks", [])):
                entries.append({"hooks": [{"type": "command", "command": command}]})
        self._write(settings)
        return self.check()

    def uninstall(self) -> None:
        """Remove only Baton's entries."""
        if not self.path.exists():
            return
        settings = self._read()
        hooks = settings.get("hooks", {})
        for event, command in self.commands.items():
            entries = hooks.get(event)
            if entries is None:
                continue
            for entry in entries:
                entry["hooks"] = [h for h in entry.get("hooks", []) if h.get("command") != command]
            hooks[event] = [entry for entry in entries if entry.get("hooks")]
            if not hooks[event]:
                del hooks[event]
        self._write(settings)

    def attach_reply(self, text: str, notice: str | None) -> str:
        """What the prompt hook prints: text for the agent, an optional notice, or `{}` when there is neither."""
        if not text and notice is None:
            return "{}"
        result: dict = {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": text}}
        if notice is not None:
            result["systemMessage"] = notice
        return json.dumps(result)

    def turn_end_reply(self) -> str:
        """Codex rejects anything but valid JSON from a Stop hook."""
        return "{}"
