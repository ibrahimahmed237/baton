"""Inspect setup through read-only ports; installation is an independent probe."""
from dataclasses import asdict
from enum import Enum
from .noteformat import NoteRef


class SetupRead:
    """Inspect installed tools and read-only setup ports independently."""
    def __init__(self, adapters, tools, installation_probe):
        self.adapters, self.tool_ids, self.installation_probe = adapters, tuple(tools), installation_probe

    def tools(self):
        """Return actual facts/findings; unavailable adapters provide no capabilities."""
        result = []
        for tool in self.tool_ids:
            installed = bool(self.installation_probe(tool))
            adapter = self.adapters.get(tool)
            if adapter is None:
                result.append({'tool': tool, 'installed': installed, 'ready': False, 'version': None,
                               'facts': {}, 'findings': [{'id': 'adapter', 'ok': False,
                                 'note': NoteRef('setup.adapter_unavailable', {'tool': tool})}], 'link_modes': []})
                continue
            check = adapter.state.format_version()
            hooks = adapter.hooks.check()
            runner = adapter.runner.available() if adapter.runner else None
            findings = [{'id': 'format', 'ok': check.known,
                         'note': NoteRef('nothing_unusual', {}) if check.known else
                         NoteRef('format.unknown_version', {'tool': tool, 'version': check.version})}]
            for finding in (hooks, runner):
                if finding:
                    findings.append({'id': finding.id, 'ok': finding.ok,
                        'note': NoteRef(finding.note_id or 'nothing_unusual', {**finding.values, 'tool': tool})})
            facts = {k: v.value if isinstance(v, Enum) else list(v) if isinstance(v, tuple) else v
                     for k, v in asdict(adapter.facts).items()}
            result.append({'tool': tool, 'installed': installed, 'ready': installed and check.known and hooks.ok,
                           'version': check.version or None, 'facts': facts, 'findings': findings,
                           'link_modes': [
                            {'mode': 'full_copy', 'available': installed and check.known, 'label': NoteRef('mode.full_copy', {}),
                             'reason': NoteRef('setup.not_installed', {'tool': tool}) if not installed else None if check.known else NoteRef('format.unknown_version', {'tool': tool, 'version': check.version})},
                            {'mode': 'attached_history', 'available': installed and hooks.ok,
                             'label': NoteRef('mode.attached_history', {}),
                             'reason': NoteRef('setup.not_installed', {'tool': tool}) if not installed else None if hooks.ok else NoteRef('setup.hooks', {'tool': tool})},
                            {'mode': 'brief', 'available': installed and check.known, 'label': NoteRef('mode.brief', {}),
                             'reason': NoteRef('setup.not_installed', {'tool': tool}) if not installed else None if check.known else NoteRef('format.unknown_version', {'tool': tool, 'version': check.version})}]})
        return result
