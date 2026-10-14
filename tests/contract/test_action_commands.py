"""Action routes exercise real writes exclusively on isolated fakes."""
from copy import deepcopy
from types import SimpleNamespace
import unittest

from baton.cli.commands import Context, discover
from baton.cli.plans import WrongPlanAction
from baton.domain.errors import ChatChanged, OrderNotAllowed
from tests.contract.generate_fixtures import original
from tests.contract.test_fixtures import world_for

REGISTRY = discover()


def run(world, command, confirm=None, **kwargs):
    args = SimpleNamespace(link=3, event=None, show=False, preset=None, order=None,
                           keep=None, split=False, first=None)
    for key, value in kwargs.items(): setattr(args, key, value)
    return REGISTRY.get(command).run(Context(world.engine, command, dry_run=confirm is None, confirm=confirm), args)


class ActionCommandsTests(unittest.TestCase):
    def conflict(self, world):
        world.pair(shared=1)
        world.seed('claude', [original(2), original(4)])
        world.seed('codex', [original(3)])

    def delivery(self, world, target):
        source = 'claude' if target == 'codex' else 'codex'
        world.pair((target, source), shared=1)
        world.seed(source, [original(2), original(3)])
        world.sync()
        return next(e.id for e in world.store.history(3) if e.kind == 'add' and e.side == target)

    def test_merge_dry_run_uses_merge_fingerprint_then_confirm_changes_chats(self):
        with world_for('action-merge') as w:
            self.conflict(w)
            before = deepcopy({s: a.chats for s, a in w.adapters.items()})
            value = run(w, 'merge', preset='by_time')
            decision = w.engine.merger.plan(3, preset='by_time')
            self.assertEqual(value['plan_id'], decision.plan_id)
            self.assertNotEqual(value['plan_id'], decision.delivery.plan_id)
            self.assertTrue(value['notes'])
            self.assertEqual(before, {s: a.chats for s, a in w.adapters.items()})
            result = run(w, 'merge', confirm=value['plan_id'])
            self.assertTrue(result['applied'])
            for side in w.chats:
                chat = w.store.get_link(3).chat(side)
                self.assertNotEqual(chat, w.chats[side])
                self.assertEqual([t.prompt.text for t in w.adapters[side].reader.read(chat)],
                                 ['Orchard task 1', 'Orchard task 2', 'Orchard task 3', 'Orchard task 4'])
                self.assertEqual(w.adapters[side].chats[w.chats[side]], before[side][w.chats[side]])
            with self.assertRaises(ChatChanged): run(w, 'merge', confirm=value['plan_id'])

    def test_keep_both_sides_split_and_dont_reorder_are_real_choices(self):
        for choice in ('claude', 'codex', 'split', 'dont_reorder'):
            with self.subTest(choice=choice), world_for('choice-' + choice) as w:
                self.conflict(w)
                before = deepcopy({s: a.chats for s, a in w.adapters.items()})
                kwargs = {'split': True} if choice == 'split' else {'preset': choice} if choice == 'dont_reorder' else {'keep': choice}
                value = run(w, 'merge', **kwargs)
                self.assertTrue(value['notes'])
                self.assertTrue(run(w, 'merge', confirm=value['plan_id'])['applied'])
                if choice == 'split':
                    self.assertTrue(w.store.get_link(3).removed_at)
                    self.assertEqual(before, {s: a.chats for s, a in w.adapters.items()})
                else:
                    self.assertEqual(dict(w.store.get_link(3).chats), w.chats)
                    if choice == 'dont_reorder':
                        self.assertEqual(len(w.adapters['claude'].reader.read(w.chats['claude'])), 4)
                        self.assertEqual(len(w.adapters['codex'].reader.read(w.chats['codex'])), 4)
                    else:
                        self.assertEqual(w.adapters[choice].chats, before[choice])
                        self.assertTrue(any('skipped' in t.states.values() for t in w.store.turns(3)))

    def test_show_selected_presets_and_order_notes_and_refused_same_side_move(self):
        with world_for('show-choice') as w:
            self.conflict(w)
            value = run(w, 'merge', show=True, preset='one_side_first', first='claude')
            self.assertEqual(value['outcome']['claude'], 'keeps_chat')
            self.assertTrue({'merge.header', 'merge.order_help', 'merge.keeps_chat', 'merge.merged_copy'} <= {n['id'] for n in value['notes']})
            no_order = run(w, 'merge', show=True, preset='dont_reorder')
            self.assertTrue(all(v == 'keeps_chat' for v in no_order['outcome'].values()))
            self.assertIn('merge.dont_reorder', [n['id'] for n in no_order['notes']])
            ids = value['order']
            with self.assertRaises(OrderNotAllowed): run(w, 'merge', show=True, order=','.join(map(str, [ids[1], ids[0], ids[2]])))

    def test_each_route_refuses_stale_id_and_wrong_command_without_consuming_it(self):
        for command in ('merge', 'undo', 'restore'):
            with self.subTest(command=command), world_for('stale-' + command) as w:
                if command == 'merge':
                    self.conflict(w); args = {'preset': 'by_time'}
                else:
                    event = self.delivery(w, 'codex')
                    if command == 'restore':
                        preview = run(w, 'undo', event=event)
                        event = run(w, 'undo', confirm=preview['plan_id'])['event_id']
                    args = {'event': event}
                value = run(w, command, **args)
                other = 'restore' if command != 'restore' else 'merge'
                with self.assertRaises(WrongPlanAction): run(w, other, confirm=value['plan_id'])
                self.assertIsNotNone(w.engine.plans.store.load(value['plan_id']))
                side = 'claude'
                chat = w.store.get_link(3).chat(side)
                w.adapters[side].chats[chat].append(original(9))
                with self.assertRaises(ChatChanged): run(w, command, confirm=value['plan_id'])

    def test_cut_and_shorter_previews_confirm_and_restore_exact_chat(self):
        for target in ('claude', 'codex'):
            with self.subTest(target=target), world_for('boundary-' + target) as w:
                event = self.delivery(w, target)
                earlier = w.chats[target]
                before = deepcopy(w.adapters[target].chats[earlier])
                value = run(w, 'undo', event=event)
                self.assertTrue(value['notes'])
                self.assertTrue(value['removal_groups'])
                self.assertTrue(all(r['tool'] == target for r in value['removes']))
                if target == 'codex':
                    self.assertIn('undo.shorter', [n['id'] for n in value['notes']])
                    self.assertIn('links it', next(n['text'] for n in value['notes'] if n['id'] == 'undo.shorter'))
                result = run(w, 'undo', confirm=value['plan_id'])
                self.assertTrue(result['applied'])
                current = w.store.get_link(3).chat(target)
                self.assertEqual(len(w.adapters[target].reader.read(current)), 1)
                if target == 'codex': self.assertEqual(w.adapters[target].chats[earlier], before)
                value = run(w, 'restore', event=result['event_id'])
                self.assertTrue(value['notes'])
                self.assertTrue(run(w, 'restore', confirm=value['plan_id'])['applied'])
                self.assertEqual(w.adapters[target].reader.read(w.store.get_link(3).chat(target)), before)

    def test_merge_undo_created_chats_move_link_back_and_remain_untouched(self):
        with world_for('merge-undo-route') as w:
            self.conflict(w)
            value = run(w, 'merge', preset='by_time')
            event = run(w, 'merge', confirm=value['plan_id'])['event_id']
            merged = dict(w.store.get_link(3).chats)
            before = deepcopy({s: w.adapters[s].chats[c] for s, c in merged.items()})
            value = run(w, 'undo', event=event)
            self.assertTrue(value['notes'])
            self.assertTrue(run(w, 'undo', confirm=value['plan_id'])['applied'])
            self.assertEqual(dict(w.store.get_link(3).chats), w.chats)
            self.assertEqual(before, {s: w.adapters[s].chats[c] for s, c in merged.items()})

    def test_history_presentation_and_empty_note(self):
        with world_for('history-presentation') as w:
            w.pair(shared=1)
            value = run(w, 'history')
            for event in value['events']:
                self.assertTrue(event['label']['text'])
                self.assertEqual(event['undo_label']['text'], 'Undo')
                self.assertEqual(event['restore_label']['text'], 'Restore')
            from baton.cli.output import read_history
            self.assertEqual(read_history([])['notes'][0]['id'], 'history.empty')

    def test_every_merge_outcome_has_completion_receipt(self):
        for choice in ('claude', 'codex', 'split', 'dont_reorder', 'by_time'):
            with self.subTest(choice=choice), world_for('completion-' + choice) as w:
                self.conflict(w)
                kwargs = {'split': True} if choice == 'split' else {'keep': choice} if choice in ('claude', 'codex') else {'preset': choice}
                plan = run(w, 'merge', **kwargs)
                result = run(w, 'merge', confirm=plan['plan_id'])
                self.assertTrue(result['applied'])
                expected = 'merge.completed_split' if choice == 'split' else 'merge.completed_keep' if choice in ('claude', 'codex') else 'merge.completed'
                self.assertIn(expected, [n['id'] for n in result['notes']])
                self.assertTrue(all(n['text'] for n in result['notes']))
