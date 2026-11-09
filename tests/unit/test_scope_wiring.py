"""Command scope on native-shaped temporary fixtures, never real chats."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from baton.cli.commands import Context, discover
from baton.cli.output import error
from baton.cli.wiring import build
from baton.domain.errors import NotAvailable
from baton.ports.clock import FixedClock
from tests.adapters.suite import turns
from tests.fixtures.claude import build as claude
from tests.fixtures.codex import build as codex
from tests.fixtures.cursor import build as cursor
from tests.fixtures.opencode import build as opencode


class CommandScope(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        home = self.root / 'tools'
        self.ids = {'claude': claude.build(home, turns()[:1]),
                    'codex': codex.build(home, turns()[:1]),
                    'opencode': opencode.build(home, turns()[:1]),
                    'cursor': cursor.build(home, turns()[:1])}
        self.engine = build(self.root / 'baton', tools_home=home,
                            clock=FixedClock('2026-11-09T10:00:00Z'))
        self.addCleanup(self.engine.close)
        self.registry = discover()

    def run_command(self, command, **args):
        with self.engine.command_lock():
            return self.registry.get(command).run(Context(self.engine, command), SimpleNamespace(**args))

    def test_two_native_cross_tool_link_previews(self):
        for source, target in (('claude', 'codex'), ('opencode', 'cursor')):
            with self.subTest(source=source, target=target):
                result = self.run_command('link', source=source + ':' + self.ids[source],
                                          to=target + ':' + self.ids[target], mode='full_copy')
                self.assertFalse(result['applied'])
                self.assertTrue(result['steps'])
                self.assertNotIn('error', result)
                self.assertTrue(self.engine.adapter(target).reader.read(self.ids[target]))

    def test_unselected_chats_refuse_content_and_writes_even_after_listing(self):
        for tool in ('codex', 'opencode', 'cursor'):
            adapter = self.engine.adapter(tool)
            self.assertIn(self.ids[tool], [ref.id for ref in adapter.locator.chats()])
            for operation in (adapter.reader.read, adapter.reader.usage,
                              lambda chat: adapter.writer.prepare(chat, 'add')):
                with self.subTest(tool=tool, operation=operation), self.assertRaises(NotAvailable):
                    operation(self.ids[tool])

    def test_link_confirmation_restores_saved_scope_in_a_fresh_engine(self):
        value = self.run_command('link', source='claude:' + self.ids['claude'],
                                 to='codex:' + self.ids['codex'], mode='full_copy')
        fresh = build(self.root / 'baton', tools_home=self.root / 'tools', clock=self.engine.clock)
        self.addCleanup(fresh.close)
        with fresh.command_lock():
            result = self.registry.get('link').run(Context(fresh, 'link', confirm=value['plan_id']),
                                                   SimpleNamespace())
        self.assertTrue(result['applied'])
        self.assertEqual(fresh.store.get_link(result['link_id']).chats,
                         {'claude': self.ids['claude'], 'codex': self.ids['codex']})

    def test_scope_resets_between_commands_and_never_crosses_tools(self):
        self.engine.scope_for({'source': 'codex:' + self.ids['codex']})
        self.assertTrue(self.engine.adapter('codex').reader.read(self.ids['codex']))
        with self.assertRaises(NotAvailable):
            self.engine.adapter('opencode').reader.read(self.ids['opencode'])
        self.engine.scope_for({'tool': 'cursor', 'chat': self.ids['cursor']})
        with self.assertRaises(NotAvailable):
            self.engine.adapter('codex').reader.read(self.ids['codex'])
        self.assertTrue(self.engine.adapter('cursor').reader.read(self.ids['cursor']))

    def test_linked_chats_work_for_status_and_sync_without_named_chats(self):
        self.engine.scope_for({'source': 'opencode:' + self.ids['opencode'],
                               'to': 'cursor:' + self.ids['cursor']})
        service = self.engine.linker
        result = service.apply(service.plan_link('opencode', self.ids['opencode'],
                                                 'cursor', self.ids['cursor'], 'attached_history'))
        self.assertTrue(result.applied)
        for command in ('status', 'sync'):
            value = self.run_command(command, link=result.link_id, to=None, messages=False)
            self.assertEqual(value['link_id'], result.link_id)
        self.engine.scope_for()
        for tool in ('opencode', 'cursor'):
            self.assertTrue(self.engine.adapter(tool).reader.read(self.ids[tool]))

    def test_native_hook_catch_up_uses_linked_chats_after_fresh_build(self):
        from baton.hooks.runtime import invoke
        source, target = 'opencode', 'cursor'
        self.engine.scope_for({'source': source + ':' + self.ids[source],
                               'to': target + ':' + self.ids[target]})
        service = self.engine.linker
        linked = service.apply(service.plan_link(source, self.ids[source], target,
                                                 self.ids[target], 'attached_history'))
        self.assertTrue(linked.applied)
        # Native append outside Baton, representing the other agent's next completed turn.
        from tests.fixtures.opencode.build import insert_message, EARLY, MODEL
        insert_message(self.root / 'tools', self.ids[source], 'extra-prompt', 'user', EARLY + 90000,
                       [{'type': 'text', 'text': 'new hook turn'}], model=MODEL, agent='build')
        insert_message(self.root / 'tools', self.ids[source], 'extra-reply', 'assistant', EARLY + 90100,
                       [{'type': 'text', 'text': 'completed hook reply'}], parentID='extra-prompt',
                       providerID=MODEL['providerID'], modelID=MODEL['modelID'], finish='stop')
        fresh = build(self.root / 'baton', tools_home=self.root / 'tools', clock=self.engine.clock)
        self.addCleanup(fresh.close)
        process = cursor.FixtureProcess(self.root / 'tools')
        process.is_running = True
        fresh.adapter(target).process = process
        fresh.adapter(target).hooks.install()
        args = SimpleNamespace(tool=target, chat=None, turn_id=None, event=None)
        payload = io.StringIO(json.dumps({'conversation_id': self.ids[target],
                                         'generation_id': 'fixture-hook'}))
        with fresh.command_lock():
            result = invoke(args, prompt=True, engine_factory=lambda: fresh, stdin=payload, locked=True)
        self.assertIn('new hook turn', result)
        self.assertTrue(any(event.kind == 'attached' for event in fresh.store.history(linked.link_id)))

    def test_confirmation_uses_saved_selection_and_ignores_new_chat_flags(self):
        token = self.engine.plans.remember('fixture', 'link',
            {'source': 'codex:' + self.ids['codex'], 'to': 'claude:' + self.ids['claude']})
        self.engine.scope_for({'source': 'cursor:' + self.ids['cursor']}, command='link', confirm=token)
        self.assertTrue(self.engine.adapter('codex').reader.read(self.ids['codex']))
        with self.assertRaises(NotAvailable):
            self.engine.adapter('cursor').reader.read(self.ids['cursor'])

    def test_every_not_available_note_has_action_tool_and_reason(self):
        for tool in ('codex', 'opencode', 'cursor'):
            try:
                self.engine.adapter(tool).reader.read(self.ids[tool])
            except NotAvailable as failure:
                note = error(failure)['error']['note']
                self.assertEqual(note['values']['tool'], {'codex': 'Codex', 'opencode': 'OpenCode', 'cursor': 'Cursor'}[tool])
                self.assertIn('Baton can only use the chats you chose or linked', note['text'])
        for failure in (NotAvailable(), NotAvailable('private diagnostic')):
            note = error(failure)['error']['note']
            for key in ('tool', 'action', 'reason'):
                self.assertTrue(note['values'][key])
            self.assertNotIn('private diagnostic', note['text'])
