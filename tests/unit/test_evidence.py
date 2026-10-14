"""E9 canonical provenance, legitimate streaming, and process-safe claims."""
from dataclasses import asdict, replace
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from baton.domain.errors import ChatChanged, NotAvailable
from baton.domain.model import Message, Turn, TOOL_CALL, turn_extends
from baton.ledger.sqlite_store import Ledger
from baton.services.digest import DigestBuilder
from baton.services.linker import Linker
from baton.services.observations import canonical_sources
from baton.services.refresh import ChatRefresh
from tests.scenarios.test_working_across import WorkingAcrossBase, at, label, make_turn


class EvidenceTests(WorkingAcrossBase):
    def record(self):
        return (self.store.get_link(self.link.id), self.store.turns(self.link.id),
                self.store.history(self.link.id), self.store.turn_evidence(self.link.id))

    def refresh(self):
        return ChatRefresh(self.store, self.adapters, self.clock).refresh(self.link.id)

    def test_streaming_same_message_suffix_and_final_metadata_advance(self):
        self.write('claude', make_turn('mine', at(13, 0), at(13, 1)))
        first = make_turn('stream', at(13, 10), at(13, 11), reply='start')
        chat = self.chats['codex']
        self.adapters['codex'].chats[chat].append(first)
        self.adapters['codex'].set_condition(chat, replying=True)
        self.refresh()
        row = self.store.turns(self.link.id)[-1]
        old_size = row.size
        final = Turn(first.prompt, (replace(first.messages[-1], text='start and finish', at=at(13, 12)),
                     Message('shell', TOOL_CALL, at=at(13, 13), tool='shell', tool_input={'command': 'pwd'}),
                     Message('answer', 'reply', 'done', at(13, 14))))
        self.adapters['codex'].chats[chat][-1] = final
        self.adapters['codex'].set_condition(chat, replying=False)
        self.adapters['codex'].changed_files['stream'] = ['done.py']
        self.refresh()
        current = self.store.turns(self.link.id)[-1]
        self.assertEqual(current.ended_at, at(13, 14))
        self.assertGreater(current.size, old_size)
        self.assertEqual(self.store.turn_evidence(self.link.id)[row.id],
                         {'turn': final, 'verified': True, 'complete': True})
        digest = DigestBuilder(self.store, self.readers, self.clock, label).for_side(self.link.id, 'claude')
        self.assertEqual((digest.until, digest.files, digest.commands), (at(13, 14), ('done.py',), 1))

    def test_completed_change_refuses_refresh_before_any_side_is_recorded(self):
        self.write('codex', make_turn('known', at(13, 0), at(13, 1)))
        before = self.record()
        self.adapters['claude'].chats[self.chats['claude']].append(make_turn('new', at(13, 2), at(13, 3)))
        original = self.adapters['codex'].chats[self.chats['codex']][0]
        self.adapters['codex'].chats[self.chats['codex']][0] = replace(
            original, messages=(replace(original.messages[-1], text='rewritten'),))
        with self.assertRaises(ChatChanged): self.refresh()
        self.assertEqual(self.record(), before)
        self.assertEqual(self.store.turn_evidence(self.link.id)[self.store.turns(self.link.id)[0].id]['turn'], original)

    def test_unfinished_rewrite_refuses_without_advancing_metadata(self):
        chat = self.chats['codex']
        source = make_turn('working', at(13, 0), at(13, 1), calls=1, reply='part')
        self.adapters['codex'].chats[chat].append(source)
        self.adapters['codex'].set_condition(chat, replying=True)
        self.refresh()
        before = self.record()
        changed = replace(source, messages=(replace(source.messages[0], tool_input={'n': 99}),
                                            replace(source.messages[-1], text='part longer', at=at(13, 9))))
        self.adapters['codex'].chats[chat][-1] = changed
        with self.assertRaises(ChatChanged): self.refresh()
        self.assertEqual(self.record(), before)

    def test_legacy_observation_never_claims_unchanged_history(self):
        self.write('claude', make_turn('mine', at(13, 0), at(13, 1)))
        self.write('codex', make_turn('legacy', at(13, 2), at(13, 3)))
        with self.store.db: self.store.db.execute('delete from turn_evidence')
        self.refresh()
        self.refresh()
        self.assertTrue(all(not value['verified'] for value in self.store.turn_evidence(self.link.id).values()))
        with self.assertRaises(NotAvailable) as error:
            DigestBuilder(self.store, self.readers, self.clock, label).for_side(self.link.id, 'claude')
        self.assertEqual(str(error.exception), 'unverified_turn_baseline')
        self.assertNotIsInstance(error.exception, ChatChanged)

    def test_explicit_fresh_link_records_verified_baseline_and_incomplete_target(self):
        self.store.remove_link(self.link.id, self.clock.now())
        self.adapters['claude'].chats[self.chats['claude']].append(make_turn('source', at(13, 0), at(13, 1)))
        target = make_turn('target', at(13, 2), at(13, 3), reply='working')
        self.adapters['codex'].chats[self.chats['codex']].append(target)
        self.adapters['codex'].set_condition(self.chats['codex'], replying=True)
        linker = Linker(self.store, self.adapters, self.clock)
        result = linker.apply(linker.plan_link('claude', self.chats['claude'], 'codex', self.chats['codex']))
        self.assertTrue(result.applied, result)
        values = list(self.store.turn_evidence(result.link_id).values())
        self.assertTrue(all(value['verified'] for value in values))
        self.assertEqual([value['complete'] for value in values], [True, False])

    def test_archive_fallback_requires_latest_sanctioned_removal(self):
        self.write('codex', make_turn('known', at(13, 0), at(13, 1)))
        row = self.store.turns(self.link.id)[0]
        source = self.adapters['codex'].chats[self.chats['codex']][0]
        before = {'turns': [{'id': row.id, 'origin': 'codex', 'origin_id': source.id}]}
        snapshot = {'chat_id': self.chats['codex'], 'turns': [asdict(source)]}
        after = {'chat_id': self.chats['codex'], 'turns': []}
        with self.store.db:
            self.store._event(self.link.id, self.clock.now(), 'undo', 'codex',
                              {'before': before, 'before_chats': {'codex': snapshot}, 'after': {'codex': after}})
        self.assertEqual(canonical_sources(self.store, self.link.id, {'codex': []})[row.id], source)
        with self.store.db:
            self.store._event(self.link.id, self.clock.now(), 'restore', 'codex', {'after': {'codex': snapshot}})
        with self.assertRaises(ChatChanged): canonical_sources(self.store, self.link.id, {'codex': []})

    def test_missing_active_origin_cannot_use_unrelated_undo_snapshot(self):
        self.write('codex', make_turn('known', at(13, 0), at(13, 1)))
        before = self.record()
        self.adapters['codex'].chats[self.chats['codex']].clear()
        with self.assertRaises(ChatChanged): self.refresh()
        self.assertEqual(before, self.record())


class GrowthTests(unittest.TestCase):
    def test_only_suffix_or_activity_append_preserves_prompt_and_identity(self):
        first = make_turn('stream', at(13, 0), at(13, 1), calls=1, reply='part')
        reply = replace(first.messages[-1], text='part complete', at=at(13, 2))
        grown = replace(first, messages=(*first.messages[:-1], reply))
        self.assertTrue(turn_extends(first, grown))
        self.assertTrue(turn_extends(first, replace(grown, messages=(*grown.messages, Message('next', 'reply', 'later')))))
        variants = [replace(grown, prompt=replace(first.prompt, id='other')),
                    replace(grown, prompt=replace(first.prompt, text='different')),
                    replace(grown, messages=(reply, first.messages[0])),
                    replace(grown, messages=(replace(first.messages[0], tool_input={'n': 9}), reply)),
                    replace(grown, messages=(first.messages[0], replace(reply, id='other'))),
                    replace(grown, messages=(first.messages[0], replace(reply, text='replacement')))]
        for value in variants:
            with self.subTest(value=value): self.assertFalse(turn_extends(first, value))

    def test_canonical_baseline_survives_reopen_and_additive_legacy_migration(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / 'ledger.sqlite')
            store = Ledger(path)
            link = store.link({'claude': 'source', 'codex': 'target'}, 'full_copy', 'now')
            turn = make_turn('known', at(13, 0), at(13, 1))
            (ident,) = store.record_turns(link.id, 'claude', [turn])
            store.close()
            store = Ledger(path)
            self.assertEqual(store.turn_evidence(link.id)[ident],
                             {'turn': turn, 'verified': True, 'complete': True})
            before = store.turns(link.id)
            with store.db:
                store.db.execute('drop table turn_evidence')
                store.db.execute('drop table limit_offers')
            store.close()
            store = Ledger(path)
            try:
                self.assertEqual(store.turns(link.id), before)
                self.assertEqual(store.turn_evidence(link.id), {})
                store.record_turns(link.id, 'claude', [turn])
                self.assertFalse(store.turn_evidence(link.id)[ident]['verified'])
                self.assertTrue(store.claim_limit_offer('limit', 'now'))
                self.assertFalse(store.claim_limit_offer('limit', 'later'))
            finally:
                store.close()


_OFFER_PROCESS = '''
import sys
from baton.adapters.fake import FakeAdapter
from baton.adapters.fake.facts import CLAUDE_LIKE, CODEX_LIKE
from baton.domain.model import Message, Turn
from baton.domain.conditions import SideCondition
from baton.ledger.sqlite_store import Ledger
from baton.ports.clock import FixedClock
from baton.ports.tool import Usage, ChatRef
from baton.services.limit_offer import LimitOffers
store = Ledger(sys.argv[1])
source, target = FakeAdapter(CLAUDE_LIKE, 'claude'), FakeAdapter(CODEX_LIKE, 'codex')
source.chats['source'] = [Turn(Message(sys.argv[2], 'prompt', 'work'))]
source.refs['source'] = ChatRef('source', 'source', '', '')
source.conditions['source'] = SideCondition()
source.usage_values['source'] = Usage(100, 1000, True, None)
target.chats['target'] = []
target.refs['target'] = ChatRef('target', 'target', '', '')
target.conditions['target'] = SideCondition()
offers = LimitOffers(store, {'claude': source.reader, 'codex': target.reader}, FixedClock('2026-10-05T14:00:00Z'))
if sys.argv[3] == 'barrier':
    print('ready', flush=True)
    sys.stdin.readline()
print(int(offers.check('claude', 'source', enabled=sys.argv[3] != 'disabled') is not None), flush=True)
store.close()
'''


class DurableOfferTests(unittest.TestCase):
    def test_actual_second_process_suppresses_same_latest_turn_linked_and_unlinked(self):
        for linked in (False, True):
            with self.subTest(linked=linked), tempfile.TemporaryDirectory() as tmp:
                path = str(Path(tmp) / 'ledger.sqlite')
                store = Ledger(path)
                if linked: store.link({'claude': 'source', 'codex': 'target'}, 'full_copy', 'now')
                store.close()
                def claim(turn='limit', mode='normal'):
                    return subprocess.check_output([sys.executable, '-c', _OFFER_PROCESS, path, turn, mode], text=True).strip()
                self.assertEqual(claim(mode='disabled'), '0')
                self.assertEqual(claim(), '1')
                self.assertEqual(claim(), '0')
                self.assertEqual(claim(turn='new-limit'), '1')

    def test_independent_processes_claim_simultaneously_exactly_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / 'ledger.sqlite')
            Ledger(path).close()
            workers = [subprocess.Popen([sys.executable, '-c', _OFFER_PROCESS, path, 'limit', 'barrier'],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                       for _ in range(2)]
            try:
                for worker in workers: self.assertEqual(worker.stdout.readline().strip(), 'ready')
                for worker in workers:
                    worker.stdin.write('go\n'); worker.stdin.flush()
                results = []
                for worker in workers:
                    output, error = worker.communicate(timeout=10)
                    self.assertEqual(worker.returncode, 0, error)
                    results.append(output.strip())
                self.assertEqual(sorted(results), ['0', '1'])
            finally:
                for worker in workers:
                    if worker.poll() is None: worker.kill()
                    worker.communicate()


if __name__ == '__main__':
    unittest.main()
