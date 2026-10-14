"""The digest counts only what this side was meant to get, in the order the user lived it."""
import unittest
from dataclasses import replace

from tests.scenarios.test_working_across import WorkingAcrossBase, label, make_turn, at
from baton.domain.errors import ChatChanged
from baton.domain.model import Message, TOOL_CALL, TOOL_RESULT
from baton.services.digest import DigestBuilder
from baton.services.refresh import ChatRefresh


class DigestTests(WorkingAcrossBase):
    def build(self, **kwargs):
        super().build(**kwargs)
        self.digests = DigestBuilder(self.store, self.readers, self.clock, label)

    def own_then_other(self, *other_turns):
        self.write('claude', make_turn('mine', at(13, 0), at(13, 5)))
        return self.write('codex', *other_turns)

    def test_singular_counts(self):
        self.adapters['codex'].changed_files['x'] = ['one.py']
        self.own_then_other(make_turn('x', at(13, 10), at(13, 15), calls=1))
        self.assertEqual(self.digests.text(self.digests.for_side(self.link.id, 'claude')),
                         'Since your last message here at 13:00, Codex did 1 turn, changed 1 file and ran 1 command.')

    def test_zero_files_and_commands_are_still_plain_numbers(self):
        self.own_then_other(make_turn('x', at(13, 10), at(13, 15)))
        digest = self.digests.for_side(self.link.id, 'claude')
        self.assertEqual((digest.turns, digest.files, digest.commands), (1, (), 0))
        self.assertIn('changed 0 files and ran 0 commands', self.digests.text(digest))

    def test_nothing_before_the_last_message_counts(self):
        self.write('codex', make_turn('early', at(12, 0), at(12, 5), calls=4))
        self.write('claude', make_turn('mine', at(13, 0), at(13, 5)))
        self.assertIsNone(self.digests.for_side(self.link.id, 'claude'))

    def test_latest_own_prompt_without_time_does_not_repeat_earlier_work(self):
        self.write('claude', make_turn('older', at(13, 0), at(13, 1)))
        self.write('codex', make_turn('between', at(13, 2), at(13, 3)))
        self.write('claude', make_turn('latest', '', ''))
        self.assertIsNone(self.digests.for_side(self.link.id, 'claude'))

    def test_a_side_the_user_never_wrote_in_has_no_digest(self):
        self.write('codex', make_turn('x', at(13, 10), at(13, 15)))
        self.assertIsNone(self.digests.for_side(self.link.id, 'claude'))

    def test_turns_kept_back_or_skipped_for_this_side_are_not_counted(self):
        ids = self.own_then_other(make_turn('a', at(13, 10), at(13, 15), calls=2),
                                  make_turn('b', at(13, 20), at(13, 25), calls=3),
                                  make_turn('c', at(13, 30), at(13, 35), calls=5))
        self.store.keep_back(self.link.id, ids[0])
        self.store.skip(self.link.id, ids[1], 'claude')
        digest = self.digests.for_side(self.link.id, 'claude')
        self.assertEqual((digest.turns, digest.commands), (1, 5))

    def test_files_are_listed_once_in_the_order_they_were_changed(self):
        self.adapters['codex'].changed_files.update({'a': ['x.py', 'y.py'], 'b': ['y.py', 'z.py']})
        self.own_then_other(make_turn('a', at(13, 10), at(13, 15)), make_turn('b', at(13, 20), at(13, 25)))
        self.assertEqual(self.digests.for_side(self.link.id, 'claude').files, ('x.py', 'y.py', 'z.py'))

    def test_the_span_ends_when_the_other_sides_latest_counted_turn_ended(self):
        self.own_then_other(make_turn('a', at(13, 10), at(13, 15)), make_turn('b', at(13, 20), at(13, 45)))
        digest = self.digests.for_side(self.link.id, 'claude')
        self.assertEqual((digest.since, digest.until), (at(13, 0), at(13, 45)))

    def test_without_times_the_order_of_the_conversation_decides(self):
        self.write('codex', make_turn('before', '', ''))
        self.write('claude', make_turn('mine', '', ''))
        self.write('codex', make_turn('after', '', ''))
        self.assertEqual(self.digests.for_side(self.link.id, 'claude').turns, 1)

    def test_other_days_say_the_date(self):
        self.write('claude', make_turn('mine', '2026-10-03T13:40:00Z', '2026-10-03T13:41:00Z'))
        self.write('codex', make_turn('x', at(13, 10), at(13, 15)))
        self.assertTrue(self.digests.text(self.digests.for_side(self.link.id, 'claude'))
                        .startswith('Since your last message here at 2026-10-03 13:40, '))

    def test_all_received_suppresses_digest_for_each_delivery_state(self):
        for state in ('shown', 'added', 'attached'):
            with self.subTest(state=state):
                self.build()
                ids = self.own_then_other(make_turn('x', at(13, 10), at(13, 15)))
                self.store.deliver(self.link.id, 'claude', ids, state, state, local_ids=['local'])
                self.assertIsNone(self.digests.for_side(self.link.id, 'claude'))

    def test_missing_or_rewritten_eligible_origin_refuses_partial_counts(self):
        for change in ('missing', 'prompt', 'reply'):
            with self.subTest(change=change):
                self.build()
                self.own_then_other(make_turn('x', at(13, 10), at(13, 15)),
                                    make_turn('y', at(13, 20), at(13, 25)))
                values = self.adapters['codex'].chats[self.chats['codex']]
                if change == 'missing': values.pop()
                elif change == 'prompt': values[-1] = replace(values[-1], prompt=replace(values[-1].prompt, text='changed'))
                else: values[-1] = replace(values[-1], messages=(replace(values[-1].messages[-1], text='changed'),))
                with self.assertRaises(ChatChanged): self.digests.for_side(self.link.id, 'claude')

    def test_missing_or_rewritten_own_anchor_refuses_digest(self):
        for missing in (False, True):
            with self.subTest(missing=missing):
                self.build()
                self.own_then_other(make_turn('x', at(13, 10), at(13, 15)))
                values = self.adapters['claude'].chats[self.chats['claude']]
                if missing: values.clear()
                else: values[0] = replace(values[0], prompt=replace(values[0].prompt, text='changed'))
                with self.assertRaises(ChatChanged): self.digests.for_side(self.link.id, 'claude')

    def test_unfinished_later_reply_does_not_hide_completed_work(self):
        self.own_then_other(make_turn('done', at(13, 10), at(13, 15)))
        incomplete = make_turn('working', at(13, 20), at(13, 21), reply='part')
        chat = self.chats['codex']
        self.adapters['codex'].chats[chat].append(incomplete)
        self.adapters['codex'].set_condition(chat, replying=True)
        refresh = ChatRefresh(self.store, self.adapters, self.clock)
        refresh.refresh(self.link.id)
        digest = self.digests.for_side(self.link.id, 'claude')
        self.assertEqual((digest.turns, digest.until), (1, at(13, 15)))
        self.adapters['codex'].chats[chat][-1] = replace(incomplete, messages=(
            replace(incomplete.messages[-1], text='part finished', at=at(13, 25)),))
        self.adapters['codex'].set_condition(chat, replying=False)
        refresh.refresh(self.link.id)
        digest = self.digests.for_side(self.link.id, 'claude')
        self.assertEqual((digest.turns, digest.until), (2, at(13, 25)))

    def test_fake_reader_command_evidence_excludes_reads_edits_searches_results(self):
        turn = make_turn('work', at(13, 10), at(13, 15))
        turn = replace(turn, messages=tuple(Message(str(i), TOOL_CALL, tool=tool)
                       for i, tool in enumerate(('shell', 'read', 'edit', 'search'))) +
                       (Message('result', TOOL_RESULT, tool='shell'), turn.messages[-1]))
        self.own_then_other(turn)
        self.assertEqual(self.digests.for_side(self.link.id, 'claude').commands, 1)


if __name__ == '__main__':
    unittest.main()
