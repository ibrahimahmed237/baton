"""Cursor adapter contract and safety tests; temporary homes and fake controls only."""
from contextlib import closing
from dataclasses import asdict
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from baton.adapters.cursor import CursorAdapter
from baton.domain.errors import AppMustBeClosed, ChatChanged, ChatReplying, NotAvailable, UnknownFormat
from baton.domain.model import Message, Turn, PROMPT, REPLY, TOOL_TEXT
from baton.ports.tool import WriteReceipt
from tests.adapters.suite import AdapterSuite, turns
from tests.fixtures.cursor import build as fx


def home(test):
    temporary = tempfile.TemporaryDirectory()
    test.addCleanup(temporary.cleanup)
    return Path(temporary.name).resolve()


def adapter(root, **options):
    options.setdefault('allowed_chat_ids', ('cursor-fixture',))
    options.setdefault('project_root', root / 'project')
    options.setdefault('now', fx.tick_clock())
    return CursorAdapter(root, **options)


class CursorStorage(unittest.TestCase):
    def setUp(self):
        self.root = home(self)
        self.chat = fx.build(self.root, turns(), transcript=True)
        self.process = fx.FixtureProcess(self.root)
        self.adapter = adapter(self.root, process=self.process)

    def snapshot(self):
        with closing(self.adapter.locator.connect()) as db:
            return (db.execute('SELECT * FROM composerHeaders ORDER BY composerId').fetchall(),
                    db.execute('SELECT * FROM cursorDiskKV ORDER BY key').fetchall(),
                    self.adapter.locator.transcript(self.chat).read_bytes())

    def test_place_with_transcript_keeps_old_text_and_native_order(self):
        middle = Turn(Message('middle', PROMPT, 'placed'), (Message('middle-reply', REPLY, 'answer'),))
        before = self.snapshot()
        result = self.adapter.writer.place(self.chat, [middle], 'p2')
        self.assertEqual(self.adapter.reader.read(self.chat), [turns()[0], middle, *turns()[1:]])
        self.adapter.writer.take_back(result.receipt)
        self.assertEqual(self.snapshot(), before)

    def test_transaction_failure_after_rows_written_restores_whole_db(self):
        before = self.snapshot()
        original = self.adapter.writer._replace
        def fail(db, ident, value):
            original(db, ident, value)
            raise OSError('injected disk failure')
        with patch.object(self.adapter.writer, '_replace', fail):
            with self.assertRaises(OSError):
                self.adapter.writer.rename(self.chat, 'new')
        self.assertEqual(self.snapshot(), before)

    def test_failed_intent_save_never_writes_database(self):
        before = self.snapshot()
        with patch('baton.adapters.cursor.writer.save_json', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.adapter.writer.add(self.chat, [Turn(Message('next', PROMPT, 'more'))])
        self.assertEqual(before, self.snapshot())

    def test_blob_and_whitespace_values_restored_byte_for_byte(self):
        key = 'composerData:' + self.chat
        raw = fx.run_sql(self.root, 'SELECT value FROM cursorDiskKV WHERE key=?', (key,))[0][0]
        fx.run_sql(self.root, 'UPDATE cursorDiskKV SET value=? WHERE key=?',
                   (('  ' + raw + '\n').encode(), key))
        header = fx.run_sql(self.root, 'SELECT value FROM composerHeaders WHERE composerId=?', (self.chat,))[0][0]
        fx.run_sql(self.root, 'UPDATE composerHeaders SET value=? WHERE composerId=?',
                   ((' ' + header).encode(), self.chat))
        before = self.snapshot()
        result = self.adapter.writer.rename(self.chat, 'new')
        self.adapter.writer.take_back(result.receipt)
        self.assertEqual(before, self.snapshot())

    def test_duplicate_ids_refused_before_db_changes(self):
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.adapter.writer.add(self.chat, turns()[:1])
        self.assertEqual(before, self.snapshot())

    def test_older_display_shape_and_missing_bubbles_block_writes(self):
        fx.run_sql(self.root, 'DELETE FROM cursorDiskKV WHERE key=?', ('bubbleId:' + self.chat + ':p1',))
        self.assertFalse(self.adapter.state.format_version().known)
        before = self.snapshot()
        with self.assertRaises(UnknownFormat):
            self.adapter.writer.rename(self.chat, 'new')
        self.assertEqual(before, self.snapshot())

    def test_runner_signed_in_uses_read_only_ephemeral_print_mode(self):
        calls = []
        def command(args, **options):
            calls.append((args, options))
            return SimpleNamespace(returncode=0, stdout='Signed in' if args[-1] == 'status' else 'answer')
        value = adapter(self.root, command=command)
        self.assertEqual(value.runner.ask('question', '/fixture/project'), 'answer')
        args, options = calls[-1]
        self.assertEqual(args, ['cursor-agent', '-p', '--mode', 'ask', '--output-format', 'text', '--', 'question'])
        self.assertEqual(options['cwd'], '/fixture/project')
        with self.assertRaises(NotAvailable):
            value.runner.ask('question', '/fixture/project', read_only=False)

    def test_native_hook_observations_persist_busy_stop_and_tokens(self):
        self.process.is_running = True
        self.adapter.state.observe({'conversation_id': self.chat, 'hook_event_name': 'beforeSubmitPrompt'})
        self.assertTrue(self.adapter.state.condition(self.chat).replying)
        restarted = adapter(self.root, process=self.process)
        self.assertTrue(restarted.state.condition(self.chat).replying)
        restarted.state.observe({'conversation_id': self.chat, 'hook_event_name': 'stop',
                                 'status': 'completed', 'tokens': {'input': 123, 'output': 10}})
        self.assertFalse(restarted.state.condition(self.chat).replying)
        self.assertEqual(restarted.state.observations()[self.chat]['tokens'], {'input': 123, 'output': 10})
        with self.assertRaises(NotAvailable):
            restarted.state.observe({'conversation_id': '../outside', 'hook_event_name': 'stop'})

    def test_transcript_failure_reason_exposes_limit_without_reset_time(self):
        path = self.adapter.locator.transcript(self.chat)
        path.write_text(path.read_text() + json.dumps({'type': 'turn_ended', 'failure_reason': 'rate_limit'}) + '\n')
        usage = self.adapter.reader.usage(self.chat)
        self.assertTrue(usage.limit_reached)
        self.assertIsNone(usage.limit_resets_at)

    def test_readiness_checks_never_spawn_a_runner(self):
        def refuse(*args, **kwargs):
            raise AssertionError('preview spawned a runner')
        value = adapter(self.root, command=refuse)
        with patch('baton.adapters.cursor.runner.which', return_value='/fixture/cursor-agent'):
            self.assertTrue(value.runner.ready().ok)
        self.assertFalse(CursorAdapter(self.root).runner.ready().ok)

    def test_injected_rollback_root_keeps_receipts_under_baton_storage(self):
        owned = self.root / 'baton-storage/rollback/cursor'
        value = adapter(self.root, process=self.process, rollback_root=owned)
        result = value.writer.rename(self.chat, 'new')
        self.assertTrue((owned / (result.receipt.data['token'] + '.json')).is_file())
        value.writer.take_back(result.receipt)
        self.assertEqual(value.locator.name(self.chat), 'fixture')

    def test_database_wal_symlink_refused_before_connect(self):
        target = self.root / 'outside'
        target.write_bytes(b'private')
        Path(str(fx.db_path(self.root)) + '-wal').symlink_to(target)
        with self.assertRaises(NotAvailable):
            self.adapter.locator.data(self.chat)
        self.assertEqual(target.read_bytes(), b'private')

    def test_app_start_during_publication_rolls_back_transaction(self):
        before = self.snapshot()
        original = self.adapter.writer._replace
        def app_starts(db, ident, value):
            original(db, ident, value)
            self.process.is_running = True
        with patch.object(self.adapter.writer, '_replace', app_starts):
            with self.assertRaises(AppMustBeClosed):
                self.adapter.writer.rename(self.chat, 'new')
        self.assertEqual(self.snapshot(), before)

    def test_usage_percent_derives_context_size_and_commands_count_calls_only(self):
        value = fx.data(self.root, self.chat)
        del value['contextTokenLimit']
        fx.put_data(self.root, self.chat, value)
        self.assertEqual(self.adapter.reader.usage(self.chat).size, 200000)
        from baton.domain.model import TOOL_CALL, TOOL_RESULT
        turn = Turn(Message('prompt', PROMPT, 'work'), (
            Message('shell', TOOL_CALL, tool='run_terminal_cmd', tool_input={'command': 'true'}),
            Message('shell-result', TOOL_RESULT, 'done', call_id='shell'),
            Message('edit', TOOL_CALL, tool='edit', tool_input={'file_path': 'changed.py'})))
        self.assertEqual(self.adapter.reader.commands_run(turn), 1)
        self.assertEqual(self.adapter.reader.files_changed(turn), ['changed.py'])

    def test_default_controls_cannot_start_replace_or_signal_any_process(self):
        from tests.fixtures.no_processes import no_processes
        with no_processes():
            value = CursorAdapter(self.root)
            value.locator.chats()
            value.reader.read(self.chat)
            value.state.condition(self.chat)
            value.runner.available()
            value.runner.ready()
            self.assertFalse(value.app.running())
            for call in (lambda: value.app.open(None, 'folder'), lambda: value.app.close(),
                         lambda: value.runner.ask('question', 'folder')):
                with self.assertRaises(NotAvailable):
                    call()

    def test_shape_check_covers_hidden_chats_and_reports_any_new_version(self):
        other = fx.build(self.root, turns(), ident='hidden')
        value = fx.data(self.root, self.chat)
        value['_v'] = 19
        fx.put_data(self.root, self.chat, value)
        self.assertTrue(self.adapter.state.format_version().new_version)
        self.assertEqual(self.adapter.state.format_version().version, '19')
        header = json.loads(fx.run_sql(self.root, 'SELECT value FROM composerHeaders WHERE composerId=?', (other,))[0][0])
        header['isArchived'] = True
        fx.run_sql(self.root, 'UPDATE composerHeaders SET value=? WHERE composerId=?', (json.dumps(header), other))
        value = fx.data(self.root, other)
        del value['conversationState']
        fx.put_data(self.root, other, value)
        self.assertNotIn(other, [ref.id for ref in self.adapter.locator.chats()])
        with self.assertRaises(UnknownFormat):
            self.adapter.writer.rename(self.chat, 'new')
