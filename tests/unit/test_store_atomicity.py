"""Delivery, history and journal completion survive or roll back together."""
from dataclasses import asdict
from pathlib import Path
import sqlite3
import tempfile
import unittest

from baton.domain.link import SHOWN, WAITING
from baton.ledger.sqlite_store import Ledger
from tests.unit.test_ledger import make_turn


class StoreAtomicityTests(unittest.TestCase):
    def test_completion_failure_and_retry_remain_atomic_after_reopen(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / 'records.sqlite')
            store = Ledger(path)
            self.addCleanup(lambda: store.close())
            link = store.link({'claude': 'source', 'codex': 'target'}, 'full_copy', at='2026-10-05T00:00:00Z')
            ids = store.record_turns(link.id, 'claude', [make_turn('source-turn')])
            receipt = {'tool': 'codex', 'chat_id': 'target', 'kind': 'add', 'data': {}}
            entry = store.journal_begin(link.id, 'codex', 'target', 'add', '2026-10-05T00:01:00Z', receipt)
            before = [asdict(event) for event in store.history(link.id)]
            store.db.execute("create trigger fail_completion before update on journal "
                             "when new.state='committed' begin select raise(abort,'completion_failed'); end")

            with self.assertRaises(sqlite3.IntegrityError):
                store.complete_write(entry, receipt, '2026-10-05T00:02:00Z', link.id,
                                     'codex', ids, SHOWN, 'add', ['local-copy'])
            store.close()
            store = Ledger(path)
            self.assertEqual(store.turns(link.id)[0].states['codex'], WAITING)
            self.assertEqual(store.local_ids(link.id, 'codex'), {})
            self.assertEqual([asdict(event) for event in store.history(link.id)], before)
            self.assertEqual(store.journal_entry(entry)['state'], 'begun')

            store.db.execute('drop trigger fail_completion')
            event = store.complete_write(entry, receipt, '2026-10-05T00:02:00Z', link.id,
                                         'codex', ids, SHOWN, 'add', ['local-copy'])
            store.close()
            store = Ledger(path)
            self.assertEqual(store.turns(link.id)[0].states['codex'], SHOWN)
            self.assertEqual(store.local_ids(link.id, 'codex'), {ids[0]: 'local-copy'})
            self.assertEqual(store.journal_entry(entry)['state'], 'committed')
            self.assertEqual(store.history(link.id)[0].id, event)
            self.assertEqual(store.history(link.id)[0].turn_ids, tuple(ids))
            self.assertEqual(len(store.history(link.id)), len(before) + 1)
