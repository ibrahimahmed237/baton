"""Independent per-tool setup checks through injected ports only."""
from dataclasses import asdict
from enum import Enum

from .noteformat import NoteRef


class SetupCheck:
    """Report independent setup findings for each injected tool."""
    def __init__(self, adapters, tools=None, *, installation_probe, hook_probe=None):
        """Use injected store, adapters and timing ports."""
        self.adapters = adapters
        self.tool_ids = tuple(adapters if tools is None else tools)
        self.installation_probe = installation_probe
        self.hook_probe = hook_probe

    def _finding(self, ident, ok, note, tool, values=None):
        return {'id': ident, 'ok': ok, 'note': NoteRef(note, {**(values or {}), 'tool': tool})}

    def _probe(self, tool, ident, call, failure_note):
        try:
            finding = call()
        except Exception:
            return self._finding(ident, False, failure_note, tool)
        return self._finding(finding.id, finding.ok, finding.note_id or
                             ('nothing_unusual' if finding.ok else failure_note), tool, finding.values)

    def complete(self, rows):
        """Complete an existing read projection with recorded hook observations."""
        for row in rows:
            tool = row['tool']
            if not row['installed']:
                row['ready'] = False
                if not any(f['id'] == 'installed' and not f['ok'] for f in row['findings']):
                    row['findings'].append(self._finding('installed', False, 'setup.not_installed', tool))
            if tool not in self.adapters: continue
            hooks = self._probe(tool, 'hooks', lambda: self.hook_probe(tool), 'setup.hooks')
            # Replace the hooks finding in place: the order of findings is part of the contract.
            if any(f['id'] == 'hooks' for f in row['findings']):
                row['findings'] = [hooks if f['id'] == 'hooks' else f for f in row['findings']]
            else:
                row['findings'] = row['findings'] + [hooks]
            row['ready'] = row['installed'] and hooks['ok'] and all(
                f['ok'] for f in row['findings'] if f['id'] == 'format')
            for mode in row['link_modes']:
                if mode['mode'] == 'attached_history':
                    mode['available'] = row['installed'] and hooks['ok']
                    mode['reason'] = None if mode['available'] else hooks['note'] if row['installed'] else NoteRef('setup.not_installed', {'tool': tool})
        return rows

    def check(self, tool):
        """Check one installed tool without hiding independent failures."""
        adapter = self.adapters.get(tool)
        installed = bool(self.installation_probe(tool))
        result = {'tool': tool, 'installed': installed, 'ready': False, 'background_ready': False,
                  'version': None, 'facts': {}, 'findings': [], 'link_modes': []}
        if not installed:
            result['findings'] = [self._finding('installed', False, 'setup.not_installed', tool)]
            return result
        if adapter is None:
            result['findings'] = [self._finding('adapter', False, 'setup.adapter_unavailable', tool)]
            return result
        result['facts'] = {k: v.value if isinstance(v, Enum) else list(v) if isinstance(v, tuple) else v
                           for k, v in asdict(adapter.facts).items()}
        try:
            check = adapter.state.format_version()
            result['version'] = check.version or None
            format_finding = self._finding('format', check.known,
                'format.new_version' if check.known and check.new_version else
                'nothing_unusual' if check.known else 'format.unknown_version', tool, {'version': check.version})
        except Exception:
            format_finding = self._finding('format', False, 'setup.format_unreadable', tool)
        hooks = self._probe(tool, 'hooks', (lambda: self.hook_probe(tool)) if self.hook_probe else adapter.hooks.check, 'setup.hooks')
        runner = self._probe(tool, 'runner', adapter.runner.available, 'setup.runner') if adapter.runner else (
            self._finding('runner', False, 'setup.runner', tool))
        result['findings'] = [self._finding('installed', True, 'nothing_unusual', tool), format_finding, hooks, runner]
        result['ready'] = format_finding['ok'] and hooks['ok']
        result['background_ready'] = runner['ok']
        result['link_modes'] = [
            {'mode': mode, 'available': available, 'label': self._finding(mode, True, 'mode.' + mode, tool)['note'],
             'reason': None if available else finding['note']}
            for mode, available, finding in (('full_copy', format_finding['ok'], format_finding),
                ('attached_history', hooks['ok'], hooks), ('brief', format_finding['ok'], format_finding))]
        return result

    def tools(self):
        """Return one setup card per requested tool."""
        return [self.check(tool) for tool in self.tool_ids]
