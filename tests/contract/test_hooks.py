"""Payload in, exact native stdout out; tests never use native chat files."""
import argparse
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from baton.cli.main import main
from baton.cli.wiring import build
from baton.hooks import protocol
from baton.hooks.runtime import invoke, dispatch
from tests.unit import test_hooks as fixtures
NATIVE = fixtures.NATIVE


class PayloadContract(unittest.TestCase):
    setUp = fixtures.HookTests.setUp
    tearDown = fixtures.HookTests.tearDown
    engine = fixtures.HookTests.engine
    def test_native_payload_in_exact_stdout_out(self):
        for tool in NATIVE:
            engine, target, chat, *_ = self.engine(tool)
            native = {'claude': {'session_id': chat, 'prompt_id': 'send'},
                      'codex': {'session_id': chat, 'turn_id': 'send'},
                      'cursor': {'conversation_id': chat, 'generation_id': 'send'},
                      'opencode': {'sessionID': chat, 'message': {'id': 'send'}}}[tool]
            args = argparse.Namespace(tool=tool, chat=None, turn_id=None, event=None)
            # Reopen the same isolated ledger after each invocation.
            factory = lambda: build(engine.root, adapters=engine.adapters, clock=engine.clock)
            out = invoke(args, prompt=True, stdin=io.StringIO(json.dumps(native)), engine_factory=factory)
            block = '<baton-catch-up>\n2026-10-14T13:10:00Z\nwork\n\ndone\n</baton-catch-up>'
            notice = 'Baton attached 1 turn from ' + ('Claude' if tool == 'codex' else 'Codex') + ' to this message: "work".'
            self.assertEqual(out, target.hooks.attach_reply(block, notice))
            self.assertEqual(invoke(args, prompt=True, stdin=io.StringIO(json.dumps(native)), engine_factory=factory), protocol(tool).nothing(True))
            self.assertEqual(invoke(args, prompt=False, stdin=io.StringIO(json.dumps(native)), engine_factory=factory), target.hooks.turn_end_reply())

    def test_registered_commands_do_not_double_lock_or_close_the_dispatchers_store(self):
        for tool in NATIVE:
            engine, target, chat, *_ = self.engine(tool)
            factory = lambda: build(engine.root, adapters=engine.adapters, clock=engine.clock)
            out = io.StringIO()
            result = main(['catch-up', '--tool', tool, '--chat', chat, '--turn-id', 'send'], engine_factory=factory, stdout=out)
            self.assertEqual(result, 0)
            self.assertIn('<baton-catch-up>', out.getvalue())
            out = io.StringIO()
            self.assertEqual(main(['notify', '--tool', tool, '--chat', chat, '--event', 'idle'], engine_factory=factory, stdout=out), 0)
            self.assertEqual(out.getvalue(), target.hooks.turn_end_reply())


class InstalledBoundary(unittest.TestCase):
    def test_early_dispatch_handles_factory_failure_and_native_empty(self):
        for tool in NATIVE:
            out = io.StringIO()
            with self.assertLogs('baton.hooks.runtime', 'WARNING'):
                code = dispatch(['notify', '--tool', tool, '--chat', 'fake'], stdout=out,
                    engine_factory=lambda: (_ for _ in ()).throw(OSError('broken')))
            self.assertEqual((code, out.getvalue()), (0, protocol(tool).nothing(False)))

    def test_early_dispatch_leaves_ordinary_cli_commands_alone(self):
        out = io.StringIO()
        self.assertIsNone(dispatch(['links', '--json'], stdout=out, engine_factory=lambda: self.fail('built')))
        self.assertEqual(out.getvalue(), '')

    def test_installed_modules_print_native_empty_for_missing_chat_and_bad_stdin(self):
        with tempfile.TemporaryDirectory() as folder:
            env = {**os.environ, 'BATON_HOME': folder}
            for tool in NATIVE:
                for module, prompt in (('prompt', True), ('turn_end', False)):
                    for raw in ('{}', 'not json'):
                        completed = subprocess.run([sys.executable, '-m', 'baton.hooks.' + module, '--tool', tool],
                            input=raw, text=True, capture_output=True, timeout=3, env=env)
                        self.assertEqual(completed.returncode, 0)
                        self.assertEqual(completed.stdout, protocol(tool).nothing(prompt))

    def test_opencode_event_payloads_keep_busy_idle_and_message_identity(self):
        native = protocol('opencode')
        self.assertEqual(native.parse({'sessionID': 'chat', 'message': {'id': 'message'}}).turn, 'message')
        for event, expected in (({'type': 'session.idle', 'properties': {'sessionID': 'chat'}}, 'idle'),
                                ({'type': 'session.status', 'properties': {'info': {'sessionID': 'chat'}, 'status': {'type': 'busy'}}}, 'busy')):
            call = native.parse({'event': event})
            self.assertEqual((call.chat, call.event), ('chat', expected))

class WholeCLIReview(unittest.TestCase):
    def test_main_factory_failure_uses_native_response_before_discovery(self):
        from unittest.mock import Mock
        for tool in NATIVE:
            factory = Mock(side_effect=OSError('broken'))
            out = io.StringIO()
            with patch('baton.cli.main.discover', side_effect=AssertionError('ordinary startup')), \
                 patch('baton.hooks.runtime.logger'):
                code = main(['notify', '--tool', tool, '--chat', 'fake'], engine_factory=factory, stdout=out)
            factory.assert_called_once()
            self.assertEqual((code, out.getvalue()), (0, protocol(tool).nothing(False)))

    def test_main_held_lock_returns_native_response_within_deadline(self):
        import time
        from baton.hooks.deadline import deadline
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            engine = build(root, adapters={})
            engine.close()
            script = "import fcntl,sys,time; f=open(sys.argv[1],'r+'); fcntl.flock(f,fcntl.LOCK_EX); print('ready',flush=True); time.sleep(.3)"
            process = subprocess.Popen([sys.executable, '-c', script, str(root / 'command.lock')], stdout=subprocess.PIPE, text=True)
            try:
                self.assertEqual(process.stdout.readline().strip(), 'ready')
                out = io.StringIO()
                started = time.monotonic()
                with patch('baton.hooks.runtime.deadline', side_effect=lambda seconds=2: deadline(min(seconds, .05))):
                    code = main(['catch-up', '--tool', 'cursor', '--chat', 'fake'],
                                engine_factory=lambda: build(root, adapters={}), stdout=out)
                self.assertEqual((code, out.getvalue()), (0, protocol('cursor').nothing(True)))
                self.assertLess(time.monotonic() - started, .10)
            finally:
                process.wait(timeout=2)
                process.stdout.close()

    def test_notify_json_returns_frozen_contract_object(self):
        from types import SimpleNamespace
        from contextlib import nullcontext
        value = {'synced': [1], 'queued': [2], 'offers': [{'id': 'offer'}]}
        engine = SimpleNamespace(adapter=lambda tool: SimpleNamespace(state=object()),
                                 command_lock=nullcontext, store=SimpleNamespace(close=lambda: None))
        out = io.StringIO()
        with patch('baton.hooks.runtime.delivery.notify', return_value=value):
            code = main(['notify', '--json', '--tool', 'codex', '--chat', 'fake'],
                        engine_factory=lambda: engine, stdout=out)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue()), value)

    def test_output_stays_inside_absolute_budget(self):
        import time
        from baton.hooks.deadline import deadline
        class SlowOutput:
            def write(self, text):
                time.sleep(1)
            def flush(self):
                time.sleep(1)
        started = time.monotonic()
        with patch('baton.hooks.runtime.deadline', side_effect=lambda seconds=2: deadline(min(seconds, .05))), \
             patch('baton.hooks.runtime.logger'):
            code = main(['notify', '--tool', 'codex', '--chat', 'fake'],
                        engine_factory=lambda: (_ for _ in ()).throw(OSError()), stdout=SlowOutput())
        self.assertEqual(code, 0)
        self.assertLess(time.monotonic() - started, .10)
