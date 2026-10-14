"""Safety rules DESIGN 5.1,1a,2a,2b,5,6 with fail-then-safe transitions."""
from dataclasses import replace
import unittest

from baton.adapters.fake import FakeAdapter
from baton.adapters.fake.facts import CLAUDE_LIKE, CODEX_LIKE, CURSOR_LIKE, OPENCODE_LIKE
from baton.domain.errors import (AppMustBeClosed, ChatChanged, ChatHeld, ChatReplying,
                                 NotAvailable, UnknownFormat)
from baton.ledger.sqlite_store import Ledger
from baton.services.journal import Guard
from tests.adapters.suite import turns


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.store = Ledger(':memory:')
        self.adapter = FakeAdapter(CLAUDE_LIKE, name='claude')
        self.chat = self.adapter.build_chat(turns())
        self.link = self.store.link({'claude': self.chat, 'codex': 'other'}, 'full_copy')
        self.guard = Guard(self.store)

    def tearDown(self):
        self.store.close()

    def check(self, **values):
        self.guard.check_write(self.adapter, self.chat, self.link.id, **values)

    def test_held_then_closed(self):
        for facts in (CLAUDE_LIKE, CODEX_LIKE):
            self.adapter.facts = facts
            self.adapter.set_condition(self.chat, open=True)
            with self.assertRaises(ChatHeld): self.check()
            self.adapter.set_condition(self.chat, open=False)
            self.check()

    def test_running_app_then_closed(self):
        self.adapter.facts = CURSOR_LIKE
        self.adapter.set_format(True, CURSOR_LIKE.checked_versions[0])
        self.adapter.set_condition(self.chat, app_running=True)
        with self.assertRaises(AppMustBeClosed): self.check()
        self.adapter.set_condition(self.chat, app_running=False)
        self.check()

    def test_replying_then_idle_and_any_time_allows_running_chat(self):
        self.adapter.set_condition(self.chat, replying=True)
        with self.assertRaises(ChatReplying): self.check()
        self.adapter.set_condition(self.chat, replying=False)
        self.check()
        self.adapter.facts = OPENCODE_LIKE
        self.adapter.set_condition(self.chat, open=True, replying=True, app_running=True)
        self.check()

    def test_unknown_format_then_known(self):
        self.adapter.set_format(False, 'unknown')
        with self.assertRaises(UnknownFormat): self.check()
        self.adapter.set_format(True, self.adapter.facts.checked_versions[0])
        self.adapter.set_condition(self.chat, format_known=False)
        with self.assertRaises(UnknownFormat): self.check()
        self.adapter.set_condition(self.chat, format_known=True)
        self.check()

    def test_changed_chat_and_missing_chat(self):
        with self.assertRaises(ChatChanged): self.check(expected=turns()[:1])
        self.check(expected=turns())
        self.adapter.set_condition(self.chat, exists=False)
        with self.assertRaises(ChatChanged): self.check()

    def test_unlinked_existing_write_refused_create_allowed(self):
        chat = self.adapter.build_chat([])
        with self.assertRaises(NotAvailable): self.guard.check_write(self.adapter, chat)
        with self.assertRaises(NotAvailable): self.guard.check_write(self.adapter, None)
        self.guard.check_write(self.adapter, None, action='create')
        self.check()

    def test_release_only_linked_open_idle_supported_chat(self):
        with self.assertRaises(NotAvailable): self.guard.check_release(self.adapter, self.chat)
        self.adapter.set_condition(self.chat, open=True, replying=True)
        with self.assertRaises(ChatReplying): self.guard.check_release(self.adapter, self.chat)
        self.adapter.set_condition(self.chat, replying=False)
        self.guard.check_release(self.adapter, self.chat)
        self.adapter.facts = CODEX_LIKE
        with self.assertRaises(NotAvailable): self.guard.check_release(self.adapter, self.chat)
        self.adapter.facts = CLAUDE_LIKE
        other = self.adapter.build_chat([])
        self.adapter.set_condition(other, open=True)
        with self.assertRaises(NotAvailable): self.guard.check_release(self.adapter, other)

    def test_cut_and_place_must_be_supported(self):
        self.adapter.facts = CODEX_LIKE
        for action in ('cut', 'place'):
            with self.assertRaises(NotAvailable): self.check(action=action)
        self.adapter.facts = replace(self.adapter.facts, can_cut=True, can_place=True)
        self.check(action='cut')
        self.check(action='place')
