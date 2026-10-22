"""Preview and confirm only the entries owned by Baton, through injected ports."""
import hashlib
import json
from copy import copy
from ..domain.errors import NotAvailable
from ..ports.tool import SetupFinding
from ..ports.setup_install import CommandMissing, InstallRefused, InstallAppRunning, ProjectRequired, UnsafeProject
from .noteformat import NoteRef


class SetupInstall:
    def __init__(self, hooks, files, executable, project=None, app_running=None):
        self.hooks, self.files, self.executable = hooks, files, executable
        self.project = project
        self.app_running = app_running if app_running is not None else {
            tool: hooks.adapter.app.running for tool, hooks in hooks.items()}

    def check(self, tool):
        hooks = copy(self.hooks[tool])
        if not hasattr(hooks, 'install_entries'):
            return hooks.check()
        try:
            record = self.files.recorded(tool)
            if not record:
                return SetupFinding('hooks', False, 'setup.hooks', {'tool': tool})
            hooks.use_install_path(record['path'])
            hooks.use_installed_command(record['executable'])
            if not self.files.command_available(record['executable']):
                return SetupFinding('hooks', False, 'setup.command_missing', {'tool': tool})
            return hooks.check()
        except Exception:
            return SetupFinding('hooks', False, 'setup.install_refused', {'tool': tool})

    def running(self, tool):
        if not self.hooks[tool].install_requires_closed_app: return False
        try:
            return self.app_running[tool]() is not False
        except Exception:
            # Failed observations cannot establish a closed app.
            return True

    def require_closed(self, tool):
        if self.running(tool): raise InstallAppRunning()

    def preview(self, tool, removing=False, scope="project", project=None):
        if tool not in self.hooks: raise NotAvailable()
        hooks = copy(self.hooks[tool])
        if scope not in ("project", "global"): raise InstallRefused()
        if scope == "global" and not hooks.global_location_verified:
            from ..ports.setup_install import GlobalUnverified
            raise GlobalUnverified(tool)
        record = self.files.recorded(tool)
        record_source = self.files.record_source(tool)
        if record:
            recorded_project = hooks.install_project(record["path"])
            if project and self.files.project_path(project) != recorded_project: raise InstallRefused()
            project = recorded_project
        project = project or self.project
        if scope == 'project':
            if not project: raise ProjectRequired()
            project = self.files.project_path(project)
        executable = record['executable'] if record else self.executable
        expected_path = hooks.install_path(scope, project)
        if record and record['path'] != str(expected_path): raise InstallRefused()
        hooks.use_install_path(record['path'] if record else expected_path)
        if not removing and not self.files.command_available(executable): raise CommandMissing()
        change = self.files.prepare(hooks, executable, removing)
        if record and record['path'] != change.path: raise InstallRefused()
        fingerprint = hashlib.sha256(json.dumps([tool, removing, scope, project, executable, record, record_source,
            change.path, change.before, change.after], sort_keys=True).encode()).hexdigest()
        notes = [NoteRef('setup.uninstall_review' if removing else 'setup.install_review', {'tool': tool})]
        notes.append(NoteRef('setup.scope_' + scope, {'project': str(project)}))
        running = self.running(tool)
        notes.append(NoteRef('setup.preview_bookkeeping', {'path': str(self.files.root)}))
        if running: notes.append(NoteRef('setup.install_app_running', {}))
        if not removing:
            notes.append(NoteRef(hooks.install_next_note, {'tool': tool}))
        return {'plan_id': fingerprint, 'applied': False, 'tool': tool, 'scope': scope, 'project': str(project),
                'facts': {'global_location_verified': hooks.global_location_verified,
                          'requires_closed_app': hooks.install_requires_closed_app,
                          'app_running': running}, 'executable': executable,
                'files': [{'path': change.path, 'action': 'unchanged' if change.before == change.after else
                           'remove' if change.after is None else 'create' if change.before is None else 'change',
                           'entries': change.entries}, *self.files.details(tool, executable, change, removing)],
                'can_confirm': not running, 'notes': notes, '_change': change, '_record': record, '_record_source': record_source}

    def apply(self, tool, removing=False, preview=None, scope="project", project=None):
        result = preview if preview is not None else self.preview(tool, removing, scope, project)
        result['backups'] = self.files.apply(tool, result['executable'], result['_change'], removing, result['_record'], result['_record_source'],
                                             before_write=lambda: self.require_closed(tool))
        result['applied'] = True
        result['notes'].append(NoteRef('setup.uninstalled' if removing else 'setup.installed', {'tool': tool}))
        return result
