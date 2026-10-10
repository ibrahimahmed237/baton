"""C2a read commands observe actual services without recovery or native effects."""
from copy import deepcopy
from contextlib import ExitStack
from dataclasses import asdict, replace
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from baton.adapters.fake import FakeAdapter
from baton.adapters.fake.facts import CLAUDE_LIKE, CODEX_LIKE, OPENCODE_LIKE
from baton.cli.main import main
from baton.cli.wiring import build
from baton.domain.model import Message, Turn, PROMPT, REPLY
from baton.domain.errors import ChatChanged
from baton.domain.capabilities import Visibility
from baton.ports.clock import FixedClock
from baton.ports.tool import Usage, SetupFinding
from baton.services.journal import Journal
from baton.services.merger import Merger
from baton.services.undo import Undo

NOW = '2026-10-10T14:00:00Z'


def turn(ident='a', text='Public work', at='2026-10-10T12:00:00Z'):
    return Turn(Message(ident, PROMPT, text, at), (Message(ident + '_r', REPLY, 'Done', at),))


class ReadCommands(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.clock = FixedClock(NOW)
        self.adapters = {'claude': FakeAdapter(CLAUDE_LIKE, 'claude'), 'codex': FakeAdapter(CODEX_LIKE, 'codex')}
        self.chats = {'claude': self.adapters['claude'].build_chat([turn()], 'Known source', '/work'),
                      'codex': self.adapters['codex'].build_chat([], 'Known target', '/work')}
        engine = self.engine()
        self.link = engine.store.link(self.chats, 'full_copy', NOW)
        engine.store.record_turns(self.link.id, 'claude', [turn()])
        engine.close()

    def engine(self):
        return build(self.root, clock=self.clock, adapters=self.adapters, installation_probe=lambda tool: tool in self.adapters)

    def read(self, *args):
        out = io.StringIO()
        result = main(list(args), engine_factory=self.engine, stdout=out)
        self.assertEqual(result, 0, out.getvalue())
        return json.loads(out.getvalue())

    def no_effects(self):
        stack = ExitStack()
        stack.enter_context(patch('baton.services.journal.Journal.recover', side_effect=AssertionError('no recovery')))
        for adapter in self.adapters.values():
            for owner, methods in ((adapter.writer, ('prepare', 'add', 'create', 'cut', 'place', 'rename', 'restore', 'take_back')),
                                   (adapter.app, ('open', 'close', 'release')), (adapter.runner, ('ask',)),
                                   (adapter.hooks, ('install', 'uninstall'))):
                if owner is not None:
                    for method in methods:
                        stack.enter_context(patch.object(owner, method, side_effect=AssertionError('effectful port called')))
        return stack

    def test_all_commands_dispatch_with_real_read_shapes_and_no_effectful_service(self):
        commands = [('setup',), ('chats', '--tool', 'claude'), ('suggestions',), ('links',),
                    ('status', '--link', str(self.link.id), '--messages'),
                    ('merge', '--link', str(self.link.id), '--show'), ('history', '--link', str(self.link.id)),
                    ('settings', 'get')]
        before = deepcopy({s: a.chats for s, a in self.adapters.items()})
        with self.no_effects():
            for command in commands:
                with self.subTest(command=command):
                    value = self.read(*command)
                    self.assertNotIn('error', value)
        self.assertEqual(before, {s: a.chats for s, a in self.adapters.items()})
        self.assertEqual({s: a.app.calls for s, a in self.adapters.items()}, {'claude': [], 'codex': []})

    def test_pending_native_append_is_preserved_and_not_promoted_to_origin(self):
        engine = self.engine()
        entry = Journal(engine.store, self.adapters, self.clock).begin(self.link.id, 'codex', self.chats['codex'], 'add')
        self.adapters['codex'].writer.add(self.chats['codex'], [turn('pending', 'Uncommitted write')])
        journal = engine.store.journal_entry(entry)
        rows = engine.store.turns(self.link.id)
        engine.close()
        before = deepcopy(self.adapters['codex'].chats)
        with patch.object(self.adapters['codex'].writer, 'take_back', side_effect=AssertionError('no recovery')):
            for command in ('links', 'status', 'merge'):
                args = (command,) if command == 'links' else (command, '--link', str(self.link.id)) + (('--show',) if command == 'merge' else ())
                self.assertEqual(self.read(*args)['error']['kind'], 'chat_changed')
            history = self.read('history', '--link', str(self.link.id))
        self.assertFalse(any(event['can_undo'] or event['can_restore'] for event in history['events']))
        engine = self.engine()
        self.addCleanup(engine.close)
        self.assertEqual(engine.store.journal_entry(entry), journal)
        self.assertEqual(engine.store.turns(self.link.id), rows)
        self.assertEqual(self.adapters['codex'].chats, before)

    def test_chats_exact_folder_and_link_identity_are_service_data(self):
        extra = self.adapters['claude'].build_chat([turn('extra')], 'Other', '/work/sub')
        values = self.read('chats', '--tool', 'claude', '--folder', '/work')['chats']
        self.assertEqual([c['id'] for c in values], [self.chats['claude']])
        self.assertEqual((values[0]['linked'], values[0]['link_id'], values[0]['tool_label']), (True, self.link.id, 'Claude'))
        self.assertNotIn(extra, [c['id'] for c in values])

    def test_suggestions_match_public_content_not_equal_counts_or_incomplete_prompts(self):
        one = self.adapters['claude'].build_chat([turn('left', 'Match')])
        two = self.adapters['codex'].build_chat([turn('right', 'Match')])
        self.adapters['codex'].build_chat([turn('unrelated', 'Unrelated')])
        draft = self.adapters['codex'].build_chat([Turn(Message('draft', PROMPT, 'Match'), ())])
        self.adapters['codex'].set_condition(draft, replying=True)
        values = self.read('suggestions')['suggestions']
        self.assertEqual([(s['a']['id'], s['b']['id'], s['matched_turns']) for s in values], [(one, two, 1)])

    def test_messages_only_when_requested_and_private_reasoning_never_crosses(self):
        adapter = self.adapters['claude']
        public = turn()
        adapter.chats[self.chats['claude']] = [Turn(public.prompt, (*public.messages, Message('secret', 'reasoning', 'PRIVATE')))]
        ordinary = self.read('status', '--link', str(self.link.id))
        self.assertNotIn('messages', ordinary['turns'][0])
        detailed = self.read('status', '--link', str(self.link.id), '--messages')
        self.assertEqual([m['kind'] for m in detailed['turns'][0]['messages']], ['prompt', 'reply'])
        self.assertNotIn('PRIVATE', json.dumps(detailed))
        merged = self.read('merge', '--link', str(self.link.id), '--show')
        self.assertNotIn('PRIVATE', json.dumps(merged))

    def test_changed_canonical_source_refuses_before_ledger_mutation(self):
        self.adapters['claude'].chats[self.chats['claude']] = [turn(text='Changed content')]
        engine = self.engine()
        before = engine.store.turns(self.link.id)
        engine.close()
        self.assertEqual(self.read('status', '--link', str(self.link.id), '--messages')['error']['kind'], 'chat_changed')
        engine = self.engine()
        self.addCleanup(engine.close)
        self.assertEqual(engine.store.turns(self.link.id), before)

    def test_cache_name_survives_missing_chat_after_engine_restart(self):
        self.read('links')
        self.adapters['codex'].set_condition(self.chats['codex'], exists=False)
        value = self.read('status', '--link', str(self.link.id))
        self.assertEqual(value['sides']['codex']['chat']['name'], 'Known target')
        self.assertFalse(value['sides']['codex']['condition']['exists'])
        self.assertFalse(value['in_sync'])

    def test_unavailable_link_adapter_has_expected_refusal_not_internal(self):
        del self.adapters['codex']
        self.assertEqual(self.read('links')['error']['kind'], 'not_available')

    def test_usage_obeys_actual_reset_unknown_size_and_half_up_policy(self):
        self.adapters['claude'].usage_values[self.chats['claude']] = Usage(81, 200, True, '2026-10-10T13:59:00Z')
        self.adapters['codex'].usage_values[self.chats['codex']] = Usage(500, None, True, None)
        value = self.read('status', '--link', str(self.link.id))
        self.assertEqual(value['sides']['claude']['usage'], {'tokens': 81, 'size': 200, 'percent': 41, 'limit': None})
        self.assertEqual(value['sides']['codex']['usage'], {'tokens': 500, 'size': None, 'percent': None, 'limit': {'resets_at': None}})
        self.assertIn('limit.available', [n['id'] for n in value['sides']['claude']['notes']])

    def test_release_note_only_true_fact_mode_and_on_button_setting(self):
        # Put waiting work on a release-capable side.
        engine = self.engine()
        self.adapters['codex'].chats[self.chats['codex']] = [turn('other', 'Destination work')]
        engine.store.record_turns(self.link.id, 'codex', [turn('other', 'Destination work')])
        engine.store.deliver(self.link.id, 'codex', [engine.store.turns(self.link.id)[0].id], 'attached', 'attached', NOW)
        engine.close()
        self.adapters['claude'].set_condition(self.chats['claude'], open=True, hooks_ready=True)
        def ids():
            return [n['id'] for n in self.read('status', '--link', str(self.link.id))['sides']['claude']['notes']]
        self.assertIn('write.chat_open_release', ids())
        self.adapters['claude'].set_condition(self.chats['claude'], replying=True)
        self.assertNotIn('write.chat_open_release', ids())
        self.adapters['claude'].set_condition(self.chats['claude'], replying=False)
        engine = self.engine()
        engine.store.save_setting('add_to_idle_claude', 'automatic')
        engine.close()
        self.assertIn('write.release', ids())
        self.assertNotIn('write.chat_open_release', ids())

    def test_attached_history_initial_delivery_never_offers_release(self):
        engine = self.engine()
        engine.store.remove_link(self.link.id)
        linked = engine.store.link(self.chats, 'attached_history', NOW)
        engine.store.record_turns(linked.id, 'claude', [turn()])
        engine.close()
        self.adapters['codex'].facts = replace(CLAUDE_LIKE, can_release_chat=True)
        self.adapters['codex'].set_condition(self.chats['codex'], open=True, hooks_ready=True)
        ids = [n['id'] for n in self.read('status', '--link', str(linked.id))['sides']['codex']['notes']]
        self.assertIn('status.first_message', ids)
        self.assertNotIn('write.chat_open_release', ids)

    def test_setup_installed_is_not_sign_in_and_unavailable_facts_are_empty(self):
        self.adapters['claude'].runner.finding = SetupFinding('runner', False, 'setup.runner', {})
        value = self.read('setup')
        tools = {t['tool']: t for t in value['tools']}
        self.assertTrue(tools['claude']['installed'])
        self.assertFalse(next(f for f in tools['claude']['findings'] if f['id'] == 'runner')['ok'])
        self.assertEqual(tools['opencode']['facts'], {})
        self.assertFalse(tools['opencode']['ready'])
        self.assertEqual(tools['claude']['facts']['write_window'], 'closed_or_released')

    def test_settings_persist_validate_and_render_labels_without_recovery(self):
        engine = self.engine()
        engine.store.save_setting('theme', 'graphite')
        engine.store.save_setting('glass', 101)
        engine.store.save_setting('unknown', True)
        engine.close()
        value = self.read('settings', 'get')
        self.assertEqual((value['settings']['theme'], value['settings']['glass']), ('graphite', 62))
        self.assertNotIn('unknown', value['settings'])
        self.assertNotIn('settings.preview', [n['id'] for n in value['notes']])

    def test_merge_preview_has_same_policy_as_merger_and_completed_history_labels(self):
        engine = self.engine()
        expected = Merger(engine.store, self.adapters, self.clock).show(self.link.id)
        engine.close()
        value = self.read('merge', '--link', str(self.link.id), '--show')
        for key in ('order', 'outcome', 'overlaps', 'same_files', 'tokens', 'offer_brief', 'automatic_allowed'):
            self.assertEqual(value[key], expected[key])
        self.assertEqual(value['presets'][0]['label'], 'By time')
        self.assertEqual(value['presets'][-1]['label'], 'Keep each chat’s order')
        self.assertEqual(self.read('history', '--link', str(self.link.id))['events'][-1]['text'], 'Linked chats')

    def test_history_undo_restore_eligibility_uses_actual_unchanged_native_evidence(self):
        engine = self.engine()
        from baton.services.applier import Applier
        applier = Applier(engine.store, self.adapters, self.clock)
        result = applier.apply(applier.preview(self.link.id))
        self.assertTrue(result.applied)
        event = next(e for e in engine.store.history(self.link.id) if e.kind == 'add')
        engine.close()
        events = self.read('history', '--link', str(self.link.id))['events']
        self.assertTrue(next(e for e in events if e['id'] == event.id)['can_undo'])
        engine = self.engine()
        undo = Undo(engine.store, self.adapters, self.clock)
        undone = undo.apply(undo.plan(self.link.id, event.id))
        self.assertTrue(undone.applied)
        engine.close()
        events = self.read('history', '--link', str(self.link.id))['events']
        self.assertTrue(next(e for e in events if e['id'] == undone.event_id)['can_restore'])
        self.adapters['codex'].chats[self.chats['codex']].append(turn('outside', 'Outside change'))
        events = self.read('history', '--link', str(self.link.id))['events']
        self.assertFalse(next(e for e in events if e['id'] == undone.event_id)['can_restore'])

    def test_history_keeps_real_alignment_queue_and_unconfirmed_events_without_claiming_delivery(self):
        from baton.services.applier import Applier
        engine = self.engine()
        engine.store.remove_link(self.link.id)
        target = self.adapters['codex'].build_chat([turn('mirror')], 'Matching chat', '/work')
        result = engine.linker.apply(engine.linker.plan_link('claude', self.chats['claude'], 'codex', target))
        self.assertTrue(result.applied, result)
        self.adapters['claude'].chats[self.chats['claude']].append(turn('next', 'New work'))
        self.adapters['codex'].set_condition(target, open=True, hooks_ready=True)
        applier = Applier(engine.store, self.adapters, self.clock)
        applier.refresh(result.link_id)
        before_queue = deepcopy(self.adapters['codex'].chats[target])
        queued = applier.apply(applier.preview(result.link_id))
        self.assertTrue(queued.applied, queued)
        self.assertEqual(self.adapters['codex'].chats[target], before_queue)
        self.adapters['codex'].chats[target] = []
        applier.refresh(result.link_id)
        recorded = engine.store.history(result.link_id)
        native = deepcopy({s: a.chats for s, a in self.adapters.items()})
        engine.close()
        with patch('baton.services.journal.Journal.recover', side_effect=AssertionError('read must not recover')):
            events = self.read('history', '--link', str(result.link_id))['events']
        self.assertEqual([e['id'] for e in events], [e.id for e in recorded])
        expected = {'aligned': 'Recognized an existing turn in Codex',
                    'attach_pending': 'Queued a turn for your next message in Codex',
                    'not_confirmed': 'Could no longer confirm a turn in the Codex chat'}
        for kind, text in expected.items():
            found = [e for e in events if e['kind'] == kind]
            self.assertTrue(found, kind)
            self.assertTrue(all(e['text'] == text for e in found), found)
            self.assertTrue(all(not e['can_undo'] and not e['can_restore'] for e in found))
        engine = self.engine()
        self.addCleanup(engine.close)
        self.assertEqual(engine.store.history(result.link_id), recorded)
        self.assertEqual({s: a.chats for s, a in self.adapters.items()}, native)

    def test_history_visibility_confirmation_describes_user_evidence_not_another_undo(self):
        from baton.services.applier import Applier
        self.adapters['codex'].facts = OPENCODE_LIKE
        engine = self.engine()
        applier = Applier(engine.store, self.adapters, self.clock)
        self.assertTrue(applier.apply(applier.preview(self.link.id)).applied)
        event = next(e for e in engine.store.history(self.link.id) if e.kind == 'add')
        undo = Undo(engine.store, self.adapters, self.clock)
        self.assertTrue(undo.apply(undo.plan(self.link.id, event.id)).applied)
        self.assertTrue(applier.refresh(self.link.id)['status'].side('codex').removed_still_shown)
        applier.mark_seen(self.link.id, 'codex')
        recorded = engine.store.history(self.link.id)
        native = deepcopy({s: a.chats for s, a in self.adapters.items()})
        engine.close()
        events = self.read('history', '--link', str(self.link.id))['events']
        shown = next(e for e in events if e['kind'] == 'undo_shown')
        self.assertEqual(shown['text'], 'You confirmed removed turns are no longer shown in Codex')
        self.assertFalse(shown['can_undo'] or shown['can_restore'])
        self.assertEqual([e['id'] for e in events], [e.id for e in recorded])
        engine = self.engine()
        self.addCleanup(engine.close)
        self.assertEqual(engine.store.history(self.link.id), recorded)
        self.assertEqual({s: a.chats for s, a in self.adapters.items()}, native)

    def test_history_unknown_future_entry_is_retained_without_blank_text_or_private_detail(self):
        engine = self.engine()
        ident = engine.store.record_event(self.link.id, 'future_kind', '', NOW,
                                         detail={'private': 'PRIVATE_FUTURE_DETAIL'})
        recorded = engine.store.history(self.link.id)
        engine.close()
        events = self.read('history', '--link', str(self.link.id))['events']
        event = next(e for e in events if e['id'] == ident)
        self.assertEqual(event['text'], 'Recorded a history entry')
        self.assertEqual(event['kind'], 'future_kind')
        self.assertFalse(event['can_undo'] or event['can_restore'])
        self.assertNotIn('PRIVATE_FUTURE_DETAIL', json.dumps(events))
        engine = self.engine()
        self.addCleanup(engine.close)
        self.assertEqual(engine.store.history(self.link.id), recorded)

    def test_valid_idle_open_cut_offers_undo_but_replying_chat_does_not(self):
        self.adapters['codex'].facts = OPENCODE_LIKE
        engine = self.engine()
        from baton.services.applier import Applier
        applier = Applier(engine.store, self.adapters, self.clock)
        self.assertTrue(applier.apply(applier.preview(self.link.id)).applied)
        event = next(e for e in engine.store.history(self.link.id) if e.kind == 'add')
        engine.close()
        self.adapters['codex'].facts = CLAUDE_LIKE
        self.adapters['codex'].set_condition(self.chats['codex'], open=True, replying=False)
        self.assertTrue(next(e for e in self.read('history', '--link', str(self.link.id))['events'] if e['id'] == event.id)['can_undo'])
        self.adapters['codex'].set_condition(self.chats['codex'], replying=True)
        self.assertFalse(next(e for e in self.read('history', '--link', str(self.link.id))['events'] if e['id'] == event.id)['can_undo'])

    def test_cut_restore_eligibility_expires_and_uses_saved_receipt(self):
        self.adapters['codex'].facts = OPENCODE_LIKE
        engine = self.engine()
        from baton.services.applier import Applier
        applier = Applier(engine.store, self.adapters, self.clock)
        self.assertTrue(applier.apply(applier.preview(self.link.id)).applied)
        event = next(e for e in engine.store.history(self.link.id) if e.kind == 'add')
        undo = Undo(engine.store, self.adapters, self.clock)
        result = undo.apply(undo.plan(self.link.id, event.id))
        self.assertTrue(result.applied)
        engine.close()
        self.assertTrue(next(e for e in self.read('history', '--link', str(self.link.id))['events'] if e['id'] == result.event_id)['can_restore'])
        self.clock.value = '2026-11-11T14:00:00Z'
        self.assertFalse(next(e for e in self.read('history', '--link', str(self.link.id))['events'] if e['id'] == result.event_id)['can_restore'])

    def test_created_twin_names_cached_before_first_read_and_visibility_needs_attention(self):
        engine = self.engine()
        engine.store.remove_link(self.link.id)
        source = self.adapters['codex'].build_chat([turn('native', 'Copy source')], 'Before first read', '/work')
        result = engine.linker.apply(engine.linker.plan_link('codex', source, 'claude', title_tag=False))
        self.assertTrue(result.applied)
        engine.close()
        value = self.read('links')['links'][0]
        self.assertTrue(value['in_sync'])
        self.assertTrue(value['needs_attention'])
        self.assertEqual(value['headline']['id'], 'relaunch_to_see')
        self.assertEqual(self.read('links')['links'][0]['headline']['id'], 'relaunch_to_see')
        self.adapters['claude'].set_condition(result.chat_id, app_started_at='2026-10-10T14:01:00Z')
        self.assertFalse(self.read('links')['links'][0]['needs_attention'])
        self.adapters['claude'].set_condition(result.chat_id, exists=False)
        self.assertEqual(self.read('links')['links'][0]['sides']['claude']['name'], 'Before first read')

    def test_on_reopen_added_visibility_requires_explicit_seen_or_later_app_start(self):
        self.adapters['codex'].facts = replace(CODEX_LIKE, added_turn_visible=Visibility.ON_REOPEN_CHAT)
        engine = self.engine()
        from baton.services.applier import Applier
        applier = Applier(engine.store, self.adapters, self.clock)
        self.assertTrue(applier.apply(applier.preview(self.link.id)).applied)
        engine.close()
        value = self.read('links')['links'][0]
        self.assertTrue(value['in_sync'])
        self.assertTrue(value['needs_attention'])
        self.assertEqual(value['headline']['id'], 'reopen_chat_to_see')
        engine = self.engine()
        engine.store.mark_shown(self.link.id, 'codex')
        engine.close()
        self.assertFalse(self.read('links')['links'][0]['needs_attention'])

    def test_pending_unlinked_create_refuses_suggestions_preserving_all_effects(self):
        engine = self.engine()
        entry = Journal(engine.store, self.adapters, self.clock).begin(None, 'codex', None, 'create')
        result = self.adapters['codex'].writer.create([turn('new', 'Match')], 'Uncommitted', '/work')
        self.adapters['claude'].build_chat([turn('pair', 'Match')])
        journal = engine.store.journal_entry(entry)
        engine.close()
        before = deepcopy({s: a.chats for s, a in self.adapters.items()})
        with self.no_effects():
            self.assertEqual(self.read('suggestions')['error']['kind'], 'chat_changed')
            for command in (('setup',), ('chats', '--tool', 'codex'), ('settings', 'get'),
                            ('history', '--link', str(self.link.id))):
                self.assertNotIn('error', self.read(*command))
        engine = self.engine()
        self.addCleanup(engine.close)
        self.assertEqual(engine.store.journal_entry(entry), journal)
        self.assertEqual(before, {s: a.chats for s, a in self.adapters.items()})
        self.assertIn(result.chat_id, self.adapters['codex'].chats)

    def test_settings_default_labels_do_not_change_with_saved_choices(self):
        engine = self.engine()
        engine.store.save_setting('theme', 'graphite')
        engine.store.save_setting('glass', 70)
        engine.close()
        result = self.read('settings', 'get')
        defaults = {n['values']['key']: n['values']['value'] for n in result['notes'] if n['id'] == 'settings.default'}
        self.assertEqual((defaults['theme'], defaults['glass']), ('System', '62'))
        self.assertEqual((result['settings']['theme'], result['settings']['glass']), ('graphite', 70))

    def test_bundled_cli_installation_is_independent_of_path_and_authentication(self):
        from baton.cli.tools import installed
        from baton.adapters.codex.runner import BUNDLED_CLI
        with patch('shutil.which', return_value=None), patch.object(Path, 'is_file', lambda p: str(p) == BUNDLED_CLI):
            self.assertTrue(installed('codex'))
            self.assertFalse(installed('claude'))
        with patch('shutil.which', return_value=None), patch.object(Path, 'is_file', lambda p: str(p) == '/Applications/Cursor.app/Contents/Info.plist'):
            self.assertTrue(installed('cursor'))
        with patch('shutil.which', return_value=None), patch.object(Path, 'is_file', lambda p: str(p) == '/Applications/Claude.app/Contents/Info.plist'):
            self.assertFalse(installed('claude'))

    def test_real_temporary_native_pending_bytes_intent_and_journal_are_preserved_by_every_read(self):
        from types import SimpleNamespace
        from baton.adapters.claude import ClaudeAdapter
        from tests.fixtures.claude.build import build as native_chat, FixtureProcess
        native_root = self.root / 'native'
        process = FixtureProcess(native_root)
        native = ClaudeAdapter(native_root, process=process, command=lambda *a, **k: SimpleNamespace(returncode=0, stdout='{"loggedIn": true}'))
        process.adapter = native
        chat = native_chat(native_root, [turn('native-origin', 'Native origin')])
        engine = self.engine()
        engine.store.remove_link(self.link.id)
        self.chats['claude'] = chat
        self.adapters['claude'] = native
        engine.adapters['claude'] = native
        link = engine.store.link(self.chats, 'full_copy', NOW)
        engine.store.record_turns(link.id, 'claude', native.reader.read(chat))
        entry = Journal(engine.store, self.adapters, self.clock).begin(link.id, 'claude', chat, 'add')
        native.writer.add(chat, [turn('pending-native', 'Uncommitted native append')])
        journal = engine.store.journal_entry(entry)
        rows = engine.store.turns(link.id)
        engine.close()
        before = {str(p.relative_to(native_root)): p.read_bytes() for p in native_root.rglob('*') if p.is_file()}
        with self.no_effects():
            for command in (('setup',), ('chats', '--tool', 'claude'), ('suggestions',), ('links',),
                            ('status', '--link', str(link.id), '--messages'), ('merge', '--link', str(link.id), '--show'),
                            ('history', '--link', str(link.id)), ('settings', 'get')):
                result = self.read(*command)
                if command[0] in ('links', 'status', 'merge'):
                    self.assertEqual(result['error']['kind'], 'chat_changed')
                else:
                    self.assertNotIn('error', result)
        after = {str(p.relative_to(native_root)): p.read_bytes() for p in native_root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)
        engine = self.engine()
        self.addCleanup(engine.close)
        self.assertEqual(engine.store.journal_entry(entry), journal)
        self.assertEqual(engine.store.turns(link.id), rows)

    def test_retained_legacy_ref_restores_missing_name_before_any_read_across_restart(self):
        # E8 retains verified before/after references even on a pre-C2 raw link.
        engine = self.engine()
        from baton.services.applier import Applier
        applier = Applier(engine.store, self.adapters, self.clock)
        self.assertTrue(applier.apply(applier.preview(self.link.id)).applied)
        event = next(e for e in engine.store.history(self.link.id) if e.kind == 'add')
        undo = Undo(engine.store, self.adapters, self.clock)
        self.assertTrue(undo.apply(undo.plan(self.link.id, event.id)).applied)
        self.assertIsNone(engine.store.known_chat('claude', self.chats['claude']))
        engine.store.remember_chat('codex', self.chats['claude'], {
            'id': self.chats['claude'], 'name': 'Other tool same ID', 'folder': '/other', 'updated_at': NOW})
        engine.close()
        self.adapters['claude'].set_condition(self.chats['claude'], exists=False)
        before = deepcopy({s: a.chats for s, a in self.adapters.items()})
        with self.no_effects():
            first = self.read('links')['links'][0]['sides']['claude']
            self.assertEqual((first['name'], first['folder']), ('Known source', '/work'))
            self.assertEqual(self.read('links')['links'][0]['sides']['claude']['name'], 'Known source')
        self.assertEqual(before, {s: a.chats for s, a in self.adapters.items()})

    def test_initial_brief_source_artifact_ref_survives_missing_before_first_read(self):
        engine = self.engine()
        engine.store.remove_link(self.link.id)
        artifact = engine.briefs.plan_new('claude', self.chats['claude'], 'codex', writer='offline')
        self.assertEqual(artifact.stage, 'create')
        result = engine.briefs.confirm(artifact)
        self.assertTrue(result.applied)
        self.assertIsNone(engine.store.known_chat('claude', self.chats['claude']))
        event = next(e for e in engine.store.history(result.link_id) if e.kind == 'brief')
        self.assertNotIn('before_chats', event.detail)
        records = engine.store.turns(result.link_id)
        engine.close()
        self.adapters['claude'].set_condition(self.chats['claude'], exists=False)
        before = deepcopy({s: a.chats for s, a in self.adapters.items()})
        with self.no_effects():
            link = next(l for l in self.read('links')['links'] if l['link_id'] == result.link_id)
            self.assertEqual((link['sides']['claude']['name'], link['sides']['claude']['folder']), ('Known source', '/work'))
        self.assertEqual(before, {s: a.chats for s, a in self.adapters.items()})
        engine = self.engine()
        self.addCleanup(engine.close)
        self.assertEqual(engine.store.turns(result.link_id), records)
        self.assertEqual(engine.store.history(result.link_id)[0], event)
