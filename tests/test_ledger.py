import os
import tempfile
import unittest

from baton import ledger
from baton.ledger import (ADDED, ATTACHED, CLAUDE, CODEX, FULL_COPY, KEPT_BACK, SHOWN, SKIPPED, WAITING,
                          WRITTEN_HERE, AlreadyDelivered, AlreadyLinked, Ledger)
from baton.model import PROMPT, REPLY, Message, Turn


def make_turn(turn_id, text="", at="", reply=""):
    messages = (Message(id=turn_id + "-reply", kind=REPLY, text=reply),) if reply else ()
    return Turn(Message(id=turn_id, kind=PROMPT, text=text or turn_id, at=at), messages)


def make_turns(prefix, count, first=1):
    return [make_turn("%s%d" % (prefix, n)) for n in range(first, first + count)]


class LedgerCase(unittest.TestCase):
    def setUp(self):
        self.ledger = Ledger(":memory:")
        self.addCleanup(self.ledger.close)
        self.link = self.ledger.link({CLAUDE: "claude-a", CODEX: "codex-b"}, FULL_COPY, at="13:40")

    def states(self, side):
        return [turn.states[side] for turn in self.ledger.turns(self.link.id)]


class LinkTest(LedgerCase):
    def test_a_chat_is_in_one_link_at_a_time(self):
        with self.assertRaises(AlreadyLinked) as caught:
            self.ledger.link({CLAUDE: "claude-a", CODEX: "codex-c"}, FULL_COPY)
        self.assertEqual(caught.exception.side, CLAUDE)
        self.assertEqual(caught.exception.link.chat(CODEX), "codex-b")
        self.assertEqual(len(self.ledger.links()), 1)

    def test_changing_the_link_removes_the_old_one_first(self):
        self.ledger.remove_link(self.link.id, at="14:00")
        new = self.ledger.link({CLAUDE: "claude-a", CODEX: "codex-c"}, FULL_COPY)
        self.assertEqual([link.id for link in self.ledger.links()], [new.id])
        self.assertIsNone(self.ledger.link_for(CODEX, "codex-b"))
        self.assertEqual(self.ledger.get_link(self.link.id).removed_at, "14:00")
        self.assertEqual(self.ledger.history(self.link.id)[0].kind, "link_removed")

    def test_a_link_joins_two_known_tools(self):
        with self.assertRaises(ValueError):
            self.ledger.link({CLAUDE: "claude-x"}, FULL_COPY)
        with self.assertRaises(ValueError):
            self.ledger.link({CLAUDE: "claude-x", "notepad": "n"}, FULL_COPY)

    def test_pause_and_resume_are_in_the_history(self):
        self.ledger.set_paused(self.link.id, True)
        self.assertTrue(self.ledger.get_link(self.link.id).paused)
        self.ledger.set_paused(self.link.id, False)
        self.assertFalse(self.ledger.get_link(self.link.id).paused)
        self.assertEqual([event.kind for event in self.ledger.history(self.link.id)],
                         ["resumed", "paused", "linked"])

    def test_a_link_can_move_to_another_chat_on_one_side(self):
        self.ledger.move_link(self.link.id, CODEX, "codex-shorter", at="14:45")
        self.assertEqual(self.ledger.get_link(self.link.id).chat(CODEX), "codex-shorter")
        self.assertIsNone(self.ledger.link_for(CODEX, "codex-b"))
        moved = self.ledger.history(self.link.id)[0]
        self.assertEqual((moved.kind, moved.side, moved.detail),
                         ("link_moved", CODEX, {"from": "codex-b", "to": "codex-shorter"}))

    def test_a_link_cannot_move_to_a_chat_that_is_linked(self):
        self.ledger.link({CLAUDE: "claude-z", CODEX: "codex-z"}, FULL_COPY)
        with self.assertRaises(AlreadyLinked):
            self.ledger.move_link(self.link.id, CODEX, "codex-z")

    def test_the_record_survives_reopening(self):
        path = os.path.join(tempfile.mkdtemp(), "ledger.sqlite")
        first = Ledger(path)
        link = first.link({CLAUDE: "claude-a", CODEX: "codex-b"}, FULL_COPY)
        first.record_turns(link.id, CLAUDE, make_turns("c", 2))
        first.close()
        again = Ledger(path)
        self.addCleanup(again.close)
        self.assertEqual(again.link_for(CLAUDE, "claude-a").id, link.id)
        self.assertEqual(len(again.turns(link.id)), 2)


class TurnTest(LedgerCase):
    def test_a_new_turn_waits_on_the_other_side(self):
        self.ledger.record_turns(self.link.id, CLAUDE, [make_turn("c1", "Add logout\nplease", "14:00", "Done.")])
        turn = self.ledger.turns(self.link.id)[0]
        self.assertEqual(turn.states, {CLAUDE: WRITTEN_HERE, CODEX: WAITING})
        self.assertEqual((turn.origin, turn.origin_id, turn.started_at), (CLAUDE, "c1", "14:00"))
        self.assertEqual(turn.first_line, "Add logout\nplease")
        self.assertEqual(turn.size, len("Add logout\nplease") + len("Done."))

    def test_reading_the_same_chat_again_adds_nothing(self):
        first = self.ledger.record_turns(self.link.id, CLAUDE, make_turns("c", 2))
        again = self.ledger.record_turns(self.link.id, CLAUDE, make_turns("c", 3))
        self.assertEqual((len(first), len(again)), (2, 1))
        self.assertEqual([turn.seq for turn in self.ledger.turns(self.link.id)], [1, 2, 3])

    def test_a_turn_baton_put_in_a_chat_is_not_taken_for_a_new_one(self):
        ids = self.ledger.record_turns(self.link.id, CLAUDE, make_turns("c", 2))
        self.ledger.deliver(self.link.id, CODEX, ids, SHOWN, "added", local_ids=["x1", "x2"])
        new = self.ledger.record_turns(self.link.id, CODEX, make_turns("x", 3))
        self.assertEqual(len(new), 1)
        self.assertEqual(self.states(CLAUDE), [WRITTEN_HERE, WRITTEN_HERE, WAITING])
        self.assertEqual(self.states(CODEX), [SHOWN, SHOWN, WRITTEN_HERE])

    def test_only_a_waiting_turn_can_be_delivered(self):
        ids = self.ledger.record_turns(self.link.id, CLAUDE, make_turns("c", 1))
        self.ledger.deliver(self.link.id, CODEX, ids, ATTACHED, "attached")
        with self.assertRaises(ValueError):
            self.ledger.deliver(self.link.id, CODEX, ids, SHOWN, "added")
        with self.assertRaises(ValueError):
            self.ledger.deliver(self.link.id, CLAUDE, ids, SHOWN, "added")
        with self.assertRaises(ValueError):
            self.ledger.deliver(self.link.id, CODEX, ids, WAITING, "added")

    def test_what_was_added_is_shown_after_a_relaunch(self):
        ids = self.ledger.record_turns(self.link.id, CODEX, make_turns("x", 2))
        self.ledger.deliver(self.link.id, CLAUDE, ids, ADDED, "added")
        self.assertEqual(self.states(CLAUDE), [ADDED, ADDED])
        self.assertEqual(self.ledger.mark_shown(self.link.id, CLAUDE), 2)
        self.assertEqual(self.states(CLAUDE), [SHOWN, SHOWN])

    def test_a_turn_can_be_kept_back_and_sent_after_all(self):
        ids = self.ledger.record_turns(self.link.id, CLAUDE, make_turns("c", 2))
        self.ledger.keep_back(self.link.id, ids[0])
        self.assertEqual(self.states(CODEX), [KEPT_BACK, WAITING])
        self.ledger.send_after_all(self.link.id, ids[0])
        self.assertEqual(self.states(CODEX), [WAITING, WAITING])

    def test_a_delivered_turn_cannot_be_kept_back(self):
        ids = self.ledger.record_turns(self.link.id, CLAUDE, make_turns("c", 1))
        self.ledger.deliver(self.link.id, CODEX, ids, SHOWN, "added", at="14:10")
        with self.assertRaises(AlreadyDelivered) as caught:
            self.ledger.keep_back(self.link.id, ids[0])
        self.assertEqual((caught.exception.side, caught.exception.at), (CODEX, "14:10"))

    def test_a_skipped_turn_stays_where_it_was_written(self):
        ids = self.ledger.record_turns(self.link.id, CODEX, make_turns("x", 1))
        self.ledger.skip(self.link.id, ids[0], CLAUDE)
        self.assertEqual(self.states(CLAUDE), [SKIPPED])
        self.assertEqual(self.states(CODEX), [WRITTEN_HERE])

    def test_pinning(self):
        ids = self.ledger.record_turns(self.link.id, CLAUDE, make_turns("c", 2))
        self.ledger.set_pinned(self.link.id, ids[1], True)
        self.assertEqual([turn.pinned for turn in self.ledger.turns(self.link.id)], [False, True])

    def test_a_turn_of_another_link_is_refused(self):
        other = self.ledger.link({CLAUDE: "claude-z", CODEX: "codex-z"}, FULL_COPY)
        ids = self.ledger.record_turns(other.id, CLAUDE, make_turns("c", 1))
        with self.assertRaises(KeyError):
            self.ledger.deliver(self.link.id, CODEX, ids, SHOWN, "added")


class HistoryTest(LedgerCase):
    def test_history_is_newest_first_and_names_the_turns(self):
        first = self.ledger.record_turns(self.link.id, CLAUDE, make_turns("c", 2))
        self.ledger.deliver(self.link.id, CODEX, first, SHOWN, "added", at="14:10")
        second = self.ledger.record_turns(self.link.id, CLAUDE, make_turns("c", 1, first=3))
        self.ledger.deliver(self.link.id, CODEX, second, ATTACHED, "attached", at="14:31",
                            detail={"message": "x9"})
        history = self.ledger.history(self.link.id)
        self.assertEqual([(event.at, event.kind, event.side) for event in history],
                         [("14:31", "attached", CODEX), ("14:10", "added", CODEX), ("13:40", "linked", "")])
        self.assertEqual(history[0].turn_ids, tuple(second))
        self.assertEqual(history[0].detail, {"message": "x9"})
        self.assertEqual(history[1].turn_ids, tuple(first))
        self.assertEqual(history[2].detail, {"mode": ledger.FULL_COPY})


if __name__ == "__main__":
    unittest.main()
