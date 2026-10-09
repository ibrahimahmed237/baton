"""A9/A10 and T7–T11 undo boundaries using isolated fake chats."""
from copy import deepcopy
from dataclasses import asdict
import unittest
from unittest.mock import patch

from baton.adapters.fake import FakeAdapter
from baton.domain.errors import ChatChanged, NotAvailable
from baton.domain.link import WAITING
from baton.domain.model import Message, Turn
from baton.ledger.sqlite_store import Ledger
from baton.ports.clock import FixedClock
from baton.services.applier import Applier
from baton.services.linker import Linker
from baton.services.undo import Undo
from tests.unit.test_linker import FACTS
from tests.scenarios import test_merge as merge_fixtures


def turn(ident):
    return Turn(Message(ident, 'prompt', ident, '2026-10-05T00:00:00Z'),
                (Message(ident+'r', 'reply', 'reply', '2026-10-05T00:01:00Z'),))


class UndoScenarios(unittest.TestCase):
    def make(self, target='claude', empty=False):
        source = 'codex' if target == 'claude' else 'claude'
        store = Ledger(':memory:'); self.addCleanup(store.close)
        clock = FixedClock('2026-10-05T01:00:00Z')
        adapters = {s: FakeAdapter(FACTS[s], s) for s in (source, target)}
        initial = [] if empty else [turn('shared')]
        a = adapters[source].build_chat(initial)
        b = adapters[target].build_chat(initial)
        link = Linker(store, adapters, clock)
        result = link.apply(link.plan_link(source, a, target, b))
        self.assertTrue(result.applied, result)
        applier = Applier(store, adapters, clock)
        syncs = []
        for i in range(3):
            adapters[source].chats[a].append(turn('sync'+str(i)))
            applier.refresh(result.link_id)
            self.assertTrue(applier.apply(applier.preview(result.link_id)).applied)
            syncs.append(next(e.id for e in store.history(result.link_id) if e.side == target and e.kind == 'add'))
        adapters[target].chats[b] += [turn('own0'), turn('own1')]
        applier.refresh(result.link_id)
        return store, adapters, Undo(store, adapters, clock), result.link_id, source, target, syncs

    def test_T7_preview_lists_removed_and_only_here_for_all_fact_sets(self):
        for target in FACTS:
            with self.subTest(target=target):
                store, adapters, service, link, source, target, events = self.make(target)
                before = deepcopy({s: a.chats for s, a in adapters.items()})
                plan = service.plan(link, events[1])
                self.assertEqual([r['turn']['first_line'] for r in plan.removes], ['sync1','sync2','own0','own1'])
                self.assertEqual([r['turn']['first_line'] for r in plan.removes if r['only_here']], ['own0','own1'])
                self.assertEqual(plan.ends_at[target]['prompt']['text'], 'sync0')
                self.assertEqual(plan.steps[0].action, 'cut' if FACTS[target].can_cut else 'create_shorter')
                self.assertEqual(before, {s: a.chats for s, a in adapters.items()})

    def test_T8_apply_pauses_and_other_side_unchanged(self):
        for target in FACTS:
            with self.subTest(target=target):
                store, adapters, service, link, source, target, events = self.make(target)
                old = store.get_link(link)
                before = deepcopy({s: a.chats for s, a in adapters.items()})
                result = service.apply(service.plan(link, events[1]))
                self.assertTrue(result.applied, result)
                fresh = store.get_link(link)
                self.assertTrue(fresh.paused)
                self.assertEqual(adapters[source].chats, before[source])
                self.assertEqual([t.prompt.text for t in adapters[target].reader.read(fresh.chat(target))], ['shared','sync0'])
                for row in store.turns(link):
                    if row.first_line in ('sync1','sync2','own0','own1'):
                        self.assertEqual(row.states[target], WAITING)
                if not FACTS[target].can_cut:
                    self.assertIsNone(store.link_for(target, old.chat(target)))
                    self.assertEqual(adapters[target].reader.read(old.chat(target)), before[target][old.chat(target)])
                    self.assertEqual(store.history(link)[0].detail['before_chats'][target]['chat_id'], old.chat(target))

    def test_T9_T10c_restore_returns_original_content_and_keeps_pause(self):
        for target in FACTS:
            with self.subTest(target=target):
                store, adapters, service, link, source, target, events = self.make(target)
                old = store.get_link(link)
                before = deepcopy(adapters[target].reader.read(old.chat(target)))
                result = service.apply(service.plan(link, events[1]))
                shortened = store.get_link(link).chat(target)
                restore = service.apply(service.restore(link, result.event_id))
                self.assertTrue(restore.applied, restore)
                self.assertEqual(store.get_link(link).chat(target), old.chat(target))
                self.assertEqual(adapters[target].reader.read(old.chat(target)), before)
                self.assertTrue(store.get_link(link).paused)
                if not FACTS[target].can_cut:
                    self.assertIsNone(store.link_for(target, shortened))
                    self.assertEqual(len(adapters[target].reader.read(shortened)), 2)
                with self.assertRaises(NotAvailable): service.restore(link, result.event_id)

    def test_T10_releases_idle_chat_and_preserves_display_until_relaunch(self):
        store, adapters, service, link, source, target, events = self.make()
        chat = store.get_link(link).chat(target)
        adapters[target].set_condition(chat, open=True)
        before = adapters[target].visible_turns(chat)
        plan = service.plan(link, events[0])
        result = service.apply(plan)
        self.assertTrue(result.applied, result)
        self.assertIn(('release', chat), adapters[target].app.calls)
        self.assertEqual(adapters[target].visible_turns(chat), before)
        self.assertIn('relaunch_to_see', plan.steps[0].needs)
        self.assertTrue(store.journal_entry(store.history(link)[0].detail['writes'][0]['entry_id'])['pre_receipt'])

    def test_T10b_replying_never_cuts_or_releases(self):
        for target in FACTS:
            store, adapters, service, link, source, target, events = self.make(target)
            chat = store.get_link(link).chat(target)
            adapters[target].set_condition(chat, open=True, replying=True)
            before = deepcopy(adapters[target].chats)
            result = service.apply(service.plan(link, events[0]))
            self.assertFalse(result.applied)
            self.assertEqual(result.error, 'ChatReplying')
            self.assertEqual(result.notes, ('undo.replying',))
            self.assertEqual(before, adapters[target].chats)
            self.assertFalse(any(c[0] == 'release' for c in adapters[target].app.calls))

    def test_T11_attached_boundary_removes_whole_receiving_turn(self):
        for target in FACTS:
            store, adapters, service, link, source, target, events = self.make(target)
            chat = store.get_link(link).chat(target)
            adapters[source].chats[store.get_link(link).chat(source)].append(turn('attached'))
            adapters[target].chats[chat].append(turn('receiving'))
            service.applier.refresh(link)
            ident = next(t.id for t in store.turns(link) if t.first_line == 'attached')
            adapters[target].hooks.ready = True
            adapters[target].set_condition(chat, hooks_ready=True)
            event = store.deliver(link, target, [ident], 'attached', 'attached', service.clock.now(), detail={'message_id': 'receivingr'})
            plan = service.plan(link, event)
            self.assertIn('undo.attached', plan.notes)
            self.assertEqual({r['turn']['first_line'] for r in plan.removes}, {'attached', 'receiving'})
            self.assertEqual(plan.ends_at[target]['prompt']['text'], 'own1')
            self.assertTrue(service.apply(plan).applied)

    def test_first_delivery_can_cut_to_empty_and_restore(self):
        for target in FACTS:
            store, adapters, service, link, source, target, events = self.make(target, empty=True)
            plan = service.plan(link, events[0])
            self.assertIsNone(plan.ends_at[target])
            result = service.apply(plan)
            self.assertTrue(result.applied, result)
            self.assertEqual(adapters[target].reader.read(store.get_link(link).chat(target)), [])
            self.assertTrue(service.apply(service.restore(link, result.event_id)).applied)

    def test_mutated_preview_and_late_native_change_refused_before_write(self):
        store, adapters, service, link, source, target, events = self.make()
        plan = service.plan(link, events[0])
        plan.detail['removed_ids'] = []
        with self.assertRaises(ChatChanged): service.apply(plan)
        plan = service.plan(link, events[0])
        adapters[target].chats[store.get_link(link).chat(target)].append(turn('new'))
        with self.assertRaises(ChatChanged): service.apply(plan)

    def test_restore_refuses_new_native_write_and_expired_cut(self):
        store, adapters, service, link, source, target, events = self.make()
        result = service.apply(service.plan(link, events[1]))
        adapters[target].chats[store.get_link(link).chat(target)].append(turn('new'))
        with self.assertRaises(ChatChanged): service.restore(link, result.event_id)
        adapters[target].chats[store.get_link(link).chat(target)].pop()
        service.clock.value = '2026-11-06T01:00:00Z'
        with self.assertRaises(NotAvailable): service.restore(link, result.event_id)

    def test_atomic_store_failure_rolls_back_content_and_record(self):
        for target in FACTS:
            store, adapters, service, link, source, target, events = self.make(target)
            before = deepcopy({s: a.chats for s,a in adapters.items()})
            record = service._record(link)
            store.db.execute("create trigger fail_undo before update of paused on links begin select raise(abort, 'late'); end")
            result = service.apply(service.plan(link, events[1]))
            self.assertFalse(result.applied)
            self.assertEqual(before, {s: a.chats for s,a in adapters.items()})
            self.assertEqual(record, service._record(link))
            self.assertFalse(store.journal_entries(pending=True))

    def test_restore_failure_rolls_back_and_can_retry(self):
        store, adapters, service, link, source, target, events = self.make()
        result = service.apply(service.plan(link, events[1]))
        before = deepcopy(adapters[target].chats)
        with patch.object(store, 'complete_undo', side_effect=RuntimeError):
            restore = service.apply(service.restore(link, result.event_id))
        self.assertFalse(restore.applied)
        self.assertEqual(before, adapters[target].chats)
        self.assertTrue(service.apply(service.restore(link, result.event_id)).applied)

    def test_U9_merge_created_chats_stay_untouched_and_old_link_returns(self):
        for preset in ('by_time', 'dont_reorder', 'claude_first'):
            fixture = merge_fixtures.MergeScenarios(); fixture.addCleanup = self.addCleanup
            store, adapters, merger, link, ids = fixture.make()
            old = store.get_link(link)
            result = merger.apply(merger.plan(link, preset=preset))
            current = store.get_link(link)
            created = {s: deepcopy(adapters[s].reader.read(current.chat(s))) for s in current.sides if current.chat(s) != old.chat(s)}
            service = Undo(store, adapters, merger.clock)
            undo = service.apply(service.plan(link, result.event_id))
            self.assertTrue(undo.applied, undo)
            self.assertTrue(store.get_link(link).paused)
            for side, content in created.items():
                self.assertEqual(store.get_link(link).chat(side), old.chat(side))
                self.assertEqual(adapters[side].reader.read(current.chat(side)), content)
            if preset == 'dont_reorder':
                self.assertEqual([t.prompt.text for t in adapters['claude'].reader.read(store.get_link(link).chat('claude'))], ['shared','C1','C2'])
                self.assertEqual([t.prompt.text for t in adapters['codex'].reader.read(store.get_link(link).chat('codex'))], ['shared','X1'])

    def test_origin_cut_keeps_remote_delivered_copy_truthful_and_resume_resolves_archive(self):
        store, adapters, service, link, source, target, events = self.make()
        # Deliver the target's native turns before removing their originating bytes.
        self.assertTrue(service.applier.apply(service.applier.preview(link)).applied)
        native = [r.id for r in store.turns(link) if r.origin == target]
        result = service.apply(service.plan(link, events[1]))
        self.assertTrue(result.applied)
        fresh = service.applier.refresh(link)
        for row in fresh['turns']:
            if row.id in native:
                self.assertNotEqual(row.states[source], WAITING)
        store.set_paused(link, False, service.clock.now())
        preview = service.applier.preview(link)
        self.assertEqual([t.prompt.text for s in preview.steps for t in s.turns], ['sync1','sync2','own0','own1'])
        self.assertTrue(service.applier.apply(preview).applied)
        self.assertEqual([t.prompt.text for t in adapters[target].reader.read(store.get_link(link).chat(target))],
                         ['shared','sync0','sync1','sync2','own0','own1'])

    def test_cut_visibility_requires_later_relaunch_or_explicit_reopen(self):
        for target in ('claude', 'opencode'):
            store, adapters, service, link, source, target, events = self.make(target)
            result = service.apply(service.plan(link, events[1]))
            self.assertTrue(result.applied)
            first = service.applier.refresh(link)['status'].side(target)
            self.assertEqual(len(first.removed_still_shown), 4)
            adapters[target].set_condition(store.get_link(link).chat(target), app_started_at=service.clock.now())
            self.assertEqual(len(service.applier.refresh(link)['status'].side(target).removed_still_shown), 4)
            if target == 'opencode':
                service.applier.mark_seen(link, target)
            else:
                adapters[target].set_condition(store.get_link(link).chat(target), app_started_at='2026-10-05T02:00:00Z')
            final = service.applier.refresh(link)['status'].side(target)
            self.assertEqual(final.removed_still_shown, ())
            self.assertEqual(final.chat_shows, 2)

    def test_interruption_during_cut_or_restore_recovers_saved_prewrite(self):
        store, adapters, service, link, source, target, events = self.make()
        chat = store.get_link(link).chat(target)
        original = deepcopy(adapters[target].reader.read(chat))
        actual = adapters[target].writer.cut
        def interrupted_cut(*args):
            actual(*args)
            raise KeyboardInterrupt()
        with patch.object(adapters[target].writer, 'cut', side_effect=interrupted_cut):
            with self.assertRaises(KeyboardInterrupt): service.apply(service.plan(link, events[1]))
        service = Undo(store, adapters, service.clock)
        self.assertEqual(adapters[target].reader.read(chat), original)
        self.assertFalse(store.journal_entries(pending=True))
        result = service.apply(service.plan(link, events[1]))
        truncated = deepcopy(adapters[target].reader.read(chat))
        actual = adapters[target].writer.restore
        def interrupted_restore(*args):
            actual(*args)
            raise KeyboardInterrupt()
        with patch.object(adapters[target].writer, 'restore', side_effect=interrupted_restore):
            with self.assertRaises(KeyboardInterrupt): service.apply(service.restore(link, result.event_id))
        service = Undo(store, adapters, service.clock)
        self.assertEqual(adapters[target].reader.read(chat), truncated)
        self.assertFalse(store.journal_entries(pending=True))
        self.assertTrue(service.apply(service.restore(link, result.event_id)).applied)

    def test_release_does_not_hide_prepare_race_or_override_live_holder(self):
        store, adapters, service, link, source, target, events = self.make()
        original = adapters[target].writer.prepare
        chat = store.get_link(link).chat(target)
        def changed_during_prepare(*args):
            result = original(*args)
            adapters[target].set_condition(chat, replying=True)
            return result
        with patch.object(adapters[target].writer, 'prepare', side_effect=changed_during_prepare):
            result = service.apply(service.plan(link, events[1]))
        self.assertFalse(result.applied)
        self.assertEqual(result.error, 'ChatReplying')
        self.assertEqual(len(adapters[target].reader.read(chat)), 6)

    def test_U9_split_can_reactivate_only_unclaimed_chats(self):
        fixture = merge_fixtures.MergeScenarios(); fixture.addCleanup = self.addCleanup
        store, adapters, merger, link, ids = fixture.make()
        result = merger.apply(merger.plan(link, split=True))
        service = Undo(store, adapters, merger.clock)
        undo = service.apply(service.plan(link, result.event_id))
        self.assertTrue(undo.applied, undo)
        self.assertFalse(store.get_link(link).removed_at)
        self.assertTrue(store.get_link(link).paused)

    def test_unknown_format_running_app_and_held_chat_guard_before_mutation(self):
        for target in FACTS:
            store, adapters, service, link, source, target, events = self.make(target)
            before = deepcopy(adapters[target].chats)
            adapters[target].set_format(False, 'unknown')
            result = service.apply(service.plan(link, events[1]))
            self.assertFalse(result.applied)
            self.assertEqual(result.error, 'UnknownFormat')
            self.assertEqual(before, adapters[target].chats)
        store, adapters, service, link, source, target, events = self.make('cursor')
        adapters[target].app_running = True
        result = service.apply(service.plan(link, events[1]))
        self.assertEqual(result.error, 'AppMustBeClosed')
        store, adapters, service, link, source, target, events = self.make('codex')
        adapters[target].set_condition(store.get_link(link).chat(target), open=True)
        # Creating a new chat does not write to the held source chat.
        self.assertTrue(service.apply(service.plan(link, events[1])).applied)

    def test_failed_rollback_blocks_next_write_until_recovered(self):
        store, adapters, service, link, source, target, events = self.make()
        original = deepcopy(adapters[target].chats)
        plan = service.plan(link, events[1])
        with patch.object(store, 'complete_undo', side_effect=RuntimeError), \
             patch.object(adapters[target].writer, 'take_back', side_effect=RuntimeError):
            result = service.apply(plan)
        self.assertFalse(result.applied)
        self.assertTrue(result.rollback_errors)
        with self.assertRaises(NotAvailable): service.apply(plan)
        restarted = Undo(store, adapters, service.clock)
        self.assertFalse(store.journal_entries(pending=True))
        self.assertEqual(original, adapters[target].chats)

    def test_restore_single_event_route_and_relinked_earlier_chat_guard(self):
        store, adapters, service, link, source, target, events = self.make('codex')
        result = service.apply(service.plan(link, events[1]))
        plan = service.restore(result.event_id)
        self.assertEqual(plan.link_id, link)
        earlier = store.history(link)[0].detail['before_chats'][target]['chat_id']
        spare = adapters[source].build_chat([])
        store.link({target: earlier, source: spare}, 'full_copy', service.clock.now())
        with self.assertRaises(NotAvailable): service.restore(result.event_id)

    def test_U9_every_capability_and_merge_outcome_preserves_created_chats(self):
        from itertools import permutations
        for first, second in permutations(FACTS, 2):
            for preset in ('by_time', 'dont_reorder', first+'_first'):
                with self.subTest(first=first, second=second, preset=preset):
                    fixture = merge_fixtures.MergeScenarios(); fixture.addCleanup = self.addCleanup
                    store, adapters, merger, link, ids = fixture.make(first, second)
                    old = store.get_link(link)
                    merged = merger.apply(merger.plan(link, preset=preset))
                    self.assertTrue(merged.applied, merged)
                    current = store.get_link(link)
                    created = {s: deepcopy(adapters[s].reader.read(current.chat(s))) for s in current.sides
                               if current.chat(s) != old.chat(s)}
                    service = Undo(store, adapters, merger.clock)
                    result = service.apply(service.plan(link, merged.event_id))
                    self.assertTrue(result.applied, result)
                    self.assertTrue(store.get_link(link).paused)
                    for side, content in created.items():
                        self.assertEqual(store.get_link(link).chat(side), old.chat(side))
                        self.assertEqual(adapters[side].reader.read(current.chat(side)), content)
                    restore = service.apply(service.restore(result.event_id))
                    self.assertTrue(restore.applied, restore)
                    self.assertEqual(store.get_link(link).chats, current.chats)

    def test_nonwrite_history_markers_use_verified_delivery_boundary_with_explicit_side(self):
        for target in FACTS:
            store, adapters, service, link, source, target, events = self.make(target)
            marker = next(e.id for e in store.history(link) if e.kind == 'linked')
            with self.assertRaises(NotAvailable): service.plan(link, marker)
            plan = service.plan(link, marker, side=target)
            self.assertEqual(plan.ends_at[target]['prompt']['text'], 'shared')
            self.assertEqual([r['turn']['first_line'] for r in plan.removes], ['sync0','sync1','sync2','own0','own1'])
            self.assertTrue(service.apply(plan).applied)
        store, adapters, service, link, source, target, events = self.make()
        store.set_paused(link, True, service.clock.now())
        marker = store.history(link)[0].id
        store.set_paused(link, False, service.clock.now())
        adapters[source].chats[store.get_link(link).chat(source)].append(turn('aftermarker'))
        service.applier.refresh(link)
        # Existing native target turns need a merge before the source can send more.
        adapters[target].set_condition(store.get_link(link).chat(target), hooks_ready=True)
        row = next(t for t in store.turns(link) if t.first_line == 'aftermarker')
        result = adapters[target].writer.add(store.get_link(link).chat(target), [turn('aftermarker')])
        store.deliver(link, target, [row.id], 'shown', 'add', service.clock.now(), result.local_ids)
        plan = service.plan(link, marker, side=target)
        self.assertEqual([r['turn']['first_line'] for r in plan.removes], ['aftermarker'])
        self.assertEqual(plan.ends_at[target]['prompt']['text'], 'own1')

    def test_history_without_demonstrable_boundary_refuses_without_writing(self):
        store, adapters, service, link, source, target, events = self.make()
        store.set_paused(link, True, service.clock.now())
        marker = store.history(link)[0].id
        before = deepcopy({s:a.chats for s,a in adapters.items()})
        with self.assertRaises(NotAvailable): service.plan(link, marker, side=target)
        self.assertEqual(before, {s:a.chats for s,a in adapters.items()})

    def test_delayed_release_is_observed_and_timeout_never_cuts(self):
        store, adapters, service, link, source, target, events = self.make()
        chat = store.get_link(link).chat(target)
        adapters[target].set_condition(chat, open=True)
        calls = []
        def wait(seconds):
            calls.append(seconds)
            adapters[target].set_condition(chat, open=False)
        service.applier.wait = wait
        with patch.object(adapters[target].app, 'release', return_value=None):
            result = service.apply(service.plan(link, events[1]))
        self.assertTrue(result.applied, result)
        self.assertEqual(len(calls), 1)
        store, adapters, service, link, source, target, events = self.make()
        chat = store.get_link(link).chat(target)
        adapters[target].set_condition(chat, open=True)
        ticks = iter((0.0, 11.0))
        service.applier.elapsed = lambda: next(ticks)
        before = deepcopy(adapters[target].chats)
        with patch.object(adapters[target].app, 'release', return_value=None):
            result = service.apply(service.plan(link, events[1]))
        self.assertFalse(result.applied)
        self.assertEqual(before, adapters[target].chats)
        self.assertEqual(result.error, 'ChatHeld')

    def test_restore_confirmation_expires_before_release_or_journal(self):
        store, adapters, service, link, source, target, events = self.make()
        undone = service.apply(service.plan(link, events[1]))
        plan = service.restore(undone.event_id)
        before = deepcopy(adapters[target].chats)
        journal = deepcopy(store.journal_entries())
        calls = deepcopy(adapters[target].app.calls)
        service.clock.value = '2026-11-06T01:00:00Z'
        with self.assertRaises(NotAvailable): service.apply(plan)
        self.assertEqual(adapters[target].chats, before)
        self.assertEqual(store.journal_entries(), journal)
        self.assertEqual(adapters[target].app.calls, calls)

    def test_repeated_cuts_accumulate_visible_removed_turns_and_restore_subtracts(self):
        for target in ('claude', 'opencode'):
            store, adapters, service, link, source, target, events = self.make(target)
            store.mark_shown(link, target)
            first = service.apply(service.plan(link, events[1]))
            self.assertTrue(first.applied)
            second = service.apply(service.plan(link, events[0]))
            self.assertTrue(second.applied)
            status = service.applier.refresh(link)['status'].side(target)
            self.assertEqual(status.chat_shows, 6)
            self.assertEqual(len(status.removed_still_shown), 5)
            self.assertTrue(service.apply(service.restore(second.event_id)).applied)
            status = service.applier.refresh(link)['status'].side(target)
            self.assertEqual(status.chat_shows, 6)
            self.assertEqual(len(status.removed_still_shown), 4)
            self.assertTrue(service.apply(service.restore(first.event_id)).applied)
            self.assertEqual(service.applier.refresh(link)['status'].side(target).removed_still_shown, ())

    def test_shorter_restore_refuses_new_native_turn_before_any_link_move(self):
        for target in ('codex', 'cursor'):
            store, adapters, service, link, source, target, events = self.make(target)
            result = service.apply(service.plan(link, events[1]))
            shorter = store.get_link(link).chat(target)
            adapters[target].chats[shorter].append(turn('newshorter'))
            service.applier.refresh(link)
            before = deepcopy(adapters[target].chats)
            with self.assertRaises(ChatChanged): service.restore(result.event_id)
            self.assertEqual(store.get_link(link).chat(target), shorter)
            self.assertEqual(adapters[target].chats, before)

    def test_merge_created_undo_refuses_later_native_write_on_created_chat(self):
        fixture = merge_fixtures.MergeScenarios(); fixture.addCleanup = self.addCleanup
        store, adapters, merger, link, ids = fixture.make()
        result = merger.apply(merger.plan(link))
        created = store.get_link(link).chat('codex')
        adapters['codex'].chats[created].append(turn('newmerged'))
        service = Undo(store, adapters, merger.clock)
        service.applier.refresh(link)
        with self.assertRaises(ChatChanged): service.plan(link, result.event_id)
        self.assertEqual(store.get_link(link).chat('codex'), created)

    def test_merge_undo_exposes_capability_notes_and_needs_for_every_side(self):
        for first, second in (('claude','codex'), ('opencode','cursor')):
            fixture = merge_fixtures.MergeScenarios(); fixture.addCleanup = self.addCleanup
            store, adapters, merger, link, ids = fixture.make(first, second)
            merged = merger.apply(merger.plan(link, preset='dont_reorder'))
            chat = store.get_link(link).chat(first)
            adapters[first].set_condition(chat, open=True)
            service = Undo(store, adapters, merger.clock)
            plan = service.plan(link, merged.event_id)
            self.assertIn('undo.merge', plan.notes)
            for step in plan.steps:
                facts = adapters[step.side].facts
                self.assertIn(service._undo_note(facts, step.action), plan.detail['notes_by_side'][step.side])
                self.assertIn('undo.ends_at', plan.detail['notes_by_side'][step.side])
                self.assertEqual(step.needs, service._undo_needs(facts, plan.snapshots[step.side]['condition'], step.action))
            cut = next(s for s in plan.steps if s.side == first)
            self.assertIn('relaunch_to_see' if first == 'claude' else 'reopen_chat_to_see', cut.needs)
            if first == 'claude': self.assertIn('release_chat', cut.needs)
            if second == 'cursor':
                shorter = next(s for s in plan.steps if s.side == second)
                self.assertIn('app_closed', shorter.needs)
                self.assertIn('relaunch_to_see', shorter.needs)

    def test_merge_undo_attached_turn_cuts_receiving_message_and_invalidates_approval(self):
        for first, second in (('claude', 'codex'), ('codex', 'claude')):
            fixture = merge_fixtures.MergeScenarios(); fixture.addCleanup = self.addCleanup
            store, adapters, merger, link, ids = fixture.make(first, second)
            chat = store.get_link(link).chat(first)
            adapters[first].set_condition(chat, open=True, hooks_ready=True)
            merged = merger.apply(merger.plan(link, preset=first+'_first'))
            self.assertTrue(merged.applied)
            adapters[first].chats[chat].append(turn('receivingmerge'))
            merger.applier.record_attached(link, first, [ids['X1']], 'receivingmerger')
            merger.applier.refresh(link)
            service = Undo(store, adapters, merger.clock)
            plan = service.plan(link, merged.event_id)
            self.assertIn('undo.attached', plan.detail['notes_by_side'][first])
            self.assertEqual(plan.ends_at[first]['prompt']['text'], 'C2')
            result = service.apply(plan)
            self.assertTrue(result.applied, result)
            self.assertEqual([t.prompt.text for t in adapters[first].reader.read(store.get_link(link).chat(first))], ['shared','C1','C2'])
            store.set_paused(link, False, service.clock.now())
            self.assertTrue(service.applier.refresh(link)['status'].decision_needed)

    def test_restoring_metadata_only_split_undo_is_not_available(self):
        fixture = merge_fixtures.MergeScenarios(); fixture.addCleanup = self.addCleanup
        store, adapters, merger, link, ids = fixture.make()
        split = merger.apply(merger.plan(link, split=True))
        service = Undo(store, adapters, merger.clock)
        undone = service.apply(service.plan(link, split.event_id))
        self.assertTrue(undone.applied)
        record = service._record(link)
        chats = deepcopy({s:a.chats for s,a in adapters.items()})
        with self.assertRaises(NotAvailable): service.restore(undone.event_id)
        self.assertEqual(service._record(link), record)
        self.assertEqual(chats, {s:a.chats for s,a in adapters.items()})
