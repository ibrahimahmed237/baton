"""Named merge scenarios using temporary fake chats and capability combinations."""
from copy import deepcopy
from dataclasses import replace
from itertools import permutations
import unittest
from unittest.mock import patch

from baton.adapters.fake import FakeAdapter
from baton.adapters.fake.facts import CLAUDE_LIKE, CODEX_LIKE, OPENCODE_LIKE, CURSOR_LIKE
from baton.domain.errors import ChatChanged, DecisionNeeded, NotAvailable, OrderNotAllowed
from baton.domain.model import Message, Turn
from baton.domain.link import WAITING, SKIPPED
from baton.ledger.sqlite_store import Ledger
from baton.ports.clock import FixedClock
from baton.services.applier import Applier
from baton.services.linker import Linker
from baton.services.merger import Merger

FACTS = {'claude': CLAUDE_LIKE, 'codex': CODEX_LIKE,
         'opencode': OPENCODE_LIKE, 'cursor': CURSOR_LIKE}


def turn(ident, minute, file=''):
    messages = [Message(ident+'r', 'reply', 'reply '+ident,
                        f'2026-10-05T00:{minute+2:02}:00Z')]
    if file:
        messages.insert(0, Message(ident+'c', 'tool_call', tool='write', tool_input={'path': file}))
    return Turn(Message(ident, 'prompt', ident, f'2026-10-05T00:{minute:02}:00Z'), tuple(messages))


class MergeScenarios(unittest.TestCase):
    def make(self, first='claude', second='codex', files=False):
        store = Ledger(':memory:')
        self.addCleanup(store.close)
        clock = FixedClock('2026-10-05T01:00:00Z')
        adapters = {s: FakeAdapter(FACTS[s], s) for s in (first, second)}
        a = adapters[first].build_chat([turn('shared', 0), turn('C1', 10), turn('C2', 30, 'same.py' if files else '')])
        b = adapters[second].build_chat([turn('shared', 0), turn('X1', 20, 'same.py' if files else '')])
        if files:
            adapters[first].changed_files['C2'] = ['same.py']
            adapters[second].changed_files['X1'] = ['same.py']
        linker = Linker(store, adapters, clock)
        link_id = linker.apply(linker.plan_link(first, a, second, b)).link_id
        merger = Merger(store, adapters, clock)
        ids = {t.first_line: t.id for t in store.turns(link_id)}
        return store, adapters, merger, link_id, ids

    def test_U1_default_order_and_two_merged_copies_without_writes(self):
        for first, second in permutations(FACTS, 2):
            with self.subTest(first=first, second=second):
                store, adapters, service, link, ids = self.make(first, second)
                before = {s: deepcopy(a.chats) for s, a in adapters.items()}
                shown = service.show(link)
                self.assertEqual(shown['order'], [ids['C1'], ids['X1'], ids['C2']])
                self.assertEqual(set(shown['outcome'].values()), {'merged_copy'})
                self.assertEqual(shown['last_shared'].first_line, 'shared')
                self.assertEqual(len(shown['messages']), 3)
                self.assertEqual(before, {s: a.chats for s, a in adapters.items()})
                self.assertEqual(len(store.history(link)), 2)

    def test_U2_origin_first_keeps_only_that_chat(self):
        for first, second in permutations(FACTS, 2):
            with self.subTest(first=first, second=second):
                store, _, service, link, ids = self.make(first, second)
                plan = service.plan(link, preset=first+'_first')
                self.assertEqual(plan.order, (ids['C1'], ids['C2'], ids['X1']))
                self.assertEqual({s.side: s.action for s in plan.delivery.steps}, {first: 'add', second: 'create'})

    def test_U3_refuse_reordering_own_turns(self):
        for first, second in permutations(FACTS, 2):
            with self.subTest(first=first, second=second):
                _, _, service, link, ids = self.make(first, second)
                with self.assertRaises(OrderNotAllowed):
                    service.plan(link, order=[ids['C2'], ids['C1'], ids['X1']])
                for invalid in ([ids['C1']], [ids['C1'], ids['X1'], ids['X1']], [999]):
                    with self.assertRaises(OrderNotAllowed): service.plan(link, order=invalid)

    def test_U4_other_first_keeps_other_chat(self):
        for first, second in permutations(FACTS, 2):
            store, _, service, link, ids = self.make(first, second)
            plan = service.plan(link, order=[ids['X1'], ids['C1'], ids['C2']])
            self.assertEqual({s.side: s.action for s in plan.delivery.steps}, {first: 'create', second: 'add'})

    def test_U5_open_first_waits_for_attachment_and_other_gets_full_copy(self):
        for first in ('claude', 'codex'):
            for second in FACTS:
                if first == second: continue
                with self.subTest(first=first, second=second):
                    store, adapters, service, link, ids = self.make(first, second)
                    old = store.get_link(link)
                    adapters[first].set_condition(old.chat(first), open=True, hooks_ready=True)
                    original = deepcopy(adapters[second].reader.read(old.chat(second)))
                    result = service.apply(service.plan(link, preset=first+'_first'))
                    self.assertTrue(result.applied, result)
                    fresh = store.get_link(link)
                    self.assertEqual(fresh.chat(first), old.chat(first))
                    self.assertNotEqual(fresh.chat(second), old.chat(second))
                    self.assertEqual([t.prompt.text for t in adapters[second].reader.read(fresh.chat(second))], ['shared', 'C1', 'C2', 'X1'])
                    self.assertEqual(adapters[second].reader.read(old.chat(second)), original)
                    self.assertEqual(next(t for t in store.turns(link) if t.id==ids['X1']).states[first], WAITING)
                    self.assertFalse(service.applier.refresh(link)['status'].decision_needed)
                    service.applier.record_attached(link, first, [ids['X1']], 'message')
                    self.assertFalse(service.applier.refresh(link)['status'].decision_needed)

    def test_U6_dont_reorder_adds_after_own_without_new_chats(self):
        for first, second in permutations(FACTS, 2):
            with self.subTest(first=first, second=second):
                store, adapters, service, link, _ = self.make(first, second)
                before = store.get_link(link)
                result = service.apply(service.plan(link, preset='dont_reorder'))
                self.assertTrue(result.applied, result)
                self.assertEqual(store.get_link(link).chats, before.chats)
                self.assertEqual([t.prompt.text for t in adapters[first].reader.read(before.chat(first))], ['shared','C1','C2','X1'])
                self.assertEqual([t.prompt.text for t in adapters[second].reader.read(before.chat(second))], ['shared','X1','C1','C2'])
                self.assertEqual(len([e for e in store.history(link) if e.kind=='merge']), 1)

    def test_U7_same_files_stop_automatic_merge(self):
        for first, second in permutations(FACTS, 2):
            with self.subTest(first=first, second=second):
                _, _, service, link, ids = self.make(first, second, files=True)
                shown = service.show(link, merge_setting='by_time')
                self.assertEqual(shown['same_files'], [{'file':'same.py', 'turns':[ids['C2'], ids['X1']]}])
                self.assertFalse(shown['automatic_allowed'])
                with self.assertRaises(NotAvailable): service.plan(link, automatic=True, merge_setting='by_time')
                self.assertIsNone(service.merge_if_automatic(link, merge_setting='by_time'))
                self.assertFalse(service.show(link, merge_setting='ask')['automatic_allowed'])

    def test_U8_keep_first_skips_other_without_removing_local_turn(self):
        for first, second in permutations(FACTS, 2):
            store, adapters, service, link, ids = self.make(first, second)
            old = store.get_link(link)
            result = service.apply(service.plan(link, keep=first))
            self.assertTrue(result.applied, result)
            self.assertEqual(next(t for t in store.turns(link) if t.id==ids['X1']).states[first], SKIPPED)
            self.assertEqual([t.prompt.text for t in adapters[second].reader.read(old.chat(second))], ['shared','X1','C1','C2'])
            self.assertFalse(service.applier.refresh(link)['status'].decision_needed)

    def test_merge_history_exposes_undo_receipts_and_old_chat_links_for_E8_U9(self):
        store, _, service, link, _ = self.make()
        before = store.get_link(link)
        result = service.apply(service.plan(link))
        self.assertTrue(result.applied, result)
        event = store.history(link)[0]
        self.assertEqual(event.kind, 'merge')
        self.assertEqual(event.detail['before']['link']['chats'], before.chats)
        self.assertEqual(len(event.detail['writes']), 2)
        for write in event.detail['writes']:
            entry = store.journal_entry(write['entry_id'])
            self.assertEqual(entry['state'], 'committed')
            self.assertIsNotNone(entry['pre_receipt'])
            self.assertIsNotNone(entry['post_receipt'])

    def test_confirmed_content_and_record_changes_refused(self):
        store, adapters, service, link, _ = self.make()
        plan = service.plan(link)
        adapters['claude'].chats[store.get_link(link).chat('claude')].append(turn('new', 40))
        with self.assertRaises(ChatChanged): service.apply(plan)
        self.assertEqual(store.journal_entries(), [])

    def test_later_side_failure_rolls_back_earlier_add_and_preserves_metadata(self):
        store, adapters, service, link, _ = self.make()
        plan = service.plan(link, preset='dont_reorder')
        before = deepcopy({s:a.chats for s,a in adapters.items()})
        records = service.applier._record(link)
        with patch.object(adapters['codex'].writer, 'add', side_effect=RuntimeError('failed')):
            result = service.apply(plan)
        self.assertFalse(result.applied)
        self.assertEqual(before, {s:a.chats for s,a in adapters.items()})
        self.assertEqual(records, service.applier._record(link))
        self.assertEqual({e['state'] for e in store.journal_entries()}, {'taken_back'})

    def test_late_store_failure_rolls_back_both_created_copies(self):
        store, adapters, service, link, _ = self.make()
        before = deepcopy({s:a.chats for s,a in adapters.items()})
        plan = service.plan(link)
        store.db.execute("create trigger fail_merge before update of state on turn_states begin select raise(abort, 'late'); end")
        result = service.apply(plan)
        self.assertFalse(result.applied)
        self.assertEqual(before, {s:a.chats for s,a in adapters.items()})
        self.assertEqual(len([e for e in store.history(link) if e.kind=='merge']), 0)
        self.assertTrue(all(e['state']=='taken_back' for e in store.journal_entries()))

    def test_open_open_dont_reorder_acknowledges_and_new_turn_requires_decision(self):
        store, adapters, service, link, ids = self.make()
        chats = store.get_link(link).chats
        for side in chats: adapters[side].set_condition(chats[side], open=True, hooks_ready=True)
        result = service.apply(service.plan(link, preset='dont_reorder'))
        self.assertTrue(result.applied, result)
        self.assertFalse(service.applier.refresh(link)['status'].decision_needed)
        self.assertFalse(service.applier.preview(link).decision_needed)
        adapters['claude'].chats[chats['claude']].append(turn('new', 40))
        self.assertTrue(service.applier.refresh(link)['status'].decision_needed)
        with self.assertRaises(DecisionNeeded): service.applier.record_attached(link, 'claude', [ids['X1']], 'message')

    def test_split_confirms_one_history_entry_and_changes_no_chat(self):
        store, adapters, service, link, _ = self.make()
        before = deepcopy({s:a.chats for s,a in adapters.items()})
        result = service.apply(service.plan(link, split=True))
        self.assertTrue(result.applied, result)
        self.assertTrue(store.get_link(link).removed_at)
        self.assertEqual(before, {s:a.chats for s,a in adapters.items()})
        self.assertEqual(store.history(link)[0].kind, 'merge')

    def test_large_merge_and_by_time_offer_are_structured_before_E10(self):
        _, _, service, link, _ = self.make()
        shown = service.show(link, merge_setting='by_time', brief_threshold_tokens=1)
        self.assertTrue(shown['offer_brief'])
        self.assertTrue(shown['automatic_allowed'])
        self.assertIsNone(service.merge_if_automatic(link, merge_setting='ask'))
        self.assertTrue(service.merge_if_automatic(link, merge_setting='by_time').applied)

    def test_show_while_replying_is_read_only_and_apply_has_no_incomplete_copy(self):
        store, adapters, service, link, ids = self.make()
        adapters['claude'].set_condition(store.get_link(link).chat('claude'), replying=True)
        before = deepcopy({s:a.chats for s,a in adapters.items()})
        self.assertEqual(len(service.show(link)['unsynced']), 3)
        with self.assertRaises(NotAvailable): service.plan(link)
        self.assertEqual(before, {s:a.chats for s,a in adapters.items()})

    def test_startup_recovers_all_begun_writes_in_reverse_after_interruption(self):
        store, adapters, service, link, _ = self.make()
        before = deepcopy({s:a.chats for s,a in adapters.items()})
        plan = service.plan(link, preset='dont_reorder')
        with patch.object(adapters['codex'].writer, 'add', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt): service.apply(plan)
        self.assertEqual(len(store.journal_entries(pending=True)), 2)
        restarted = Merger(store, adapters, service.clock)
        self.assertEqual([e['id'] for e in restarted.recovery], [2, 1])
        self.assertEqual(before, {s:a.chats for s,a in adapters.items()})
        self.assertFalse(store.journal_entries(pending=True))
        self.assertFalse(any(e.kind=='merge' for e in store.history(link)))

    def test_rollback_failure_remains_pending_and_prevents_more_writes_until_recovery(self):
        store, adapters, service, link, _ = self.make()
        before = deepcopy({s:a.chats for s,a in adapters.items()})
        plan = service.plan(link, preset='dont_reorder')
        with patch.object(adapters['codex'].writer, 'add', side_effect=RuntimeError), \
             patch.object(adapters['claude'].writer, 'take_back', side_effect=RuntimeError):
            result = service.apply(plan)
        self.assertFalse(result.applied)
        self.assertEqual(len(result.rollback_errors), 1)
        with self.assertRaises(NotAvailable): service.apply(plan)
        Merger(store, adapters, service.clock)
        self.assertEqual(before, {s:a.chats for s,a in adapters.items()})
        self.assertFalse(store.journal_entries(pending=True))

    def test_unknown_format_release_and_running_guards(self):
        store, adapters, service, link, _ = self.make('claude', 'cursor')
        adapters['cursor'].app_running = True
        before = deepcopy({s:a.chats for s,a in adapters.items()})
        result = service.apply(service.plan(link))
        self.assertEqual(result.error, 'AppMustBeClosed')
        self.assertEqual(before, {s:a.chats for s,a in adapters.items()})
        adapters['cursor'].app_running = False
        adapters['cursor'].set_format(False, 'unknown')
        result = service.apply(service.plan(link))
        self.assertEqual(result.error, 'UnknownFormat')
        self.assertEqual(before, {s:a.chats for s,a in adapters.items()})

    def test_open_open_acknowledges_each_side_without_inventing_delivery(self):
        store, adapters, service, link, ids = self.make()
        chats = store.get_link(link).chats
        for side in chats: adapters[side].set_condition(chats[side], open=True, hooks_ready=True)
        self.assertTrue(service.apply(service.plan(link, preset='dont_reorder')).applied)
        service.applier.record_attached(link, 'claude', [ids['X1']], 'claude_message')
        self.assertFalse(service.applier.preview(link).decision_needed)
        service.applier.record_attached(link, 'codex', [ids['C1'], ids['C2']], 'codex_message')
        self.assertFalse(service.applier.preview(link).steps)
        self.assertEqual(service.applier.refresh(link)['status'].side('claude').attached, 1)
        self.assertEqual(service.applier.refresh(link)['status'].side('codex').attached, 2)

    def test_merge_add_and_created_copy_become_shown_only_after_later_app_start(self):
        for side, other in (('claude', 'codex'), ('cursor', 'opencode')):
            for preset in ('dont_reorder', 'by_time'):
                with self.subTest(side=side, preset=preset):
                    store, adapters, service, link, _ = self.make(side, other)
                    self.assertTrue(service.apply(service.plan(link, preset=preset)).applied)
                    chat = store.get_link(link).chat(side)
                    before = service.applier.refresh(link)['status'].side(side)
                    self.assertGreater(before.added, 0)
                    adapters[side].set_condition(chat, app_started_at='2026-10-05T01:00:00Z')
                    self.assertGreater(service.applier.refresh(link)['status'].side(side).added, 0)
                    adapters[side].set_condition(chat, app_started_at='2026-10-05T02:00:00Z')
                    after = service.applier.refresh(link)['status'].side(side)
                    self.assertEqual(after.added, 0)
                    self.assertEqual(after.chat_shows, after.total)
                    self.assertNotIn('relaunch_to_see', after.needs)

    def test_merge_open_code_add_waits_for_explicit_seen_or_later_app_start(self):
        store, adapters, service, link, _ = self.make('opencode', 'codex')
        self.assertTrue(service.apply(service.plan(link, preset='dont_reorder')).applied)
        self.assertGreater(service.applier.refresh(link)['status'].side('opencode').added, 0)
        service.applier.mark_seen(link, 'opencode')
        self.assertEqual(service.applier.refresh(link)['status'].side('opencode').added, 0)

    def test_split_paused_link_leaves_both_chats_unchanged(self):
        store, adapters, service, link, _ = self.make()
        store.set_paused(link, True)
        before = deepcopy({s: a.chats for s, a in adapters.items()})
        result = service.apply(service.plan(link, split=True))
        self.assertTrue(result.applied, result)
        self.assertTrue(store.get_link(link).removed_at)
        self.assertEqual(before, {s: a.chats for s, a in adapters.items()})
        self.assertFalse(store.journal_entries())

    def test_unexpected_created_id_rolls_back_actual_chat_before_another_write(self):
        store, adapters, service, link, _ = self.make()
        before = deepcopy({s: a.chats for s, a in adapters.items()})
        original = adapters['claude'].writer.create
        def wrong_reservation(*args):
            adapters['claude'].writer._prepared_create = None
            return original(*args)
        with patch.object(adapters['claude'].writer, 'create', side_effect=wrong_reservation), \
             patch.object(adapters['codex'].writer, 'create', wraps=adapters['codex'].writer.create) as later:
            result = service.apply(service.plan(link))
        self.assertFalse(result.applied)
        self.assertEqual(result.error, 'ChatChanged')
        self.assertFalse(result.rollback_errors)
        later.assert_not_called()
        self.assertEqual(before, {s: a.chats for s, a in adapters.items()})
        self.assertFalse(store.journal_entries(pending=True))

    def test_unexpected_created_id_failed_rollback_stays_durable_for_recovery(self):
        store, adapters, service, link, _ = self.make()
        before = deepcopy({s: a.chats for s, a in adapters.items()})
        original = adapters['claude'].writer.create
        def wrong_reservation(*args):
            adapters['claude'].writer._prepared_create = None
            return original(*args)
        with patch.object(adapters['claude'].writer, 'create', side_effect=wrong_reservation), \
             patch.object(adapters['claude'].writer, 'take_back', side_effect=RuntimeError):
            result = service.apply(service.plan(link))
        self.assertFalse(result.applied)
        self.assertTrue(result.rollback_errors)
        self.assertTrue(store.journal_entries(pending=True))
        Merger(store, adapters, service.clock)
        self.assertEqual(before, {s: a.chats for s, a in adapters.items()})
        self.assertFalse(store.journal_entries(pending=True))
