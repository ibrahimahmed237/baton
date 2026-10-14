"""E11 explicit names across each measured capability set."""
import unittest
from dataclasses import replace
from unittest.mock import patch

from baton.adapters.fake import FakeAdapter
from baton.adapters.fake.facts import CLAUDE_LIKE, CODEX_LIKE, OPENCODE_LIKE, CURSOR_LIKE
from baton.domain.errors import AppMustBeClosed, ChatChanged, NotAvailable, UnknownFormat
from baton.ledger.sqlite_store import Ledger
from baton.ports.clock import FixedClock
from baton.services.names import Names

FACTS = (CLAUDE_LIKE, CODEX_LIKE, OPENCODE_LIKE, CURSOR_LIKE)


class NamesTests(unittest.TestCase):
    def setUp(self):
        self.store = Ledger(':memory:')
        self.addCleanup(self.store.close)
        self.adapters = {'claude': FakeAdapter(CLAUDE_LIKE, 'claude'),
                         'codex': FakeAdapter(CODEX_LIKE, 'codex')}
        self.chats = {s: a.build_chat([], name=s, folder='/fixture') for s, a in self.adapters.items()}
        self.link = self.store.link(self.chats, 'full_copy')
        self.service = Names(self.store, self.adapters, FixedClock('2026-10-14T00:00:00Z'))

    def test_names_read_native_changes_each_time_and_never_rename(self):
        self.assertEqual(self.service.names(self.link.id), {'claude': 'claude', 'codex': 'codex'})
        a = self.adapters['claude']
        a.refs[self.chats['claude']] = replace(a.refs[self.chats['claude']], name='new native name')
        with patch.object(a.writer, 'rename', side_effect=AssertionError):
            self.assertEqual(self.service.names(self.link.id)['claude'], 'new native name')
        self.assertEqual(self.store.known_chat('claude', self.chats['claude'])['name'], 'new native name')

    def test_per_fact_rename_needs_and_notes(self):
        for facts, needs in zip(FACTS, [('app_closed', 'relaunch_to_see'), ('relaunch_to_see',), (), ('app_closed', 'relaunch_to_see')]):
            self.adapters['claude'].facts = facts
            plan = self.service.plan_rename(self.link.id, 'same', ['claude'])
            self.assertEqual(plan.steps[0].needs, needs)
            from baton.notes.catalogue import get
            get(self.service.notes(plan)[0].id).render(self.service.notes(plan)[0].values)
            self.assertEqual(self.adapters['claude'].locator.name(self.chats['claude']), 'claude')

    def test_apply_only_selected_side_and_record_exact_earlier_title(self):
        plan = self.service.plan_rename(self.link.id, 'same', ['codex'])
        result = self.service.apply(plan)
        self.assertTrue(result.applied)
        self.assertEqual(result.renamed, ('codex',))
        self.assertEqual(self.service.names(self.link.id), {'claude': 'claude', 'codex': 'same'})
        event = self.store.history(self.link.id)[0]
        self.assertEqual((event.kind, event.detail), ('renamed', {'before': 'codex', 'name': 'same'}))
        self.assertEqual(self.store.journal_entries()[0]['state'], 'committed')
        self.service.journal.take_back(self.store.journal_entries()[0]['id'])
        self.assertEqual(self.service.names(self.link.id)['codex'], 'codex')

    def test_closed_rename_refuses_running_app_even_when_chat_unheld(self):
        for facts in (CLAUDE_LIKE, CURSOR_LIKE):
            self.adapters['claude'].facts = facts
            self.adapters['claude'].set_format(True, facts.checked_versions[0])
            self.adapters['claude'].app_running = True
            plan = self.service.plan_rename(self.link.id, 'same')
            with self.assertRaises(AppMustBeClosed):
                self.service.apply(plan)
            self.assertEqual(self.service.names(self.link.id)['codex'], 'codex')
            self.assertEqual(self.store.journal_entries(), [])

    def test_changed_name_content_record_or_facts_refuses_confirmation(self):
        for mutation in ('name', 'record', 'facts'):
            with self.subTest(mutation=mutation):
                self.store.set_paused(self.link.id, False)
                plan = self.service.plan_rename(self.link.id, 'same')
                a = self.adapters['codex']
                if mutation == 'name':
                    a.refs[self.chats['codex']] = replace(a.refs[self.chats['codex']], name='outside')
                elif mutation == 'record':
                    self.store.set_paused(self.link.id, True)
                else:
                    a.facts = OPENCODE_LIKE
                with self.assertRaises(ChatChanged):
                    self.service.apply(plan)
        self.assertEqual(self.store.journal_entries(), [])

    def test_unknown_format_refuses_before_first_write(self):
        self.adapters['codex'].set_format(False, 'future')
        plan = self.service.plan_rename(self.link.id, 'same')
        with self.assertRaises(UnknownFormat):
            self.service.apply(plan)
        self.assertEqual(self.service.names(self.link.id)['claude'], 'claude')

    def test_failed_readback_rolls_back_both_names(self):
        writer = self.adapters['codex'].writer
        original = writer.rename
        def bad(chat, name):
            return original(chat, 'wrong')
        with patch.object(writer, 'rename', side_effect=bad):
            with self.assertRaises(ChatChanged):
                self.service.apply(self.service.plan_rename(self.link.id, 'same'))
        self.assertEqual(self.service.names(self.link.id), {'claude': 'claude', 'codex': 'codex'})
        self.assertTrue(all(e['state'] == 'taken_back' for e in self.store.journal_entries()))

    def test_invalid_selection_and_empty_name_refuse(self):
        for name, tools in [(' ', None), ('same', []), ('same', ['missing']), ('same', ['codex', 'codex'])]:
            with self.assertRaises(NotAvailable):
                self.service.plan_rename(self.link.id, name, tools)

    def test_matching_name_is_noop(self):
        plan = self.service.plan_rename(self.link.id, 'codex', ['codex'])
        self.assertEqual(plan.steps, ())
        self.service.apply(plan)
        self.assertEqual(self.store.journal_entries(), [])

    def test_other_name_changes_during_first_write_is_not_overwritten(self):
        first = self.adapters['claude'].writer
        original = first.rename
        def rename(chat, name):
            result = original(chat, name)
            target = self.adapters['codex']
            target.refs[self.chats['codex']] = replace(target.refs[self.chats['codex']], name='outside name')
            return result
        with patch.object(first, 'rename', side_effect=rename):
            with self.assertRaises(ChatChanged):
                self.service.apply(self.service.plan_rename(self.link.id, 'same'))
        self.assertEqual(self.service.names(self.link.id), {'claude': 'claude', 'codex': 'outside name'})

    def test_content_change_after_preview_is_refused(self):
        from baton.domain.model import Message, Turn
        plan = self.service.plan_rename(self.link.id, 'same')
        self.adapters['codex'].chats[self.chats['codex']].append(Turn(Message('new', 'prompt', 'new', ''), ()))
        with self.assertRaises(ChatChanged):
            self.service.apply(plan)
        self.assertEqual(self.store.journal_entries(), [])
