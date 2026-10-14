"""Runner deadlines never write late or cancelled results."""
import threading
import time
import unittest
from unittest.mock import patch

from baton.services.background import Background, BackgroundStopped
from baton.adapters.fake.tool import FakeBackgroundRunner
from tests.contract.test_fixtures import world_for


class ImmediateProcess:
    """Injected controller for canned runners; no native process is started."""
    def __init__(self, runner, prompt, folder):
        try:
            self.result = runner.ask(prompt, folder, read_only=True), None
        except Exception as error:
            self.result = None, error
        self.closed = False

    def poll(self, seconds):
        return self.result

    def close(self):
        self.closed = True


class WaitingProcess:
    """Injected running process records termination and reaping on close."""
    def __init__(self, *args):
        self.closed = False

    def poll(self, seconds):
        time.sleep(seconds)
        return None

    def close(self):
        self.closed = True


class BackgroundTests(unittest.TestCase):
    def setUp(self):
        from tests.fixtures.no_processes import no_processes
        self.process_attempts = self.enterContext(no_processes())
        self.enterContext(patch('os.setsid', side_effect=AssertionError('real setsid')))
        controller = patch('baton.services.background.RunnerProcess', ImmediateProcess)
        controller.start()
        self.addCleanup(controller.stop)

    def test_result_is_durable_and_read_only(self):
        with world_for('background-result') as w, patch('subprocess.run', side_effect=AssertionError('subprocess')):
            b = Background(w.store, w.clock)
            ident = b.create('ask', {'question': 'Review'})
            deadline = b.begin(ident)
            runner = FakeBackgroundRunner('answer')
            text = b.ask(ident, runner, 'safe', '/imaginary', deadline)
            b.finish(ident, {'answer': text})
            from baton.ledger.sqlite_store import Ledger
            path = w.store.db.execute('pragma database_list').fetchone()[2]
            w.store.close()
            w.store = w.engine.store = Ledger(path)
            self.assertEqual(Background(w.store, w.clock).status(ident)['result']['answer'], 'answer')
            self.assertEqual(runner.calls, [('safe', '/imaginary', True)])
            self.assertEqual(w.store.brief_artifact(ident + '_result'), {'answer': 'answer'})

    def test_deadline_terminates_and_reaps_injected_process(self):
        with world_for('background-deadline') as w:
            release = threading.Event()
            class Runner:
                cancelled = False
                def ask(self, *args, **kwargs):
                    release.wait(2)
                    return 'late'
                def cancel(self):
                    self.cancelled = True
            runner = Runner()
            process = WaitingProcess()
            b = Background(w.store, w.clock, seconds=.02, process_controller=lambda *args: process)
            ident = b.create('ask', {})
            started = time.monotonic()
            with self.assertRaises(BackgroundStopped):
                b.ask(ident, runner, 'prompt', '', b.begin(ident))
            self.assertLess(time.monotonic() - started, .5)
            self.assertTrue(process.closed)
            self.assertEqual(b.status(ident)['state'], 'deadline')
            release.set()
            with self.assertRaises(BackgroundStopped): b.finish(ident, {'answer': 'late'})

    def test_cancel_before_start_never_calls_runner(self):
        with world_for('background-cancel') as w:
            b = Background(w.store, w.clock)
            ident = b.create('ask', {})
            b.stop(ident)
            runner = FakeBackgroundRunner('answer')
            with self.assertRaises(BackgroundStopped): b.begin(ident)
            with self.assertRaises(BackgroundStopped): b.ask(ident, runner, 'prompt', '', time.monotonic() + 1)
            self.assertFalse(runner.calls)
            self.assertEqual(b.status(ident)['state'], 'cancelled')

    def test_cancellation_during_call_discards_answer(self):
        with world_for('background-active-cancel') as w:
            release = threading.Event()
            class Runner:
                def ask(self, *args, **kwargs):
                    release.wait(1)
                    return 'late'
            process = WaitingProcess()
            b = Background(w.store, w.clock, process_controller=lambda *args: process)
            ident = b.create('ask', {})
            deadline = b.begin(ident)
            original = b.status
            calls = []
            def status(token):
                calls.append(token)
                if len(calls) == 3:
                    w.store.brief_cache_put(token, {'request_id': token, 'state': 'cancelled'})
                return original(token)
            b.status = status
            try:
                with self.assertRaises(BackgroundStopped): b.ask(ident, Runner(), 'prompt', '', deadline)
                self.assertEqual(original(ident)['state'], 'cancelled')
                self.assertTrue(process.closed)
                with self.assertRaises(BackgroundStopped): b.finish(ident, {'answer': 'late'})
            finally:
                release.set()

    def test_one_hour_expiry(self):
        from baton.domain.errors import ChatChanged
        with world_for('background-expiry') as w:
            b = Background(w.store, w.clock)
            ident = b.create('ask', {})
            from datetime import datetime, timedelta
            now = (datetime.fromisoformat(w.clock.now()) + timedelta(hours=1)).isoformat()
            with patch.object(w.clock, 'now', return_value=now):
                with self.assertRaises(ChatChanged): b.status(ident)

    def test_poll_relaunch_expiry_without_worker(self):
        from datetime import datetime, timedelta
        with world_for('relaunch-poll-expiry') as w:
            b = Background(w.store, w.clock)
            expiry = (datetime.fromisoformat(w.clock.now()) + timedelta(minutes=5)).isoformat()
            ident = b.create('relaunch', {'plan': {'expires_at': expiry}})
            with patch.object(w.clock, 'now', return_value=expiry):
                value = b.status(ident)
                self.assertEqual(value['state'], 'completed')
                self.assertEqual(value['result']['error']['kind'], 'idle_timeout')

    def test_cleanup_persists_after_restart_and_preserves_referenced_artifact(self):
        from datetime import datetime, timedelta
        from baton.ledger.sqlite_store import Ledger
        from baton.domain.errors import ChatChanged
        with world_for('background-cleanup') as w:
            w.pair()
            b = Background(w.store, w.clock)
            w.store.save_brief_plan('initial-generation', 'generate', {'prompt': 'private prompt'})
            ident = b.create('brief', {'service_plan': 'initial-generation'})
            w.store.save_brief_artifact('owned', {'text': 'private generated brief'})
            w.store.save_brief_artifact('retained', {'text': 'canonical brief'})
            w.store.save_brief_plan('owned-plan', 'create', {'artifact_id': 'owned'})
            w.store.brief_cache_put('owned-cache', {'summary': 'private summary'})
            w.store.own_background_resources(ident, [('artifact', 'owned'), ('artifact', 'retained'),
                ('plan', 'owned-plan'), ('cache', 'owned-cache')])
            w.store.record_event(3, 'brief', 'codex', w.clock.now(), detail={'artifact_id': 'retained'})
            b.finish(ident, {'answer': 'private answer'})
            future = (datetime.fromisoformat(w.clock.now()) + timedelta(hours=1)).isoformat()
            path = w.store.db.execute('pragma database_list').fetchone()[2]
            w.store.close()
            w.store = w.engine.store = Ledger(path)
            with patch.object(w.clock, 'now', return_value=future):
                with self.assertRaises(ChatChanged): Background(w.store, w.clock).status(ident)
            w.store.close()
            w.store = w.engine.store = Ledger(path)
            for key in (ident, ident + '_result', 'owned'):
                with self.assertRaises(ChatChanged): w.store.brief_artifact(key)
            with self.assertRaises(ChatChanged): w.store.brief_plan('owned-plan')
            with self.assertRaises(ChatChanged): w.store.brief_plan('initial-generation')
            self.assertIsNone(w.store.brief_cache_get(ident))
            self.assertIsNone(w.store.brief_cache_get('owned-cache'))
            self.assertEqual(w.store.brief_artifact('retained')['text'], 'canonical brief')

    def test_supervised_controller_is_closed_on_error_and_success(self):
        with world_for('controller-close') as w:
            for error in (None, ValueError('runner failed')):
                controller = ImmediateProcess(FakeBackgroundRunner('answer', error), 'prompt', '')
                b = Background(w.store, w.clock, process_controller=lambda *args: controller)
                ident = b.create('ask', {})
                if error:
                    with self.assertRaises(ValueError): b.ask(ident, None, '', '', b.begin(ident))
                else:
                    self.assertEqual(b.ask(ident, None, '', '', b.begin(ident)), 'answer')
                self.assertTrue(controller.closed)

    def test_process_controller_terminates_group_and_reaps_before_close(self):
        from baton.services.runner_process import RunnerProcess
        from unittest.mock import Mock, call
        import signal
        process = RunnerProcess.__new__(RunnerProcess)
        process.process = Mock(pid=321)
        process.connection = Mock()
        with patch('baton.services.runner_process.os.killpg') as kill:
            process.close()
        self.assertEqual(kill.call_args_list, [call(321, signal.SIGTERM), call(321, signal.SIGKILL)])
        self.assertEqual(process.process.join.call_args_list, [call(.1), call()])
        process.connection.close.assert_called_once()

    def test_resource_ownership_is_connection_scoped_and_shared_cache_survives(self):
        from datetime import datetime, timedelta
        from baton.ledger.sqlite_store import Ledger
        with world_for('scoped-cleanup') as w:
            b = Background(w.store, w.clock)
            first = b.create('brief', {})
            w.store.brief_cache_put('external-cache', {'summary': 'external'})
            w.store.set_background_owner(first)
            w.store.save_brief_artifact('generated-artifact', {'text': 'owned'})
            w.store.save_brief_plan('generated-plan', 'create', {'artifact_id': 'generated-artifact'})
            w.store.brief_cache_put('shared-cache', {'summary': 'shared'})
            w.store.brief_cache_put('external-cache', {'summary': 'updated external'})
            w.store.set_background_owner(None)
            path = w.store.db.execute('pragma database_list').fetchone()[2]
            other = Ledger(path)
            other.brief_cache_put('other-command', {'summary': 'unrelated'})
            other.close()
            b.finish(first, {'answer': 'first'})
            later = (datetime.fromisoformat(w.clock.now()) + timedelta(minutes=30)).isoformat()
            with patch.object(w.clock, 'now', return_value=later):
                second = b.create('brief', {})
                w.store.set_background_owner(second)
                w.store.brief_cache_put('shared-cache', {'summary': 'shared'})
                w.store.set_background_owner(None)
                b.finish(second, {'answer': 'second'})
            future = (datetime.fromisoformat(w.clock.now()) + timedelta(hours=1)).isoformat()
            w.store.cleanup_background(future)
            self.assertEqual(w.store.brief_cache_get('shared-cache'), {'summary': 'shared'})
            self.assertEqual(w.store.brief_cache_get('external-cache'), {'summary': 'updated external'})
            self.assertEqual(w.store.brief_cache_get('other-command'), {'summary': 'unrelated'})
            from baton.domain.errors import ChatChanged
            with self.assertRaises(ChatChanged): w.store.brief_artifact('generated-artifact')
            with self.assertRaises(ChatChanged): w.store.brief_plan('generated-plan')
            w.store.cleanup_background((datetime.fromisoformat(future) + timedelta(minutes=30)).isoformat())
            self.assertIsNone(w.store.brief_cache_get('shared-cache'))

    def test_signal_permission_failure_still_terminates_reaps_and_closes(self):
        from baton.services.runner_process import RunnerProcess
        from unittest.mock import Mock, call
        process = RunnerProcess.__new__(RunnerProcess)
        process.process = Mock(pid=321)
        process.connection = Mock()
        with patch('baton.services.runner_process.os.killpg', side_effect=PermissionError):
            process.close()
        process.process.terminate.assert_called_once()
        process.process.kill.assert_called_once()
        self.assertEqual(process.process.join.call_args_list, [call(.1), call()])
        process.connection.close.assert_called_once()

    def test_direct_signal_failure_still_reaps_and_closes(self):
        from baton.services.runner_process import RunnerProcess
        from unittest.mock import Mock, call
        process = RunnerProcess.__new__(RunnerProcess)
        process.process = Mock(pid=321)
        process.process.terminate.side_effect = PermissionError
        process.process.kill.side_effect = ProcessLookupError
        process.connection = Mock()
        with patch('baton.services.runner_process.os.killpg', side_effect=PermissionError):
            process.close()
        self.assertEqual(process.process.join.call_args_list, [call(.1), call()])
        process.connection.close.assert_called_once()

    def test_worker_detachment_parent_returns_without_constructing(self):
        from baton.services.background_worker import dispatch_background
        from unittest.mock import Mock
        engine, work, construct = Mock(background_dispatch=None), Mock(), Mock()
        with patch('baton.services.background_worker.os.fork', return_value=42) as fork:
            dispatch_background(engine, work, construct)
        fork.assert_called_once()
        construct.assert_not_called()
        work.assert_not_called()

    def test_worker_detachment_child_closes_fresh_engine_even_on_failure(self):
        from baton.services.background_worker import dispatch_background
        from unittest.mock import Mock, call
        from contextlib import ExitStack
        for fail in (False, True):
            with self.subTest(fail=fail), ExitStack() as stack:
                engine = Mock(background_dispatch=None, root='/imaginary/baton')
                fresh = Mock()
                construct = Mock(return_value=fresh)
                work = Mock(side_effect=ValueError('worker failed') if fail else None)
                stack.enter_context(patch('baton.services.background_worker.os.fork', return_value=0))
                setsid = stack.enter_context(patch('baton.services.background_worker.os.setsid'))
                dispose = stack.enter_context(patch('baton.services.background_worker.os.closerange'))
                stack.enter_context(patch('baton.services.background_worker.resource.getrlimit', return_value=(256, 256)))
                stack.enter_context(patch('baton.services.background_worker.os.open', return_value=7))
                duplicate = stack.enter_context(patch('baton.services.background_worker.os.dup2'))
                close = stack.enter_context(patch('baton.services.background_worker.os.close'))
                leave = stack.enter_context(patch('baton.services.background_worker.os._exit', side_effect=RuntimeError('fake exit')))
                with self.assertRaisesRegex(RuntimeError, 'fake exit'):
                    dispatch_background(engine, work, construct)
                setsid.assert_called_once()
                dispose.assert_called_once_with(3, 256)
                self.assertEqual(duplicate.call_args_list, [call(7, 0), call(7, 1), call(7, 2)])
                close.assert_called_once_with(7)
                construct.assert_called_once_with(engine.root, adapters=engine.adapters, clock=engine.clock)
                work.assert_called_once_with(fresh)
                fresh.close.assert_called_once()
                leave.assert_called_once_with(0)

    def test_process_guard_rejects_uninjected_process_entry_points(self):
        import os
        import subprocess
        for entry in (os.fork, os.setsid, subprocess.Popen, subprocess.run):
            with self.subTest(entry=entry), self.assertRaises(AssertionError):
                entry()
        # The guard records these deliberate attempts; this test alone may make them.
        self.assertTrue(self.process_attempts)
        self.process_attempts.clear()
