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


class CursorSuite(AdapterSuite, unittest.TestCase):
    def make_adapter(self):
        self.root = home(self)
        self.process = fx.FixtureProcess(self.root)
        result = adapter(self.root, process=self.process)
        result.hooks.install()
        return result

    def test_facts_match_behaviour(self):
        # This one shared contract check explicitly simulates future C4 readiness.
        self.adapter.hooks.entrypoints_available = lambda: True
        self.adapter.hooks.install()
        super().test_facts_match_behaviour()

    def build_chat(self, values):
        return fx.build(self.root, values)

    def insert_text(self, chat, message):
        fx.insert_text(self.root, chat, message)

    def set_condition(self, chat, **values):
        if 'app_running' in values:
            self.process.is_running = values['app_running']
        if values.get('exists') is False:
            fx.run_sql(self.root, 'DELETE FROM composerHeaders WHERE composerId=?', (chat,))
        fx.observation(self.root, chat, open=values.get('open', False), replying=values.get('replying', False))

    def set_format(self, known, version):
        value = fx.data(self.root, self.chat)
        if not known:
            del value['conversationState']
        if version not in self.adapter.facts.checked_versions:
            value['_v'] = 'unknown'
        fx.put_data(self.root, self.chat, value)

    def configure_usage(self, chat):
        value = fx.data(self.root, chat)
        value['usageLimitReached'] = True
        fx.put_data(self.root, chat, value)
        return self.adapter.reader.usage(chat)

    def visible_turns(self, chat):
        return self.process.visible.get(chat)


class CursorSpecific(unittest.TestCase):
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

    def test_transcript_preferred_prompt_wrapper_removed_ids_and_times_native(self):
        path = self.adapter.locator.transcript(self.chat)
        raw = path.read_text().replace('first', 'exported prompt').replace('reply', 'exported answer')
        path.write_text(raw)
        read = self.adapter.reader.read(self.chat)
        self.assertEqual(read[0].prompt.text, 'exported prompt')
        self.assertEqual(read[0].reply_text, 'exported answer')
        self.assertEqual(read[0].prompt.id, 'p1')
        self.assertEqual(read[0].prompt.at, turns()[0].prompt.at)
        self.assertEqual(read[0].messages[:2], turns()[0].messages[:2])

    def test_transcript_end_failure_is_not_a_reply_and_incomplete_turn_retained(self):
        path = self.adapter.locator.transcript(self.chat)
        path.write_text(path.read_text() + json.dumps({'type': 'turn_ended', 'reason': 'failed'}) + '\n')
        self.assertEqual(self.adapter.reader.read(self.chat), turns())
        result = self.adapter.writer.add(self.chat, [Turn(Message('next', PROMPT, 'unfinished'))])
        self.assertEqual(self.adapter.reader.read(self.chat)[-1], Turn(Message('next', PROMPT, 'unfinished')))
        self.adapter.writer.take_back(result.receipt)

    def test_new_version_same_shape_trusted_unknown_shape_blocks_every_write(self):
        data = fx.data(self.root, self.chat)
        data['_v'] = 19
        fx.put_data(self.root, self.chat, data)
        self.assertTrue(self.adapter.state.format_version().known)
        self.assertTrue(self.adapter.state.format_version().new_version)
        self.assertTrue(self.adapter.state.condition(self.chat).format_new_version)
        changed = self.adapter.writer.rename(self.chat, 'new name')
        self.adapter.writer.take_back(changed.receipt)
        del data['fullConversationHeadersOnly']
        fx.put_data(self.root, self.chat, data)
        before = self.snapshot()
        for call in (lambda: self.adapter.writer.create([], 'x', 'folder'),
                     lambda: self.adapter.writer.add(self.chat, []),
                     lambda: self.adapter.writer.place(self.chat, [], 'p1'),
                     lambda: self.adapter.writer.rename(self.chat, 'x'),
                     lambda: self.adapter.writer.cut(self.chat, 'p1')):
            with self.assertRaises(UnknownFormat):
                call()
        self.assertEqual(before, self.snapshot())

    def test_all_writes_refuse_running_including_preparation_rollback_restore(self):
        receipt = self.adapter.writer.rename(self.chat, 'renamed').receipt
        before = self.snapshot()
        self.process.is_running = True
        for call in (lambda: self.adapter.writer.prepare(self.chat, 'add'),
                     lambda: self.adapter.writer.create([], 'x', 'folder'),
                     lambda: self.adapter.writer.add(self.chat, []),
                     lambda: self.adapter.writer.place(self.chat, [], 'p1'),
                     lambda: self.adapter.writer.rename(self.chat, 'x'),
                     lambda: self.adapter.writer.cut(self.chat, 'p1'),
                     lambda: self.adapter.writer.restore(receipt),
                     lambda: self.adapter.writer.take_back(receipt)):
            with self.assertRaises(AppMustBeClosed):
                call()
        self.assertEqual(before, self.snapshot())

    def test_prepared_receipt_saved_before_changes_and_restart_rollback_exact(self):
        before = self.snapshot()
        receipt = self.adapter.writer.prepare(self.chat, 'add')
        intent = self.adapter.writer.receipts / (receipt.data['token'] + '.json')
        self.assertTrue(intent.exists())
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(intent.stat().st_mode & 0o777, 0o600)
        self.adapter.writer.add(self.chat, [Turn(Message('next', PROMPT, 'more'))])
        loaded = WriteReceipt(**json.loads(json.dumps(asdict(receipt))))
        restarted = adapter(self.root, process=self.process)
        restarted.writer.take_back(loaded)
        restarted.writer.take_back(loaded)
        self.assertEqual(self.snapshot(), before)

    def test_prepare_then_external_change_refuses_comparison(self):
        self.adapter.writer.prepare(self.chat, 'rename')
        data = fx.data(self.root, self.chat)
        data['name'] = 'external'
        fx.put_data(self.root, self.chat, data)
        before = self.snapshot()
        with self.assertRaises(ChatChanged):
            self.adapter.writer.rename(self.chat, 'baton')
        self.assertEqual(before, self.snapshot())

    def test_stale_receipt_and_changed_transcript_refuse_without_overwriting(self):
        result = self.adapter.writer.add(self.chat, [Turn(Message('next', PROMPT, 'more'))])
        path = self.adapter.locator.transcript(self.chat)
        path.write_bytes(path.read_bytes() + b'\n')
        before = self.snapshot()
        with self.assertRaises(ChatChanged):
            self.adapter.writer.take_back(result.receipt)
        self.assertEqual(before, self.snapshot())

    def test_agent_state_preserved_add_place_rename_created_state_empty(self):
        state = fx.data(self.root, self.chat)['conversationState']
        transcript = self.adapter.locator.transcript(self.chat).read_bytes()
        for result in (self.adapter.writer.add(self.chat, [Turn(Message('next', PROMPT, 'more'))]),
                       self.adapter.writer.place(self.chat, [Turn(Message('middle', PROMPT, 'placed'))], 'p2'),
                       self.adapter.writer.rename(self.chat, 'new')):
            self.assertEqual(fx.data(self.root, self.chat)['conversationState'], state)
        self.assertEqual(self.adapter.locator.transcript(self.chat).read_bytes(), transcript)
        result = self.adapter.writer.create(turns(), 'copy', '/copy')
        self.assertEqual(fx.data(self.root, result.chat_id)['conversationState'], '~')
        self.assertEqual(self.adapter.reader.read(result.chat_id), turns())

    def test_flattened_tool_activity_is_not_a_final_reply(self):
        value = Turn(Message('prompt', PROMPT, 'work'), (Message('activity', TOOL_TEXT, 'tool text'),))
        result = self.adapter.writer.create([value], 'activity', 'folder')
        read = self.adapter.reader.read(result.chat_id)
        self.assertEqual(read, [value])
        self.assertEqual(read[0].reply_text, '')
        bubbles = self.adapter.locator.bubbles(result.chat_id)
        self.assertNotIn('toolCall', bubbles[-1])
        self.assertNotIn('toolResult', bubbles[-1])

    def test_scope_required_writes_created_scope_survives_restart(self):
        inert = CursorAdapter(self.root)
        before = self.snapshot()
        for call in (lambda: inert.writer.add(self.chat, []), lambda: inert.writer.create([], 'new', '')):
            with self.assertRaises(NotAvailable):
                call()
        self.assertEqual(before, self.snapshot())
        result = self.adapter.writer.create([], 'new', '')
        restarted = adapter(self.root, process=self.process)
        restarted.writer.add(result.chat_id, [Turn(Message('next', PROMPT, 'more'))])
        self.assertEqual(len(restarted.reader.read(result.chat_id)), 1)

    def test_symlink_database_transcript_and_hook_config_refused(self):
        path = self.adapter.locator.transcript(self.chat)
        original = path.read_bytes()
        target = self.root / 'elsewhere'
        target.write_bytes(original)
        path.unlink()
        path.symlink_to(target)
        with self.assertRaises(NotAvailable):
            self.adapter.reader.read(self.chat)
        with self.assertRaises(NotAvailable):
            self.adapter.writer.prepare(self.chat, 'add')

    def test_hooks_preserve_other_entries_no_session_start_and_native_reply(self):
        self.adapter.hooks.entrypoints_available = lambda: True
        path = self.adapter.hooks.path
        path.parent.mkdir(parents=True, exist_ok=True)
        other = {'version': 1, 'other': 'keep', 'hooks': {'stop': [{'command': 'other'}]}}
        path.write_text(json.dumps(other))
        self.assertFalse(self.adapter.hooks.check().values['installed'])
        self.assertTrue(self.adapter.hooks.install().ok)
        self.adapter.hooks.install()
        settings = json.loads(path.read_text())
        self.assertNotIn('sessionStart', settings['hooks'])
        self.assertEqual(len(settings['hooks']['stop']), 2)
        self.assertEqual(json.loads(self.adapter.hooks.attach_reply('history', 'notice')),
                         {'continue': True, 'additional_context': 'notice\nhistory'})
        self.assertEqual(json.loads(self.adapter.hooks.turn_end_reply()), {})
        self.adapter.hooks.uninstall()
        self.assertEqual(json.loads(path.read_text()), other)

    def test_missing_entrypoints_do_not_claim_ready_or_install(self):
        value = adapter(self.root, hook_entrypoints_available=lambda: False)
        self.assertFalse(value.hooks.install().ok)
        self.assertFalse(value.hooks.path.exists())

    def test_app_open_folder_and_busy_close_refusal(self):
        fx.observation(self.root, self.chat, replying=True, open=True)
        self.process.is_running = True
        with self.assertRaises(ChatReplying):
            self.adapter.app.close()
        self.assertEqual(self.process.quits, 0)
        fx.observation(self.root, self.chat, replying=False)
        with self.assertRaises(NotAvailable) as raised:
            self.adapter.app.close()
        self.assertEqual(raised.exception.note_id, 'relaunch.replying_unknown')
        self.assertEqual(self.process.quits, 0)
        self.adapter.hooks.entrypoints_available = lambda: True
        self.adapter.hooks.install()
        self.adapter.app.close()
        self.adapter.app.open(self.chat, '/ignored')
        self.assertEqual(self.process.opened, ['/fixture/project'])

    def test_default_controls_inert(self):
        with patch('subprocess.run', side_effect=AssertionError('real process')):
            value = CursorAdapter(self.root)
            self.assertFalse(value.app.running())
            self.assertFalse(value.runner.available().ok)
            with self.assertRaises(NotAvailable):
                value.app.open(self.chat, None)
            with self.assertRaises(NotAvailable):
                value.runner.ask('question', 'folder')

    def test_runner_signed_out_and_no_linked_chat_resume(self):
        calls = []
        def command(args, **options):
            calls.append(args)
            return SimpleNamespace(returncode=1, stdout='Please sign in')
        value = adapter(self.root, command=command)
        self.assertFalse(value.runner.available().ok)
        with self.assertRaises(NotAvailable):
            value.runner.ask('question', 'folder')
        self.assertNotIn('--resume', str(calls))

