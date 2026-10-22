"""Installation is confined to temporary homes and never controls a process."""
from contextlib import contextmanager, nullcontext
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import sqlite3

from baton.adapters.setup_files import SetupFiles
from baton.cli.main import main
from baton.cli.wiring import build
from baton.domain.errors import ChatChanged
from baton.ports.setup_install import InstallRefused, HookChange
from baton.services.setup_install import SetupInstall
from tests.fixtures.no_processes import no_processes

REPO = Path(__file__).resolve().parents[2]


@contextmanager
def temporary_home_guard(root):
    original = Path.open
    original_os_open = os.open
    original_connect = sqlite3.connect
    attempts = []
    descriptors = {}
    def confined(path, *args, **kwargs):
        resolved = path.absolute()
        if not resolved.is_relative_to(root) and not resolved.is_relative_to(REPO):
            attempts.append(str(resolved))
            raise AssertionError('outside temporary home: ' + str(resolved))
        return original(path, *args, **kwargs)
    def open_descriptor(path, *args, **kwargs):
        directory = kwargs.get('dir_fd')
        resolved = (descriptors[directory] / path) if directory is not None else Path(path).absolute()
        if not resolved.is_relative_to(root) and not (root.is_relative_to(resolved) and args and args[0] & os.O_DIRECTORY):
            attempts.append(str(resolved))
            raise AssertionError('descriptor outside temporary home: ' + str(resolved))
        descriptor = original_os_open(path, *args, **kwargs)
        descriptors[descriptor] = resolved
        return descriptor
    def connect(path, *args, **kwargs):
        if path != ':memory:' and not Path(path).absolute().is_relative_to(root):
            attempts.append(str(path))
            raise AssertionError('database outside temporary home')
        return original_connect(path, *args, **kwargs)
    with patch.object(Path, 'home', return_value=root), patch.object(Path, 'open', confined), \
         patch.object(os, 'open', open_descriptor), patch.object(sqlite3, 'connect', connect), \
         patch.dict(os.environ, {'HOME':str(root), 'BATON_TOOLS_HOME':str(root)}):
        yield
    if attempts: raise AssertionError(attempts)


class SetupInstallation(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='baton-setup-')
        self.addCleanup(self.temporary.cleanup)
        temporary_root = Path(self.temporary.name).resolve()
        self.home = temporary_root / 'project'
        self.home.mkdir()
        self.guard = temporary_home_guard(temporary_root)
        self.guard.__enter__(); self.addCleanup(self.guard.__exit__, None, None, None)
        self.process_guard = no_processes()
        self.process_guard.__enter__(); self.addCleanup(self.process_guard.__exit__, None, None, None)
        self.command = self.home / '.local/bin/baton'
        self.command.parent.mkdir(parents=True)
        self.command.write_text('#!/bin/sh\nexit 0\n'); self.command.chmod(0o755)
        self.engine = build(self.home / 'store', tools_home=self.home)
        self.service = SetupInstall({t: a.hooks for t, a in self.engine.adapters.items()},
                                    SetupFiles(self.engine.root, coordinate=lambda path: nullcontext()), str(self.command), project=str(self.home))
        for hooks in (a.hooks for a in self.engine.adapters.values()):
            hooks.use_install_path(hooks.install_path('project', self.home))
        self.engine.setup_install = self.service
        self.addCleanup(lambda: self.engine.close())

    def call(self, *words):
        out = io.StringIO()
        status = main(words, engine_factory=lambda: self.engine, stdout=out)
        # main closes its connection; reopen for subsequent independent calls.
        self.engine = build(self.home / 'store', tools_home=self.home)
        self.engine.setup_install = self.service
        self.assertEqual(status, 0, out.getvalue())
        return json.loads(out.getvalue())

    def test_L1_home_root_and_missing_project_are_refused_for_both_actions(self):
        self.service.project = None
        for action in ('install', 'uninstall'):
            result = self.call('setup', action, '--tool', 'claude')
            self.assertEqual(result['error']['note']['id'], 'setup.project_required')
            for project in (Path.home(), Path('/'), Path.home() / 'project/..'):
                # Test the service too: the CLI sandbox refuses / before dispatch.
                from baton.services.setup_install import UnsafeProject
                with self.assertRaises(UnsafeProject):
                    self.service.preview('claude', removing=action == 'uninstall', project=str(project))
        self.assertFalse(self.service.files.record_path('claude').exists())

    def test_L1_recorded_project_is_used_without_a_project_argument(self):
        self.service.apply('claude')
        self.service.project = None
        with patch.object(Path, 'cwd', return_value=Path.home()):
            preview = self.call('setup', 'uninstall', '--tool', 'claude')
        self.assertEqual(preview['project'], str(self.home))
        self.assertTrue(self.call('setup', 'uninstall', '--confirm', preview['plan_id'])['applied'])

    def test_L3_invalid_confirmation_notes_for_both_setup_actions(self):
        import base64
        import time
        for action in ('install', 'uninstall'):
            preview = self.call('setup', action, '--tool', 'claude')
            token = preview['plan_id'].removeprefix('p_si_')
            stored = json.loads(base64.urlsafe_b64decode(token + '=' * (-len(token) % 4)))
            expired = {**stored, 'at': time.time() - 601}
            malformed = {**stored, 'request': []}
            ids = ['p_missing', 'p_si_!!!', 'p_si_W10']
            ids += ['p_si_' + base64.urlsafe_b64encode(json.dumps(v).encode()).decode() for v in (expired, malformed)]
            for ident in ids:
                result = self.call('setup', action, '--confirm', ident)
                self.assertEqual(result['error']['note']['id'], 'plan.invalid', result)

    def test_L2_restore_exact_bytes_and_remove_created_hooks_key(self):
        for tool in ('claude', 'codex', 'cursor'):
            hooks = self.engine.adapters[tool].hooks
            path = hooks.path
            path.parent.mkdir(parents=True, exist_ok=True)
            original = '{\r\n  "other" : [1.00, "\\u0061"]\r\n}\r\n'
            path.write_bytes(original.encode())
            self.service.apply(tool)
            self.service.apply(tool)  # Reinstall must retain the original backup.
            self.service.apply(tool, True)
            self.assertEqual(path.read_bytes(), original.encode())
            self.assertNotIn('hooks', json.loads(path.read_bytes()))

    def test_L2_later_edits_and_their_whitespace_survive_uninstall(self):
        for tool in ('claude', 'codex', 'cursor'):
            hooks = self.engine.adapters[tool].hooks
            path = hooks.path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('{\n  "other" : 1.00\n}\n')
            self.service.apply(tool)
            source = path.read_text().replace('1.00', '[ 2.00, "\\u0062" ]')
            path.write_text(source)
            self.service.apply(tool, True)
            self.assertEqual(path.read_text(), '{\n  "other" : [ 2.00, "\\u0062" ]\n}\n')

    def test_L2_adopting_existing_entries_still_saves_a_real_backup(self):
        hooks = self.engine.adapters['claude'].hooks
        path = hooks.path
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'hooks': {event: [entry] for event, entry in hooks.install_entries(str(self.command)).items()}}))
        original = path.read_bytes()
        result = self.service.apply('claude')
        record = self.service.files.recorded('claude')
        self.assertEqual(Path(record['backup']).read_bytes(), original)
        self.assertIn(record['backup'], result['backups'])
        self.service.apply('claude', True)
        self.assertEqual(json.loads(path.read_text()), {'hooks': {}})

    def test_L2_legacy_record_recovers_original_backup_bytes(self):
        path = self.engine.adapters['claude'].hooks.path
        path.parent.mkdir(parents=True)
        original = '{\n "untouched" : 1.00\n}\n'
        path.write_text(original)
        self.service.apply('claude')
        record_path = self.service.files.record_path('claude')
        record = json.loads(record_path.read_text())
        record.pop('backup')
        record_path.write_text(json.dumps(record))
        self.service.apply('claude', True)
        self.assertEqual(path.read_text(), original)

    def test_L5_setup_uses_recorded_project_and_executable_with_explanations(self):
        from baton.ports.tool import FormatCheck
        alternate = self.home / 'bin/baton-custom'
        alternate.parent.mkdir()
        alternate.write_text('fixture'); alternate.chmod(0o755)
        self.service.executable = str(alternate)
        for tool in self.engine.adapters:
            self.service.apply(tool)
        engine = build(self.home / 'store', tools_home=self.home, installation_probe=lambda _: True)
        try:
            for adapter in engine.adapters.values():
                adapter.state.format_version = lambda: FormatCheck(True, 'fixture')
            out = io.StringIO()
            with patch.object(engine, 'close'):
                self.assertEqual(main(['setup', '--json'], engine_factory=lambda: engine, stdout=out), 0)
            rows = {r['tool']: r for r in json.loads(out.getvalue())['tools']}
            for tool, row in rows.items():
                hooks = next(f for f in row['findings'] if f['id'] == 'hooks')
                if tool == 'codex':
                    self.assertFalse(row['ready'])
                    self.assertEqual(hooks['note']['id'], 'setup.trust_once')
                else: self.assertTrue(row['ready'], row)
            self.assertFalse(self.service.check('codex').ok)
            trust_before = (self.home / '.codex/hooks.json').read_bytes()
            with patch.object(self.engine.adapters['codex'].hooks, 'trusted', return_value=True):
                self.assertTrue(self.service.check('codex').ok)
            self.assertEqual((self.home / '.codex/hooks.json').read_bytes(), trust_before)
            alternate.unlink()
            for tool in rows:
                self.assertEqual(self.service.check(tool).note_id, 'setup.command_missing')
        finally: engine.close()

    def test_L5_unrecorded_global_entries_do_not_establish_readiness(self):
        hooks = self.engine.adapters['claude'].hooks
        path = hooks.path
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'hooks': {event: [entry] for event, entry in hooks.install_entries(str(self.command)).items()}}))
        self.assertTrue(hooks.check().ok)
        finding = self.service.check('claude')
        self.assertFalse(finding.ok)
        self.assertEqual(finding.note_id, 'setup.hooks')

    def test_L5_exact_entries_missing_file_and_entrypoints_are_checked(self):
        for tool in self.engine.adapters:
            self.service.apply(tool)
            hooks = self.engine.adapters[tool].hooks
            path = Path(self.service.files.recorded(tool)['path'])
            original = path.read_text()
            if tool != 'opencode':
                settings = json.loads(original)
                event = next(iter(hooks.install_entries(str(self.command))))
                settings['hooks'][event][0]['matcher'] = 'never'
                path.write_text(json.dumps(settings))
            else: path.write_text(original + '// changed')
            finding = self.service.check(tool)
            self.assertFalse(finding.ok)
            self.assertEqual(finding.note_id, 'setup.hooks')
            path.write_text(original)
            with patch.object(hooks, 'entrypoints_available', return_value=False):
                self.assertEqual(self.service.check(tool).note_id, 'setup.hooks')
            path.unlink()
            self.assertEqual(self.service.check(tool).note_id, 'setup.hooks')

    def test_all_preview_paths_entries_and_first_steps_without_writes(self):
        expected = {'claude': '.claude/settings.local.json', 'codex': '.codex/hooks.json',
                    'cursor': '.cursor/hooks.json', 'opencode': '.opencode/plugins/baton.js'}
        steps = {'claude': 'setup.no_hook_step', 'codex': 'setup.trust_once',
                 'cursor': 'setup.restart_hooks', 'opencode': 'setup.restart_once'}
        for tool, relative in expected.items():
            with self.subTest(tool=tool):
                result = self.call('setup', 'install', '--tool', tool, '--json')
                self.assertFalse(result['applied'])
                self.assertEqual(result['files'][0]['path'], str(self.home / relative))
                self.assertFalse((self.home / relative).exists())
                self.assertIn(str(self.command), json.dumps(result['files'][0]['entries']))
                self.assertNotIn('python3 -m', json.dumps(result['files'][0]['entries']))
                self.assertIn(steps[tool], [n['id'] for n in result['notes']])
        self.assertFalse((self.engine.root / 'hook-backups').exists())
        self.assertFalse((self.engine.root / 'hook-installs').exists())

    def test_merge_backup_idempotence_uninstall_each_tool(self):
        for tool in ('claude', 'codex', 'cursor', 'opencode'):
            with self.subTest(tool=tool):
                hooks = self.engine.adapter(tool).hooks
                path = hooks.path
                if tool != 'opencode':
                    path.parent.mkdir(parents=True, exist_ok=True)
                    before = '{\n "untouched" : { "number":1.00, "s":"\\u0061" }, "hooks": {}\n}\n'
                    path.write_text(before)
                else: before = None
                preview = self.call('setup', 'install', '--tool', tool)
                result = self.call('setup', 'install', '--confirm', preview['plan_id'])
                self.assertTrue(result['applied'])
                installed = path.read_bytes()
                if before:
                    self.assertIn('"untouched" : { "number":1.00, "s":"\\u0061" }', installed.decode())
                    self.assertEqual(Path(result['backups'][0]).read_text(), before)
                    self.assertTrue(Path(result['backups'][0]).is_relative_to(self.engine.root))
                else: self.assertEqual(result['backups'], [])
                preview = self.call('setup', 'install', '--tool', tool)
                again = self.call('setup', 'install', '--confirm', preview['plan_id'])
                self.assertEqual(path.read_bytes(), installed)
                self.assertEqual(again['backups'], [])
                preview = self.call('setup', 'uninstall', '--tool', tool)
                self.assertEqual(path.read_bytes(), installed)
                result = self.call('setup', 'uninstall', '--confirm', preview['plan_id'])
                self.assertTrue(result['applied'])
                if before: self.assertEqual(path.read_text(), before)
                else: self.assertFalse(path.exists())

    def test_existing_other_hooks_survive_and_only_own_entries_removed(self):
        for tool in ('claude', 'codex', 'cursor'):
            hooks = self.engine.adapter(tool).hooks
            entries = hooks.install_entries(str(self.command))
            event = next(iter(entries))
            other = {'hooks': [{'type':'command', 'command':'other --keep'}], 'matcher':'*'} if hooks.install_nested else {'command':'other --keep'}
            path = hooks.path; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({'approval': {'trusted': ['other']}, 'hooks': {event: [other]}}))
            self.service.apply(tool)
            self.service.apply(tool, True)
            result = json.loads(path.read_text())
            self.assertEqual(result['approval'], {'trusted': ['other']})
            self.assertEqual(result['hooks'][event], [other])

    def test_uninstall_without_owned_entries_changes_nothing(self):
        path = self.engine.adapter('claude').hooks.path
        path.parent.mkdir(parents=True)
        for source in ('{"other":1}', '{"hooks":{"Stop":[],"UserPromptSubmit":[]}}'):
            path.write_text(source)
            result = self.service.apply('claude', True)
            self.assertEqual(result['backups'], [])
            self.assertEqual(path.read_text(), source)
        path.unlink()
        self.service.apply('claude', True)
        self.assertFalse(path.exists())

    def test_bad_json_duplicate_keys_and_bad_hook_shape_refused_unchanged(self):
        path = self.engine.adapter('codex').hooks.path
        path.parent.mkdir(parents=True, exist_ok=True)
        for source in ('{oops', '{"hooks":{},"hooks":{}}', '{"hooks":[]}', '{"hooks":{"Stop":[{"hooks":3}]}}'):
            path.write_text(source)
            with self.assertRaises(InstallRefused): self.service.preview('codex')
            self.assertEqual(path.read_text(), source)
        self.assertFalse((self.engine.root / 'hook-backups').exists())

    def test_changed_preview_and_wrong_action_refused(self):
        preview = self.call('setup', 'install', '--tool', 'claude')
        wrong = self.call('setup', 'uninstall', '--confirm', preview['plan_id'])
        self.assertEqual(wrong['error']['kind'], 'wrong_plan_action')
        path = self.home / '.claude/settings.local.json'
        path.parent.mkdir(parents=True); path.write_text('{"other": 7}')
        result = self.call('setup', 'install', '--confirm', preview['plan_id'])
        self.assertEqual(result['error']['note']['id'], 'plan.invalid')
        self.assertEqual(path.read_text(), '{"other": 7}')

    def test_project_hook_paths_are_recorded_and_restored(self):
        project = self.home / 'project'
        expected = {'cursor': project / '.cursor/hooks.json',
                    'opencode': project / '.opencode/plugins/baton.js'}
        for tool, path in expected.items():
            self.engine.adapter(tool).hooks.use_install_path(str(path))
            preview = self.service.preview(tool, project=str(project))
            self.assertEqual(preview['files'][0]['path'], str(path))
            self.service.apply(tool, preview=preview)
        with patch.object(Path, 'cwd', return_value=self.home / 'other-project'):
            engine = build(self.home / 'store', tools_home=self.home)
        try:
            for tool, path in expected.items():
                self.assertEqual(engine.adapter(tool).hooks.path, path)
                finding = engine.adapter(tool).hooks.check()
                self.assertTrue(finding.ok if tool == 'cursor' else finding.values['installed'])
        finally: engine.close()

    def test_every_changed_storage_path_is_disclosed_and_private(self):
        path = self.engine.adapter('claude').hooks.path
        path.parent.mkdir(parents=True); path.write_text('{"other":true}')
        preview = self.service.preview('claude')
        disclosed = {f['path'] for f in preview['files'][1:]}
        result = self.service.apply('claude', preview=preview)
        self.assertTrue(set(result['backups']) <= disclosed)
        self.assertIn(str(self.service.files.record_path('claude')), disclosed)
        for backup in result['backups']:
            self.assertEqual(Path(backup).stat().st_mode & 0o777, 0o600)

    def test_change_after_confirmation_replay_cannot_be_silently_replanned(self):
        reviewed = self.service.preview('claude')
        path = Path(reviewed['_change'].path)
        path.parent.mkdir(parents=True); path.write_text('{"new": 9}')
        with self.assertRaises(ChatChanged): self.service.apply('claude', preview=reviewed)
        self.assertEqual(path.read_text(), '{"new": 9}')
        reviewed = self.service.preview('claude')
        self.service.files.record_path('claude').parent.mkdir(parents=True, exist_ok=True)
        self.service.files.record_path('claude').write_text(json.dumps({'executable':str(self.command), 'path':str(path)}))
        with self.assertRaises(ChatChanged): self.service.apply('claude', preview=reviewed)

    def test_uninstall_mixed_entry_preserves_other_hook_bytes(self):
        hooks = self.engine.adapter('claude').hooks
        own = hooks.install_entries(str(self.command))['Stop']['hooks'][0]
        path = hooks.path; path.parent.mkdir(parents=True)
        foreign = '{ "command" : "other", "timeout": 1.00 }'
        path.write_text('{"hooks":{"Stop":[{"matcher":"*","hooks":[' + json.dumps(own) + ',' + foreign + ']}]}}')
        self.service.apply('claude', True)
        self.assertIn(foreign, path.read_text())
        self.assertEqual(json.loads(path.read_text())['hooks']['Stop'][0]['matcher'], '*')

    def test_plugin_conflict_symlink_missing_command_refused(self):
        path = self.engine.adapter('opencode').hooks.path
        path.parent.mkdir(parents=True); path.write_text('other plugin')
        with self.assertRaises(InstallRefused): self.service.preview('opencode')
        path.unlink(); path.symlink_to(self.command)
        with self.assertRaises(InstallRefused): self.service.preview('opencode')
        configuration = self.home / '.claude/settings.local.json'
        configuration.parent.mkdir(parents=True); configuration.write_text('{}')
        with patch('baton.adapters.setup_files.snapshot', return_value=(None, None)):
            with self.assertRaises(InstallRefused): self.service.preview('claude')
        record = self.service.files.record_path('claude')
        record.parent.mkdir(parents=True); record.write_text('{}')
        with patch('baton.adapters.setup_files.snapshot', return_value=(None, None)):
            with self.assertRaises(InstallRefused): self.service.files.record_source('claude')
        record.unlink()
        self.command.unlink()
        result = self.call('setup', 'install', '--tool', 'claude')
        self.assertEqual(result['error']['note']['id'], 'setup.command_missing')

    def test_apply_rechecks_file_and_installed_commands_survive_new_engine(self):
        self.service.apply('claude')
        engine = build(self.home / 'store', tools_home=self.home)
        try:
            self.assertTrue(engine.adapter('claude').hooks.check().ok)
            self.assertTrue(all(str(self.command) in c for c in engine.adapter('claude').hooks.commands.values()))
        finally: engine.close()
        change = self.service.preview('claude')['_change']
        Path(change.path).write_text('{}')
        with self.assertRaises(ChatChanged): self.service.files.apply('claude', str(self.command), change, False, self.service.files.recorded('claude'))

    def test_review_preview_has_no_persisted_plan(self):
        before = {str(p.relative_to(self.engine.root)) for p in self.engine.root.rglob('*') if p.is_file()}
        preview = self.call('setup', 'install', '--tool', 'claude')
        after = {str(p.relative_to(self.engine.root)) for p in self.engine.root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)
        self.assertTrue(preview['plan_id'].startswith('p_si_'))
        self.assertFalse((self.engine.root / 'plans').exists())

    def test_review_backup_time_edit_is_not_overwritten(self):
        from baton.adapters import setup_files
        path = self.home / '.claude/settings.local.json'
        path.parent.mkdir(parents=True); path.write_text('{"before":1}')
        preview = self.service.preview('claude')
        original = setup_files.atomic
        def backup_then_edit(*args, **kwargs):
            original(*args, **kwargs)
            path.write_text('{"outside":2}')
        with patch.object(setup_files, 'atomic', backup_then_edit):
            with self.assertRaises(ChatChanged): self.service.apply('claude', preview=preview)
        self.assertEqual(path.read_text(), '{"outside":2}')
        self.assertFalse(self.service.files.record_path('claude').exists())

    def test_review_backup_time_directory_swap_cannot_redirect_publication(self):
        from baton.adapters import setup_files
        path = self.home / '.claude/settings.local.json'
        path.parent.mkdir(parents=True); path.write_text('{"before":1}')
        foreign = self.home / 'foreign'; foreign.mkdir()
        (foreign / path.name).write_text('{"foreign":2}')
        preview = self.service.preview('claude')
        original = setup_files.atomic
        moved = self.home / 'moved'
        def backup_then_swap(*args, **kwargs):
            original(*args, **kwargs)
            path.parent.rename(moved); path.parent.symlink_to(foreign, target_is_directory=True)
        with patch.object(setup_files, 'atomic', backup_then_swap):
            with self.assertRaises(InstallRefused): self.service.apply('claude', preview=preview)
        self.assertEqual((foreign / path.name).read_text(), '{"foreign":2}')
        self.assertEqual((moved / path.name).read_text(), '{"before":1}')

    def test_review_ownership_publish_failure_leaves_configuration_exact(self):
        path = self.home / '.claude/settings.local.json'
        path.parent.mkdir(parents=True); path.write_text('{"before":1}')
        preview = self.service.preview('claude')
        record = self.service.files.record_path('claude')
        original = os.replace
        def refuse_record(source, destination, **kwargs):
            if destination == record.name: raise OSError('record publication failed')
            return original(source, destination, **kwargs)
        with patch.object(os, 'replace', refuse_record):
            with self.assertRaises((OSError, InstallRefused)): self.service.apply('claude', preview=preview)
        self.assertEqual(path.read_text(), '{"before":1}')
        self.assertFalse(record.exists())

    def test_review_edit_during_ownership_publication_is_not_overwritten(self):
        path = self.home / '.claude/settings.local.json'
        path.parent.mkdir(parents=True); path.write_text('{"before":1}')
        preview = self.service.preview('claude')
        record = self.service.files.record_path('claude')
        original = os.replace
        def publish_record_then_edit(source, destination, **kwargs):
            result = original(source, destination, **kwargs)
            if destination == record.name: path.write_text('{"outside":2}')
            return result
        with patch.object(os, 'replace', publish_record_then_edit):
            with self.assertRaises(ChatChanged): self.service.apply('claude', preview=preview)
        self.assertEqual(path.read_text(), '{"outside":2}')
        self.assertFalse(record.exists())

    def test_review_record_preparation_failure_publishes_nothing(self):
        from baton.adapters import setup_files
        path = self.home / '.claude/settings.local.json'
        path.parent.mkdir(parents=True); path.write_text('{"before":1}')
        preview = self.service.preview('claude')
        original = setup_files.stage
        def refuse_record_stage(descriptor, text, *args, **kwargs):
            if text and '"executable"' in text: raise OSError('record staging failed')
            return original(descriptor, text, *args, **kwargs)
        with patch.object(setup_files, 'stage', refuse_record_stage):
            with self.assertRaises(InstallRefused): self.service.apply('claude', preview=preview)
        self.assertEqual(path.read_text(), '{"before":1}')
        self.assertFalse(self.service.files.record_path('claude').exists())
        self.assertEqual(list(self.home.rglob('.baton-*')), [])

    def test_review_configuration_publish_failure_restores_ownership(self):
        path = self.home / '.claude/settings.local.json'
        path.parent.mkdir(parents=True); path.write_text('{"before":1}')
        preview = self.service.preview('claude')
        original = os.replace
        def refuse_configuration(source, destination, **kwargs):
            if destination == path.name: raise OSError('configuration publication failed')
            return original(source, destination, **kwargs)
        with patch.object(os, 'replace', refuse_configuration):
            with self.assertRaises((OSError, InstallRefused)): self.service.apply('claude', preview=preview)
        self.assertEqual(path.read_text(), '{"before":1}')
        self.assertFalse(self.service.files.record_path('claude').exists())

    def test_review_removed_entry_before_mixed_entry_preserves_source_spelling(self):
        hooks = self.engine.adapter('claude').hooks
        own = hooks.install_entries(str(self.command))['Stop']['hooks'][0]
        path = self.home / '.claude/settings.local.json'; path.parent.mkdir(parents=True)
        foreign = '{ "timeout" : 1.00, "command": "other" }'
        path.write_text('{"hooks":{"Stop":[' + json.dumps({'hooks':[own]}) +
                        ',{"matcher":"*","hooks":[' + json.dumps(own) + ',' + foreign + ']}]}}')
        self.service.apply('claude', True)
        self.assertIn(foreign, path.read_text())
        self.assertLess(path.read_text().index('matcher'), path.read_text().index('hooks', path.read_text().index('matcher')))

    def test_review_ownership_remove_has_exact_disclosed_backup(self):
        self.service.apply('claude')
        record = self.service.files.record_path('claude')
        before = record.read_bytes()
        preview = self.service.preview('claude', True)
        expected = self.service.files.backup_path('claude', HookChange(str(record), before.decode(), None, []))
        self.assertIn(str(expected), [f['path'] for f in preview['files']])
        result = self.service.apply('claude', True, preview=preview)
        self.assertIn(str(expected), result['backups'])
        self.assertEqual(expected.read_bytes(), before)
        self.assertFalse(record.exists())

    def test_review_record_formatting_is_fingerprinted_backed_up_and_disclosed(self):
        self.service.apply('claude')
        record = self.service.files.record_path('claude')
        source = json.dumps(json.loads(record.read_text()), indent=4) + '\n'
        record.write_text(source)
        preview = self.service.preview('claude')
        self.assertEqual(next(f['action'] for f in preview['files'] if f['path'] == str(record)), 'change')
        result = self.service.apply('claude', preview=preview)
        backup = self.service.files.backup_path('claude', HookChange(str(record), source, None, []))
        self.assertIn(str(backup), result['backups'])
        self.assertEqual(backup.read_text(), source)
        reviewed = self.service.preview('claude')
        record.write_text(source)
        with self.assertRaises(ChatChanged): self.service.apply('claude', preview=reviewed)
        self.assertEqual(record.read_text(), source)

    def test_review_dropped_special_permissions_refused(self):
        from baton.adapters import setup_files
        path = self.home / '.claude/settings.local.json'; path.parent.mkdir(parents=True)
        path.write_text('{}'); path.chmod(0o750)
        original = setup_files.snapshot
        def special_metadata(descriptor, name):
            data, info = original(descriptor, name)
            if info is not None and name == path.name:
                fields = list(info); fields[0] |= 0o6000
                info = os.stat_result(fields)
            return data, info
        before = path.stat()
        # Model a filesystem dropping requested set-id bits after fchmod.
        actual_chmod = os.fchmod
        def dropping(handle, mode): actual_chmod(handle, mode & ~0o6000)
        with patch.object(setup_files, 'snapshot', special_metadata), patch.object(os, 'fchmod', side_effect=dropping):
            with self.assertRaises(InstallRefused): self.service.apply('claude')
        self.assertEqual(path.read_text(), '{}')
        after = path.stat()
        self.assertEqual(after.st_mode & 0o777, before.st_mode & 0o777)
        self.assertEqual((after.st_uid, after.st_gid), (before.st_uid, before.st_gid))

    def test_review_staged_attribute_loss_refused(self):
        import ctypes
        import sys
        path = self.home / '.claude/settings.local.json'; path.parent.mkdir(parents=True)
        path.write_text('{}')
        name = b'user.baton-test' if sys.platform != 'darwin' else b'com.baton.test'
        if sys.platform == 'darwin':
            libc = ctypes.CDLL(None, use_errno=True)
            handle = os.open(path, os.O_RDONLY)
            try: self.assertEqual(libc.fsetxattr(handle, name, b'exact value', 11, 0, 0), 0)
            finally: os.close(handle)
        else: os.setxattr(path, name, b'exact value')
        with patch('baton.adapters.setup_files.copy_attributes', lambda source, destination: None):
            with self.assertRaises(InstallRefused): self.service.apply('claude')
        self.assertEqual(path.read_text(), '{}')
        self.assertFalse(self.service.files.record_path('claude').exists())

    def test_review_extended_attributes_survive_replacement(self):
        import ctypes
        import sys
        path = self.home / '.claude/settings.local.json'; path.parent.mkdir(parents=True)
        path.write_text('{}')
        name = b'user.baton-test' if sys.platform != 'darwin' else b'com.baton.test'
        if sys.platform == 'darwin':
            libc = ctypes.CDLL(None, use_errno=True)
            handle = os.open(path, os.O_RDONLY)
            try: self.assertEqual(libc.fsetxattr(handle, name, b'exact value', 11, 0, 0), 0)
            finally: os.close(handle)
        else: os.setxattr(path, name, b'exact value')
        self.service.apply('claude')
        from baton.adapters.setup_files import directory, attributes
        with directory(path.parent) as descriptor:
            self.assertIn((name if sys.platform == 'darwin' else name.decode(), b'exact value'), attributes(descriptor, path.name))

    def test_review_permission_metadata_added_during_backup_refused(self):
        from baton.adapters import setup_files
        for kind in ('acl', 'xattr'):
            with self.subTest(kind=kind):
                path = self.home / '.claude/settings.local.json'
                path.parent.mkdir(exist_ok=True); before = json.dumps({'kind': kind}); path.write_text(before)
                preview = self.service.preview('claude')
                original = setup_files.atomic
                added = False
                def backup(*args, **kwargs):
                    nonlocal added
                    original(*args, **kwargs); added = True
                original_mode = setup_files.permission_mode
                original_names = setup_files.attributes
                def permission(descriptor, name, info):
                    if added and name == path.name and kind == 'acl': raise InstallRefused()
                    return original_mode(descriptor, name, info)
                def attributes(descriptor, name):
                    result = original_names(descriptor, name)
                    if added and name == path.name and kind == 'xattr':
                        return (*result, ('outside.attribute', b'changed'))
                    return result
                with patch.object(setup_files, 'atomic', backup), patch.object(setup_files, 'permission_mode', permission), patch.object(setup_files, 'attributes', attributes):
                    with self.assertRaises((InstallRefused, ChatChanged)): self.service.apply('claude', preview=preview)
                self.assertEqual(path.read_text(), before)
                self.assertFalse(self.service.files.record_path('claude').exists())

    def test_review_recovery_refuses_outside_identity_permissions_ancestors_and_app(self):
        from baton.ports.setup_install import InstallAppRunning
        for kind in ('inode', 'mode', 'parent', 'app'):
            with self.subTest(kind=kind):
                path = self.home / '.claude/settings.local.json'
                path.parent.mkdir(exist_ok=True); path.write_text('{}')
                self.service.apply('claude')
                change = self.service.files.prepare(self.engine.adapters['claude'].hooks, str(self.command), True)
                record = self.service.files.record_path('claude')
                record_source = record.read_text()
                original = os.unlink
                late = False
                moved = self.home / ('moved-' + kind)
                def unlink(destination, **kwargs):
                    nonlocal late
                    if destination == record.name:
                        late = True
                        if kind == 'inode':
                            outside = path.with_name('outside')
                            outside.write_bytes(path.read_bytes()); outside.replace(path)
                        elif kind == 'mode': path.chmod(0o640)
                        elif kind == 'parent':
                            path.parent.rename(moved); path.parent.mkdir()
                            path.write_text('outside')
                        raise OSError('fail ownership publication')
                    return original(destination, **kwargs)
                def guard():
                    if late and kind == 'app': raise InstallAppRunning()
                with patch.object(os, 'unlink', unlink):
                    with self.assertRaises((ChatChanged, InstallAppRunning, InstallRefused)):
                        self.service.files.apply('claude', str(self.command), change, True,
                                                 json.loads(record_source), record_source, guard)
                surviving = moved / path.name if kind == 'parent' else path
                self.assertEqual(surviving.read_text(), change.after)
                self.assertEqual(record.read_text(), record_source)
                if kind == 'mode': self.assertEqual(path.stat().st_mode & 0o777, 0o640)
                if kind == 'parent':
                    self.assertEqual(path.read_text(), 'outside')
                    path.unlink(); path.parent.rmdir(); moved.rename(path.parent)
                # Restore fixture ownership for the next subcase using its own bytes.
                record.unlink()

    def test_review_acl_refuses_before_writes(self):
        import ctypes
        from unittest.mock import Mock
        path = self.home / '.claude/settings.local.json'; path.parent.mkdir(parents=True)
        path.write_text('{}')
        libc = Mock(); libc.acl_get_fd_np.return_value = 123
        with patch('baton.adapters.setup_files.sys.platform', 'darwin'), patch.object(ctypes, 'CDLL', return_value=libc):
            with self.assertRaises(InstallRefused): self.service.preview('claude')
        self.assertEqual(path.read_text(), '{}')
        self.assertFalse((self.engine.root / 'hook-backups').exists())

    def test_cli_requires_explicit_project_instead_of_current_folder(self):
        project = self.home / 'project'
        expected = {'claude': '.claude/settings.local.json', 'codex': '.codex/hooks.json',
                    'opencode': '.opencode/plugins/baton.js', 'cursor': '.cursor/hooks.json'}
        self.service.project = None
        try:
            for tool, relative in expected.items():
                self.engine.sandboxed = False
                with patch.object(Path, 'cwd', return_value=project):
                    refused = self.call('setup', 'install', '--tool', tool)
                    self.assertEqual(refused['error']['note']['id'], 'setup.project_required')
                    preview = self.call('setup', 'install', '--tool', tool, '--project', str(project))
                self.assertEqual(preview['files'][0]['path'], str(project / relative))
                self.assertEqual(preview['project'], str(project))
                self.assertFalse((project / relative).exists())
        finally: self.service.project = str(self.home)

    def test_review_global_is_refused_for_every_tool_before_writes(self):
        from baton.ports.setup_install import GlobalUnverified
        for tool in self.engine.adapters:
            with self.subTest(tool=tool):
                with self.assertRaises(GlobalUnverified): self.service.preview(tool, scope='global')
                preview = self.service.preview(tool)
                self.assertEqual(preview['scope'], 'project')
                self.assertFalse(preview['facts']['global_location_verified'])
                self.assertIn('setup.scope_project', [n.id for n in preview['notes']])
        self.assertFalse((self.engine.root / 'hook-installs').exists())

    def snapshot_outside_store(self):
        return {str(p.relative_to(self.home)): (p.is_dir(), None if p.is_dir() else p.read_bytes())
                for p in self.home.rglob('*') if not p.is_relative_to(self.engine.root)}

    def use_production_checks(self, running):
        self.service = SetupInstall({t: a.hooks for t, a in self.engine.adapters.items()},
                                    SetupFiles(self.engine.root), str(self.command), project=str(self.home),
                                    app_running={t: running for t in self.engine.adapters})
        self.engine.setup_install = self.service

    def test_running_app_preview_has_note_and_no_confirm_or_writes(self):
        self.use_production_checks(lambda: True)
        for tool in ('claude', 'codex', 'cursor'):
            with self.subTest(tool=tool):
                before = self.snapshot_outside_store()
                result = self.call('setup', 'install', '--tool', tool)
                self.assertIsNone(result['plan_id'])
                self.assertFalse(result['can_confirm'])
                self.assertIn('setup.install_app_running', [n['id'] for n in result['notes']])
                from baton.ports.setup_install import InstallAppRunning
                with self.assertRaises(InstallAppRunning): self.service.apply(tool)
                self.assertEqual(before, self.snapshot_outside_store())
                self.assertFalse((self.engine.root / 'hook-installs').exists())

    def test_closed_app_installs_without_coordinator_and_uninstall_waits(self):
        running = [False]
        self.use_production_checks(lambda: running[0])
        for tool in ('claude', 'codex', 'cursor'):
            with self.subTest(tool=tool):
                preview = self.call('setup', 'install', '--tool', tool)
                self.assertTrue(preview['can_confirm'])
                result = self.call('setup', 'install', '--confirm', preview['plan_id'])
                self.assertTrue(result['applied'])
                self.assertTrue(Path(result['files'][0]['path']).exists())
                removing = self.call('setup', 'uninstall', '--tool', tool)
                running[0] = True
                before = self.snapshot_outside_store()
                refused = self.call('setup', 'uninstall', '--confirm', removing['plan_id'])
                self.assertEqual(refused['error']['note']['id'], 'setup.install_app_running')
                self.assertEqual(before, self.snapshot_outside_store())
                running[0] = False

    def test_app_starts_between_preview_and_confirm_nothing_written(self):
        running = [False]
        self.use_production_checks(lambda: running[0])
        for tool in ('claude', 'codex', 'cursor'):
            with self.subTest(tool=tool):
                preview = self.call('setup', 'install', '--tool', tool)
                running[0] = True
                before = self.snapshot_outside_store()
                result = self.call('setup', 'install', '--confirm', preview['plan_id'])
                self.assertEqual(result['error']['note']['id'], 'setup.install_app_running')
                self.assertEqual(before, self.snapshot_outside_store())
                self.assertFalse((self.engine.root / 'hook-installs').exists())
                self.assertFalse((self.engine.root / 'hook-backups').exists())
                self.assertFalse(Path(preview['files'][0]['path']).exists())
                running[0] = False

    def test_ps_failure_is_running_using_existing_process_checks(self):
        from baton.adapters.claude.app import SystemProcess as ClaudeProcess
        from baton.adapters.codex.app import SystemProcess as CodexProcess
        from baton.adapters.cursor.app import SystemProcess as CursorProcess
        for process in (ClaudeProcess(), CodexProcess(), CursorProcess()):
            with self.subTest(process=type(process).__module__):
                self.use_production_checks(process.running)
                with patch.object(subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'ps')):
                    preview = self.call('setup', 'install', '--tool', 'claude')
                self.assertFalse(preview['can_confirm'])
                self.assertIsNone(preview['plan_id'])
                self.assertIn('setup.install_app_running', [n['id'] for n in preview['notes']])

    def test_opencode_owned_plugin_installs_while_running_or_check_fails(self):
        def failed(): raise OSError('fake ps failed')
        self.use_production_checks(failed)
        preview = self.call('setup', 'install', '--tool', 'opencode')
        self.assertTrue(preview['can_confirm'])
        result = self.call('setup', 'install', '--confirm', preview['plan_id'])
        self.assertTrue(result['applied'])
        removing = self.call('setup', 'uninstall', '--tool', 'opencode')
        self.assertTrue(self.call('setup', 'uninstall', '--confirm', removing['plan_id'])['applied'])

    def test_app_starts_during_preparation_refused_before_hook_publication(self):
        from baton.ports.setup_install import InstallAppRunning
        running = [False]
        self.use_production_checks(lambda: running[0])
        preview = self.service.preview('claude')
        from baton.adapters.setup_files import stage
        def starting(*args, **kwargs):
            result = stage(*args, **kwargs)
            running[0] = True
            return result
        with patch('baton.adapters.setup_files.stage', starting):
            with self.assertRaises(InstallAppRunning): self.service.apply('claude', preview=preview)
        self.assertFalse(Path(preview['files'][0]['path']).exists())
        self.assertFalse(self.service.files.record_path('claude').exists())

    def test_fresh_cli_preview_only_touches_batons_folder(self):
        own_root = self.home / 'fresh-baton'
        existing = self.home / '.claude/settings.local.json'
        existing.parent.mkdir()
        existing.write_text('{"hooks": {}}')
        def snapshot():
            return {str(p.relative_to(self.home)): (p.is_dir(), p.stat().st_mode,
                     None if p.is_dir() else (p.read_bytes(), p.stat().st_mtime_ns))
                    for p in self.home.rglob('*') if not p.is_relative_to(own_root)}
        before = snapshot()
        def factory():
            engine = build(own_root, tools_home=self.home)
            # Use the production composition with injected, inert process evidence.
            for adapter in engine.adapters.values():
                adapter.process.running = lambda: False
            return engine
        with patch.dict(os.environ, {'BATON_COMMAND': str(self.command)}):
            for tool in ('claude', 'codex', 'cursor', 'opencode'):
                out = io.StringIO()
                self.assertEqual(main(['setup', 'install', '--tool', tool, '--project', str(self.home)],
                                      engine_factory=factory, stdout=out), 0)
                preview = json.loads(out.getvalue())
                self.assertIn('setup.preview_bookkeeping', [n['id'] for n in preview['notes']])
                note = next(n for n in preview['notes'] if n['id'] == 'setup.preview_bookkeeping')
                self.assertEqual(note['values']['path'], str(own_root))
                self.assertEqual(snapshot(), before)
        self.assertTrue(own_root.exists())
        self.assertFalse((own_root / 'plans').exists())



class LauncherInstallation(unittest.TestCase):
    def test_installer_and_launcher_never_create_repository_bytecode(self):
        import shutil
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve(); repo = root / 'repo'; home = root / 'home'; home.mkdir()
            shutil.copytree(REPO / 'baton', repo / 'baton', ignore=shutil.ignore_patterns('__pycache__'))
            script = repo / 'tools/install/install-baton.sh'; script.parent.mkdir(parents=True)
            shutil.copyfile(REPO / 'tools/install/install-baton.sh', script)
            env = {**os.environ, 'HOME': str(home), 'BATON_HOME': str(home / 'store'), 'BATON_TOOLS_HOME': str(home / 'tools')}
            env.pop('PYTHONDONTWRITEBYTECODE', None)
            env.pop('PYTHONPYCACHEPREFIX', None)
            installed = subprocess.run(['/bin/sh', str(script)], env=env, capture_output=True, text=True)
            self.assertEqual(installed.returncode, 0, installed.stderr)
            self.assertEqual(list(repo.rglob('__pycache__')), [])
            command = home / '.local/bin/baton'
            self.assertIn('export PYTHONDONTWRITEBYTECODE=1', command.read_text())
            preview = subprocess.run([str(command), 'setup', 'install', '--tool', 'codex'], cwd=home, env=env, capture_output=True, text=True)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            self.assertEqual(list(repo.rglob('__pycache__')), [])

    def test_installer_chmod_cannot_follow_swapped_launcher_or_parent(self):
        script = (REPO / 'tools/install/install-baton.sh').read_text().split("<<'PY'\n", 1)[1].rsplit('\nPY', 1)[0]
        for kind in ('launcher', 'parent'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as folder:
                home = Path(folder).resolve(); command = home / '.local/bin/baton'
                foreign = home / 'foreign'; foreign.mkdir()
                victim = foreign / 'baton'; victim.write_text('outside'); victim.chmod(0o600)
                original = os.fdopen
                @contextmanager
                def swapping(*args, **kwargs):
                    with original(*args, **kwargs) as stream: yield stream
                    if kind == 'launcher': command.unlink(); command.symlink_to(victim)
                    else:
                        command.parent.rename(home / 'moved')
                        command.parent.symlink_to(foreign, target_is_directory=True)
                with patch.object(Path, 'home', return_value=home), patch.dict(os.environ, {'BATON_REPO': str(REPO), 'BATON_PYTHON': 'python3'}), patch.object(os, 'fdopen', swapping), patch('sys.stdout', io.StringIO()):
                    with self.assertRaises(SystemExit): exec(compile(script, '<installer>', 'exec'), {})
                self.assertEqual(victim.read_text(), 'outside')
                self.assertEqual(victim.stat().st_mode & 0o777, 0o600)

    def test_script_installs_launcher_runs_empty_links_and_refuses_other_command(self):
        with tempfile.TemporaryDirectory(prefix='baton launcher ') as folder:
            home = Path(folder).resolve()
            env = {**os.environ, 'HOME': str(home), 'BATON_HOME': str(home / 'store'), 'BATON_TOOLS_HOME': str(home / 'store/tools')}
            script = REPO / 'tools/install/install-baton.sh'
            # This is the one authorized subprocess check: the installer and Baton,
            # with temporary HOME/BATON_HOME, never a coding tool or native app.
            result = subprocess.run(['/bin/sh', str(script)], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            command = home / '.local/bin/baton'
            result = subprocess.run([str(command), 'links', '--json'], cwd=folder, env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['links'], [])
            result = subprocess.run([str(command), 'setup', 'install', '--tool', 'codex', '--project', str(home / 'store/tools/project')], cwd=folder, env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            preview = json.loads(result.stdout)
            self.assertEqual(preview['executable'], str(command))
            self.assertFalse(Path(preview['files'][0]['path']).exists())
            result = subprocess.run([str(command), 'setup', 'install', '--confirm', preview['plan_id']], cwd=folder, env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(json.loads(result.stdout)['applied'])
            self.assertTrue(Path(preview['files'][0]['path']).exists())
            self.assertTrue(Path(preview['files'][0]['path']).is_relative_to(home / 'store'))
            before = command.read_bytes()
            self.assertEqual(subprocess.run(['/bin/sh', str(script)], env=env, capture_output=True).returncode, 0)
            self.assertEqual(command.read_bytes(), before)
            command.write_text('other baton')
            self.assertNotEqual(subprocess.run(['/bin/sh', str(script)], env=env, capture_output=True).returncode, 0)
            self.assertEqual(command.read_text(), 'other baton')


class ProvenanceAttribute(unittest.TestCase):
    """macOS gives a rewritten file the writer's provenance; that alone must not refuse an install."""

    def test_provenance_is_neither_compared_nor_copied(self):
        from baton.adapters import setup_files
        self.assertIn(b'com.apple.provenance', setup_files.SYSTEM_ATTRIBUTES)
        self.assertIn(b'com.apple.macl', setup_files.SYSTEM_ATTRIBUTES)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'settings.local.json'
            path.write_text('{}')
            descriptor = os.open(folder, os.O_RDONLY)
            try:
                before = setup_files.attributes(descriptor, path.name)
                self.assertFalse(any(name in setup_files.SYSTEM_ATTRIBUTES for name, _ in before))
            finally:
                os.close(descriptor)
