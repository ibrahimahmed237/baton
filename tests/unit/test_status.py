"""The scenarios of docs/features/sync-status.md, at the level of the record."""
import unittest

from baton.adapters.fake.facts import CLAUDE_LIKE
from baton.services import status
from baton.domain.link import ADDED, ATTACHED, ATTACHED_HISTORY, CLAUDE, CODEX, FULL_COPY, SHOWN
from baton.ledger.sqlite_store import Ledger
from baton.domain.conditions import SideCondition
from baton.services.status import link_status
from tests.unit.test_ledger import make_turn, make_turns

OPEN = SideCondition(open=True)


class StatusCase(unittest.TestCase):
    mode = FULL_COPY

    def setUp(self):
        self.ledger = Ledger(":memory:")
        self.addCleanup(self.ledger.close)
        self.link = self.ledger.link({CLAUDE: "claude-a", CODEX: "codex-b"}, self.mode)

    def write(self, side, prefix, count, first=1):
        return self.ledger.record_turns(self.link.id, side, make_turns(prefix, count, first))

    def synced(self, count=12):
        """A conversation written in Claude and fully shown in Codex."""
        ids = self.write(CLAUDE, "c", count)
        self.ledger.deliver(self.link.id, CODEX, ids, SHOWN, "twin_created")
        return ids

    def status(self, **conditions):
        link = self.ledger.get_link(self.link.id)
        return link_status(link, self.ledger.turns(link.id), conditions, facts={side: CLAUDE_LIKE for side in link.sides})


class FullCopyTest(StatusCase):
    def test_everything_delivered_is_in_sync(self):
        self.synced()
        result = self.status()
        self.assertTrue(result.in_sync)
        self.assertFalse(result.decision_needed)
        for side in (CLAUDE, CODEX):
            self.assertEqual((result.side(side).agent_has, result.side(side).chat_shows), (12, 12))
            self.assertEqual(result.side(side).waiting_reason, "")

    def test_s1_turns_wait_for_an_open_chat(self):
        self.synced()
        self.write(CODEX, "x", 2)
        result = self.status(claude=OPEN)
        claude = result.side(CLAUDE)
        self.assertEqual((claude.total, claude.agent_has, claude.chat_shows, claude.waiting), (14, 12, 12, 2))
        self.assertEqual(claude.waiting_reason, status.CHAT_OPEN)
        self.assertEqual(claude.attached_on_next_message, 2)
        self.assertEqual(claude.synced_up_to.origin_id, "c12")
        self.assertTrue(result.side(CODEX).in_sync)
        self.assertFalse(result.in_sync)

    def test_s2_attached_turns_are_known_but_not_shown(self):
        self.synced()
        new = self.write(CODEX, "x", 2)
        self.ledger.deliver(self.link.id, CLAUDE, new, ATTACHED, "attached")
        result = self.status(claude=OPEN)
        claude = result.side(CLAUDE)
        self.assertEqual((claude.agent_has, claude.chat_shows, claude.attached, claude.waiting), (14, 12, 2, 0))
        self.assertEqual(claude.attached_on_next_message, 0)
        self.assertEqual(claude.synced_up_to.origin_id, "x2")
        self.assertTrue(result.in_sync)

    def test_s3_turns_added_to_a_closed_chat_are_shown(self):
        self.synced()
        new = self.write(CODEX, "x", 2)
        self.ledger.deliver(self.link.id, CLAUDE, new, SHOWN, "added")
        claude = self.status().side(CLAUDE)
        self.assertEqual((claude.agent_has, claude.chat_shows), (14, 14))

    def test_s10_added_turns_show_after_a_relaunch(self):
        ids = self.write(CODEX, "x", 3)
        self.ledger.deliver(self.link.id, CLAUDE, ids, ADDED, "twin_created")
        claude = self.status(claude=OPEN).side(CLAUDE)
        self.assertEqual((claude.agent_has, claude.chat_shows, claude.added), (3, 0, 3))
        self.ledger.mark_shown(self.link.id, CLAUDE)
        claude = self.status(claude=OPEN).side(CLAUDE)
        self.assertEqual((claude.agent_has, claude.chat_shows, claude.added), (3, 3, 0))

    def test_a_closed_chat_just_has_not_been_synced_yet(self):
        self.synced()
        self.write(CLAUDE, "c", 1, first=13)
        codex = self.status().side(CODEX)
        self.assertEqual((codex.waiting, codex.waiting_reason), (1, status.NOT_SYNCED_YET))
        self.assertEqual(codex.attached_on_next_message, 0)

    def test_synced_up_to_is_the_turn_before_the_waiting_ones(self):
        self.synced()
        self.write(CLAUDE, "c", 2, first=13)
        self.assertEqual(self.status().side(CODEX).synced_up_to.origin_id, "c12")
        self.assertEqual(self.status().side(CLAUDE).synced_up_to.origin_id, "c14")

    def test_the_size_of_what_the_next_message_carries(self):
        self.ledger.record_turns(self.link.id, CODEX, [make_turn("x1", "p" * 300, reply="r" * 500)])
        claude = self.status(claude=OPEN).side(CLAUDE)
        self.assertEqual((claude.attached_on_next_message, claude.attached_tokens), (1, 200))


class WaitingReasonTest(StatusCase):
    def setUp(self):
        super().setUp()
        self.synced()
        self.write(CODEX, "x", 2)

    def test_paused(self):
        self.ledger.set_paused(self.link.id, True)
        result = self.status(claude=OPEN)
        self.assertTrue(result.paused)
        self.assertEqual(result.side(CLAUDE).waiting_reason, status.PAUSED)
        self.assertEqual(result.side(CLAUDE).attached_on_next_message, 0)

    def test_hooks_not_ready(self):
        claude = self.status(claude=SideCondition(open=True, hooks_ready=False)).side(CLAUDE)
        self.assertEqual(claude.waiting_reason, status.HOOKS_NOT_READY)
        self.assertEqual(claude.attached_on_next_message, 0)

    def test_side_missing(self):
        claude = self.status(claude=SideCondition(exists=False)).side(CLAUDE)
        self.assertEqual(claude.waiting_reason, status.SIDE_MISSING)

    def test_both_sides_have_new_turns(self):
        self.write(CLAUDE, "c", 1, first=13)
        result = self.status(claude=OPEN, codex=OPEN)
        self.assertTrue(result.decision_needed)
        self.assertEqual((result.side(CLAUDE).waiting, result.side(CODEX).waiting), (2, 1))
        for side in (CLAUDE, CODEX):
            self.assertEqual(result.side(side).waiting_reason, status.DECISION_NEEDED)
            self.assertEqual(result.side(side).attached_on_next_message, 0)
        self.assertEqual(result.side(CLAUDE).synced_up_to.origin_id, "c12")
        self.assertEqual(result.side(CODEX).synced_up_to.origin_id, "x2")


class KeptAndSkippedTest(StatusCase):
    def test_v11_a_kept_turn_is_not_waiting(self):
        ids = self.write(CLAUDE, "c", 2)
        self.ledger.keep_back(self.link.id, ids[0])
        self.ledger.deliver(self.link.id, CODEX, ids[1:], SHOWN, "added")
        result = self.status()
        codex = result.side(CODEX)
        self.assertEqual((codex.agent_has, codex.waiting, codex.kept_elsewhere), (1, 0, 1))
        self.assertTrue(result.in_sync)

    def test_a_skipped_turn_is_not_waiting(self):
        ids = self.write(CODEX, "x", 1)
        self.ledger.skip(self.link.id, ids[0], CLAUDE)
        claude = self.status().side(CLAUDE)
        self.assertEqual((claude.agent_has, claude.waiting, claude.skipped), (0, 0, 1))


class AttachedHistoryTest(StatusCase):
    mode = ATTACHED_HISTORY

    def test_s5_the_history_waits_for_the_first_message(self):
        self.write(CLAUDE, "c", 12)
        codex = self.status(codex=OPEN).side(CODEX)
        self.assertEqual((codex.agent_has, codex.chat_shows, codex.waiting), (0, 0, 12))
        self.assertEqual(codex.waiting_reason, status.CHAT_OPEN)
        self.assertEqual(codex.attached_on_next_message, 12)
        self.assertIsNone(codex.synced_up_to)


if __name__ == "__main__":
    unittest.main()
