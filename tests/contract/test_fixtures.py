"""C2b reproducibility, independent state semantics and genuine service effects."""
from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from baton.cli import output
from baton.cli.commands import REGISTRY
from baton.domain.errors import ChatChanged, DecisionNeeded
from baton.domain.link import AGENT_HAS, CHAT_SHOWS, SUMMARIZED
from baton.notes.catalogue import CATALOGUE
from baton.services.limit_offer import LimitOffers, MemoryOffers
from tests.contract.fixture_manifest import MANIFEST, BY_NAME
from tests.contract.generate_fixtures import World, audit_notes, fixed_ids, generate, original, NOW, LATER, VirtualTranscripts

TRACKED = Path(__file__).resolve().parents[2] / 'app' / 'Fixtures'

@contextmanager
def world_for(state):
    """Build a single private recipe world with stable pre-sealing identities."""
    with tempfile.TemporaryDirectory(prefix='baton-fixture-proof-') as folder, fixed_ids(state):
        world = World(Path(folder))
        try: yield world
        finally: world.close()


def notes(value):
    """Collect recursive contract notes without overlooking nested buttons."""
    if isinstance(value, dict):
        if {'id', 'tone', 'values', 'text', 'buttons'} <= value.keys(): yield value
        for child in value.values(): yield from notes(child)
    elif isinstance(value, list):
        for child in value: yield from notes(child)


class GeneratedFixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='baton-generated-proof-')
        cls.root = Path(cls.temporary.name)
        cls.first, cls.second = cls.root / 'first', cls.root / 'second'
        generate(cls.first)
        generate(cls.second)
        cls.payloads = {p.name: json.loads(p.read_bytes()) for p in cls.first.glob('*.json')}

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def fixture(self, name):
        return self.payloads[name]

    def test_two_distinct_private_roots_generate_identical_bytes(self):
        self.assertEqual({p.name: p.read_bytes() for p in self.first.glob('*.json')},
                         {p.name: p.read_bytes() for p in self.second.glob('*.json')})
        self.assertEqual(set(self.payloads), set(BY_NAME))

    def test_tracked_fixtures_match_generated_bytes_exactly(self):
        self.assertEqual({p.name for p in TRACKED.glob('*.json')}, set(BY_NAME))
        for filename in BY_NAME:
            with self.subTest(filename=filename):
                self.assertEqual((TRACKED / filename).read_bytes(), (self.first / filename).read_bytes())

    def test_independent_required_screen_routes_and_explicit_authority(self):
        # This ledger is intentionally independent of _routes()/state constants.
        required = {
            'D2': ('no_links', 'in_sync', 'one_side_ahead', 'waiting', 'relaunch_needed', 'decision_needed', 'paused', 'setup_incomplete'),
            'D3': ('empty', 'filled', 'tool_missing'),
            'D4': ('s1', 's2', 's3', 's4', 's4b', 's5', 's6', 's7', 's8', 's9', 's10', 's11', 's12', 'paused', 'missing', 'hooks', 'unknown'),
            'D5': ('claude', 'codex', 'opencode', 'cursor', 'already', 'unavailable', 'large'),
            'D6': ('claude_open_idle', 'claude_replying', 'codex_holding', 'cursor_running', 'opencode_any_time'),
            'D7': ('limit_reset', 'limit_no_reset', 'context_size', 'no_size', 'brief_fallback'),
        }
        command = {'D2': 'links', 'D3': 'links', 'D4': 'status', 'D5': 'setup', 'D6': 'sync', 'D7': 'status'}
        for screen, states in required.items():
            for state in states:
                item = BY_NAME[f'{command[screen]}.{screen.lower()}_{state}.json']
                self.assertIn(state, item.recipe)
                self.assertIn(screen, item.requirement)
                self.assertTrue(item.callable)
        for state in ('claude', 'codex', 'opencode', 'cursor', 'replying'):
            self.assertIn('undo.d6_' + state + '.json', BY_NAME)
        self.assertIn('setup-install.d6_missing_hooks.json', BY_NAME)
        for state in ('limit_reset', 'limit_no_reset', 'context_size', 'no_size'):
            self.assertIn('brief.d7_' + state + '_generated.json', BY_NAME)
        self.assertIn('brief.d7_offline.json', BY_NAME)
        self.assertIn('notify.d7_unlinked.json', BY_NAME)
        self.assertEqual(len(MANIFEST), len(BY_NAME))
        self.assertEqual({i.provider for i in MANIFEST}, {'real_read', 'real_service_plan', 'real_service_receipt', 'model_projection', 'future_contract'})
        for item in MANIFEST:
            if item.provider != 'real_read': continue
            command_name = {'merge-show': 'merge', 'settings-get': 'settings get'}.get(item.command, item.command)
            handler = REGISTRY.get(command_name).run
            self.assertEqual(item.callable, handler.__module__ + '.' + handler.__name__)

    def test_recursive_notes_are_exact_and_private_content_is_absent(self):
        for filename, value in self.payloads.items():
            with self.subTest(filename=filename):
                audit_notes(value)
                self.assertNotIn('PRIVATE_FIXTURE_REASONING', json.dumps(value))
                self.assertNotIn(str(self.root), json.dumps(value))
                self.assertNotIn('fixture.links.ready', json.dumps(value))
                if filename.startswith('status.'):
                    self.assertFalse(any(n['id'].startswith(('handoff.', 'quit.')) for n in notes(value)))
                if any(n['id'].startswith('quit.') for n in notes(value)):
                    self.assertTrue(filename.startswith('setup.') or filename == 'links.sample.json', filename)
        self.assertTrue(any(n['id'] == 'quit.title' for n in notes(self.fixture('links.sample.json'))))

    def test_catalogue_audit_detects_each_rendering_mutation(self):
        value = self.fixture('note.sample.json')
        for key, changed in (('id', 'unknown.note'), ('tone', 'danger'), ('text', 'wrong'), ('status_line', 'wrong'),
                             ('values', {}), ('buttons', [])):
            mutant = deepcopy(value); mutant[key] = changed
            with self.subTest(key=key), self.assertRaises((AssertionError, KeyError)):
                audit_notes(mutant)
        for key in ('id', 'tone', 'values', 'text', 'buttons', 'status_line'):
            mutant = deepcopy(value); mutant.pop(key)
            with self.subTest(deleted=key), self.assertRaises((AssertionError, KeyError)):
                audit_notes(mutant)
        mutant = deepcopy(value); mutant['buttons'][0]['primary'] = False
        with self.assertRaises(AssertionError): audit_notes(mutant)

    def test_every_status_counter_and_receipt_agrees_with_actual_turn_states(self):
        for filename, value in self.payloads.items():
            if not filename.startswith('status.'): continue
            if not filename.startswith('status.d7_'):
                first_unshared = next((i for i, turn in enumerate(value['turns'])
                                       if any(state not in ('written_here', 'shown') for state in turn['states'].values())),
                                      len(value['turns']))
                expected_fold = max(0, first_unshared - 1) if first_unshared == len(value['turns']) else first_unshared
                folded = next(n for n in value['notes'] if n['id'] == 'screen.earlier_turns')
                self.assertEqual(folded['values']['n'], expected_fold, filename)
                states = {state for turn in value['turns'] for state in turn['states'].values()}
                self.assertTrue({'turn.' + state for state in states} <= {n['id'] for n in value['notes']}, filename)
            else:
                self.assertFalse(any(n['id'].startswith(('empty.', 'filter.', 'message.', 'turn.')) or
                                     n['id'].startswith('screen.') and not n['id'].startswith('screen.received_')
                                     for n in value['notes']))
            for tool, side in value['sides'].items():
                with self.subTest(filename=filename, tool=tool):
                    states = [t['states'][tool] for t in value['turns']]
                    self.assertEqual(side['total'], len(states))
                    for field, accepted in (('agent_has', AGENT_HAS), ('chat_shows', CHAT_SHOWS), ('waiting', ('waiting',)),
                                            ('added', ('added',)), ('attached', ('attached',)), ('skipped', ('skipped',))):
                        self.assertEqual(side[field], sum(s in accepted for s in states))
                    reached = side['synced_up_to']
                    if reached:
                        self.assertIn(reached['id'], [t['id'] for t in value['turns'] if t['states'][tool] in AGENT_HAS])
                    if not side['waiting']:
                        self.assertEqual(side['next_message']['turns'], 0)
                    usage = side['usage']
                    if usage['size'] is None: self.assertIsNone(usage['percent'])
                    if usage['percent'] is not None:
                        self.assertEqual(usage['percent'], (usage['tokens'] * 200 + usage['size']) // (2 * usage['size']))

    def test_d2_eight_states_have_distinct_service_state_and_suggestions(self):
        for state in ('no_links', 'in_sync', 'one_side_ahead', 'waiting', 'relaunch_needed', 'decision_needed', 'paused', 'setup_incomplete'):
            links = self.fixture(f'links.d2_{state}.json')['links']
            suggestions = self.fixture(f'suggestions.d2_{state}.json')['suggestions']
            self.assertEqual(bool(links), state != 'no_links')
            self.assertEqual(bool(suggestions), state != 'no_links')
            if not links: continue
            link = links[0]
            self.assertEqual(link['paused'], state == 'paused')
            self.assertEqual(link['decision_needed'], state == 'decision_needed')
            if state == 'relaunch_needed':
                self.assertEqual(link['headline']['id'], 'relaunch_to_see')
            if state == 'in_sync':
                self.assertTrue(link['in_sync']); self.assertEqual(link['headline']['id'], 'status.in_sync')
            if state in ('one_side_ahead', 'waiting', 'setup_incomplete'):
                self.assertFalse(link['in_sync']); self.assertTrue(link['needs_attention'])

    def test_d3_lists_missing_tool_and_three_real_receipt_positions(self):
        for command in ('links', 'chats', 'suggestions', 'history'):
            key = {'history': 'events', 'links': 'links', 'chats': 'chats', 'suggestions': 'suggestions'}[command]
            self.assertFalse(self.fixture(command + '.d3_empty.json')[key])
            self.assertTrue(self.fixture(command + '.d3_filled.json')[key])
        cursor = next(t for t in self.fixture('setup.d3_tool_missing.json')['tools'] if t['tool'] == 'cursor')
        self.assertFalse(cursor['installed']); self.assertFalse(cursor['ready']); self.assertEqual(cursor['facts'], {})
        three, four, five = (self.fixture(f'status.d3_filled_{n}.json') for n in (3, 4, 5))
        self.assertTrue(three['decision_needed'])
        self.assertNotEqual(three['sides']['claude']['synced_up_to']['id'], three['sides']['codex']['synced_up_to']['id'])
        self.assertGreater(four['sides']['claude']['added'], 0)
        self.assertTrue(any(n['id'] == 'screen.received_hidden_tool' for n in four['notes']))
        self.assertTrue(five['in_sync'])
        self.assertEqual(five['sides']['claude']['synced_up_to']['id'], five['sides']['codex']['synced_up_to']['id'])
        self.assertTrue(any(n['id'] == 'screen.received_both' for n in five['notes']))
        pin = next(t for t in three['turns'] if t['pinned'])
        self.assertTrue(any(s['synced_up_to']['id'] != pin['id'] for s in three['sides'].values()))

    def test_scoped_chat_reads_preserve_the_requested_tool_and_actual_lists(self):
        for family, states in (('d3', ('empty', 'filled', 'tool_missing')),
                              ('d5', ('claude', 'codex', 'opencode', 'cursor', 'already', 'unavailable', 'large'))):
            for state in states:
                for tool in ('claude', 'codex', 'opencode', 'cursor'):
                    filename = f'chats.{family}_{state}_{tool}.json'
                    with self.subTest(filename=filename):
                        value = self.fixture(filename)
                        if family == 'd3' and state == 'tool_missing' and tool == 'cursor':
                            self.assertEqual(value['error']['kind'], 'not_available')
                            continue
                        chats = value['chats']
                        self.assertTrue(all(chat['tool'] == tool for chat in chats))
                        if family == 'd3':
                            self.assertEqual(bool(chats), state == 'filled')
                        else:
                            self.assertTrue(chats)

    def test_s1_to_s12_and_missing_paused_hooks_unknown_semantics(self):
        # Counters come from actual service actions, not legacy handwritten copy.
        expected = {'s1': ('claude', 2, 2, 2), 's2': ('claude', 4, 2, 0), 's3': ('claude', 4, 4, 0),
                    's4': ('codex', 4, 4, 0), 's4b': ('codex', 3, 3, 1), 's5': ('codex', 0, 0, 12),
                    's6': ('codex', 12, 0, 0), 's7': ('claude', 4, 4, 1), 's8': ('codex', 3, 3, 1),
                    's9': ('claude', 4, 4, 1), 's10': ('claude', 4, 0, 0), 's11': ('codex', 4, 4, 0),
                    's12': ('claude', 4, 4, 0)}
        for scenario, (tool, agent, shown, waiting) in expected.items():
            value = self.fixture(f'status.d4_{scenario}.json'); side = value['sides'][tool]
            with self.subTest(scenario=scenario):
                self.assertEqual((side['agent_has'], side['chat_shows'], side['waiting']), (agent, shown, waiting))
        for state, reason in (('paused', 'paused'), ('missing', 'side_missing'), ('hooks', 'hooks_not_ready'), ('unknown', 'format_unknown')):
            side = self.fixture(f'status.d4_{state}.json')['sides']['claude']
            self.assertEqual(side['waiting_reason'], reason)
        self.assertTrue(self.fixture('status.d4_s9.json')['decision_needed'])
        self.assertTrue(all(s['waiting_reason'] == 'decision_needed' for s in self.fixture('status.d4_s9.json')['sides'].values()))
        self.assertEqual(self.fixture('status.d4_s11.json')['sides']['codex']['chat']['name'], 'Renamed orchard tests')
        long = self.fixture('status.d4_s12.json')['turns'][-1]['messages']
        self.assertGreater(len(next(m['text'] for m in long if m['kind'] == 'reply')), 240)
        self.assertEqual(sum(m['kind'] in ('tool_call', 'tool_result') for m in long), 4)

    def test_d5_targets_modes_and_capability_selected_notes_are_real(self):
        for target in ('opencode', 'codex', 'cursor'):
            for mode in ('', '_attached_history', '_brief'):
                value = self.fixture(f'link.d5_opencode_{target}{mode}.json')
                self.assertFalse(value['applied']); self.assertEqual(value['steps'][0]['tool'], target)
                if mode == '_brief':
                    self.assertIn(value['stage'], ('generate', 'create'))
                elif mode == '_attached_history':
                    self.assertEqual(value['steps'][0]['action'], 'attach')
                    self.assertIn('link.attached_history', [n['id'] for n in value['notes']])
                    self.assertFalse(any(n['id'].startswith('new_chat.') or n['id'] == 'write.app_must_close' for n in value['notes']))
                else:
                    self.assertEqual(value['steps'][0]['action'], 'create')
                    self.assertEqual('relaunch_to_see' in value['steps'][0]['needs'], target in ('claude', 'cursor'))
        unavailable = self.fixture('setup.d5_unavailable.json')
        target = next(t for t in unavailable['tools'] if t['tool'] == 'opencode')
        self.assertFalse(next(m for m in target['link_modes'] if m['mode'] == 'full_copy')['available'])
        self.assertFalse(next(m for m in target['link_modes'] if m['mode'] == 'brief')['available'])
        self.assertTrue(next(m for m in target['link_modes'] if m['mode'] == 'attached_history')['available'])
        already = self.fixture('link.d5_already.json')
        self.assertEqual(already['confirmation']['id'], 'plan.unavailable')
        self.assertIn('link.already_linked', [n['id'] for n in already['notes']])
        large = self.fixture('link.d5_large_codex.json')
        self.assertIn('link.large_copy', [n['id'] for n in large['notes']])
        self.assertEqual(large['steps'][0]['notes'], large['notes'])
        removal = self.fixture('unlink.d4_actions.json')
        self.assertEqual([(n['values']['tool'], n['values']['n']) for n in removal['notes']], [('Claude', 2)])
        receipt = self.fixture('link.service_full_copy_applied.json')
        self.assertTrue(receipt['applied']); self.assertTrue(receipt['chat_id']); self.assertEqual(receipt['link_id'], 3)

    def test_d6_every_button_note_table_row_and_action_specific_cancel(self):
        expected = {'link.d6_new_chat_claude.json': 'new_chat.relaunch',
                    'link.d6_new_chat_cursor.json': 'write.app_must_close',
                    'relaunch.d6_cursor_running.json': 'write.app_must_close',
                    'relaunch.d6_replying.json': 'relaunch.replying',
                    'sync.d6_claude_open_idle.json': 'write.chat_open_release',
                    'sync.d6_codex_holding.json': 'write.chat_open',
                    'sync.d6_cursor_running.json': 'write.chat_open',
                    'setup-install.d6_missing_hooks.json': 'setup.missing',
                    'undo.d6_claude.json': 'undo.cut', 'undo.d6_codex.json': 'undo.shorter',
                    'undo.d6_opencode.json': 'undo.cut_reopen', 'undo.d6_cursor.json': 'undo.shorter_closed',
                    'undo.d6_replying.json': 'undo.replying', 'copy.sample.json': 'link.copy',
                    'unlink.sample.json': 'link.remove'}
        for filename, ident in expected.items():
            with self.subTest(filename=filename):
                found = next(n for n in notes(self.fixture(filename)) if n['id'] == ident)
                self.assertTrue(found['buttons']); self.assertEqual(found, output.note(ident, found['values']))
        for filename in ('link.d6_new_chat_claude.json', 'copy.sample.json', 'unlink.sample.json', 'sync.sample.json'):
            confirmation = self.fixture(filename)['confirmation']
            self.assertEqual([b['id'] for b in confirmation['buttons']], ['confirm', 'cancel'])
        attaching = self.fixture('sync.d6_cursor_running.json')
        self.assertEqual(attaching['steps'][0]['action'], 'attach')
        self.assertEqual(attaching['steps'][0]['needs'], [])
        self.assertFalse(any(n['id'] == 'write.app_must_close' for n in notes(attaching)))
        future_closure = self.fixture('relaunch.d6_cursor_running.json')
        self.assertEqual(future_closure['fixture_provider'], 'future_contract')
        self.assertEqual(future_closure['execution'], 'unavailable')
        self.assertFalse(future_closure['applied'])
        self.assertEqual(future_closure['steps'][0]['tool'], 'cursor')
        self.assertEqual([step['action'] for step in future_closure['steps']], ['close', 'add', 'reopen'])
        self.assertEqual(future_closure['replying'], [])
        self.assertEqual(future_closure['confirmation']['id'], 'plan.unavailable')

    def test_d7_usage_limit_routes_generation_review_offline_fallback(self):
        known = self.fixture('status.d7_context_size.json')
        self.assertEqual([known['sides'][s]['usage']['percent'] for s in ('claude', 'codex')], [82, 13])
        self.assertIn('brief.large_chat', [n['id'] for n in known['notes']])
        unknown = self.fixture('status.d7_no_size.json')['sides']['claude']['usage']
        self.assertEqual((unknown['tokens'], unknown['size'], unknown['percent']), (164000, None, None))
        reset = self.fixture('notify.d7_limit_reset.json')['offers'][0]
        self.assertEqual(reset['values']['source_tool_id'], 'claude'); self.assertEqual(reset['values']['destination_tool_id'], 'codex')
        no_reset = self.fixture('notify.d7_limit_no_reset.json')['offers'][0]
        self.assertEqual(no_reset['values']['source_tool_id'], 'opencode'); self.assertNotIn('time', no_reset['values'])
        unlinked = self.fixture('notify.d7_unlinked.json')['offers'][0]
        self.assertIsNone(unlinked['values']['link_id']); self.assertIsNone(unlinked['values']['destination_chat_id'])
        for state in ('limit_reset', 'limit_no_reset', 'context_size', 'no_size'):
            cost, review = (self.fixture(f'brief.d7_{state}{suffix}.json') for suffix in ('', '_generated'))
            self.assertEqual((cost['stage'], review['stage']), ('generate', 'create'))
            self.assertNotEqual(cost['plan_id'], review['plan_id'])
            self.assertEqual(cost['brief']['estimated_tokens'], sum(c['tokens'] for c in cost['brief']['candidate_estimates']))
            self.assertTrue(review['brief']['artifact_id']); self.assertTrue(review['brief']['text'])
        for state in ('offline', 'brief_fallback'):
            offline = self.fixture(f'brief.d7_{state}.json')
            self.assertEqual((offline['stage'], offline['brief']['writer']), ('create', 'offline'))
            self.assertIn('brief.used_offline', [n['id'] for n in offline['notes']])

    def test_future_commands_never_claim_executable_success(self):
        for item in MANIFEST:
            if item.provider != 'future_contract': continue
            value = self.fixture(item.filename)
            self.assertEqual(value['fixture_provider'], 'future_contract')
            self.assertEqual(value['execution'], 'unavailable')
            self.assertFalse(value.get('applied', False))
            self.assertIn(value.get('opened', False), (False, 'unavailable'))
            if 'confirmation' in value: self.assertFalse(any(b.get('primary') for b in value['confirmation']['buttons']))
            if item.command == 'ask': self.assertEqual((value['answer_id'], value['answer']), ('', ''))
            self.assertFalse(item.executable)


class ServiceEffectProofs(unittest.TestCase):
    def test_kept_and_pinned_private_turn_stays_out_of_all_brief_outputs_and_native_creation(self):
        secrets = ('PRIVATE-KEPT-PROMPT', 'PRIVATE-KEPT-REPLY', 'PRIVATE-KEPT-FILE')
        for writer in (None, 'claude', 'offline'):
            with self.subTest(writer=writer), world_for('privacy-' + str(writer)) as world:
                world.pair(shared=2)
                private = original(3, text=secrets[0])
                private = type(private)(private.prompt, (type(private.prompt)('private-reply', 'reply', secrets[1], NOW),))
                world.seed('claude', [private])
                private_id = world.store.turns(3)[-1].id
                world.adapters['claude'].changed_files[private.prompt.id] = [secrets[2]]
                world.store.set_pinned(3, private_id, True)
                world.store.keep_back(3, private_id)
                world.seed('claude', [original(4)])
                if writer is None: world.adapters['codex'].runner.error = RuntimeError('fallback proof')
                review = world.briefs.plan(3, 'codex', writer=writer)
                before = deepcopy({s: a.chats for s, a in world.adapters.items()})
                if review.stage == 'generate':
                    if writer is None:
                        with self.assertLogs('baton.services.brief', level='ERROR'):
                            creation = world.briefs.confirm(review)
                    else: creation = world.briefs.confirm(review)
                else: creation = review
                self.assertEqual(before, {s: a.chats for s, a in world.adapters.items()})
                self.assertNotIn(private_id, creation.pinned)
                self.assertNotIn(private_id, world.store.brief_artifact(creation.artifact_id)['covered_ids'])
                self.assertEqual(creation.writer, 'offline' if writer == 'offline' else 'claude')
                visible = [json.dumps(review.as_contract()), json.dumps(creation.as_contract()),
                           creation.text, json.dumps([t.prompt.text + t.reply_text for t in creation.originals]),
                           Path(world.transcripts.paths[creation.transcript_path]).read_text()]
                visible.extend(prompt for adapter in world.adapters.values() for prompt, _, _ in adapter.runner.calls)
                receipt = world.briefs.confirm(creation)
                self.assertTrue(receipt.applied)
                native = world.adapters['codex'].reader.read(receipt.chat_id)
                self.assertEqual(native, [creation.turn, *creation.originals])
                visible.append(json.dumps([t.prompt.text + t.reply_text for t in native]))
                for text in visible:
                    for secret in secrets: self.assertNotIn(secret, text)
                self.assertEqual(world.adapters['claude'].chats, before['claude'])

    def test_kept_and_pinned_private_turn_stays_out_of_full_copy_plan_and_native_copy(self):
        with world_for('private-copy') as world:
            world.pair(shared=2)
            world.seed('claude', [original(3, text='PRIVATE-KEPT-COPY')])
            ident = world.store.turns(3)[-1].id
            world.store.set_pinned(3, ident, True)
            world.store.keep_back(3, ident)
            world.seed('claude', [original(4)])
            plan = world.engine.linker.plan_full_copy(3, 'codex')
            self.assertNotIn(ident, plan.turn_ids)
            self.assertNotIn('PRIVATE-KEPT-COPY', str(plan.turns))
            result = world.engine.linker.apply(plan, plan.plan_id)
            self.assertTrue(result.applied)
            self.assertEqual(world.adapters['codex'].reader.read(result.chat_id), list(plan.turns))
            self.assertNotIn('PRIVATE-KEPT-COPY', str(world.adapters['codex'].reader.read(result.chat_id)))

    def test_s9_bypass_plus_completed_destination_work_holds_both_then_merge_redelivers(self):
        with world_for('s9-proof') as world:
            world.status_recipe('d4_s9')
            before = deepcopy({s: a.chats for s, a in world.adapters.items()})
            plan = world.engine.applier.preview(3)
            self.assertTrue(plan.decision_needed)
            self.assertEqual({s.action for s in plan.steps}, {'hold'})
            with self.assertRaises(DecisionNeeded): world.engine.applier.apply(plan)
            self.assertEqual(before, {s: a.chats for s, a in world.adapters.items()})
            decision = world.engine.merger.plan(3, preset='dont_reorder')
            result = world.engine.merger.apply(decision, decision.plan_id)
            self.assertTrue(result.applied)
            for tool in world.chats:
                text = [t.prompt.text for t in world.adapters[tool].reader.read(world.chats[tool])]
                self.assertIn('Orchard task 4', text); self.assertIn('Orchard task 5', text)
            self.assertFalse(world.engine.applier.refresh(3)['status'].decision_needed)
            self.assertTrue(world.engine.applier.refresh(3)['status'].in_sync)

    def test_d6_profiles_hold_attach_release_and_any_time_have_physical_effect_proofs(self):
        for target in ('claude', 'codex', 'cursor', 'opencode'):
            with self.subTest(target=target), world_for('delivery-' + target) as world:
                source = 'codex' if target != 'codex' else 'claude'
                world.pair((target, source), shared=0)
                world.seed(source, [original(1), original(2)])
                world.condition(target, open=True, app_running=True)
                before = deepcopy(world.adapters[target].chats)
                prepared = world.engine.applier.preview(3)
                result = world.engine.applier.apply(prepared)
                self.assertTrue(result.applied)
                state = world.engine.applier.refresh(3)['status'].side(target)
                if target == 'opencode':
                    self.assertEqual(prepared.steps[0].action, 'add')
                    self.assertEqual((state.agent_has, state.chat_shows, state.added), (2, 0, 2))
                    self.assertEqual(len(world.adapters[target].reader.read(world.chats[target])), 2)
                else:
                    self.assertEqual(prepared.steps[0].action, 'attach')
                    self.assertEqual(before, world.adapters[target].chats)
                    self.assertEqual((state.agent_has, state.waiting, state.attached), (0, 2, 0))
                if target == 'claude':
                    releasing = world.engine.applier.preview(3, add_when_idle=('claude',))
                    self.assertEqual(releasing.steps[0].action, 'add_after_release')
                    result = world.engine.applier.apply(releasing)
                    self.assertTrue(result.applied)
                    self.assertIn(('release', world.chats['claude']), world.adapters['claude'].app.calls)
                    self.assertEqual(len(world.adapters['claude'].reader.read(world.chats['claude'])), 2)

    def test_d5_copy_does_not_link_and_link_creates_exact_native_copy_and_stale_refusal(self):
        for and_link in (False, True):
            with self.subTest(and_link=and_link), world_for('copy-' + str(and_link)) as world:
                world.dialog('d5_claude_claude')
                before = deepcopy(world.adapters['codex'].chats['source'])
                plan = world.engine.linker.plan_copy('codex', 'source', 'claude', and_link=and_link)
                existing = deepcopy({s: a.chats for s, a in world.adapters.items()})
                stale = world.engine.linker.plan_copy('codex', 'source', 'cursor')
                result = world.engine.linker.apply(plan, plan.plan_id)
                self.assertTrue(result.applied)
                self.assertEqual(world.adapters['codex'].chats['source'], before)
                self.assertEqual(world.adapters['claude'].reader.read(result.chat_id), list(plan.turns))
                self.assertEqual(bool(world.store.links()), and_link)
                if and_link:
                    with self.assertRaises(ChatChanged): world.engine.linker.apply(stale, stale.plan_id)
                self.assertEqual(existing['cursor'], world.adapters['cursor'].chats)

    def test_d5_attached_counterpart_creates_metadata_without_fabricating_delivery(self):
        with world_for('attached-dialog') as world:
            world.dialog('d5_opencode_codex_attached_history')
            before = deepcopy({s: a.chats for s, a in world.adapters.items()})
            plan = world.engine.linker.plan_link('claude', 'source', 'codex', 'codex-existing', 'attached_history')
            result = world.engine.linker.apply(plan, plan.plan_id)
            self.assertTrue(result.applied)
            self.assertEqual(before, {s: a.chats for s, a in world.adapters.items()})
            world.link = world.store.get_link(result.link_id); world.chats = dict(world.link.chats)
            pending = world.engine.applier.preview(result.link_id)
            self.assertEqual((pending.steps[0].action, pending.steps[0].reason), ('attach', 'initial_history'))
            world.engine.applier.apply(pending)
            side = world.engine.applier.refresh(result.link_id)['status'].side('codex')
            self.assertEqual((side.agent_has, side.attached, side.waiting), (0, 0, 4))
            self.assertEqual(world.adapters['codex'].reader.read('codex-existing'), [])

    def test_d6_all_four_undo_profiles_have_native_cut_or_shorter_copy_and_restore_effects(self):
        for target in ('claude', 'codex', 'opencode', 'cursor'):
            with self.subTest(target=target), world_for('undo-' + target) as world:
                source = 'claude' if target == 'codex' else 'codex'
                world.pair((target, source), shared=1)
                world.seed(source, [original(2), original(3)])
                world.sync()
                old_target = world.chats[target]
                before_other = deepcopy(world.adapters[source].chats)
                before_target = world.adapters[target].reader.read(old_target)
                event = next(e for e in world.store.history(3) if e.kind == 'add' and e.side == target)
                plan = world.engine.undo.plan(3, event.id)
                self.assertEqual(len(plan.removes), 2)
                self.assertEqual(plan.steps[0].action, 'cut' if world.adapters[target].facts.can_cut else 'create_shorter')
                result = world.engine.undo.apply(plan)
                self.assertTrue(result.applied)
                current = world.store.get_link(3).chat(target)
                self.assertEqual(len(world.adapters[target].reader.read(current)), 1)
                self.assertEqual(world.adapters[source].chats, before_other)
                if not world.adapters[target].facts.can_cut:
                    self.assertNotEqual(current, old_target)
                    self.assertEqual(world.adapters[target].reader.read(old_target), before_target)
                restoring = world.engine.undo.restore(3, result.event_id)
                restored = world.engine.undo.apply(restoring)
                self.assertTrue(restored.applied)
                latest = world.store.get_link(3).chat(target)
                self.assertEqual([t.prompt.text for t in world.adapters[target].reader.read(latest)],
                                 [t.prompt.text for t in before_target])
                self.assertEqual(world.adapters[source].chats, before_other)

    def test_d7_preview_generation_creation_summary_coverage_and_single_use(self):
        with world_for('brief-lifecycle') as world:
            world.handoff('d7_context_size')
            before = deepcopy({s: a.chats for s, a in world.adapters.items()})
            preview = world.briefs.plan(3, 'codex', recent_turns=1)
            self.assertEqual(preview.stage, 'generate')
            self.assertFalse(any(a.runner.calls for a in world.adapters.values()))
            self.assertEqual(preview.estimated_tokens, sum(c['tokens'] for c in preview.candidate_estimates))
            creation = world.briefs.confirm(preview)
            self.assertEqual(creation.stage, 'create'); self.assertNotEqual(preview.plan_id, creation.plan_id)
            self.assertEqual(before, {s: a.chats for s, a in world.adapters.items()})
            self.assertEqual(len(world.adapters['codex'].runner.calls), 1)
            self.assertTrue(world.adapters['codex'].runner.calls[0][2])
            artifact = world.store.brief_artifact(creation.artifact_id)
            self.assertEqual(artifact['text'], creation.text)
            world.clock.value = LATER
            receipt = world.briefs.confirm(creation)
            self.assertTrue(receipt.applied)
            self.assertEqual(world.adapters['codex'].reader.read(receipt.chat_id)[0].prompt.at, NOW)
            self.assertEqual(world.adapters['codex'].reader.read(receipt.chat_id), [creation.turn, *creation.originals])
            self.assertEqual(len(world.adapters['codex'].runner.calls), 1)
            coverage = world.store.summary_coverage(3, 'codex')
            self.assertEqual(coverage['artifact_id'], creation.artifact_id)
            states = [r.states['codex'] for r in world.store.turns(3)]
            self.assertIn(SUMMARIZED, states)
            side = world.engine.applier.refresh(3)['status'].side('codex')
            self.assertEqual(side.agent_has, sum(s in AGENT_HAS for s in states))
            for old in (preview, creation):
                with self.assertRaises(ChatChanged): world.briefs.confirm(old)

    def test_d7_offline_never_asks_and_runner_failure_uses_once_disclosed_fallback(self):
        with world_for('offline-proof') as world:
            world.handoff('d7_context_size')
            plan = world.briefs.plan(3, 'codex', writer='offline')
            self.assertEqual(plan.stage, 'create')
            result = world.briefs.confirm(plan)
            self.assertTrue(result.applied)
            self.assertFalse(any(a.runner.calls for a in world.adapters.values()))
        with world_for('fallback-proof') as world:
            world.handoff('d7_context_size')
            world.adapters['codex'].runner.error = RuntimeError('private fixture failure')
            preview = world.briefs.plan(3, 'codex')
            self.assertEqual([c['writer'] for c in preview.candidate_estimates], ['codex', 'claude'])
            with self.assertLogs('baton.services.brief', level='ERROR'):
                creation = world.briefs.confirm(preview)
            self.assertEqual(creation.writer, 'claude')
            self.assertEqual([len(world.adapters[s].runner.calls) for s in ('codex', 'claude')], [1, 1])
            self.assertIn('brief.skipped_failed', [n.id for n in creation.notes])
            result = world.briefs.confirm(creation)
            self.assertTrue(result.applied)
            self.assertEqual([len(world.adapters[s].runner.calls) for s in ('codex', 'claude')], [1, 1])

    def test_virtual_transcript_is_stable_private_verified_before_sealing(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            one, two = VirtualTranscripts(Path(first)), VirtualTranscripts(Path(second))
            path = one.save(3, 'public snapshot')
            self.assertEqual(path, two.save(3, 'public snapshot'))
            real = Path(one.paths[path])
            self.assertEqual(stat.S_IMODE(real.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(real.parent.stat().st_mode), 0o700)
            digest = sha256(b'public snapshot').hexdigest()
            one.verify(path, digest)
            real.write_text('changed')
            with self.assertRaises(ValueError): one.verify(path, digest)

    def test_limit_offer_is_genuine_deduplicated_and_routes_original_destination(self):
        for state in ('d7_limit_reset', 'd7_limit_no_reset', 'd7_unlinked'):
            with self.subTest(state=state), world_for(state) as world:
                world.handoff(state)
                service = LimitOffers(world.store, {s: a.reader for s, a in world.adapters.items()}, world.clock, MemoryOffers())
                source = world.limit_source
                offer = service.check(source, world.chats[source], to='codex')
                self.assertIsNotNone(offer)
                self.assertEqual(offer.to_side, 'codex')
                self.assertEqual(offer.note.values['source_chat_id'], world.chats[source])
                self.assertEqual(offer.note.values['destination_chat_id'], world.chats['codex'] if world.link else None)
                self.assertIsNone(service.check(source, world.chats[source], to='claude'))

    def test_read_recipe_guards_detect_a_writer_runner_or_app_mutation(self):
        with world_for('guard-proof') as world:
            world.status_recipe('d4_s1')
            handler = world.engine.reads.status
            for effect in (lambda: world.adapters['claude'].writer.add(world.chats['claude'], []),
                           lambda: world.adapters['claude'].runner.ask('bad', '', True),
                           lambda: world.adapters['claude'].app.close()):
                def bad(*args, **kwargs):
                    effect()
                    return handler(*args, **kwargs)
                with self.subTest(effect=effect), patch.object(world.engine.reads, 'status', side_effect=bad), self.assertRaises(AssertionError):
                    world.read('status')

if __name__ == '__main__': unittest.main()
