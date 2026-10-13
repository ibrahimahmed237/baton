"""Review-round regressions, using temporary files and injected controls only."""
from contextlib import closing
import json
import sqlite3
import subprocess
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from baton.adapters.cursor import CursorAdapter
from baton.adapters.cursor.app import SystemProcess
from baton.domain.errors import NotAvailable, UnknownFormat
from baton.domain.model import Message, Turn, PROMPT, REPLY, TOOL_CALL, TOOL_RESULT
from baton.services.mapping import for_target
from tests.adapters.test_cursor import home, adapter
from tests.adapters.suite import turns
from tests.fixtures.cursor import build as fx


class CursorReview(unittest.TestCase):
    def setUp(self):
        self.root = home(self)
        self.chat = fx.build(self.root, turns())
        self.process = fx.FixtureProcess(self.root)
        self.adapter = adapter(self.root, process=self.process)

    def bubble(self, ident, chat=None):
        return next(b for b in self.adapter.locator.bubbles(chat or self.chat) if b['bubbleId'] == ident)

    def put_bubble(self, bubble):
        fx.run_sql(self.root, 'UPDATE cursorDiskKV SET value=? WHERE key=?',
                   (json.dumps(bubble), 'bubbleId:' + self.chat + ':' + bubble['bubbleId']))

    def test_scoped_inert_adapter_refuses_every_write_but_reads_work(self):
        receipt = self.adapter.writer.rename(self.chat, 'changed').receipt
        inert = adapter(self.root)
        with self.assertRaises(NotAvailable):
            inert.process.running()
        before = fx.run_sql(self.root, 'SELECT * FROM cursorDiskKV ORDER BY key')
        self.assertEqual(inert.reader.read(self.chat), turns())
        self.assertTrue(inert.state.condition(self.chat).exists)
        self.assertEqual(len(inert.locator.chats()), 1)
        for call in (lambda: inert.writer.prepare(self.chat, 'add'),
                     lambda: inert.writer.create([], 'new', ''),
                     lambda: inert.writer.add(self.chat, []),
                     lambda: inert.writer.place(self.chat, [], 'p1'),
                     lambda: inert.writer.rename(self.chat, 'new'),
                     lambda: inert.writer.cut(self.chat, ''),
                     lambda: inert.writer.restore(receipt),
                     lambda: inert.writer.take_back(receipt)):
            with self.assertRaises(NotAvailable):
                call()
        self.assertEqual(fx.run_sql(self.root, 'SELECT * FROM cursorDiskKV ORDER BY key'), before)

    def test_process_matches_arguments_other_install_paths_and_helpers(self):
        process = SystemProcess()
        for command in ('/Applications/Cursor.app/Contents/MacOS/Cursor --flag',
                        '/Users/test/Apps/Cursor.app/Contents/MacOS/Cursor',
                        '/Volumes/Tools/Cursor.app/Contents/Frameworks/Cursor Helper (GPU).app/Contents/MacOS/Cursor Helper (GPU) --flag',
                        'Cursor --flag', 'Cursor Helper (Renderer) --flag'):
            with self.subTest(command=command), patch('subprocess.run', return_value=SimpleNamespace(returncode=0, stdout=command)):
                self.assertTrue(process.running())
        with patch('subprocess.run', return_value=SimpleNamespace(returncode=0, stdout='/usr/bin/python cursor_tests.py')):
            self.assertFalse(process.running())

    def test_failed_ps_refuses_as_running(self):
        for failure in (OSError('unavailable'), subprocess.CalledProcessError(1, ['ps'])):
            with patch('subprocess.run', side_effect=failure):
                self.assertTrue(SystemProcess().running())
                self.assertEqual(SystemProcess().started_at(), '')
        with patch('subprocess.run', return_value=SimpleNamespace(returncode=1, stdout='')):
            self.assertTrue(SystemProcess().running())

    def test_default_entrypoints_refuse_ready_and_running_close_without_evidence(self):
        self.assertFalse(self.adapter.hooks.install().ok)
        self.assertFalse(self.adapter.hooks.path.exists())
        # Even installed-looking entries and a stale idle observation cannot prove idle.
        path = self.adapter.hooks.path
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'hooks': {k: [{'command': v}] for k, v in self.adapter.hooks.commands.items()}}))
        self.assertFalse(self.adapter.hooks.check().ok)
        fx.observation(self.root, self.chat, replying=False)
        self.process.is_running = True
        with self.assertRaises(NotAvailable) as raised:
            self.adapter.app.close()
        self.assertEqual(raised.exception.note_id, 'relaunch.replying_unknown')
        self.assertEqual(self.process.quits, 0)

    def test_newest_native_role_templates_keep_rich_text_and_safe_grouping(self):
        latest = self.bubble('a3')
        latest.update(attachments=['private'], context={'secret': True}, toolResults=['secret'], summary='secret')
        self.put_bubble(latest)
        data = fx.data(self.root, self.chat)
        data['fullConversationHeadersOnly'][-1]['grouping'].update(summary='private', context='private')
        fx.put_data(self.root, self.chat, data)
        self.adapter.writer.add(self.chat, [Turn(Message('new-p', PROMPT, 'new prompt'), (Message('new-a', REPLY, 'new reply'),))])
        reply = self.bubble('new-a')
        self.assertEqual(reply['text'], 'new reply')
        self.assertIn('richText', reply)
        self.assertEqual(json.loads(reply['richText'])['root']['children'][0]['children'][0]['text'], 'new reply')
        self.assertTrue(set(reply) <= {'bubbleId', 'type', 'text', 'createdAt', 'richText', 'batonMessage'})
        head = fx.data(self.root, self.chat)['fullConversationHeadersOnly'][-1]
        self.assertEqual(head['grouping'], {'hasText': True, 'textPreview': 'new reply'})
        # Removing richText from the newest bubble proves older same-role shapes are not chosen.
        latest.pop('richText')
        self.put_bubble(latest)
        self.adapter.writer.add(self.chat, [Turn(Message('p-next', PROMPT, 'again'), (Message('a-next', REPLY, 'again'),))])
        self.assertNotIn('richText', self.bubble('a-next'))

    def test_missing_same_role_native_template_refuses_add_place_and_create(self):
        heads = fx.data(self.root, self.chat)['fullConversationHeadersOnly']
        for head in heads:
            if head['type'] == 2:
                bubble = self.bubble(head['bubbleId'])
                bubble['toolCall'] = {'name': 'tool'}
                self.put_bubble(bubble)
        turn = Turn(Message('fresh-p', PROMPT, 'prompt'), (Message('fresh-a', REPLY, 'reply'),))
        before = fx.run_sql(self.root, 'SELECT * FROM cursorDiskKV ORDER BY key')
        for call in (lambda: self.adapter.writer.add(self.chat, [turn]),
                     lambda: self.adapter.writer.place(self.chat, [turn], 'p2'),
                     lambda: self.adapter.writer.create([turn], 'new', '/copy')):
            with self.assertRaises(UnknownFormat):
                call()
        self.assertEqual(before, fx.run_sql(self.root, 'SELECT * FROM cursorDiskKV ORDER BY key'))

    def test_create_whitelists_chat_header_and_bubbles_and_uses_scoped_role_templates(self):
        data = fx.data(self.root, self.chat)
        data.update(summary='private', context={'secret': True}, attachments=['private'], toolResults=['private'])
        fx.put_data(self.root, self.chat, data)
        header = json.loads(fx.run_sql(self.root, 'SELECT value FROM composerHeaders')[0][0])
        header.update(summary='private', context='private', attachments=['private'])
        fx.run_sql(self.root, 'UPDATE composerHeaders SET value=?, unused=?', (json.dumps(header), 'private'))
        result = self.adapter.writer.create([Turn(Message('fresh-p', PROMPT, 'prompt'), (Message('fresh-a', REPLY, 'reply'),))], 'new', '/copy')
        copied = fx.data(self.root, result.chat_id)
        self.assertEqual(copied['folder'], '/copy')
        self.assertEqual(copied['workspacePath'], '/copy')
        for key in ('summary', 'context', 'attachments', 'toolResults'):
            self.assertNotIn(key, copied)
            self.assertNotIn(key, json.loads(self.adapter.locator.header(result.chat_id)['value']))
        self.assertIsNone(self.adapter.locator.header(result.chat_id)['unused'])
        self.assertIn('richText', self.bubble('fresh-a', result.chat_id))

    def test_tool_display_text_matches_non_replay_mapping(self):
        turn = Turn(Message('fresh-p', PROMPT, 'work'), (
            Message('call', TOOL_CALL, tool='write', tool_input={'path': 'file.py'}, call_id='native'),
            Message('result', TOOL_RESULT, 'done', call_id='native'),
            Message('orphan', TOOL_RESULT, 'elsewhere', call_id='missing')))
        result = self.adapter.writer.create([turn], 'new', '/copy')
        expected = for_target(turn, self.adapter.facts)
        for message in expected.messages:
            bubble = self.bubble(message.id, result.chat_id)
            self.assertEqual(bubble['text'], message.text)
            self.assertNotIn('toolCall', bubble)
            self.assertNotIn('toolResult', bubble)
        self.assertEqual(self.adapter.reader.read(result.chat_id)[0].reply_text, '')

    def test_native_tool_and_other_kinds_need_no_text_or_created_at(self):
        bubble = self.bubble('c1')
        bubble.pop('text')
        bubble.pop('createdAt')
        self.put_bubble(bubble)
        data = fx.data(self.root, self.chat)
        data['fullConversationHeadersOnly'].append({'bubbleId': 'native-other', 'type': 9})
        fx.put_data(self.root, self.chat, data)
        fx.run_sql(self.root, 'INSERT INTO cursorDiskKV VALUES(?,?)',
                   ('bubbleId:' + self.chat + ':native-other', json.dumps({'bubbleId': 'native-other', 'type': 9})))
        self.assertTrue(self.adapter.state.format_version().known)
        self.adapter.writer.rename(self.chat, 'allowed')
        bubble = self.bubble('p1')
        bubble.pop('text')
        self.put_bubble(bubble)
        self.assertFalse(self.adapter.state.format_version().known)

    def test_receipt_root_and_ancestor_symlinks_refused_before_resolve(self):
        target = self.root / 'owned'
        target.mkdir()
        link = self.root / 'link'
        link.symlink_to(target, target_is_directory=True)
        for path in (link, link / 'child'):
            with self.assertRaises(NotAvailable):
                adapter(self.root, rollback_root=path)
        self.assertEqual(list(target.iterdir()), [])

    def test_read_paths_use_sqlite_read_only_connection(self):
        original = sqlite3.connect
        urls = []
        def connect(url, **options):
            urls.append(url)
            return original(url, **options)
        with patch('baton.adapters.cursor.locator.sqlite3.connect', side_effect=connect):
            self.adapter.locator.chats()
            self.adapter.reader.read(self.chat)
            self.adapter.state.condition(self.chat)
        self.assertTrue(urls)
        self.assertTrue(all(url.endswith('?mode=ro') for url in urls))
        with closing(self.adapter.locator.connect()) as db:
            with self.assertRaises(sqlite3.OperationalError):
                db.execute("DELETE FROM cursorDiskKV")

    def test_hooks_use_injected_project_and_wiring_entrypoint(self):
        project = self.root / 'other-project'
        value = adapter(self.root, project_root=project, baton_command='/fixture/bin/baton command',
                        hook_entrypoints_available=lambda: True)
        self.assertTrue(value.hooks.install().ok)
        self.assertEqual(value.hooks.path, project / '.cursor/hooks.json')
        settings = json.loads(value.hooks.path.read_text())
        self.assertEqual(settings['hooks']['stop'][0]['command'], "'/fixture/bin/baton command' notify --tool cursor")
        self.assertEqual(settings['hooks']['beforeSubmitPrompt'][0]['command'], "'/fixture/bin/baton command' catch-up --tool cursor")
        self.assertFalse((self.root / '.cursor/hooks.json').exists())
        self.assertFalse(CursorAdapter(self.root).hooks.check().ok)

    def test_runner_unknown_login_prose_is_nonfatal_and_unavailable(self):
        from baton.adapters.cursor.runner import CursorRunner
        for text in ('unknown', 'not currently logged in', 'previously signed in', 'logged in status unavailable', '未登录', ''):
            with self.subTest(text=text):
                runner = CursorRunner(lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=text))
                finding = runner.available()
                self.assertFalse(finding.ok)
                self.assertEqual(finding.note_id, 'setup.runner')
        for text in ('logged in', 'signed in'):
            runner = CursorRunner(lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=text))
            self.assertTrue(runner.available().ok)
