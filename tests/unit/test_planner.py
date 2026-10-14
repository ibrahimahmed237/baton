"""Delivery rules, and the scenarios of docs/features/merge.md at the level of the record."""
import unittest

from baton.adapters.fake.facts import CLAUDE_LIKE
from baton.services import planner, status
from baton.domain.link import ATTACHED_HISTORY, CLAUDE, CODEX, FULL_COPY, SHOWN, SKIPPED
from baton.ledger.sqlite_store import Ledger
from baton.services.planner import (ADD, ADD_AFTER_RELEASE, ATTACH, BY_TIME, DONT_REORDER, HOLD, KEEPS_CHAT, MERGED_COPY,
                           plan_sync)
from baton.domain.conditions import SideCondition
from baton.domain.errors import OrderNotAllowed
from tests.unit.test_ledger import make_turn, make_turns

OPEN = SideCondition(open=True)
REPLYING = SideCondition(open=True, replying=True)


class PlannerCase(unittest.TestCase):
    mode = FULL_COPY

    def setUp(self):
        self.ledger = Ledger(":memory:")
        self.addCleanup(self.ledger.close)
        self.link = self.ledger.link({CLAUDE: "claude-a", CODEX: "codex-b"}, self.mode)
        shared = self.ledger.record_turns(self.link.id, CLAUDE, make_turns("s", 3))
        self.ledger.deliver(self.link.id, CODEX, shared, SHOWN, "twin_created")

    def write(self, side, *turns):
        return self.ledger.record_turns(self.link.id, side, turns)

    def turns(self):
        return self.ledger.turns(self.link.id)

    def plan(self, add_when_idle=(), **conditions):
        return plan_sync(self.ledger.get_link(self.link.id), self.turns(), conditions, add_when_idle, facts={side: CLAUDE_LIKE for side in self.link.sides})

    def names(self, order):
        return [turn.origin_id for turn in order]


class DeliveryTest(PlannerCase):
    def test_nothing_to_do_when_in_sync(self):
        result = self.plan()
        self.assertEqual(result.steps, {})
        self.assertFalse(result.writes_anything)

    def test_a_closed_chat_gets_the_turns_added(self):
        self.write(CLAUDE, make_turn("c1"), make_turn("c2"))
        step = self.plan().steps[CODEX]
        self.assertEqual((step.action, self.names(step.turns)), (ADD, ["c1", "c2"]))

    def test_an_open_chat_gets_them_attached_to_the_next_message(self):
        self.write(CODEX, make_turn("x1"))
        result = self.plan(claude=OPEN)
        self.assertEqual((result.steps[CLAUDE].action, result.steps[CLAUDE].reason), (ATTACH, status.CHAT_OPEN))
        self.assertFalse(result.writes_anything)

    def test_an_idle_open_chat_gets_them_added_when_the_user_chose_automatic(self):
        self.write(CODEX, make_turn("x1"))
        self.assertEqual(self.plan(add_when_idle={CLAUDE}, claude=OPEN).steps[CLAUDE].action, ADD_AFTER_RELEASE)

    def test_a_replying_chat_is_never_released(self):
        self.write(CODEX, make_turn("x1"))
        self.assertEqual(self.plan(add_when_idle={CLAUDE}, claude=REPLYING).steps[CLAUDE].action, ATTACH)

    def test_a_paused_link_holds_everything(self):
        self.write(CLAUDE, make_turn("c1"))
        self.ledger.set_paused(self.link.id, True)
        step = self.plan().steps[CODEX]
        self.assertEqual((step.action, step.reason), (HOLD, status.PAUSED))

    def test_hooks_not_ready_holds_an_open_chat(self):
        self.write(CODEX, make_turn("x1"))
        step = self.plan(claude=SideCondition(open=True, hooks_ready=False)).steps[CLAUDE]
        self.assertEqual((step.action, step.reason), (HOLD, status.HOOKS_NOT_READY))

    def test_m1_nothing_is_written_when_both_sides_have_new_turns(self):
        self.write(CLAUDE, make_turn("c1"))
        self.write(CODEX, make_turn("x1"))
        result = self.plan()
        self.assertTrue(result.decision_needed)
        self.assertFalse(result.writes_anything)
        self.assertEqual({step.action for step in result.steps.values()}, {HOLD})
        self.assertEqual({step.reason for step in result.steps.values()}, {status.DECISION_NEEDED})


class AttachedHistoryDeliveryTest(PlannerCase):
    mode = ATTACHED_HISTORY

    def test_a_link_with_attached_history_is_not_released(self):
        self.write(CODEX, make_turn("x1"))
        self.assertEqual(self.plan(add_when_idle={CLAUDE}, claude=OPEN).steps[CLAUDE].action, ATTACH)


class MergeTest(PlannerCase):
    """C1 at 14:00, X1 at 14:05, C2 at 14:10: the case of U1 to U8."""

    def setUp(self):
        super().setUp()
        self.c1, self.c2 = self.write(CLAUDE, make_turn("c1", at="14:00", ended="14:03"),
                                      make_turn("c2", at="14:10", ended="14:12"))
        self.x1, = self.write(CODEX, make_turn("x1", at="14:05", ended="14:08"))

    def order(self, preset=BY_TIME):
        return planner.merge_order(self.turns(), preset)

    def test_m2_the_last_shared_turn_and_the_unsynced_ones(self):
        self.assertEqual(planner.last_shared(self.turns()).origin_id, "s3")
        self.assertEqual(self.names(planner.unsynced(self.turns())), ["c1", "c2", "x1"])

    def test_u1_time_order_gives_both_sides_a_merged_copy(self):
        order = self.order()
        self.assertEqual(self.names(order), ["c1", "x1", "c2"])
        self.assertEqual(planner.outcome(order), {CLAUDE: MERGED_COPY, CODEX: MERGED_COPY})

    def test_u2_claudes_first_lets_claude_keep_its_chat(self):
        order = self.order(CLAUDE)
        self.assertEqual(self.names(order), ["c1", "c2", "x1"])
        self.assertEqual(planner.outcome(order), {CLAUDE: KEEPS_CHAT, CODEX: MERGED_COPY})

    def test_u3_an_apps_own_turns_cannot_pass_each_other(self):
        with self.assertRaises(OrderNotAllowed):
            planner.move(self.turns(), self.order(), self.c2, 0)
        with self.assertRaises(OrderNotAllowed):
            planner.check_order(self.turns(), self.order()[:2])

    def test_u4_moving_the_codex_turn_to_the_top(self):
        order = planner.move(self.turns(), self.order(), self.x1, 0)
        self.assertEqual(self.names(order), ["x1", "c1", "c2"])
        self.assertEqual(planner.outcome(order), {CODEX: KEEPS_CHAT, CLAUDE: MERGED_COPY})

    def test_u6_dont_reorder_keeps_both_chats(self):
        order = self.order(DONT_REORDER)
        self.assertEqual(planner.outcome(order, DONT_REORDER), {CLAUDE: KEEPS_CHAT, CODEX: KEEPS_CHAT})

    def test_the_chosen_order_becomes_the_conversation(self):
        order = self.order(CODEX)
        self.ledger.set_order(self.link.id, [turn.id for turn in order])
        self.assertEqual(self.names(self.turns()), ["s1", "s2", "s3", "x1", "c1", "c2"])

    def test_u8_keeping_one_side_skips_the_others_turns(self):
        skipped = planner.turns_to_skip(self.turns(), CLAUDE)
        self.assertEqual(self.names(skipped), ["x1"])
        for turn in skipped:
            self.ledger.skip(self.link.id, turn.id, CLAUDE)
        result = self.plan()
        self.assertFalse(result.decision_needed)
        self.assertEqual(self.names(result.steps[CODEX].turns), ["c1", "c2"])
        self.assertNotIn(CLAUDE, result.steps)
        self.assertEqual(self.turns()[-1].states[CLAUDE], SKIPPED)

    def test_a_preset_for_a_side_without_turns_is_refused(self):
        with self.assertRaises(ValueError):
            self.order("opencode")


class OverlapTest(PlannerCase):
    def test_m7_turns_that_ran_at_the_same_time_are_named(self):
        self.write(CLAUDE, make_turn("c1", at="14:00", ended="14:06"), make_turn("c2", at="14:10", ended="14:12"))
        self.write(CODEX, make_turn("x1", at="14:05", ended="14:08"))
        order = planner.merge_order(self.turns())
        self.assertEqual(self.names(order), ["c1", "x1", "c2"])
        self.assertEqual([(a.origin_id, b.origin_id) for a, b in planner.overlapping(order)], [("c1", "x1")])


if __name__ == "__main__":
    unittest.main()
