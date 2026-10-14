"""Review-round regressions using temporary worlds and in-memory adapters."""
import ast
from pathlib import Path
import unittest
from unittest.mock import patch

from baton.cli.commands import discover
from baton.cli.main import build_parser
from baton.domain.errors import NotAvailable
from tests.contract.test_action_commands import run
from tests.contract.test_background_commands import run as background, scheduler
from tests.contract.test_fixtures import world_for
from tests.contract.generate_fixtures import original
from tests.unit import test_relaunch as relaunch_tests


class ClosureSafetyTests(unittest.TestCase):
    build = relaunch_tests.RelaunchTests.build
    plan = relaunch_tests.RelaunchTests.plan

    def setUp(self):
        self.build()

    def test_unknown_during_settling_reopens_without_write(self):
        planned = self.plan()
        close = self.target.app.close
        def closing():
            close()
            self.target.set_condition(self.chats['codex'], replying=None)
        self.target.app.close = closing
        writes = []
        result = self.service.apply(planned, write=lambda: writes.append(True))
        self.assertEqual(writes, [])
        self.assertTrue(result.opened)
        self.assertIn('relaunch.replying_unknown', [n.id for n in result.notes])
        self.assertEqual(result.notes[0].values['title'], 'destination')

    def test_unknown_after_validation_reopens_without_write(self):
        planned = self.plan()
        validate = self.service._validate
        def checking(plan, *, closed=False):
            validate(plan, closed=closed)
            if closed:
                self.target.set_condition(self.chats['codex'], replying=None)
        self.service._validate = checking
        writes = []
        result = self.service.apply(planned, write=lambda: writes.append(True))
        self.assertEqual(writes, [])
        self.assertTrue(result.opened)
        self.assertIn('relaunch.replying_unknown', [n.id for n in result.notes])

    def test_unknown_during_delivery_rebase_reopens_without_write(self):
        planned = self.plan()
        prepare = self.service.preview.prepare
        def preparing(*args, **kwargs):
            fresh = prepare(*args, **kwargs)
            self.target.set_condition(self.chats['codex'], replying=None)
            return fresh
        self.service.preview.prepare = preparing
        with patch.object(self.target.writer, 'add') as add:
            result = self.service.apply(planned)
        add.assert_not_called()
        self.assertFalse(result.applied)
        self.assertTrue(result.opened)
        self.assertEqual(result.notes[0].id, 'relaunch.replying_unknown')


class ReviewCommandTests(unittest.TestCase):
    def test_copy_failure_keeps_lifecycle_note_and_open_outcome(self):
        with world_for('review-failure') as w:
            source = w.chat('claude', 'source', [original(1)])
            w.adapters['codex'].app_running = True
            review = run(w, 'copy', source='claude:' + source, to='codex')
            with patch.object(w.adapters['codex'].writer, 'create', side_effect=NotAvailable()):
                receipt = run(w, 'copy', confirm=review['plan_id'])
            self.assertFalse(receipt['applied'])
            self.assertTrue(receipt['opened'])
            self.assertEqual(receipt['error']['note']['id'], 'relaunch.write_failed')
            self.assertIn('relaunch.write_failed', [n['id'] for n in receipt['notes']])

    def test_busy_copy_has_no_unbound_idle_button(self):
        with world_for('review-busy') as w:
            source = w.chat('claude', 'source', [original(1)])
            target = w.chat('codex', 'busy', [])
            w.adapters['codex'].set_condition(target, replying=True, app_running=True)
            review = run(w, 'copy', source='claude:' + source, to='codex')
            self.assertIn('relaunch.replying_safe', [n['id'] for n in review['notes']])
            self.assertNotIn('when_idle', [b['id'] for n in review['notes'] for b in n['buttons']])

    def test_creation_wording_follows_close_steps_and_open_at_capability(self):
        for running in (False, True):
            for tool in ('claude', 'cursor'):
                with self.subTest(running=running, tool=tool), world_for('review-wording') as w:
                    source = w.chat('codex', 'source', [original(1)])
                    w.adapters[tool].app_running = running
                    review = run(w, 'copy', source='codex:' + source, to=tool)
                    note = next(n for n in review['notes'] if n['id'] == 'new_chat.relaunch')
                    self.assertEqual('Baton closes' in note['text'], running)
                    self.assertEqual('again at it' in note['text'], tool == 'claude')
                    button = next(b for b in note['buttons'] if b['id'] == 'close_sync_reopen')
                    self.assertEqual(button['label'].startswith('Close'), running)

    def test_wrapped_sync_names_destination(self):
        with world_for('review-destination') as w:
            w.pair(shared=1)
            w.seed('claude', [original(2)])
            w.condition('codex', open=True, app_running=True)
            review = run(w, 'sync', to='codex')
            step = next(s for s in review['steps'] if s['action'] == 'add')
            self.assertEqual(step['chat']['id'], w.chats['codex'])
            self.assertEqual(step['chat']['name'], w.adapters['codex'].locator.resolve(w.chats['codex']).name)

    def test_standalone_offline_brief_uses_creation_lifecycle(self):
        for running in (False, True):
            with self.subTest(running=running), world_for('review-brief') as w:
                w.pair(shared=1)
                w.adapters['claude'].app_running = running
                review = background(w, 'brief', link=3, to='claude', writer='offline')
                self.assertEqual(review['stage'], 'create')
                self.assertIn('reopen', [s['action'] for s in review['steps']])
                self.assertEqual('close' in [s['action'] for s in review['steps']], running)
                receipt = background(w, 'brief', confirm=review['plan_id'])
                self.assertTrue(receipt['applied'], receipt)
                self.assertTrue(receipt['opened'])

    def test_standalone_brief_failure_preserves_lifecycle(self):
        with world_for('review-brief-failure') as w:
            w.pair(shared=1)
            w.adapters['claude'].app_running = True
            review = background(w, 'brief', link=3, to='claude', writer='offline')
            with patch.object(w.adapters['claude'].writer, 'create', side_effect=NotAvailable()):
                receipt = background(w, 'brief', confirm=review['plan_id'])
            self.assertFalse(receipt['applied'])
            self.assertTrue(receipt['opened'])
            self.assertEqual(receipt['error']['note']['id'], 'relaunch.write_failed')

    def test_wrapped_undo_names_existing_destination(self):
        with world_for('review-undo-destination') as w:
            w.pair(('claude', 'cursor'), shared=1)
            w.seed('claude', [original(2), original(3)])
            w.sync()
            event = next(e.id for e in w.store.history(3) if e.kind == 'add' and e.side == 'cursor')
            w.condition('cursor', app_running=True)
            review = run(w, 'undo', event=event)
            step = next(s for s in review['steps'] if s['action'] == 'create_shorter')
            self.assertEqual(step['chat']['id'], w.chats['cursor'])
            self.assertEqual(step['chat']['name'], w.adapters['cursor'].locator.resolve(w.chats['cursor']).name)

    def test_creation_reopen_failure_keeps_committed_write_identity(self):
        with world_for('review-reopen-failure') as w:
            source = w.chat('claude', 'source', [original(1)])
            w.adapters['codex'].app_running = True
            review = run(w, 'copy', source='claude:' + source, to='codex')
            with patch.object(w.adapters['codex'].app, 'open', side_effect=NotAvailable()):
                receipt = run(w, 'copy', confirm=review['plan_id'])
            self.assertTrue(receipt['applied'])
            self.assertFalse(receipt['opened'])
            self.assertIn(receipt['chat_id'], w.adapters['codex'].chats)
            self.assertEqual(receipt['reopen_error'], 'ReopenFailed')
            self.assertEqual(receipt['error']['note']['id'], 'relaunch.reopen_failed')

    def test_generated_standalone_brief_registers_creation_lifecycle(self):
        from tests.fixtures.no_processes import no_processes
        from tests.unit.test_background import ImmediateProcess
        with world_for('review-generated-brief') as w, no_processes(), patch(
                'baton.services.background.RunnerProcess', ImmediateProcess):
            w.pair(shared=1)
            w.adapters['claude'].app_running = True
            tasks = scheduler(w)
            preview = background(w, 'brief', link=3, to='claude')
            queued = background(w, 'brief', confirm=preview['plan_id'])
            tasks.pop()()
            review = background(w, 'brief', status=queued['request_id'])['result']
            self.assertEqual(review['stage'], 'create')
            self.assertEqual([s['action'] for s in review['steps']], ['close', 'wait_until_still', 'create', 'reopen'])
            alias = next(n['values']['relaunch_plan_id'] for n in review['notes'] if 'relaunch_plan_id' in n['values'])
            receipt = background(w, 'relaunch', confirm=alias)
            self.assertTrue(receipt['applied'], receipt)
            self.assertTrue(receipt['opened'])

    def test_cli_help_and_summaries_are_catalogued(self):
        from baton.notes.catalogue import CATALOGUE
        texts = {n.template for n in CATALOGUE.values()}
        registry = discover()
        self.assertTrue(all(c.summary in texts for c in registry))
        parser = build_parser(registry)
        self.assertIn(parser.description, texts)
        self.assertIn(parser._positionals.title, texts)
        self.assertIn(parser._optionals.title, texts)
        for action in parser._actions:
            if action.help is not None:
                self.assertIn(action.help, texts)
        for node in ast.walk(ast.parse(Path('baton/cli/main.py').read_text())):
            if isinstance(node, ast.keyword) and node.arg in ('description', 'help'):
                self.assertNotIsInstance(node.value, ast.Constant)
        for path in Path('baton/cli/commands').glob('*.py'):
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'command' and len(node.args) > 1:
                    self.assertNotIsInstance(node.args[1], ast.Constant, str(path))
