"""E13 setup, including X5 and independent failing probes."""
import unittest
from unittest.mock import Mock
from baton.adapters.fake import FakeAdapter
from baton.adapters.fake.facts import CLAUDE_LIKE, CODEX_LIKE, OPENCODE_LIKE, CURSOR_LIKE
from baton.ports.tool import FormatCheck, SetupFinding
from baton.services.setup_check import SetupCheck
from baton.notes.catalogue import get


class SetupCheckTests(unittest.TestCase):
    def setUp(self):
        self.adapter = FakeAdapter(CLAUDE_LIKE, 'claude')

    def test_X5_not_installed_left_alone_and_unavailable(self):
        self.adapter.state.format_version = Mock(side_effect=AssertionError)
        self.adapter.hooks.check = Mock(side_effect=AssertionError)
        self.adapter.runner.available = Mock(side_effect=AssertionError)
        row = SetupCheck({'claude': self.adapter}, installation_probe=lambda _: False).tools()[0]
        self.assertFalse(row['installed'])
        self.assertFalse(row['ready'])
        self.assertIsNone(row['version'])
        self.assertEqual(row['findings'][0]['note'].id, 'setup.not_installed')
        self.adapter.state.format_version.assert_not_called()
        self.adapter.hooks.check.assert_not_called()
        self.adapter.runner.available.assert_not_called()

    def test_missing_adapter_no_fabricated_capabilities(self):
        row = SetupCheck({}, ['other'], installation_probe=lambda _: True).tools()[0]
        self.assertEqual(row['facts'], {})
        self.assertEqual(row['findings'][0]['note'].id, 'setup.adapter_unavailable')

    def test_each_fact_set_reports_version_hooks_and_runner(self):
        for facts in (CLAUDE_LIKE, CODEX_LIKE, OPENCODE_LIKE, CURSOR_LIKE):
            adapter = FakeAdapter(facts, 'claude')
            adapter.hooks.ready = True
            row = SetupCheck({'claude': adapter}, installation_probe=lambda _: True).tools()[0]
            self.assertTrue(row['ready'])
            self.assertTrue(row['background_ready'])
            self.assertEqual(row['version'], facts.checked_versions[0])
            self.assertEqual(row['facts']['write_window'], facts.write_window.value)
            for finding in row['findings']:
                get(finding['note'].id).render(finding['note'].values)

    def test_unknown_shape_only_disables_that_tool(self):
        self.adapter.set_format(False, 'future')
        rows = SetupCheck({'claude': self.adapter, 'codex': FakeAdapter(CLAUDE_LIKE, 'codex')}, installation_probe=lambda _: True).tools()
        self.assertFalse(rows[0]['ready'])
        self.assertTrue(rows[1]['ready'])
        self.assertEqual(rows[0]['findings'][1]['note'].id, 'format.unknown_version')

    def test_missing_hooks_and_runner_supply_fixes(self):
        self.adapter.hooks.uninstall()
        self.adapter.runner.finding = SetupFinding('runner', False, 'setup.runner_reinstall', {})
        row = SetupCheck({'claude': self.adapter}, installation_probe=lambda _: True).tools()[0]
        self.assertFalse(row['ready'])
        self.assertFalse(row['background_ready'])
        self.assertEqual([f['note'].id for f in row['findings'][2:]], ['setup.hooks', 'setup.runner_reinstall'])

    def test_trust_and_sign_in_notes_are_preserved(self):
        self.adapter.hooks.check = lambda: SetupFinding('trust', False, 'setup.trust_once', {})
        self.adapter.runner.finding = SetupFinding('login', False, 'setup.runner', {'reason': 'signed_out'})
        row = SetupCheck({'claude': self.adapter}, installation_probe=lambda _: True).tools()[0]
        self.assertEqual(row['findings'][2]['note'].id, 'setup.trust_once')
        self.assertEqual(row['findings'][3]['id'], 'login')

    def test_failed_probe_does_not_hide_other_findings(self):
        self.adapter.state.format_version = Mock(side_effect=OSError)
        self.adapter.hooks.check = Mock(side_effect=OSError)
        row = SetupCheck({'claude': self.adapter}, installation_probe=lambda _: True).tools()[0]
        self.assertEqual(len(row['findings']), 4)
        self.assertTrue(row['background_ready'])
        self.assertIsNone(row['version'])

    def test_no_runner_sync_remains_ready_offline_available(self):
        self.adapter.runner = None
        row = SetupCheck({'claude': self.adapter}, installation_probe=lambda _: True).tools()[0]
        self.assertTrue(row['ready'])
        self.assertFalse(row['background_ready'])

    def test_new_release_known_shape_is_information_only(self):
        self.adapter.state.format_version = lambda: FormatCheck(True, 'new release', new_version=True)
        row = SetupCheck({'claude': self.adapter}, installation_probe=lambda _: True).tools()[0]
        self.assertTrue(row['ready'])
        self.assertEqual(row['findings'][1]['note'].id, 'format.new_version')

    def test_X5_link_choices_exclude_uninstalled_tool(self):
        other = FakeAdapter(CURSOR_LIKE, 'cursor')
        rows = SetupCheck({'claude': self.adapter, 'cursor': other},
                          installation_probe=lambda tool: tool != 'cursor').tools()
        offered = [row['tool'] for row in rows if any(m['available'] for m in row['link_modes'])]
        self.assertEqual(offered, ['claude'])
        self.assertEqual(rows[1]['link_modes'], [])
        self.assertEqual([m['mode'] for m in rows[0]['link_modes']],
                         ['full_copy', 'attached_history', 'brief'])
