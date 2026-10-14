"""C5/C6 commands use isolated adapters and explicitly scheduled fake work."""
from contextlib import nullcontext
from copy import deepcopy
from datetime import datetime, timedelta
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from baton.cli.commands import Context, discover
from baton.domain.errors import ChatChanged, NotAvailable
from baton.cli.plans import WrongPlanAction
from baton.ports.tool import Usage
from tests.contract.generate_fixtures import original
from tests.contract.test_fixtures import world_for

REGISTRY = discover()


def run(world, command, confirm=None, **kwargs):
    args = SimpleNamespace(link=None, tool=None, to=None, writer='auto', chat=None, source=None,
        question=None, turn=None, status=None, cancel=None, answer=None, add_to_chat=False,
        when_idle=False, then_sync=None, background=True)
    for key, value in kwargs.items(): setattr(args, key, value)
    return REGISTRY.get(command).run(Context(world.engine, command, confirm=confirm), args)


def scheduler(world):
    tasks = []
    world.engine.background_dispatch = tasks.append
    return tasks


class BackgroundCommandsTests(unittest.TestCase):
    def setUp(self):
        from tests.fixtures.no_processes import no_processes
        self.enterContext(no_processes())
        self.enterContext(patch('os.setsid', side_effect=AssertionError('real setsid')))
        from tests.unit.test_background import ImmediateProcess
        controller = patch('baton.services.background.RunnerProcess', ImmediateProcess)
        controller.start()
        self.addCleanup(controller.stop)

    def test_brief_generation_review_and_creation_are_distinct_confirmations(self):
        with world_for('brief-command') as w, patch('subprocess.run', side_effect=AssertionError('subprocess')):
            w.pair()
            tasks = scheduler(w)
            before = deepcopy({s: a.chats for s, a in w.adapters.items()})
            preview = run(w, 'brief', link=3, to='codex')
            self.assertEqual(preview['stage'], 'generate')
            self.assertGreater(preview['brief']['estimated_tokens'], 0)
            self.assertFalse(any(a.runner.calls for a in w.adapters.values()))
            queued = run(w, 'brief', confirm=preview['plan_id'])
            self.assertEqual(queued['state'], 'pending')
            self.assertEqual(before, {s: a.chats for s, a in w.adapters.items()})
            tasks.pop()()
            reviewed = run(w, 'brief', status=queued['request_id'])['result']
            self.assertEqual(reviewed['stage'], 'create')
            self.assertNotEqual(reviewed['plan_id'], preview['plan_id'])
            self.assertTrue(reviewed['brief']['text'])
            self.assertEqual(before, {s: a.chats for s, a in w.adapters.items()})
            self.assertTrue(run(w, 'brief', confirm=reviewed['plan_id'])['applied'])
            self.assertNotEqual(w.store.get_link(3).chat('codex'), w.chats['codex'])
            with self.assertRaises(ChatChanged): run(w, 'brief', confirm=preview['plan_id'])

    def test_automatic_writer_limit_and_no_runner_fallback_then_offline(self):
        for reason in ('limit', 'no_runner', 'both'):
            with self.subTest(reason=reason), world_for('fallback-' + reason) as w:
                w.pair()
                scheduler(w)
                if reason == 'limit':
                    w.adapters['codex'].usage_values[w.chats['codex']] = Usage(8000, 200000, True, None)
                else:
                    w.adapters['codex'].runner = None
                if reason == 'both': w.adapters['claude'].runner = None
                preview = run(w, 'brief', link=3)
                self.assertEqual(preview['brief']['writer'], 'offline' if reason == 'both' else 'claude')
                self.assertEqual(preview['stage'], 'create' if reason == 'both' else 'generate')
                ids = [n['id'] for n in preview['notes']]
                self.assertIn('brief.skipped_limit' if reason == 'limit' else 'brief.skipped_no_runner', ids)

    def test_fallback_tries_disclosed_writers_once_in_order(self):
        with world_for('fallback-run') as w:
            w.pair()
            tasks = scheduler(w)
            w.adapters['codex'].runner.error = NotAvailable()
            preview = run(w, 'brief', link=3)
            self.assertEqual([e['writer'] for e in preview['brief']['candidate_estimates']], ['codex', 'claude'])
            queued = run(w, 'brief', confirm=preview['plan_id'])
            tasks.pop()()
            result = run(w, 'brief', status=queued['request_id'])['result']
            self.assertEqual(result['brief']['writer'], 'claude')
            self.assertEqual([len(w.adapters[s].runner.calls) for s in ('codex', 'claude')], [1, 1])

    def test_brief_and_opinion_prompts_exclude_kept_turns(self):
        with world_for('private-prompts') as w:
            w.pair(shared=1)
            ids = w.seed('claude', [original(8)])
            w.store.keep_back(3, ids[0])
            tasks = scheduler(w)
            preview = run(w, 'brief', link=3, to='codex', writer='codex')
            queued = run(w, 'brief', confirm=preview['plan_id'])
            tasks.pop()()
            prompt = w.adapters['codex'].runner.calls[-1][0]
            self.assertNotIn('Orchard task 8', prompt)
            preview = run(w, 'ask', chat='claude:' + w.chats['claude'], question='Review', tool='codex')
            queued = run(w, 'ask', confirm=preview['plan_id'])
            tasks.pop()()
            self.assertNotIn('Orchard task 8', w.adapters['codex'].runner.calls[-1][0])
            with self.assertRaises(NotAvailable):
                run(w, 'ask', chat='claude:' + w.chats['claude'], question='Review', tool='codex', turn=ids[0])

    def test_second_opinion_never_adds_before_separate_confirm(self):
        with world_for('opinion-add') as w, patch('subprocess.run', side_effect=AssertionError('subprocess')):
            w.pair()
            tasks = scheduler(w)
            before = deepcopy(w.adapters['claude'].chats)
            preview = run(w, 'ask', chat='claude:' + w.chats['claude'], question='Review', add_to_chat=True)
            self.assertEqual(preview['writer'], 'codex')
            self.assertTrue(preview['read_only'])
            queued = run(w, 'ask', confirm=preview['plan_id'])
            tasks.pop()()
            answer = run(w, 'ask', status=queued['request_id'])['result']
            self.assertTrue(answer['answer'])
            self.assertEqual(w.adapters['codex'].runner.calls[-1][2], True)
            self.assertEqual(before, w.adapters['claude'].chats)
            addition = run(w, 'ask add', answer=answer['answer_id'])
            self.assertEqual(before, w.adapters['claude'].chats)
            result = run(w, 'ask add', confirm=addition['plan_id'])
            self.assertTrue(result['applied'])
            self.assertIn('Second opinion from Codex', w.adapters['claude'].reader.read(w.chats['claude'])[-1].prompt.text)
            self.assertTrue(w.store.journal_entries()[-1]['state'] == 'committed')
            with self.assertRaises(ChatChanged): run(w, 'ask add', confirm=addition['plan_id'])

    def test_cancelled_generation_cannot_be_restarted_or_added(self):
        with world_for('cancel-command') as w:
            w.pair()
            tasks = scheduler(w)
            preview = run(w, 'ask', chat='claude:' + w.chats['claude'], question='Review')
            queued = run(w, 'ask', confirm=preview['plan_id'])
            run(w, 'ask', cancel=queued['request_id'])
            with self.assertRaises(NotAvailable): tasks.pop()()
            self.assertFalse(w.adapters['codex'].runner.calls)
            with self.assertRaises(NotAvailable): run(w, 'ask add', answer=queued['request_id'])

    def test_wrong_action_and_changed_chat_refuse_before_generation(self):
        with world_for('opinion-stale') as w:
            w.pair()
            scheduler(w)
            preview = run(w, 'ask', chat='claude:' + w.chats['claude'], question='Review')
            with self.assertRaises(WrongPlanAction): run(w, 'brief', confirm=preview['plan_id'])
            w.seed('claude', [original(4)])
            with self.assertRaises(ChatChanged): run(w, 'ask', confirm=preview['plan_id'])
            self.assertFalse(w.adapters['codex'].runner.calls)

    def test_open_chat_add_queues_without_native_write(self):
        with world_for('opinion-open') as w:
            w.pair()
            tasks = scheduler(w)
            preview = run(w, 'ask', chat='claude:' + w.chats['claude'], question='Review')
            queued = run(w, 'ask', confirm=preview['plan_id']); tasks.pop()()
            w.condition('claude', open=True)
            addition = run(w, 'ask add', answer=queued['request_id'])
            self.assertFalse(addition['decision_needed'])
            self.assertEqual(addition['confirmation']['id'], 'ask.attach_preview')
            before = deepcopy(w.adapters['claude'].chats)
            self.assertTrue(run(w, 'ask add', confirm=addition['plan_id'])['queued'])
            self.assertEqual(before, w.adapters['claude'].chats)

    def test_relaunch_preview_names_exact_write_chats_and_lifecycle(self):
        with world_for('relaunch-command') as w:
            w.pair(shared=1)
            w.seed('claude', [original(2)])
            w.condition('codex', open=True, app_running=True)
            tasks = scheduler(w)
            preview = run(w, 'relaunch', tool='codex')
            self.assertEqual([s['action'] for s in preview['steps']], ['close', 'wait_until_still', 'add', 'reopen'])
            written = next(s for s in preview['steps'] if s['action'] == 'add')
            self.assertEqual(written['chat']['id'], w.chats['codex'])
            queued = run(w, 'relaunch', confirm=preview['plan_id'])
            with patch.object(w.engine, 'command_lock', return_value=nullcontext()): tasks.pop()()
            result = run(w, 'relaunch', status=queued['request_id'])['result']
            self.assertTrue(result['applied'])
            self.assertTrue(result['opened'])
            self.assertEqual([t.prompt.text for t in w.adapters['codex'].reader.read(w.chats['codex'])],
                             ['Orchard task 1', 'Orchard task 2'])

    def test_relaunch_refuses_replying_and_unknown_with_chat_names(self):
        for state in (True, None):
            with self.subTest(state=state), world_for('replying-' + str(state)) as w:
                w.pair()
                scheduler(w)
                w.condition('codex', replying=state)
                preview = run(w, 'relaunch', tool='codex')
                self.assertTrue(preview['decision_needed'])
                self.assertEqual(preview['replying'][0]['id'], w.chats['codex'])
                if state is True:
                    self.assertEqual(run(w, 'relaunch', confirm=preview['plan_id'])['error']['kind'], 'chat_replying')
                self.assertFalse(any(c[0] == 'close' for c in w.adapters['codex'].app.calls))

    def test_when_idle_pending_request_keeps_original_expiry(self):
        with world_for('relaunch-idle') as w:
            w.pair()
            w.condition('codex', replying=True)
            tasks = scheduler(w)
            preview = run(w, 'relaunch', tool='codex', when_idle=True)
            queued = run(w, 'relaunch', confirm=preview['plan_id'])
            self.assertEqual(queued['state'], 'pending')
            self.assertEqual(queued['expires_at'], preview['expires_at'])
            with patch.object(w.clock, 'now', return_value=preview['expires_at']), patch.object(w.engine, 'command_lock', return_value=nullcontext()):
                tasks.pop()()
                result = run(w, 'relaunch', status=queued['request_id'])['result']
                self.assertEqual(result['error']['kind'], 'idle_timeout')
                self.assertFalse(result['applied'])
            self.assertFalse(any(c[0] == 'close' for c in w.adapters['codex'].app.calls))

    def test_relaunch_close_timeout_reports_no_writes(self):
        from baton.services import background_relaunch as module
        from baton.services.relaunch import Relaunch
        with world_for('relaunch-timeout') as w:
            w.pair(shared=1)
            w.seed('claude', [original(2)])
            w.condition('codex', open=True, app_running=True)
            tasks = scheduler(w)
            elapsed = [0.0]
            def wait(seconds): elapsed[0] += seconds
            def factory(store, adapters, clock):
                return Relaunch(store, adapters, clock, elapsed=lambda: elapsed[0], wait=wait)
            with patch.object(module, 'Relaunch', side_effect=factory):
                preview = run(w, 'relaunch', tool='codex')
                queued = run(w, 'relaunch', confirm=preview['plan_id'])
                before = deepcopy(w.adapters['codex'].chats)
                with patch.object(w.adapters['codex'].app, 'close'), patch.object(w.engine, 'command_lock', return_value=nullcontext()):
                    tasks.pop()()
                result = run(w, 'relaunch', status=queued['request_id'])['result']
            self.assertEqual(result['error']['kind'], 'close_timeout')
            self.assertEqual(before, w.adapters['codex'].chats)
            self.assertFalse(result['applied'])

    def test_preview_never_probes_runner_and_selected_turn_is_full(self):
        with world_for('opinion-selected') as w:
            w.pair(shared=1)
            row = w.store.turns(3)[0]
            tasks = scheduler(w)
            runner = w.adapters['codex'].runner
            with patch.object(runner, 'available', side_effect=AssertionError('availability probe')):
                preview = run(w, 'ask', chat='claude:' + w.chats['claude'], question='Review', turn=row.id)
                run(w, 'brief', link=3, to='codex')
            queued = run(w, 'ask', confirm=preview['plan_id']); tasks.pop()()
            self.assertIn(original(1).prompt.text, runner.calls[-1][0])
            self.assertIn(original(1).reply_text, runner.calls[-1][0])

    def test_writer_limit_and_missing_runner_are_named_refusals(self):
        from baton.cli import output
        for reason in ('limit', 'runner'):
            with self.subTest(reason=reason), world_for('ask-unavailable-' + reason) as w:
                w.pair()
                if reason == 'limit':
                    w.adapters['codex'].usage_values[w.chats['codex']] = Usage(8000, 200000, True, None)
                else:
                    w.adapters['codex'].runner = None
                with self.assertRaises(NotAvailable) as raised:
                    run(w, 'ask', chat='claude:' + w.chats['claude'], question='Review')
                note = output.error(raised.exception)['error']['note']
                self.assertEqual(note['values']['tool'], 'Codex')
                self.assertEqual(note['id'], 'limit.reached' if reason == 'limit' else 'brief.skipped_no_runner')

    def test_scheduled_worker_uses_fake_runner_and_persists_poll_result(self):
        with world_for('scheduled-fake') as w:
            w.pair()
            tasks = scheduler(w)
            preview = run(w, 'brief', link=3)
            queued = run(w, 'brief', confirm=preview['plan_id'])
            self.assertEqual(len(tasks), 1)
            self.assertEqual(run(w, 'brief', status=queued['request_id'])['state'], 'pending')
            tasks.pop()()
            status = run(w, 'brief', status=queued['request_id'])
            self.assertEqual(status['state'], 'completed')
            self.assertEqual(status['result']['stage'], 'create')
            self.assertTrue(status['result']['brief']['text'])
            self.assertEqual(w.store.get_link(3).chat('codex'), w.chats['codex'])

    def test_brief_deadline_does_not_publish_offline_fallback_or_create_chat(self):
        import threading
        from tests.unit.test_background import WaitingProcess
        from baton.services import background_brief as module
        from baton.services.background import Background
        with world_for('brief-command-deadline') as w:
            w.pair()
            tasks = scheduler(w)
            release = threading.Event()
            runner = w.adapters['codex'].runner
            def slow(*args, **kwargs):
                release.wait(1)
                return 'late'
            before = deepcopy({s: a.chats for s, a in w.adapters.items()})
            preview = run(w, 'brief', link=3)
            queued = run(w, 'brief', confirm=preview['plan_id'])
            try:
                with patch.object(runner, 'ask', side_effect=slow), patch.object(module, 'Background',
                        side_effect=lambda store, clock: Background(store, clock, seconds=.02,
                            process_controller=lambda *args: WaitingProcess())):
                    tasks.pop()()
                result = run(w, 'brief', status=queued['request_id'])
                self.assertEqual(result['state'], 'deadline')
                self.assertNotIn('result', result)
                self.assertEqual(before, {s: a.chats for s, a in w.adapters.items()})
            finally:
                release.set()

    def test_unlinked_chat_opinion_and_add_keep_it_unlinked(self):
        with world_for('unlinked-opinion') as w:
            chat = w.chat('claude', 'unlinked', [original(1)])
            tasks = scheduler(w)
            preview = run(w, 'ask', chat='claude:' + chat, tool='codex', question='Review')
            self.assertIsNone(preview['link_id'])
            queued = run(w, 'ask', confirm=preview['plan_id']); tasks.pop()()
            addition = run(w, 'ask', answer=queued['request_id'], add_to_chat=True)
            self.assertTrue(run(w, 'ask', confirm=addition['plan_id'])['applied'])
            self.assertIsNone(w.store.link_for('claude', chat))
            self.assertEqual(len(w.adapters['claude'].reader.read(chat)), 2)

    def test_runner_with_only_spawning_probe_is_not_offered_at_preview(self):
        with world_for('no-readiness-proof') as w:
            w.pair()
            class ProbeOnly:
                def available(self): raise AssertionError('spawning probe')
                def ask(self, *args, **kwargs): raise AssertionError('runner')
            w.adapters['codex'].runner = ProbeOnly()
            preview = run(w, 'brief', link=3)
            self.assertEqual(preview['brief']['writer'], 'claude')
            with self.assertRaises(NotAvailable):
                run(w, 'ask', chat='claude:' + w.chats['claude'], question='Review', tool='codex')

    def test_linked_opinion_refuses_third_installed_writer(self):
        with world_for('three-writer-privacy') as w:
            w.pair(shared=1)
            kept = w.seed('claude', [original(8)])[0]
            w.store.keep_back(3, kept)
            with self.assertRaises(NotAvailable):
                run(w, 'ask', chat='claude:' + w.chats['claude'], tool='cursor', question='Review')
            self.assertFalse(w.adapters['cursor'].runner.calls)
            self.assertFalse(w.adapters['codex'].runner.calls)

    def test_cancel_at_relaunch_lock_boundary_prevents_all_actions(self):
        from contextlib import contextmanager
        from baton.services.background import Background
        with world_for('cancel-lock-boundary') as w:
            w.pair()
            w.condition('codex', open=True, app_running=True)
            tasks = scheduler(w)
            preview = run(w, 'relaunch', tool='codex')
            queued = run(w, 'relaunch', confirm=preview['plan_id'])
            @contextmanager
            def lock():
                Background(w.store, w.clock).stop(queued['request_id'])
                yield
            before = deepcopy(w.adapters['codex'].chats)
            w.adapters['codex'].app.calls.clear()
            with patch.object(w.engine, 'command_lock', side_effect=lock): tasks.pop()()
            self.assertEqual(run(w, 'relaunch', status=queued['request_id'])['state'], 'cancelled')
            self.assertEqual(before, w.adapters['codex'].chats)
            self.assertFalse(w.adapters['codex'].app.calls)

    def test_frozen_ask_signature_returns_immediate_answer(self):
        with world_for('legacy-ask-result') as w:
            w.pair(shared=1)
            tasks = scheduler(w)
            result = run(w, 'ask', source='claude:' + w.chats['claude'], turn=w.store.turns(3)[0].id,
                         tool='codex', question='Review', background=False)
            self.assertTrue({'answer_id', 'answer', 'tokens', 'seconds', 'notes'} <= result.keys())
            self.assertTrue(result['answer'])
            self.assertNotIn('plan_id', result)
            self.assertEqual(tasks, [])
            self.assertEqual(w.adapters['codex'].runner.calls[-1][2], True)
            self.assertTrue(run(w, 'ask add', answer=result['answer_id'])['plan_id'])

    def test_frozen_brief_confirmation_returns_creation_review(self):
        with world_for('legacy-brief-transition') as w:
            w.pair()
            tasks = scheduler(w)
            preview = run(w, 'brief', link=3, to='codex', background=False)
            self.assertTrue({'plan_id', 'applied', 'link_id', 'steps', 'brief'} <= preview.keys())
            result = run(w, 'brief', confirm=preview['plan_id'], background=False)
            self.assertEqual(result['stage'], 'create')
            self.assertNotEqual(result['plan_id'], preview['plan_id'])
            self.assertTrue(result['brief']['artifact_id'])
            self.assertFalse(result['applied'])
            self.assertEqual(tasks, [])
            applied = run(w, 'brief', confirm=result['plan_id'])
            self.assertTrue(applied['applied'])
            self.assertTrue({'steps', 'brief', 'decision_needed', 'notes'} <= applied.keys())
            self.assertEqual(applied['brief'], result['brief'])

    def test_confirmed_open_answer_survives_restart_and_attaches_once(self):
        from baton.hooks.prompt import reviewed_reply
        from baton.hooks import HookCall
        from baton.ledger.sqlite_store import Ledger
        with world_for('opinion-attachment-restart') as w:
            w.pair()
            tasks = scheduler(w)
            preview = run(w, 'ask', chat='claude:' + w.chats['claude'], question='Review')
            queued = run(w, 'ask', confirm=preview['plan_id']); tasks.pop()()
            w.condition('claude', open=True)
            before = deepcopy(w.adapters['claude'].chats)
            addition = run(w, 'ask add', answer=queued['request_id'])
            call = HookCall(w.chats['claude'], 'next-prompt')
            self.assertEqual(reviewed_reply(w.engine, 'claude', call), '')
            self.assertTrue(run(w, 'ask add', confirm=addition['plan_id'])['queued'])
            path = w.store.db.execute('pragma database_list').fetchone()[2]
            w.store.close()
            w.store = w.engine.store = Ledger(path)
            self.assertEqual(reviewed_reply(w.engine, 'codex', HookCall(w.chats['codex'], 'other')), '')
            reply = reviewed_reply(w.engine, 'claude', call)
            self.assertIn('Second opinion from Codex', reply)
            self.assertEqual(reviewed_reply(w.engine, 'claude', call), '')
            self.assertEqual(reviewed_reply(w.engine, 'claude', HookCall(call.chat, 'later')), '')
            self.assertEqual(before, w.adapters['claude'].chats)

    def test_queued_answer_expires_or_refuses_changed_privacy(self):
        from baton.hooks.prompt import reviewed_reply
        from baton.hooks import HookCall
        for change in ('expiry', 'privacy', 'pause'):
            with self.subTest(change=change), world_for('queued-' + change) as w:
                w.pair(shared=1)
                private_id = w.seed('claude', [original(8)])[0]
                tasks = scheduler(w)
                preview = run(w, 'ask', chat='claude:' + w.chats['claude'], question='Review')
                queued = run(w, 'ask', confirm=preview['plan_id']); tasks.pop()()
                w.condition('claude', open=True)
                addition = run(w, 'ask add', answer=queued['request_id'])
                run(w, 'ask add', confirm=addition['plan_id'])
                if change == 'privacy': w.store.keep_back(3, private_id)
                if change == 'pause': w.store.set_paused(3, True)
                future = (datetime.fromisoformat(w.clock.now()) + timedelta(hours=1)).isoformat()
                with patch.object(w.clock, 'now', return_value=future if change == 'expiry' else w.clock.now()):
                    self.assertEqual(reviewed_reply(w.engine, 'claude', HookCall(w.chats['claude'], 'next')), '')
                if change == 'expiry': self.assertEqual(w.store.reviewed_answers('claude', w.chats['claude']), [])

    def test_prompt_runtime_delivers_unlinked_confirmed_answer_with_legacy_identity(self):
        import argparse
        import io
        from baton.hooks.runtime import invoke
        with world_for('prompt-runtime-answer') as w:
            chat = w.chat('claude', 'unlinked', [original(1)])
            tasks = scheduler(w)
            preview = run(w, 'ask', chat='claude:' + chat, tool='codex', question='Review')
            queued = run(w, 'ask', confirm=preview['plan_id']); tasks.pop()()
            w.adapters['claude'].conditions[chat] = w.adapters['claude'].conditions[chat].__class__(
                exists=True, open=True, replying=False, hooks_ready=True)
            addition = run(w, 'ask add', answer=queued['request_id'])
            run(w, 'ask add', confirm=addition['plan_id'])
            args = argparse.Namespace(tool='claude', chat=chat, turn_id='', event=None)
            reply = invoke(args, prompt=True, engine_factory=lambda: w.engine, stdin=io.StringIO(), locked=True)
            self.assertIn('Second opinion from Codex', reply)
            self.assertEqual(invoke(args, prompt=True, engine_factory=lambda: w.engine,
                stdin=io.StringIO(), locked=True), '')

    def test_command_policies_use_service_orchestration(self):
        import ast
        from pathlib import Path
        # Protect the architectural regression: services own adapter/runner policy.
        for command in ('brief', 'relaunch'):
            tree = ast.parse((Path(__file__).parents[2] / 'baton' / 'cli' / 'commands' / (command + '.py')).read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    self.assertNotEqual(node.func.attr, '_validate')
                if isinstance(node, ast.Assign):
                    self.assertFalse(any(isinstance(target, ast.Attribute) and target.attr == 'runner'
                                         for target in node.targets))

    def test_real_brief_job_cleanup_retains_only_canonical_artifacts_after_restart(self):
        from baton.ledger.sqlite_store import Ledger
        from baton.services.background import Background
        for create in (False, True):
            with self.subTest(create=create), world_for('brief-job-cleanup-' + str(create)) as w:
                w.pair()
                tasks = scheduler(w)
                preview = run(w, 'brief', link=3, to='codex')
                job = run(w, 'brief', confirm=preview['plan_id'])
                tasks.pop()()
                review = run(w, 'brief', status=job['request_id'])['result']
                artifact_id = review['brief']['artifact_id']
                owned = {(row['kind'], row['ident']) for row in w.store.db.execute(
                    'select kind,ident from background_resources where job=?', (job['request_id'],))}
                self.assertIn(('plan', preview['plan_id']), owned)
                self.assertIn(('plan', review['plan_id']), owned)
                self.assertIn(('artifact', artifact_id), owned)
                self.assertTrue(any(kind == 'cache' and ident != job['request_id'] for kind, ident in owned))
                if create: run(w, 'brief', confirm=review['plan_id'])
                future = (datetime.fromisoformat(w.clock.now()) + timedelta(hours=1)).isoformat()
                path = w.store.db.execute('pragma database_list').fetchone()[2]
                w.store.close()
                w.store = w.engine.store = Ledger(path)
                with patch.object(w.clock, 'now', return_value=future):
                    with self.assertRaises(ChatChanged): Background(w.store, w.clock).status(job['request_id'])
                for kind, ident in owned:
                    if kind == 'artifact' and create and ident == artifact_id:
                        self.assertTrue(w.store.brief_artifact(ident)['text'])
                    elif kind == 'artifact':
                        with self.assertRaises(ChatChanged): w.store.brief_artifact(ident)
                    elif kind == 'plan':
                        with self.assertRaises(ChatChanged): w.store.brief_plan(ident)
                    else:
                        self.assertIsNone(w.store.brief_cache_get(ident))

    def test_opinion_intersects_source_and_writer_privacy(self):
        from dataclasses import replace
        for state in ('keep', 'skip'):
            with self.subTest(state=state), world_for('opinion-source-private-' + state) as w:
                w.pair(shared=1)
                private_turn = original(8)
                private_turn = replace(private_turn, messages=(replace(private_turn.messages[0], text='PRIVATE_CODEX_REPLY'),))
                private = w.seed('codex', [private_turn])[0]
                if state == 'keep':
                    w.store.keep_back(3, private)
                else:
                    w.store.skip(3, private, 'claude')
                tasks = scheduler(w)
                preview = run(w, 'ask', chat='claude:' + w.chats['claude'], tool='codex', question='Review')
                queued = run(w, 'ask', confirm=preview['plan_id'])
                tasks.pop()()
                prompt = w.adapters['codex'].runner.calls[-1][0]
                self.assertNotIn(private_turn.prompt.text, prompt)
                self.assertNotIn(private_turn.reply_text, prompt)
                with self.assertRaises(NotAvailable):
                    run(w, 'ask', chat='claude:' + w.chats['claude'], tool='codex',
                        turn=private, question='Review')
                addition = run(w, 'ask add', answer=queued['request_id'])
                self.assertTrue(run(w, 'ask add', confirm=addition['plan_id'])['applied'])

    def test_worker_boundary_excludes_process_and_construction_policy_from_commands(self):
        import ast
        from pathlib import Path
        forbidden = {'fork', 'setsid', 'closerange', 'dup2', '_exit', 'build'}
        for command in ('brief', 'ask', 'relaunch'):
            tree = ast.parse((Path(__file__).parents[2] / 'baton/cli/commands' / (command + '.py')).read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, 'id', '')
                    self.assertNotIn(name, forbidden)

    def test_brief_expiry_removes_cli_review_and_unreferenced_transcript(self):
        from pathlib import Path
        from baton.services.transcripts import FolderTranscripts
        from baton.ledger.sqlite_store import Ledger
        from baton.cli.plans import FilePlanStore
        for create in (False, True):
            with self.subTest(create=create), world_for('external-cleanup-' + str(create)) as w:
                w.pair()
                w.briefs.transcripts = FolderTranscripts(w.root / 'transcripts')
                w.engine.plans.store = FilePlanStore(w.root / 'plans')
                tasks = scheduler(w)
                preview = run(w, 'brief', link=3, to='codex')
                queued = run(w, 'brief', confirm=preview['plan_id'])
                tasks.pop()()
                review = run(w, 'brief', status=queued['request_id'])['result']
                artifact = w.store.brief_artifact(review['brief']['artifact_id'])
                transcript = Path(artifact['transcript_path'])
                self.assertTrue(transcript.exists())
                self.assertIsNotNone(w.engine.plans.store.load(review['plan_id']))
                if create: run(w, 'brief', confirm=review['plan_id'])
                path = w.store.db.execute('pragma database_list').fetchone()[2]
                w.store.close()
                w.store = w.engine.store = Ledger(path)
                future = (datetime.fromisoformat(w.clock.now()) + timedelta(hours=1)).isoformat()
                with patch.object(w.clock, 'now', return_value=future):
                    with self.assertRaises(ChatChanged): run(w, 'brief', status=queued['request_id'])
                self.assertIsNone(w.engine.plans.store.load(review['plan_id']))
                self.assertEqual(transcript.exists(), create)
