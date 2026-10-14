"""D10/D11 command recipes prove engine behavior on isolated fake data."""
import tempfile
from pathlib import Path
import unittest
from tests.contract.fixture_manifest import BY_NAME
from tests.contract.generate_fixtures import generate_one

class OpinionSetupFixtures(unittest.TestCase):
    def value(self, filename):
        with tempfile.TemporaryDirectory(prefix='baton-d10-d11-') as root:
            return generate_one(BY_NAME[filename], Path(root))

    def test_generation_answer_add_and_attach_are_distinct_real_commands(self):
        preview = self.value('ask.d10_before.json')
        self.assertEqual(preview['stage'], 'generate')
        self.assertTrue(preview['read_only'])
        self.assertFalse(preview['applied'])
        self.assertGreater(preview['estimated_tokens'], 0)
        answer = self.value('ask.d10_answer.json')
        self.assertEqual(answer['state'], 'completed')
        self.assertTrue(answer['result']['answer_id'])
        self.assertTrue(answer['result']['answer'])
        review = self.value('ask-add.d10_review.json')
        self.assertEqual(review['stage'], 'add')
        self.assertFalse(review['applied'])
        self.assertTrue(self.value('ask-add.d10_applied.json')['applied'])
        self.assertEqual(self.value('ask-add.d10_attached.json')['steps'][0]['action'], 'attach')
        self.assertTrue(self.value('ask-add.d10_unavailable.json')['decision_needed'])

    def test_unavailable_cancelled_and_deadline_have_engine_notes(self):
        for state in ('limit', 'command_missing', 'signed_out'):
            value = self.value(f'ask.d10_{state}.json')
            self.assertTrue(value['error']['note']['text'])
        for state in ('pending', 'cancelled', 'deadline'):
            value = self.value(f'ask.d10_{state}.json')
            self.assertEqual(value['state'], state)
            self.assertTrue(value['notes'][0]['text'])
            self.assertFalse(value['applied'])

    def test_setup_findings_and_settings_are_actual_engine_projections(self):
        findings = {'codex_trust': 'setup.trust_once', 'opencode_damaged': 'setup.runner_reinstall',
                    'cursor_signed_out': 'setup.runner', 'not_installed': 'setup.not_installed',
                    'unknown_format': 'format.unknown_version', 'missing_hooks': 'setup.hooks'}
        for state, note in findings.items():
            value = self.value(f'setup.d11_{state}.json')
            self.assertEqual(len(value['tools']), 4)
            self.assertTrue(any(f['note']['id'] == note and not f['ok'] for t in value['tools'] for f in t['findings']))
        self.assertEqual(self.value('setup.d11_empty.json')['tools'], [])
        self.assertEqual(self.value('setup.d11_error.json')['error']['note']['id'], 'error.unexpected')
        self.assertTrue(all(t['ready'] for t in self.value('setup.d11_ready.json')['tools']))
        self.assertEqual(self.value('settings-get.d11_loaded.json')['settings']['theme'], 'system')
        self.assertEqual(self.value('settings-set.d11_saved.json')['settings']['theme'], 'graphite')
