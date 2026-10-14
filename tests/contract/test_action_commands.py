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


class CarryOverActionTests(unittest.TestCase):
    def test_closed_app_rename_write_failure_returns_receipt_and_note(self):
        from unittest.mock import patch
        from baton.services.names import Names
        from baton.services.relaunch import Relaunch
        with world_for('closed-rename-failure') as w:
            w.pair(shared=1)
            names = Names(w.store, w.adapters, w.clock)
            rename = names.plan_rename(3, 'New orchard', ['claude'])
            service = Relaunch(w.store, w.adapters, w.clock)
            plan = service.plan_relaunch('claude', rename=rename)
            self.assertFalse(plan.running)
            before = deepcopy(w.adapters['claude'].chats)
            with patch.object(w.adapters['claude'].writer, 'rename', side_effect=OSError('fake write failure')):
                result = service.apply(plan)
            self.assertFalse(result.applied)
            self.assertEqual(result.error, 'OSError')
            self.assertIn('relaunch.write_failed', [n.id for n in result.notes])
            self.assertFalse(result.opened)
            self.assertEqual(before, w.adapters['claude'].chats)
            self.assertFalse(w.store.journal_entries(pending=True))

    def test_notify_delivery_exception_returns_queued_receipt_and_retains_record(self):
        from unittest.mock import patch
        from baton.hooks import HookCall
        from baton.hooks.delivery import notify
        for method in ('prepare', 'apply'):
            with self.subTest(method=method), world_for('queued-delivery-' + method) as w:
                w.pair(shared=1)
                w.seed('claude', [original(2)])
                before = deepcopy(w.adapters['codex'].chats)
                with patch.object(w.engine.applier, method, side_effect=ChatChanged()):
                    receipt = notify(w.engine, 'claude', HookCall(w.chats['claude'], 'finished', 'turn_end'))
                self.assertEqual(receipt['synced'], [])
                self.assertEqual(receipt['queued'], [3])
                self.assertEqual([n['id'] for n in receipt['offers']], ['hook.delivery_failed'])
                self.assertEqual(before, w.adapters['codex'].chats)
                self.assertTrue(any(e.kind == 'turn_end' and e.detail['message_id'] == 'finished'
                                    for e in w.store.history(3)))
                self.assertEqual(w.store.turns(3)[-1].states['codex'], 'waiting')


class DeliveryAndRemovalCommandsTests(unittest.TestCase):
    def test_sync_first_call_and_dry_run_preview_then_confirm_delivers_exact_turns(self):
        for dry_run in (False, True):
            with self.subTest(dry_run=dry_run), world_for('sync-route-' + str(dry_run)) as w:
                w.pair(shared=1)
                w.seed('claude', [original(2)])
                before = deepcopy({s: a.chats for s, a in w.adapters.items()})
                args = SimpleNamespace(link=3, to='codex')
                value = REGISTRY.get('sync').run(Context(w.engine, 'sync', dry_run=dry_run), args)
                self.assertFalse(value['applied'])
                self.assertTrue(value['notes'])
                self.assertEqual(before, {s: a.chats for s, a in w.adapters.items()})
                self.assertEqual([s['tool'] for s in value['steps']], ['codex'])
                self.assertTrue(run(w, 'sync', confirm=value['plan_id'])['applied'])
                self.assertEqual([t.prompt.text for t in w.adapters['codex'].reader.read(w.chats['codex'])],
                                 ['Orchard task 1', 'Orchard task 2'])
                self.assertEqual(w.store.turns(3)[-1].states['codex'], 'shown')

    def test_unlink_preview_then_confirm_changes_only_link_record_including_paused(self):
        for paused in (False, True):
            with self.subTest(paused=paused), world_for('unlink-route-' + str(paused)) as w:
                w.pair(shared=1)
                w.seed('claude', [original(2)])
                w.store.set_paused(3, paused, w.clock.now())
                before = deepcopy({s: a.chats for s, a in w.adapters.items()})
                value = run(w, 'unlink')
                self.assertFalse(value['applied'])
                self.assertTrue(value['notes'])
                self.assertFalse(w.store.get_link(3).removed_at)
                self.assertTrue(run(w, 'unlink', confirm=value['plan_id'])['applied'])
                self.assertTrue(w.store.get_link(3).removed_at)
                self.assertEqual(before, {s: a.chats for s, a in w.adapters.items()})

    def test_sync_and_unlink_refuse_stale_and_wrong_command_without_consuming_plan(self):
        for command in ('sync', 'unlink'):
            with self.subTest(command=command), world_for('stale-' + command) as w:
                w.pair(shared=1)
                w.seed('claude', [original(2)])
                value = run(w, command)
                other = 'unlink' if command == 'sync' else 'sync'
                with self.assertRaises(WrongPlanAction):
                    run(w, other, confirm=value['plan_id'])
                self.assertIsNotNone(w.engine.plans.store.load(value['plan_id']))
                if command == 'sync':
                    w.adapters['claude'].chats[w.chats['claude']].append(original(3))
                else:
                    w.store.set_paused(3, True, w.clock.now())
                with self.assertRaises(ChatChanged):
                    run(w, command, confirm=value['plan_id'])

    def test_paused_sync_is_only_a_hold_and_never_writes_or_queues_attachment(self):
        with world_for('paused-sync-route') as w:
            w.pair(shared=1)
            w.seed('claude', [original(2)])
            w.store.set_paused(3, True, w.clock.now())
            before = deepcopy({s: a.chats for s, a in w.adapters.items()})
            value = run(w, 'sync')
            self.assertTrue(value['notes'])
            self.assertTrue(all(s['action'] == 'hold' for s in value['steps']))
            run(w, 'sync', confirm=value['plan_id'])
            self.assertEqual(before, {s: a.chats for s, a in w.adapters.items()})
            self.assertEqual(w.store.turns(3)[-1].states['codex'], 'waiting')
            self.assertFalse(any(e.kind == 'attach_pending' for e in w.store.history(3)))


class ActionBoundaryTests(unittest.TestCase):
    def test_hook_real_change_after_preparation_returns_queued_only(self):
        from unittest.mock import patch
        from baton.hooks import HookCall
        from baton.hooks.delivery import notify
        with world_for('hook-actual-race') as w:
            w.pair(shared=1)
            w.seed('claude', [original(2)])
            prepare = w.engine.applier.prepare
            def changed(*args, **kwargs):
                plan = prepare(*args, **kwargs)
                w.adapters['codex'].chats[w.chats['codex']].append(original(3))
                return plan
            with patch.object(w.engine.applier, 'prepare', side_effect=changed):
                result = notify(w.engine, 'claude', HookCall(w.chats['claude'], 'finished', 'turn_end'))
            self.assertEqual(result['synced'], [])
            self.assertEqual(result['queued'], [3])
            self.assertEqual(result['offers'][0]['id'], 'hook.delivery_failed')
            self.assertEqual([t.prompt.text for t in w.adapters['codex'].reader.read(w.chats['codex'])],
                             ['Orchard task 1', 'Orchard task 3'])
            self.assertEqual(w.store.turns(3)[-1].states['codex'], 'waiting')

    def test_pause_after_sync_preview_refuses_confirmation_and_preserves_chats(self):
        with world_for('sync-pause-after-preview') as w:
            w.pair(shared=1)
            w.seed('claude', [original(2)])
            value = run(w, 'sync')
            before = deepcopy({s: a.chats for s, a in w.adapters.items()})
            w.store.set_paused(3, True, w.clock.now())
            with self.assertRaises(ChatChanged):
                run(w, 'sync', confirm=value['plan_id'])
            self.assertEqual(before, {s: a.chats for s, a in w.adapters.items()})

    def test_unlink_missing_native_chat_needs_no_content_read(self):
        from unittest.mock import patch
        with world_for('unlink-missing-chat') as w:
            w.pair(shared=1)
            w.adapters['codex'].chats.pop(w.chats['codex'])
            with patch.object(w.adapters['codex'].reader, 'read', side_effect=AssertionError('content read')):
                value = run(w, 'unlink')
                self.assertTrue(value['notes'])
                self.assertTrue(run(w, 'unlink', confirm=value['plan_id'])['applied'])

    def test_sync_queue_attach_conflict_and_write_failure_receipts(self):
        from unittest.mock import patch
        for outcome in ('attach', 'conflict', 'failed'):
            with self.subTest(outcome=outcome), world_for('sync-' + outcome) as w:
                w.pair(shared=1)
                w.seed('claude', [original(2)])
                if outcome == 'attach':
                    w.condition('codex', open=True, app_running=True)
                elif outcome == 'conflict':
                    w.seed('codex', [original(3)])
                value = run(w, 'sync')
                self.assertTrue(value['notes'])
                before = deepcopy({s: a.chats for s, a in w.adapters.items()})
                if outcome == 'conflict':
                    from baton.domain.errors import DecisionNeeded
                    self.assertTrue(value['decision_needed'])
                    with self.assertRaises(DecisionNeeded):
                        run(w, 'sync', confirm=value['plan_id'])
                elif outcome == 'failed':
                    with patch.object(w.adapters['codex'].writer, 'add', side_effect=OSError('fake failure')):
                        receipt = run(w, 'sync', confirm=value['plan_id'])
                    self.assertFalse(receipt['applied'])
                    self.assertEqual(receipt['error']['kind'], 'o_s_error')
                    self.assertTrue(receipt['error']['note']['text'])
                else:
                    attach = next(n['values']['attach_plan_id'] for n in value['notes'] if 'attach_plan_id' in n['values'])
                    self.assertTrue(run(w, 'sync', confirm=attach)['applied'])
                    self.assertEqual(w.store.turns(3)[-1].states['codex'], 'waiting')
                    self.assertTrue(any(e.kind == 'attach_pending' for e in w.store.history(3)))
                self.assertEqual(before, {s: a.chats for s, a in w.adapters.items()})

    def test_sync_and_unlink_through_parser_use_notes_and_stored_arguments(self):
        from baton.cli.main import main
        import io
        import json
        for command in ('sync', 'unlink'):
            with self.subTest(command=command), world_for('parser-' + command) as w:
                w.pair(shared=1)
                w.seed('claude', [original(2)])
                from contextlib import nullcontext
                from unittest.mock import patch
                # World already owns the lock and closes its engine on exit.
                with patch.object(w.engine, 'command_lock', side_effect=nullcontext), patch.object(w.engine, 'close'):
                    stream = io.StringIO()
                    self.assertEqual(main([command, '--link', '3', '--dry-run', '--json'],
                                          engine_factory=lambda: w.engine, stdout=stream), 0)
                    value = json.loads(stream.getvalue())
                    self.assertTrue(value['notes'])
                    stream = io.StringIO()
                    self.assertEqual(main([command, '--confirm', value['plan_id'], '--json'],
                                          engine_factory=lambda: w.engine, stdout=stream), 0)
                    self.assertTrue(json.loads(stream.getvalue())['applied'])


class C3CompletionTests(unittest.TestCase):
    def request(self, w, command):
        if command in ('link', 'copy'):
            source = w.chat('claude', 'source', [original(1), original(2)])
            return {'source': 'claude:' + source, 'to': 'opencode', 'mode': 'full_copy'}
        w.pair(shared=1)
        if command == 'relink':
            return {'to': 'opencode', 'keep': 'claude', 'mode': 'full_copy'}
        if command == 'rename':
            return {'name': 'Chosen name', 'tools': 'codex'}
        w.seed('claude', [original(2)])
        return {'destination': 'codex'}

    def test_each_new_planned_command_has_notes_and_applies_its_fake_effect(self):
        for command in ('link', 'copy', 'relink', 'rename', 'continue'):
            with self.subTest(command=command), world_for('c3-' + command) as w:
                args = self.request(w, command)
                before = deepcopy({s: a.chats for s, a in w.adapters.items()})
                value = run(w, command, **args)
                self.assertFalse(value['applied'])
                self.assertTrue(value['notes'])
                self.assertEqual(before, {s: a.chats for s, a in w.adapters.items()})
                result = run(w, command, confirm=value['plan_id'])
                self.assertTrue(result['applied'], result)
                if command in ('link', 'copy', 'relink'):
                    self.assertEqual(len(w.adapters['opencode'].reader.read(result['chat_id'])), 2 if command in ('link', 'copy') else 1)
                    self.assertEqual(bool(w.store.link_for('opencode', result['chat_id'])), command != 'copy')
                elif command == 'rename':
                    self.assertEqual(w.adapters['codex'].locator.name(w.chats['codex']), 'Chosen name')
                else:
                    self.assertTrue(result['opened'])
                    self.assertEqual(len(w.adapters['codex'].reader.read(w.chats['codex'])), 2)
                    self.assertTrue(any(c[0] == 'open' for c in w.adapters['codex'].app.calls))
                with self.assertRaises(ChatChanged):
                    run(w, command, confirm=value['plan_id'])

    def test_new_plans_refuse_native_staleness_and_wrong_command_without_claim(self):
        for command in ('link', 'copy', 'relink', 'rename', 'continue'):
            with self.subTest(command=command), world_for('c3-stale-' + command) as w:
                value = run(w, command, **self.request(w, command))
                other = 'copy' if command != 'copy' else 'rename'
                with self.assertRaises(WrongPlanAction): run(w, other, confirm=value['plan_id'])
                self.assertIsNotNone(w.engine.plans.store.load(value['plan_id']))
                chat = next(iter(w.adapters['claude'].chats))
                w.adapters['claude'].chats[chat].append(original(9))
                with self.assertRaises(ChatChanged): run(w, command, confirm=value['plan_id'])

    def test_r9_replacement_and_existing_retained_side_relink(self):
        for action in ('replace', 'relink'):
            with self.subTest(action=action), world_for('c3-r9-' + action) as w:
                w.pair(shared=1)
                old = deepcopy(w.adapters['codex'].chats[w.chats['codex']])
                if action == 'replace':
                    command, args = 'link', {'replace': 'codex', 'mode': 'full_copy'}
                else:
                    target = w.chat('opencode', 'existing', [original(1)])
                    command, args = 'relink', {'to': 'opencode:' + target, 'keep': 'claude', 'mode': 'attached_history'}
                plan = run(w, command, **args)
                self.assertTrue(plan['notes'])
                result = run(w, command, confirm=plan['plan_id'])
                self.assertTrue(result['applied'])
                self.assertEqual(w.adapters['codex'].chats[w.chats['codex']], old)
                link = w.store.get_link(result['link_id'])
                self.assertEqual(link.chat('claude'), w.chats['claude'])
                if action == 'replace': self.assertNotEqual(link.chat('codex'), w.chats['codex'])
                else: self.assertEqual(link.chat('opencode'), target)

    def test_paused_link_guards_at_preview_and_after_preview(self):
        from baton.domain.errors import LinkPaused
        for command, args in (('link', {'replace': 'codex', 'mode': 'full_copy'}),
                              ('relink', {'to': 'opencode', 'keep': 'claude'}),
                              ('rename', {'name': 'No write', 'tools': 'codex'}),
                              ('continue', {'destination': 'codex'})):
            for after in (False, True):
                with self.subTest(command=command, after=after), world_for('c3-paused') as w:
                    w.pair(shared=1)
                    value = run(w, command, **args) if after else None
                    run(w, 'pause')
                    before = deepcopy({s: a.chats for s, a in w.adapters.items()})
                    with self.assertRaises(ChatChanged if after else LinkPaused):
                        run(w, command, confirm=value['plan_id']) if after else run(w, command, **args)
                    self.assertEqual(before, {s: a.chats for s, a in w.adapters.items()})

    def test_service_pause_checks_immediately_before_native_mutation(self):
        from unittest.mock import patch
        from baton.services.names import Names
        for action in ('replace', 'relink', 'rename'):
            with self.subTest(action=action), world_for('c3-race') as w:
                w.pair(shared=1)
                service = Names(w.store, w.adapters, w.clock) if action == 'rename' else w.engine.linker
                planned = service.plan_rename(3, 'Blocked', ['codex']) if action == 'rename' else (
                    service.plan_full_copy(3, 'codex') if action == 'replace' else service.plan_relink(3, 'opencode', from_side='claude'))
                before = deepcopy({s: a.chats for s, a in w.adapters.items()})
                begin = service.journal.begin
                def pause_at_begin(*args, **kwargs):
                    entry = begin(*args, **kwargs)
                    w.store.set_paused(3, True, w.clock.now())
                    return entry
                with patch.object(service.journal, 'begin', side_effect=pause_at_begin):
                    if action == 'rename':
                        from baton.domain.errors import LinkPaused
                        with self.assertRaises(LinkPaused): service.apply(planned)
                    else:
                        self.assertFalse(service.apply(planned).applied)
                self.assertEqual(before, {s: a.chats for s, a in w.adapters.items()})

    def test_paused_source_allows_read_only_standalone_copy_preserving_link_and_chats(self):
        from dataclasses import asdict
        from baton.domain.errors import LinkPaused
        with world_for('c3-paused-copy') as w:
            w.pair(shared=1)
            run(w, 'pause')
            before_link = asdict(w.store.get_link(3))
            before_turns = w.store.turns(3)
            before_history = w.store.history(3)
            before_chats = deepcopy({s: a.chats for s, a in w.adapters.items() if s != 'opencode'})
            args = {'source': 'claude:' + w.chats['claude'], 'to': 'opencode'}
            value = run(w, 'copy', **args)
            self.assertTrue(run(w, 'copy', confirm=value['plan_id'])['applied'])
            self.assertEqual(asdict(w.store.get_link(3)), before_link)
            self.assertEqual(w.store.turns(3), before_turns)
            self.assertEqual(w.store.history(3), before_history)
            self.assertEqual(before_chats, {s: a.chats for s, a in w.adapters.items() if s != 'opencode'})
            with self.assertRaises(LinkPaused): run(w, 'copy', and_link=True, **args)

    def test_immediate_marks_return_notes_and_only_change_records(self):
        from baton.domain.errors import NotAvailable
        with world_for('c3-immediate') as w:
            w.pair(shared=1)
            ids = w.seed('claude', [original(2)])
            before = deepcopy({s: a.chats for s, a in w.adapters.items()})
            for action, key, expected in (('keep', 'states', 'kept_back'), ('send', 'states', 'waiting'),
                                          ('pin', 'pinned', True), ('unpin', 'pinned', False)):
                value = run(w, action, turn=ids[0])
                self.assertTrue(value['notes'])
                self.assertEqual(value['turn'][key]['codex'] if key == 'states' else value['turn'][key], expected)
                with self.assertRaises(NotAvailable): run(w, action, turn=999999)
            for action, paused in (('pause', True), ('resume', False)):
                value = run(w, action)
                self.assertEqual(value['paused'], paused)
                self.assertTrue(value['notes'])
                with self.assertRaises(NotAvailable): run(w, action, link=999999)
            self.assertEqual(before, {s: a.chats for s, a in w.adapters.items()})

    def test_open_chat_or_folder_selects_note_before_app_call_and_refuses_missing(self):
        from unittest.mock import patch
        from baton.services.continue_open import ContinueOpen
        from baton.domain.errors import NotAvailable
        with world_for('c3-open') as w:
            for side in ('codex', 'opencode'):
                chat = w.chat(side, side + '-open', [original(1)])
                service = ContinueOpen(w.store, w.adapters)
                expected = service.opening(side, chat)
                self.assertTrue(expected['note'])
                value = run(w, 'open', tool=side, chat=chat)
                self.assertEqual(value['opened'], 'chat' if side == 'codex' else 'folder')
                self.assertTrue(value['note']['text'])
                self.assertIn(('open', chat if side == 'codex' else None, expected['folder']), w.adapters[side].app.calls)
                with self.assertRaises(NotAvailable): run(w, 'open', tool=side, chat='missing')

    def test_continue_failure_conflict_and_held_delivery_never_open(self):
        from unittest.mock import patch
        for case in ('conflict', 'attach', 'hold', 'failure'):
            with self.subTest(case=case), world_for('c3-continue-' + case) as w:
                w.pair(shared=1)
                w.seed('claude', [original(2)])
                if case == 'conflict': w.seed('codex', [original(3)])
                if case in ('attach', 'hold'): w.condition('codex', open=True, hooks_ready=case == 'attach')
                value = run(w, 'continue', destination='codex')
                if case == 'failure':
                    with patch.object(w.adapters['codex'].writer, 'add', side_effect=OSError):
                        result = run(w, 'continue', confirm=value['plan_id'])
                else: result = run(w, 'continue', confirm=value['plan_id'])
                self.assertFalse(result['opened'])
                self.assertFalse(result['applied'])
                self.assertTrue(result['notes'])
                self.assertFalse(any(c[0] == 'open' for c in w.adapters['codex'].app.calls))

    def test_settings_parse_every_type_validate_choices_and_bounds_before_save(self):
        from baton.services.settings_write import InvalidSetting
        with world_for('c3-settings') as w:
            for key, raw, value in (('notice_on_attach', 'false', False), ('offer_relaunch', 'true', True),
                    ('offer_switch_at_limit', 'false', False), ('hide_script_chats', 'false', False),
                    ('title_tag', 'false', False), ('add_to_idle_claude', 'automatic', 'automatic'),
                    ('merge', 'by_time', 'by_time'), ('theme', 'graphite', 'graphite'),
                    ('glass', '40.5', 40.5), ('glass', '95', 95), ('brief_threshold_tokens', '12000', 12000)):
                result = run(w, 'settings set', key=key, value=raw)
                self.assertEqual(result['settings'][key], value)
                self.assertTrue(result['notes'])
                self.assertEqual(w.store.settings_values()[key], value)
            before = w.store.settings_values()
            for key, raw in (('unknown', '1'), ('theme', 'dark'), ('merge', 'auto'), ('glass', '39'),
                    ('glass', '96'), ('glass', 'NaN'), ('glass', 'Infinity'), ('glass', 'true'),
                    ('brief_threshold_tokens', '0'), ('brief_threshold_tokens', '2.5'),
                    ('notice_on_attach', '1'), ('notice_on_attach', 'yes'), ('add_to_idle_claude', 'yes')):
                with self.subTest(key=key, value=raw), self.assertRaises(InvalidSetting):
                    run(w, 'settings set', key=key, value=raw)
            self.assertEqual(w.store.settings_values(), before)

    def test_brief_link_and_relink_keep_both_review_stages_and_command_identity(self):
        from unittest.mock import patch
        for command in ('link', 'relink'):
            with self.subTest(command=command), world_for('c3-brief-' + command) as w:
                if command == 'link':
                    source = w.chat('claude', 'source', [original(1), original(2)])
                    args = {'source': 'claude:' + source, 'to': 'codex', 'mode': 'brief'}
                else:
                    w.pair()
                    args = {'to': 'opencode', 'keep': 'claude', 'mode': 'brief'}
                tasks = []
                w.engine.background_dispatch = tasks.append
                before = deepcopy({s: a.chats for s, a in w.adapters.items()})
                with patch('subprocess.run', side_effect=AssertionError('process')):
                    preview = run(w, command, **args)
                    self.assertEqual(preview['stage'], 'generate')
                    self.assertTrue(preview['notes'])
                    self.assertFalse(any(a.runner.calls for a in w.adapters.values()))
                    with self.assertRaises(WrongPlanAction): run(w, 'rename', confirm=preview['plan_id'])
                    queued = run(w, command, confirm=preview['plan_id'])
                    self.assertEqual(before, {s: a.chats for s, a in w.adapters.items()})
                    tasks.pop()()
                    reviewed = run(w, command, status=queued['request_id'])['result']
                    self.assertEqual(reviewed['stage'], 'create')
                    self.assertTrue(reviewed['brief']['text'])
                    self.assertEqual(before, {s: a.chats for s, a in w.adapters.items()})
                    with self.assertRaises(WrongPlanAction): run(w, 'copy', confirm=reviewed['plan_id'])
                    self.assertTrue(run(w, command, confirm=reviewed['plan_id'])['applied'])
                    with self.assertRaises(ChatChanged): run(w, command, confirm=reviewed['plan_id'])

    def test_rename_running_app_closes_writes_and_reopens_via_service(self):
        with world_for('c3-rename-lifecycle') as w:
            w.pair()
            w.adapters['claude'].app_running = True
            preview = run(w, 'rename', name='One title')
            self.assertIn('close', [s['action'] for s in preview['steps']])
            result = run(w, 'rename', confirm=preview['plan_id'])
            self.assertTrue(result['applied'], result)
            self.assertTrue(w.adapters['claude'].app_running)
            self.assertEqual(w.adapters['claude'].locator.name(w.chats['claude']), 'One title')
            self.assertEqual(w.adapters['codex'].locator.name(w.chats['codex']), 'One title')
            calls = w.adapters['claude'].app.calls
            self.assertTrue(any(c[0] == 'close' for c in calls))
            self.assertTrue(any(c[0] == 'open' for c in calls))

    def test_rename_replying_app_does_not_close_or_rename(self):
        with world_for('c3-rename-replying') as w:
            w.pair()
            w.adapters['claude'].app_running = True
            w.condition('claude', open=True, replying=True)
            before = w.adapters['claude'].locator.name(w.chats['claude'])
            preview = run(w, 'rename', name='Blocked', tools='claude')
            result = run(w, 'rename', confirm=preview['plan_id'])
            self.assertFalse(result['applied'])
            self.assertEqual(w.adapters['claude'].locator.name(w.chats['claude']), before)
            self.assertFalse(any(c[0] == 'close' for c in w.adapters['claude'].app.calls))

    def test_immediate_actions_and_settings_have_no_plan_flags_in_parser(self):
        from baton.cli.main import build_parser
        parser = build_parser(REGISTRY)
        for command in ('pause', 'resume', 'keep', 'send', 'pin', 'unpin', 'open', 'settings set'):
            self.assertFalse(REGISTRY.get(command).plan)
        parsed = parser.parse_args(['link', '--from', 'claude:source', '--to', 'codex', '--dry-run', '--json'])
        self.assertEqual(parsed.source, 'claude:source')
        parsed = parser.parse_args(['relink', '--link', '3', '--to', 'opencode:target', '--keep', 'claude', '--mode', 'attached_history'])
        self.assertEqual(parsed.keep, 'claude')
        parsed = parser.parse_args(['settings', 'set', 'glass', '62'])
        self.assertEqual((parsed.key, parsed.value), ('glass', '62'))

    def test_settings_failed_save_returns_catalogue_error(self):
        from unittest.mock import patch
        from baton.services.settings_write import SettingSaveFailed
        with world_for('c3-settings-failure') as w:
            before = w.engine.settings_read.get()
            with patch.object(w.store, 'save_setting', side_effect=OSError):
                with self.assertRaises(SettingSaveFailed) as error:
                    run(w, 'settings set', key='glass', value='70')
            self.assertEqual(error.exception.note_id, 'settings.error')
            self.assertEqual(w.engine.settings_read.get(), before)

    def test_link_existing_chats_and_copy_and_link_apply_with_notes(self):
        for command in ('link', 'copy'):
            with self.subTest(command=command), world_for('c3-existing-' + command) as w:
                source = w.chat('claude', 'existing-source', [original(1)])
                target = w.chat('codex', 'existing-target', [original(1)])
                args = {'source': 'claude:' + source, 'to': 'codex:' + target, 'mode': 'attached_history'} if command == 'link' else {
                    'source': 'claude:' + source, 'to': 'opencode', 'and_link': True}
                preview = run(w, command, **args)
                self.assertTrue(preview['notes'])
                result = run(w, command, confirm=preview['plan_id'])
                self.assertTrue(result['applied'])
                self.assertEqual(w.store.get_link(result['link_id']).chat('claude'), source)
                if command == 'link': self.assertEqual(w.store.get_link(result['link_id']).chat('codex'), target)

    def test_metadata_relink_rechecks_pause_before_replacing_records(self):
        from unittest.mock import patch
        with world_for('c3-metadata-race') as w:
            w.pair(shared=1)
            target = w.chat('opencode', 'target', [original(1)])
            service = w.engine.linker
            planned = service.plan_relink(3, 'opencode', target, from_side='claude')
            old_chats = dict(w.store.get_link(3).chats)
            resolve = w.adapters['opencode'].locator.resolve
            def pause_before_records(ident):
                ref = resolve(ident)
                w.store.set_paused(3, True, w.clock.now())
                return ref
            # Observation validation is complete before the final metadata lookup.
            with patch.object(service, '_validate'), patch.object(w.adapters['opencode'].locator, 'resolve', side_effect=pause_before_records):
                result = service.apply(planned)
            self.assertFalse(result.applied)
            self.assertEqual(dict(w.store.get_link(3).chats), old_chats)
            self.assertEqual(len(w.store.links()), 1)


class C3ReviewRoundOneTests(unittest.TestCase):
    def assert_plan_schema(self, value):
        self.assertIsInstance(value['plan_id'], str)
        self.assertIsInstance(value['applied'], bool)
        self.assertTrue(value['link_id'] is None or isinstance(value['link_id'], int))
        self.assertIsInstance(value['decision_needed'], bool)
        self.assertIsInstance(value['notes'], list)
        self.assertIsInstance(value['steps'], list)
        for step in value['steps']:
            for key in ('tool', 'tool_label', 'action', 'turns', 'reason', 'needs', 'notes'):
                self.assertIn(key, step)
            for note in step['notes'] + value['notes']:
                for key in ('id', 'tone', 'values', 'text', 'buttons', 'status_line'):
                    self.assertIn(key, note)

    def test_command_dispatches_brief_policy_to_public_service(self):
        from unittest.mock import patch
        from baton.services.brief_link import BriefLink
        with world_for('c3-review-dispatch') as w:
            source = w.chat('claude', 'source', [original(1)])
            calls = []
            class RecordingService(BriefLink):
                def preview(self, prepare, request):
                    calls.append('preview')
                    return super().preview(prepare, request)
                def confirm(self, token, review, dispatch, publish):
                    calls.append('confirm')
                    return super().confirm(token, review, dispatch, publish)
                def status(self, ident, cancel=False):
                    calls.append('cancel' if cancel else 'status')
                    return super().status(ident, cancel)
            tasks = []
            w.engine.background_dispatch = tasks.append
            with patch('baton.cli.commands.link_action.BriefLink', RecordingService):
                preview = run(w, 'link', source='claude:' + source, to='codex', mode='brief')
                queued = run(w, 'link', confirm=preview['plan_id'])
                polled = run(w, 'link', status=queued['request_id'])
                cancelled = run(w, 'link', cancel=queued['request_id'])
            self.assertEqual(calls, ['preview', 'confirm', 'status', 'status', 'cancel'])
            self.assert_plan_schema(polled)
            self.assert_plan_schema(cancelled)
            self.assertEqual(cancelled['state'], 'cancelled')
            self.assertFalse(any(a.runner.calls for a in w.adapters.values()))

    def test_brief_link_public_service_owns_preview_and_both_stages(self):
        from baton.services.brief_link import BriefLink
        from unittest.mock import patch
        for command in ('link', 'relink'):
            with self.subTest(command=command), world_for('c3-review-brief') as w:
                source = w.chat('claude', 'source', [original(1)])
                if command == 'relink':
                    w.pair()
                    args = {'to': 'opencode', 'keep': 'claude', 'mode': 'brief'}
                else:
                    args = {'source': 'claude:' + source, 'to': 'codex', 'mode': 'brief'}
                tasks = []
                w.engine.background_dispatch = tasks.append
                preview = run(w, command, **args)
                self.assert_plan_schema(preview)
                self.assertFalse(any(a.runner.calls for a in w.adapters.values()))
                queued = run(w, command, confirm=preview['plan_id'])
                self.assert_plan_schema(queued)
                self.assertEqual(queued['state'], 'pending')
                self.assertIsNone(queued['confirmation'])
                self.assert_plan_schema(run(w, command, status=queued['request_id']))
                tasks.pop()()
                polled = run(w, command, status=queued['request_id'])
                self.assert_plan_schema(polled)
                review = polled['result']
                self.assert_plan_schema(review)
                self.assertEqual(w.engine.plans.store.load(review['plan_id']).command, command)
                receipt = run(w, command, confirm=review['plan_id'])
                self.assert_plan_schema(receipt)
                self.assertTrue(receipt['applied'])
        with world_for('c3-review-service') as w:
            source = w.chat('claude', 'source', [original(1)])
            runner = w.adapters['codex'].runner
            with patch.object(runner, 'available', side_effect=AssertionError('spawning readiness')):
                service = BriefLink(w.engine)
                planned = service.preview(lambda r: w.engine.linker.plan_link('claude', source, 'codex', mode='brief'), {})
                self.assertEqual(planned.stage, 'generate')
                self.assertIs(w.adapters['codex'].runner, runner)

    def test_running_creation_offers_executable_close_create_reopen(self):
        with world_for('c3-review-create') as w:
            source = w.chat('claude', 'source', [original(1)])
            w.adapters['cursor'].app_running = True
            preview = run(w, 'copy', source='claude:' + source, to='cursor')
            self.assert_plan_schema(preview)
            self.assertIn('new_chat.relaunch', [n['id'] for n in preview['notes']])
            self.assertNotIn('create.close_manually', [n['id'] for n in preview['notes']])
            before = deepcopy(w.adapters['cursor'].chats)
            self.assertEqual(w.adapters['cursor'].chats, before)
            self.assertFalse(any(c[0] in ('close', 'open') for c in w.adapters['cursor'].app.calls))
            self.assertTrue(run(w, 'copy', confirm=preview['plan_id'])['applied'])
            self.assertEqual([c[0] for c in w.adapters['cursor'].app.calls if c[0] in ('close', 'open')], ['close', 'open'])

    def test_rename_actions_are_documented_and_complete_in_preview_and_receipt(self):
        from pathlib import Path
        contract = Path('docs/plan/CONTRACT.md').read_text()
        with world_for('c3-review-rename') as w:
            w.pair()
            w.adapters['claude'].app_running = True
            preview = run(w, 'rename', name='Chosen title')
            self.assert_plan_schema(preview)
            for action in ('rename', 'wait_until_still'):
                self.assertIn(action, [s['action'] for s in preview['steps']])
                self.assertIn('`' + action + '`', contract)
            self.assert_plan_schema(run(w, 'rename', confirm=preview['plan_id']))

    def test_large_json_integer_settings_never_overflow_validation(self):
        from baton.services.settings_write import InvalidSetting
        with world_for('c3-review-integer') as w:
            huge = 10 ** 400
            before = w.store.settings_values()
            with self.assertRaises(InvalidSetting):
                run(w, 'settings set', key='glass', value=str(huge))
            self.assertEqual(w.store.settings_values(), before)
            result = run(w, 'settings set', key='brief_threshold_tokens', value=str(huge))
            self.assertEqual(result['settings']['brief_threshold_tokens'], huge)
            self.assertEqual(w.store.settings_values()['brief_threshold_tokens'], huge)

    def test_open_flushes_displayed_note_before_public_execution_and_app_open(self):
        from contextlib import redirect_stderr
        from unittest.mock import patch
        from baton.services.continue_open import ContinueOpen
        from baton.domain.errors import NotAvailable
        for side in ('codex', 'opencode'):
            with self.subTest(side=side), world_for('c3-review-open') as w:
                chat = w.chat(side, 'open-target', [original(1)])
                events = []
                class Display:
                    def write(self, text): events.append(('display', text))
                    def flush(self): events.append(('flush',))
                execute = ContinueOpen.execute_open
                app_open = w.adapters[side].app.open
                def execution(service, prepared):
                    events.append(('execute',))
                    return execute(service, prepared)
                def opening(*args):
                    events.append(('app',))
                    return app_open(*args)
                with redirect_stderr(Display()), patch.object(ContinueOpen, 'execute_open', execution), patch.object(w.adapters[side].app, 'open', side_effect=opening):
                    result = run(w, 'open', tool=side, chat=chat)
                    self.assertEqual([e[0] for e in events], ['display', 'flush', 'execute', 'app'])
                    self.assertEqual(events[0][1], result['note']['text'] + '\n')
                    events.clear()
                    with self.assertRaises(NotAvailable):
                        run(w, 'open', tool=side, chat='missing')
                    self.assertEqual(events, [])

    def test_prepared_open_revalidates_before_app_control(self):
        from baton.services.continue_open import ContinueOpen
        with world_for('c3-review-open-stale') as w:
            chat = w.chat('codex', 'open-target', [original(1)])
            service = ContinueOpen(w.store, w.adapters)
            prepared = service.opening('codex', chat)
            w.adapters['codex'].writer.rename(chat, 'Changed title')
            with self.assertRaises(ChatChanged):
                service.execute_open(prepared)
            self.assertFalse(any(c[0] == 'open' for c in w.adapters['codex'].app.calls))


class ReviewRoundTwoTests(unittest.TestCase):
    def test_brief_creation_running_destination_relaunches_link_and_relink(self):
        for command in ('link', 'relink'):
            with self.subTest(command=command), world_for('round2-' + command) as w:
                if command == 'link':
                    source = w.chat('claude', 'source', [original(1)])
                    args = {'source': 'claude:' + source, 'to': 'cursor', 'mode': 'brief'}
                else:
                    w.pair()
                    args = {'to': 'cursor', 'keep': 'claude', 'mode': 'brief'}
                w.adapters['cursor'].app_running = True
                tasks = []
                w.engine.background_dispatch = tasks.append
                preview = run(w, command, **args)
                accepted = run(w, command, confirm=preview['plan_id'])
                tasks.pop()()
                review = run(w, command, status=accepted['request_id'])['result']
                self.assertEqual(review['stage'], 'create')
                self.assertIn('new_chat.relaunch', [n['id'] for n in review['notes']])
                self.assertEqual(review['confirmation']['id'], 'plan.confirm_brief_creation')
                before = deepcopy(w.adapters['cursor'].chats)
                artifact = deepcopy(w.store.brief_artifact(review['brief']['artifact_id']))
                self.assertFalse(any(c[0] in ('open', 'close') for c in w.adapters['cursor'].app.calls))
                receipt = run(w, command, confirm=review['plan_id'])
                self.assertTrue(receipt['applied'], receipt)
                self.assertEqual(w.store.brief_artifact(review['brief']['artifact_id']), artifact)
                self.assertEqual([c[0] for c in w.adapters['cursor'].app.calls if c[0] in ('close', 'open')], ['close', 'open'])
                for chat, content in before.items():
                    self.assertEqual(w.adapters['cursor'].chats[chat], content)

    def test_offline_brief_creation_review_also_checks_running_destination(self):
        for command in ('link', 'relink'):
            with self.subTest(command=command), world_for('round2-offline') as w:
                if command == 'link':
                    source = w.chat('claude', 'source', [original(1)])
                    args = {'source': 'claude:' + source, 'to': 'cursor', 'mode': 'brief'}
                else:
                    w.pair(); args = {'to': 'cursor', 'keep': 'claude', 'mode': 'brief'}
                for adapter in w.adapters.values(): adapter.runner = None
                w.adapters['cursor'].app_running = True
                review = run(w, command, **args)
                self.assertEqual(review['stage'], 'create')
                self.assertIn('new_chat.relaunch', [n['id'] for n in review['notes']])
                self.assertEqual(review['confirmation']['id'], 'plan.confirm_brief_creation')
                alias = next(n['values']['relaunch_plan_id'] for n in review['notes'] if 'relaunch_plan_id' in n['values'])
                self.assertTrue(run(w, 'relaunch', confirm=alias)['applied'])

    def test_background_preserves_accepted_notes_on_accept_poll_complete_and_cancel(self):
        for command in ('link', 'relink'):
            for cancel in (False, True):
                with self.subTest(command=command, cancel=cancel), world_for('round2-notes') as w:
                    if command == 'link':
                        source = w.chat('claude', 'source', [original(1)])
                        args = {'source': 'claude:' + source, 'to': 'codex', 'mode': 'brief'}
                    else:
                        w.pair(); args = {'to': 'opencode', 'keep': 'claude', 'mode': 'brief'}
                    tasks = []; w.engine.background_dispatch = tasks.append
                    preview = run(w, command, **args)
                    self.assertIn('brief.cost', [n['id'] for n in preview['notes']])
                    accepted = run(w, command, confirm=preview['plan_id'])
                    def assert_notes(value):
                        self.assertEqual(value['notes'][:-1], preview['notes'])
                        self.assertEqual(value['notes'][-1]['id'], 'background.' + value['state'])
                    assert_notes(accepted)
                    assert_notes(run(w, command, status=accepted['request_id']))
                    if cancel:
                        from baton.services.background import Background
                        Background(w.store, w.engine.clock).begin(accepted['request_id'])
                        running = run(w, command, status=accepted['request_id'])
                        self.assertEqual(running['state'], 'running')
                        assert_notes(running)
                        assert_notes(run(w, command, cancel=accepted['request_id']))
                    else:
                        tasks.pop()()
                        assert_notes(run(w, command, status=accepted['request_id']))

    def test_mark_seen_command_parser_selective_idempotent_and_refuses_other_visibility(self):
        from baton.cli.main import build_parser
        from baton.domain.errors import NotAvailable
        parser = build_parser(REGISTRY)
        args = parser.parse_args(['mark-seen', '--link', '3', '--tool', 'opencode', '--turns', '42'])
        self.assertEqual(args.turns, [42])
        with world_for('round2-seen') as w:
            w.pair(('claude', 'opencode'), shared=1)
            w.seed('claude', [original(2), original(3)])
            w.sync()
            ids = [t.id for t in w.store.turns(3)][1:]
            value = run(w, 'mark-seen', tool='opencode', turns=ids[:1])
            self.assertEqual(value, {'link_id': 3, 'tool': 'opencode', 'marked': 1, 'notes': []})
            self.assertEqual(run(w, 'mark-seen', tool='opencode', turns=ids[:1])['marked'], 0)
            self.assertEqual([t.states['opencode'] for t in w.store.turns(3)][1:], ['shown', 'added'])
            self.assertEqual(run(w, 'mark-seen', tool='opencode', turns=None)['marked'], 1)
            with self.assertRaises(NotAvailable): run(w, 'mark-seen', tool='claude', turns=None)
