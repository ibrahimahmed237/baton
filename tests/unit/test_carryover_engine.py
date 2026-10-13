"""CP3 carry-over regressions: CLI notes and preview side effects."""
import io
import json
import unittest
from unittest.mock import patch

from baton.cli import main, output
from baton.notes.catalogue import CATALOGUE
from tests.unit.test_brief import BriefBase


class PreviewReadiness(BriefBase):
    def test_preview_never_calls_availability_but_generation_checks_it(self):
        with patch.object(self.runners['codex'], 'available', side_effect=AssertionError('spawn')) as available:
            plan = self.briefs.plan(self.link.id, 'codex')
            available.assert_not_called()
        with patch.object(self.runners['codex'], 'available', wraps=self.runners['codex'].available) as available:
            artifact = self.briefs.confirm(plan)
            self.assertEqual(artifact.stage, 'create')
            self.assertGreater(available.call_count, 0)


    def test_cached_unready_runner_is_skipped_without_process_checks(self):
        from baton.ports.tool import SetupFinding
        self.runners['codex'].finding = SetupFinding('runner', False, 'setup.runner', {})
        with patch.object(self.runners['codex'], 'available', side_effect=AssertionError('spawn')):
            plan = self.briefs.plan(self.link.id, 'codex')
        self.assertEqual(plan.writer, 'claude')
        self.assertIn('setup.runner', [note.id for note in plan.notes])


class UsageNotes(unittest.TestCase):
    def test_parser_refusal_is_catalogue_copy_without_raw_parser_sentence(self):
        stdout = io.StringIO()
        self.assertEqual(main.main(['not-a-command'], stdout=stdout), 2)
        error = json.loads(stdout.getvalue())['error']
        self.assertEqual(error['note']['id'], 'cli.usage')
        self.assertEqual(error['message'], CATALOGUE['cli.usage'].template)

    def test_usage_and_crash_sentences_are_catalogue_notes(self):
        self.assertEqual(output.usage_error('cli.conflicting_flags')['error']['note']['id'], 'cli.conflicting_flags')
        self.assertEqual(output.internal_error(RuntimeError('private'))['error']['note']['id'], 'error.unexpected')
        self.assertNotIn('private', json.dumps(output.internal_error(RuntimeError('private'))))

    def test_wrong_command_confirmation_has_its_own_catalogue_refusal(self):
        from baton.cli.plans import PlanBook, MemoryPlanStore
        from baton.domain.errors import BatonError
        from baton.ports.clock import SystemClock
        book = PlanBook(MemoryPlanStore(), SystemClock())
        shown = book.remember('fingerprint', 'sync', {})
        with self.assertRaises(BatonError) as refusal:
            book.confirm(shown, 'unlink', lambda _: self.fail('replanned wrong command'))
        payload = output.error(refusal.exception)['error']
        self.assertEqual(payload['note']['id'], 'plan.wrong_action')
        self.assertEqual(payload['note']['text'], CATALOGUE['plan.wrong_action'].template)
        self.assertIsNotNone(book.store.load(shown))
        book.confirm(shown, 'sync', lambda _: 'fingerprint')
