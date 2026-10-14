"""DESIGN 5 safety-rule test index (all tool data is temporary/in memory).
1/1a: GuardTests.test_held_then_closed, test_running_app_then_closed,
       test_replying_then_idle_and_any_time_allows_running_chat.
2: test_crash_between_add_and_record_recovers_across_instances.
2a/A10: test_saved_cut_can_be_restored_after_restart,
        test_saved_cut_is_retained_30_days_and_pending_is_never_pruned;
        GuardTests.test_cut_and_place_must_be_supported.
2b: GuardTests.test_release_only_linked_open_idle_supported_chat.
3: test_create_recovery_removes_written_chat_but_not_other_chats.
4: test_prepare_without_write_is_safe_to_recover proves preparation is read-only;
   preview/plan execution is tested by the dependent E5 package.
5: GuardTests.test_unlinked_existing_write_refused_create_allowed.
6: GuardTests.test_unknown_format_then_known.
7: no network code/dependency; tests exercise only fake tool and local store.
"""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from baton.adapters.fake import FakeAdapter
from baton.ledger.sqlite_store import Ledger
from baton.ports.clock import FixedClock
from baton.services.journal import Journal
from tests.adapters.suite import turns


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = str(Path(self.folder.name) / 'records.sqlite')
        self.store = Ledger(self.path)
        self.adapter = FakeAdapter(name='claude')
        self.chat = self.adapter.build_chat(turns())
        self.link = self.store.link({'claude': self.chat, 'codex': 'other'}, 'full_copy')
        self.clock = FixedClock('2026-01-01T00:00:00Z')
        self.journal = Journal(self.store, {'claude': self.adapter}, self.clock)

    def tearDown(self):
        self.store.close()
        self.folder.cleanup()

    def restart(self):
        self.store.close()
        self.store = Ledger(self.path)
        # A new adapter object uses the same simulated tool storage, but no writer state.
        adapter = FakeAdapter(name='claude')
        for name in ('chats', 'refs', 'conditions', 'inserted_text', 'visible'):
            setattr(adapter, name, deepcopy(getattr(self.adapter, name)))
        self.adapter = adapter
        self.journal = Journal(self.store, {'claude': adapter}, self.clock)

    def test_crash_between_add_and_record_recovers_across_instances(self):
        entry = self.journal.begin(self.link.id, 'claude', self.chat, 'add')
        before = self.store.journal_entry(entry)
        self.assertEqual(before['state'], 'begun')
        self.assertEqual(len(before['pre_receipt']['data']['turns']), 3)
        extra = replace(turns()[0], prompt=replace(turns()[0].prompt, id='p4'))
        self.adapter.writer.add(self.chat, [extra])
        self.assertEqual(len(self.adapter.reader.read(self.chat)), 4)
        self.restart()
        result = self.journal.recover()
        self.assertEqual(result[0]['state'], 'taken_back')
        self.assertEqual(self.adapter.reader.read(self.chat), turns())
        self.assertEqual(self.journal.recover(), [])
        self.journal.take_back(entry)

    def test_create_recovery_removes_written_chat_but_not_other_chats(self):
        entry = self.journal.begin(None, 'claude', None, 'create')
        receipt = self.store.journal_entry(entry)['pre_receipt']
        self.assertFalse(receipt['data']['exists'])
        result = self.adapter.writer.create(turns(), 'copy', '')
        self.assertEqual(receipt['chat_id'], result.chat_id)
        self.restart()
        self.journal.recover()
        self.assertFalse(self.adapter.state.condition(result.chat_id).exists)
        self.assertEqual(self.adapter.reader.read(self.chat), turns())

    def test_prepare_without_write_is_safe_to_recover(self):
        self.journal.begin(None, 'claude', None, 'create')
        self.restart()
        self.assertEqual(self.journal.recover()[0]['state'], 'taken_back')
        self.assertEqual(len(self.adapter.locator.chats()), 1)

    def test_commit_keeps_post_receipt_and_prevents_recovery(self):
        entry = self.journal.begin(self.link.id, 'claude', self.chat, 'rename')
        result = self.adapter.writer.rename(self.chat, 'new')
        self.journal.commit(entry, result.receipt)
        self.restart()
        self.assertEqual(self.journal.recover(), [])
        self.assertEqual(self.adapter.locator.name(self.chat), 'new')
        self.assertEqual(self.store.journal_entry(entry)['post_receipt']['kind'], 'rename')

    def test_failed_rollback_stays_pending_and_is_retried(self):
        entry = self.journal.begin(self.link.id, 'claude', self.chat, 'cut')
        self.adapter.writer.cut(self.chat, 'p1')
        self.adapter.set_format(False, 'unknown')
        self.assertEqual(self.journal.recover()[0]['state'], 'failed')
        self.assertEqual(len(self.store.journal_entries(pending=True)), 1)
        self.adapter.set_format(True, self.adapter.facts.checked_versions[0])
        self.assertEqual(self.journal.recover()[0]['state'], 'taken_back')
        self.assertEqual(self.adapter.reader.read(self.chat), turns())

    def test_saved_cut_is_retained_30_days_and_pending_is_never_pruned(self):
        entry = self.journal.begin(self.link.id, 'claude', self.chat, 'cut')
        result = self.adapter.writer.cut(self.chat, 'p1')
        self.journal.commit(entry, result.receipt)
        pending = self.journal.begin(self.link.id, 'claude', self.chat, 'add')
        self.clock.value = '2026-01-31T00:00:00Z'
        self.assertEqual(self.journal.prune(), 0)
        self.clock.value = '2026-01-31T00:00:01Z'
        self.assertEqual(self.journal.prune(), 1)
        self.assertIsNone(self.store.journal_entry(entry)['pre_receipt'])
        self.assertIsNotNone(self.store.journal_entry(pending)['pre_receipt'])

    def test_saved_cut_can_be_restored_after_restart(self):
        entry = self.journal.begin(self.link.id, 'claude', self.chat, 'cut')
        result = self.adapter.writer.cut(self.chat, 'p1')
        self.journal.commit(entry, result.receipt)
        self.restart()
        self.journal.take_back(entry)
        self.journal.take_back(entry)
        self.assertEqual(self.adapter.reader.read(self.chat), turns())

    def test_recovery_stops_on_latest_failure_without_overwriting_it(self):
        first = self.journal.begin(self.link.id, 'claude', self.chat, 'cut')
        self.adapter.writer.cut(self.chat, 'p2')
        second = self.journal.begin(self.link.id, 'claude', self.chat, 'cut')
        self.adapter.writer.cut(self.chat, 'p1')
        self.adapter.set_format(False, 'unknown')
        result = self.journal.recover()
        self.assertEqual([r['id'] for r in result], [second])
        self.assertEqual(self.store.journal_entry(first)['state'], 'begun')
        self.adapter.set_format(True, self.adapter.facts.checked_versions[0])
        self.assertEqual([r['id'] for r in self.journal.recover()], [second, first])
        self.assertEqual(self.adapter.reader.read(self.chat), turns())

    def test_mark_shown_selects_only_turns_with_visibility_evidence(self):
        ids = self.store.record_turns(self.link.id, 'claude', turns())
        self.store.deliver(self.link.id, 'codex', ids, 'added', 'added', at=self.clock.now())
        self.assertEqual(self.store.mark_shown(self.link.id, 'codex', ids[:1]), 1)
        self.assertEqual([t.states['codex'] for t in self.store.turns(self.link.id)],
                         ['shown', 'added', 'added'])
        self.assertEqual(self.store.mark_shown(self.link.id, 'codex', []), 0)
        self.assertEqual(self.store.mark_shown(self.link.id, 'codex'), 2)

    def test_commit_refuses_receipt_for_another_write(self):
        entry = self.journal.begin(self.link.id, 'claude', self.chat, 'rename')
        result = self.adapter.writer.create([], 'other', '')
        with self.assertRaises(ValueError):
            self.journal.commit(entry, result.receipt)
        self.assertEqual(self.store.journal_entry(entry)['state'], 'begun')
