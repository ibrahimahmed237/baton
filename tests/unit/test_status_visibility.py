"""Visibility needs actual app-start evidence, never a prompt-hook call."""
import unittest

from baton.adapters.fake.facts import CLAUDE_LIKE, CODEX_LIKE, OPENCODE_LIKE
from baton.domain.conditions import SideCondition
from baton.domain.link import ADDED, ATTACHED, FULL_COPY
from baton.ledger.sqlite_store import Ledger
from baton.services.status import link_status
from tests.unit.test_ledger import make_turn


class VisibilityTest(unittest.TestCase):
    def setUp(self):
        self.store = Ledger(":memory:")
        self.addCleanup(self.store.close)
        self.link = self.store.link({"claude": "a", "codex": "b"}, FULL_COPY)
        self.ids = self.store.record_turns(self.link.id, "claude", [make_turn("one")])
        self.store.deliver(self.link.id, "codex", self.ids, ADDED, "added", at="2026-10-05T10:00:00Z")

    def side(self, facts, start=""):
        return link_status(self.link, self.store.turns(self.link.id),
                           {"codex": SideCondition(open=True, app_started_at=start)},
                           facts={"claude": facts, "codex": facts},
                           history=self.store.history(self.link.id)).side("codex")

    def test_at_once_is_immediately_shown(self):
        side = self.side(CODEX_LIKE)
        self.assertEqual((side.chat_shows, side.added, side.needs), (1, 0, ()))

    def test_relaunch_keeps_note_until_later_start(self):
        for start in ("", "2026-10-05T09:00:00Z", "2026-10-05T10:00:00Z", "bad"):
            with self.subTest(start=start):
                side = self.side(CLAUDE_LIKE, start)
                self.assertEqual((side.chat_shows, side.added, side.needs), (0, 1, ("relaunch_to_see",)))
        side = self.side(CLAUDE_LIKE, "2026-10-05T10:00:00.001Z")
        self.assertEqual((side.chat_shows, side.added, side.shown_turn_ids), (1, 0, tuple(self.ids)))

    def test_reopen_requires_start_or_explicit_user_mark(self):
        self.assertEqual(self.side(OPENCODE_LIKE).needs, ("reopen_chat_to_see",))
        self.assertEqual(self.side(OPENCODE_LIKE, "2026-10-05T10:01:00Z").chat_shows, 1)
        self.store.mark_shown(self.link.id, "codex")
        self.assertEqual(self.side(OPENCODE_LIKE).chat_shows, 1)

    def test_prompt_hook_and_non_delivery_event_are_not_evidence(self):
        self.store._event(self.link.id, "2026-10-05T11:00:00Z", "prompt_hook", "codex", turn_ids=self.ids)
        self.assertEqual(self.side(OPENCODE_LIKE).chat_shows, 0)
        self.assertEqual(self.side(OPENCODE_LIKE, "2026-10-05T10:01:00Z").chat_shows, 1)

    def test_mixed_delivery_times_only_show_older_turn(self):
        ids = self.store.record_turns(self.link.id, "claude", [make_turn("two")])
        self.store.deliver(self.link.id, "codex", ids, ADDED, "added", at="2026-10-05T12:00:00Z")
        side = self.side(CLAUDE_LIKE, "2026-10-05T11:00:00Z")
        self.assertEqual((side.chat_shows, side.added, side.shown_turn_ids), (1, 1, tuple(self.ids)))

    def test_attached_never_becomes_shown_after_start(self):
        ids = self.store.record_turns(self.link.id, "claude", [make_turn("two")])
        self.store.deliver(self.link.id, "codex", ids, ATTACHED, "attached", at="2026-10-05T10:00:00Z")
        side = self.side(CLAUDE_LIKE, "2026-10-05T12:00:00Z")
        self.assertEqual((side.chat_shows, side.attached), (1, 1))

    def test_naive_or_invalid_delivery_time_does_not_prove_visibility(self):
        self.store.db.execute("update events set at='bad' where kind='added'")
        self.assertEqual(self.side(CLAUDE_LIKE, "2026-10-05T12:00:00Z").chat_shows, 0)
        self.store.db.execute("update events set at='2026-10-05T10:00:00' where kind='added'")
        self.assertEqual(self.side(CLAUDE_LIKE, "2026-10-05T12:00:00Z").chat_shows, 0)
