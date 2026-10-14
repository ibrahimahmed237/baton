"""Native payload boundaries, timeouts and delivery safety on temporary fakes."""
import argparse
import io
import json
import subprocess
import sys
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch, Mock

from baton.adapters.fake import FakeAdapter
from baton.adapters.fake.facts import CLAUDE_LIKE, CODEX_LIKE, OPENCODE_LIKE, CURSOR_LIKE
from baton.adapters.claude.hooks import ClaudeHooks
from baton.adapters.codex.hooks import CodexHooks
from baton.adapters.opencode.hooks import OpenCodeHooks
from baton.adapters.cursor.hooks import CursorHooks
from baton.cli.wiring import build
from baton.domain.model import Message, Turn
from baton.hooks import HookCall, protocol
from baton.hooks.runtime import invoke
from baton.hooks.delivery import catch_up, notify
from baton.ports.clock import FixedClock

NATIVE = {'claude': (CLAUDE_LIKE, ClaudeHooks), 'codex': (CODEX_LIKE, CodexHooks),
          'opencode': (OPENCODE_LIKE, OpenCodeHooks), 'cursor': (CURSOR_LIKE, CursorHooks)}


def turn(name='work', at='2026-10-14T13:10:00Z'):
    return Turn(Message(name, 'prompt', name, at), (Message(name + '-reply', 'reply', 'done', at),))


class HookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.engines = []

    def tearDown(self):
        for engine in self.engines:
            engine.store.close()
        self.tmp.cleanup()

    def engine(self, tool='claude', mode='attached_history', target_turns=()):
        facts, native = NATIVE[tool]
        target = FakeAdapter(facts, tool)
        target.hooks = native.__new__(native)
        source_name = 'codex' if tool != 'codex' else 'claude'
        source = FakeAdapter(CODEX_LIKE, source_name)
        source_chat = source.build_chat([turn()])
        target_chat = target.build_chat(target_turns)
        target.set_condition(target_chat, open=True, app_running=True)
        engine = build(self.root / str(len(self.engines)), adapters={tool: target, source_name: source},
                       clock=FixedClock('2026-10-14T14:00:00Z'))
        link = engine.store.link({tool: target_chat, source_name: source_chat}, mode)
        self.engines.append(engine)
        return engine, target, target_chat, source, source_chat, link

    def test_exact_native_attach_and_idempotency_for_every_tool(self):
        for tool in NATIVE:
            with self.subTest(tool=tool):
                engine, target, chat, source, source_chat, link = self.engine(tool)
                with engine.command_lock():
                    result = catch_up(engine, tool, HookCall(chat, 'send-1'))
                    block = '<baton-catch-up>\n2026-10-14T13:10:00Z\nwork\n\ndone\n</baton-catch-up>'
                    notice = 'Baton attached 1 turn from ' + ('Claude' if tool == 'codex' else 'Codex') + ' to this message: "work".'
                    self.assertEqual(result, target.hooks.attach_reply(block, notice))
                    self.assertEqual(catch_up(engine, tool, HookCall(chat, 'send-1')), '')
                    self.assertEqual(engine.store.turns(link.id)[0].states[tool], 'attached')
                    self.assertEqual(target.reader.read(chat), [])
                    source.chats[source_chat].append(turn('later', '2026-10-14T13:20:00Z'))
                    self.assertEqual(catch_up(engine, tool, HookCall(chat, 'send-1')), '')
                    if tool != 'opencode':
                        self.assertTrue(catch_up(engine, tool, HookCall(chat, 'send-2')))
                    else:
                        self.assertEqual(catch_up(engine, tool, HookCall(chat, 'send-2')), '')

    def test_tool_calls_and_results_attach_as_public_text_and_private_reasoning_does_not(self):
        engine, target, chat, source, source_chat, link = self.engine('claude')
        source.chats[source_chat][0] = replace(turn(), messages=(
            Message('call', 'tool_call', tool='Read', tool_input={'path': 'safe.py'}),
            Message('result', 'tool_result', 'public output', call_id='call'),
            Message('private', 'reasoning', 'SECRET'), Message('reply', 'reply', 'done')))
        with engine.command_lock():
            result = catch_up(engine, 'claude', HookCall(chat, 'send'))
        self.assertIn('safe.py', result)
        self.assertIn('public output', result)
        self.assertNotIn('SECRET', result)

    def test_notice_setting_is_respected(self):
        engine, target, chat, *_ = self.engine('codex')
        engine.store.save_setting('notice_on_attach', False)
        with engine.command_lock():
            result = json.loads(catch_up(engine, 'codex', HookCall(chat, 't')))
        self.assertNotIn('systemMessage', result)

    def test_digest_is_first_and_each_turn_has_its_time(self):
        engine, target, chat, source, source_chat, link = self.engine('claude', 'full_copy', [turn('mine', '2026-10-14T13:00:00Z')])
        source.chats[source_chat].insert(0, target.chats[chat][0])
        ids = engine.store.record_turns(link.id, 'claude', target.reader.read(chat))
        engine.store.deliver(link.id, source.name, ids, 'shown', 'add', local_ids=['mine'])
        with engine.command_lock():
            result = json.loads(catch_up(engine, 'claude', HookCall(chat, 'send')))
        text = result['hookSpecificOutput']['additionalContext']
        self.assertTrue(text.startswith('<baton-catch-up>\nSince your last message here at 13:00, Codex did 1 turn'))
        self.assertLess(text.index('Since your'), text.index('2026-10-14T13:10:00Z'))

    def test_notify_never_writes_held_or_replying_chats(self):
        for tool in NATIVE:
            for values in ({'open': True, 'replying': False}, {'open': False, 'replying': True}):
                with self.subTest(tool=tool, values=values):
                    engine, target, chat, source, source_chat, link = self.engine(tool, 'full_copy')
                    target.set_condition(chat, **values)
                    with engine.command_lock():
                        result = notify(engine, source.name, HookCall(source_chat, 'done', 'turn_end'))
                    self.assertEqual(target.reader.read(chat), [])
                    self.assertEqual(result, {'synced': [], 'queued': [link.id], 'offers': []})
                    self.assertEqual(engine.store.history(link.id)[0].kind, 'turn_end')

    def test_notify_writes_only_safe_planned_adds_and_records_busy(self):
        engine, target, chat, source, source_chat, link = self.engine('codex', 'full_copy')
        target.set_condition(chat, open=False, replying=False, app_running=False)
        with engine.command_lock():
            self.assertEqual(notify(engine, 'codex', HookCall(chat, 'a', 'busy')), {'synced': [], 'queued': [link.id], 'offers': []})
            notify(engine, source.name, HookCall(source_chat, 'end'))
            self.assertEqual(target.reader.read(chat), [])
            self.assertEqual(notify(engine, 'codex', HookCall(chat, 'a', 'idle'))['synced'], [link.id])
            self.assertEqual(len(target.reader.read(chat)), 1)

    def test_paused_link_and_decision_do_not_attach(self):
        engine, target, chat, source, source_chat, link = self.engine()
        engine.store.set_paused(link.id, True)
        with engine.command_lock():
            self.assertEqual(catch_up(engine, 'claude', HookCall(chat, 'a')), '')
        engine.store.set_paused(link.id, False)
        target.chats[chat].append(turn('conflict'))
        with engine.command_lock():
            self.assertEqual(catch_up(engine, 'claude', HookCall(chat, 'a')), '')

    def test_slow_build_and_errors_are_bounded_with_native_nothing(self):
        for tool in NATIVE:
            args = argparse.Namespace(tool=tool, chat='fake', turn_id=None, event=None)
            for factory in (lambda: time.sleep(1), lambda: (_ for _ in ()).throw(OSError('broken'))):
                started = time.monotonic()
                with patch('baton.hooks.runtime.logger'):
                    self.assertEqual(invoke(args, prompt=True, engine_factory=factory,
                                            stdin=io.StringIO(), seconds=0.04), protocol(tool).nothing(True))
                self.assertLess(time.monotonic() - started, 0.3)

    def test_other_process_holding_build_lock_is_inside_deadline(self):
        engine, *_ = self.engine()
        script = "import fcntl,sys,time; f=open(sys.argv[1],'r+'); fcntl.flock(f,fcntl.LOCK_EX); print('ready',flush=True); time.sleep(5)"
        process = subprocess.Popen([sys.executable, '-c', script, str(engine.root / 'command.lock')], stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(process.stdout.readline().strip(), 'ready')
            args = argparse.Namespace(tool='claude', chat='fake', turn_id=None, event=None)
            started = time.monotonic()
            with patch('baton.hooks.runtime.logger'):
                result = invoke(args, prompt=True, engine_factory=lambda: build(engine.root, adapters={}), seconds=0.08)
            self.assertEqual(result, '')
            self.assertLess(time.monotonic() - started, 0.4)
        finally:
            process.terminate()
            process.wait()
            process.stdout.close()

    def test_malformed_payload_never_builds_engine(self):
        for tool in NATIVE:
            for raw in ('broken', '[]', '{"session_id": 3}'):
                args = argparse.Namespace(tool=tool, chat=None, turn_id=None, event=None)
                factory = Mock()
                with self.assertLogs('baton.hooks.runtime', 'WARNING'):
                    result = invoke(args, prompt=True, stdin=io.StringIO(raw), engine_factory=factory)
                factory.assert_not_called()
                self.assertEqual(result, protocol(tool).nothing(True))

    def test_failed_notify_is_only_queued_with_failure_note(self):
        engine, target, chat, source, source_chat, link = self.engine('codex', 'full_copy')
        target.set_condition(chat, open=False, app_running=False)
        with engine.command_lock(), patch.object(target.writer, 'add', side_effect=OSError()):
            result = notify(engine, 'claude', HookCall(source_chat, 'done', 'turn_end'))
        self.assertEqual(result['synced'], [])
        self.assertEqual(result['queued'], [link.id])
        self.assertEqual(result['offers'][0]['id'], 'hook.delivery_failed')
        self.assertIn('remain queued', result['offers'][0]['text'])

class ReviewRegressions(unittest.TestCase):
    def test_cleanup_and_logging_share_work_budget(self):
        from contextlib import nullcontext
        from types import SimpleNamespace
        args = argparse.Namespace(tool='codex', chat='fake', turn_id=None, event=None)
        for phase in ('cleanup', 'logging'):
            store = SimpleNamespace(close=lambda: time.sleep(1) if phase == 'cleanup' else None)
            engine = SimpleNamespace(store=store, command_lock=nullcontext,
                                     adapter=lambda tool: SimpleNamespace(state=object()))
            with patch('baton.hooks.runtime.delivery.notify', side_effect=OSError()), \
                 patch('baton.hooks.runtime.logger.warning', side_effect=lambda *a, **k: time.sleep(1) if phase == 'logging' else None):
                started = time.monotonic()
                self.assertEqual(invoke(args, prompt=False, engine_factory=lambda: engine,
                                        seconds=.05, stdin=io.StringIO()), '{}')
                self.assertLess(time.monotonic() - started, .10)

    def test_cleanup_failure_discards_successful_context(self):
        from contextlib import nullcontext
        from types import SimpleNamespace
        engine = SimpleNamespace(store=SimpleNamespace(close=Mock(side_effect=OSError())),
                                 command_lock=nullcontext,
                                 adapter=lambda tool: SimpleNamespace(state=object()))
        args = argparse.Namespace(tool='cursor', chat='fake', turn_id=None, event=None)
        with patch('baton.hooks.runtime.delivery.catch_up', return_value='context'), \
             patch('baton.hooks.runtime.logger'):
            self.assertEqual(invoke(args, prompt=True, engine_factory=lambda: engine,
                                    stdin=io.StringIO()), protocol('cursor').nothing(True))

    def test_expired_work_does_not_start_cleanup(self):
        from contextlib import nullcontext
        from types import SimpleNamespace
        close = Mock(side_effect=lambda: time.sleep(1))
        engine = SimpleNamespace(store=SimpleNamespace(close=close), command_lock=nullcontext,
                                 adapter=lambda tool: SimpleNamespace(state=object()))
        args = argparse.Namespace(tool='codex', chat='fake', turn_id=None, event=None)
        with patch('baton.hooks.runtime.delivery.notify', side_effect=lambda *a: time.sleep(1)):
            started = time.monotonic()
            self.assertEqual(invoke(args, prompt=False, engine_factory=lambda: engine,
                                    seconds=.05, stdin=io.StringIO()), '{}')
            self.assertLess(time.monotonic() - started, .10)
        close.assert_not_called()

    def test_sqlite_busy_waits_fit_tiny_hook_budget(self):
        import sqlite3
        from baton.ledger.sqlite_store import Ledger
        from baton.adapters.cursor.locator import CursorLocator
        from tests.fixtures.cursor import build as fx
        args = argparse.Namespace(tool='codex', chat='fake', turn_id=None, event=None)
        def opened_ledger(path):
            value = Ledger.__new__(Ledger)
            try:
                value.__init__(path)
                return value
            except BaseException:
                if hasattr(value, 'db'):
                    value.db.close()
                raise
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            ledger = root / 'ledger.sqlite'
            Ledger(str(ledger)).close()
            fx.build(root, [])
            locator = CursorLocator(root)
            for path, factory in ((ledger, lambda: opened_ledger(str(ledger))),
                                  (locator.state_db, lambda: locator.headers())):
                blocker = sqlite3.connect(path)
                try:
                    blocker.execute('BEGIN EXCLUSIVE')
                    started = time.monotonic()
                    with patch('baton.hooks.runtime.logger'):
                        self.assertEqual(invoke(args, prompt=True, engine_factory=factory,
                                                seconds=.05, stdin=io.StringIO()), '{}')
                    self.assertLess(time.monotonic() - started, .10)
                finally:
                    blocker.rollback()
                    blocker.close()

    def test_cursor_native_observations_survive_rebuild_and_unknown_refuses_close(self):
        from baton.adapters.cursor import CursorAdapter
        from baton.domain.errors import ChatReplying
        from tests.fixtures.cursor import build as fx
        from tests.fixtures.no_processes import no_processes
        from types import SimpleNamespace
        from contextlib import nullcontext
        with tempfile.TemporaryDirectory() as folder, no_processes():
            root = Path(folder).resolve()
            chat = fx.build(root, [])
            process = fx.FixtureProcess(root)
            process.is_running = True
            adapter = CursorAdapter(root, process=process, project_root=root / 'project')
            self.assertEqual(adapter.state.replying(chat), 'unknown')
            self.assertEqual(adapter.state.condition(chat).replying, 'unknown')
            with self.assertRaises(ChatReplying):
                adapter.app.close()
            self.assertTrue(process.is_running)
            self.assertEqual(process.quits, 0)
            engine = SimpleNamespace(adapter=lambda tool: adapter, command_lock=nullcontext,
                                     store=SimpleNamespace(close=lambda: None))
            args = argparse.Namespace(tool='cursor', chat=None, turn_id=None, event=None)
            for prompt, event, expected in ((True, 'beforeSubmitPrompt', True), (False, 'stop', False)):
                with patch('baton.hooks.runtime.delivery.catch_up', return_value=''), \
                     patch('baton.hooks.runtime.delivery.notify', return_value={'synced': [], 'queued': [], 'offers': []}):
                    invoke(args, prompt=prompt, engine_factory=lambda: engine,
                           stdin=io.StringIO(json.dumps({'conversation_id': chat, 'hook_event_name': event})))
                rebuilt = CursorAdapter(root, process=process, project_root=root / 'project')
                self.assertIs(rebuilt.state.replying(chat), expected)

    def test_opencode_installs_corrected_generator_with_quoted_executable(self):
        from baton.adapters.opencode import OpenCodeAdapter
        from tests.fixtures.no_processes import no_processes
        with tempfile.TemporaryDirectory() as folder, no_processes(), patch.object(Path, 'home', return_value=Path(folder)):
            adapter = OpenCodeAdapter(Path(folder), hook_entrypoints_available=lambda: True)
            adapter.hooks.executable = '/temporary folder/baton'
            adapter.hooks.install()
            text = adapter.hooks.path.read_text()
            self.assertIn('execFile("/temporary folder/baton",', text)
            self.assertIn('"--turn-id", messageID', text)
            self.assertIn('"--event", name', text)
            self.assertIn('timeout: 2000', text)
            self.assertNotIn('timeout: 5000', text)
            self.assertTrue(adapter.hooks.path.is_relative_to(Path(folder).resolve()))

    def test_readiness_checks_real_registry_and_installs_stay_inside_temp_home(self):
        from baton.cli.commands import CommandRegistry
        from baton.cli.tools import hook_entrypoints_available
        from tests.fixtures.no_processes import no_processes
        self.assertTrue(hook_entrypoints_available())
        with patch('baton.cli.commands.discover', return_value=CommandRegistry()):
            self.assertFalse(hook_entrypoints_available())
        with tempfile.TemporaryDirectory() as folder, no_processes(), patch.object(Path, 'home', return_value=Path(folder)):
            root = Path(folder).resolve()
            engine = build(root / 'baton', tools_home=root / 'tools')
            try:
                for adapter in engine.adapters.values():
                    try:
                        adapter.hooks.install()
                    except Exception as error:
                        from baton.domain.errors import NotAvailable
                        if not isinstance(error, NotAvailable):
                            raise
                for path in root.rglob('*'):
                    self.assertTrue(path.resolve().is_relative_to(root.resolve()))
            finally:
                engine.close()


class SQLiteHookBudgetTests(unittest.TestCase):
    def test_held_native_databases_return_nothing_within_50ms_budget(self):
        from contextlib import nullcontext
        from types import SimpleNamespace
        import sqlite3
        from baton.adapters.codex import CodexAdapter
        from baton.adapters.cursor import CursorAdapter
        from baton.adapters.opencode import OpenCodeAdapter
        from tests.fixtures.codex import build as codex_fx
        from tests.fixtures.cursor import build as cursor_fx
        from tests.fixtures.opencode import build as opencode_fx
        timings = {}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            codex_chat = codex_fx.build(root / 'codex', [turn()])
            cursor_chat = cursor_fx.build(root / 'cursor', [turn()])
            opencode_fx.create_database(root / 'opencode')
            opencode_chat = opencode_fx.build(root / 'opencode', [turn()])
            codex = CodexAdapter(root / 'codex', allowed_chat_ids=(codex_chat,))
            cursor = CursorAdapter(root / 'cursor', allowed_chat_ids=(cursor_chat,))
            opencode = OpenCodeAdapter(root / 'opencode', allowed_chat_ids=(opencode_chat,))
            def history():
                if codex.state.index.read_offset(codex_chat) is None: raise ValueError('unreadable')
            def ledger():
                from baton.ledger.sqlite_store import Ledger
                with_store = Ledger(root / 'ledger.sqlite')
                with_store.close()
            ledger()
            probes = [
                ('codex-locator', 'codex', codex, codex_chat, codex.locator.state_db, lambda: codex.locator.row(codex_chat)),
                ('codex-state', 'codex', codex, codex_chat, codex.locator.state_db, codex.state._threads_columns_ok),
                ('codex-history', 'codex', codex, codex_chat, codex.locator.history_db, history),
                ('cursor', 'cursor', cursor, cursor_chat, cursor_fx.db_path(root / 'cursor'), cursor.locator.chats),
                ('opencode', 'opencode', opencode, opencode_chat, opencode.locator.database, opencode.locator.chats),
                ('ledger', 'codex', codex, codex_chat, root / 'ledger.sqlite', ledger),
            ]
            for name, tool, adapter, chat, path, probe in probes:
                with self.subTest(database=name):
                    lock = sqlite3.connect(path)
                    try:
                        lock.execute('PRAGMA journal_mode=DELETE')
                        lock.execute('BEGIN EXCLUSIVE')
                        engine = SimpleNamespace(adapter=lambda name: adapter, command_lock=nullcontext,
                                                 store=SimpleNamespace(close=lambda: None))
                        args = argparse.Namespace(tool=tool, chat=chat, turn_id='prompt', event=None)
                        def deliver(*args):
                            probe()
                            return 'unsafe attachment'
                        connections = []
                        timeouts = []
                        connect = sqlite3.connect
                        def tracked(*args, **kwargs):
                            timeouts.append(kwargs.get('timeout', 5))
                            db = connect(*args, **kwargs)
                            connections.append(db)
                            return db
                        started = time.monotonic()
                        with patch('sqlite3.connect', side_effect=tracked), patch('baton.hooks.runtime.delivery.catch_up', side_effect=deliver), patch('baton.hooks.runtime.logger.warning'):
                            result = invoke(args, prompt=True, engine_factory=lambda: engine, stdin=io.StringIO(), seconds=.05)
                        elapsed = time.monotonic() - started
                        for connection in connections: connection.close()
                        self.assertTrue(connections, name)
                        timings[name] = round(elapsed * 1000, 2)
                        self.assertEqual(result, protocol(tool).nothing(True))
                        self.assertLess(elapsed, .10, timings)
                        self.assertTrue(all(timeout <= .05 for timeout in timeouts), timeouts)
                    finally:
                        lock.rollback()
                        lock.close()
        print('SQLite hook milliseconds:', timings)

    def test_sqlite_timeout_keeps_defaults_outside_hooks_and_bounds_remaining_budget(self):
        from baton.hooks.deadline import deadline, sqlite_timeout
        self.assertEqual(sqlite_timeout(), 5)
        self.assertEqual(sqlite_timeout(.1), .1)
        with deadline(.05):
            self.assertLessEqual(sqlite_timeout(), .01)
            time.sleep(.043)
            self.assertLess(sqlite_timeout(), .01)
