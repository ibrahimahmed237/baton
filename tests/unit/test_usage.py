"""Context in use and limit state: nothing is claimed that the tool did not record."""
from datetime import timedelta, timezone
import unittest

from baton.ports.tool import Usage
from baton.services.noteformat import clock_time, day_of
from baton.services.usage import context_use, limit_state
from tests.scenarios.test_working_across import WorkingAcrossBase, make_turn, at

NOW = '2026-10-05T14:00:00Z'


class ContextUseTests(unittest.TestCase):
    def test_warning_uses_raw_ratio_even_when_display_rounds_to_80(self):
        for tokens, nearly_full in ((159999, False), (160000, False), (160001, True), (160400, True)):
            with self.subTest(tokens=tokens):
                use = context_use(Usage(tokens, 200000, False, None))
                self.assertEqual(use.nearly_full, nearly_full)
                self.assertEqual(use.percent, 80)

    def test_percent_is_rounded_half_up_in_integers(self):
        for tokens, size, percent in ((164000, 200000, 82), (1, 3, 33), (2, 3, 67), (1, 200, 1), (0, 100, 0)):
            with self.subTest(tokens=tokens, size=size):
                self.assertEqual(context_use(Usage(tokens, size, False, None)).percent, percent)

    def test_unusable_sizes_are_no_size(self):
        for size in (None, 0, -5):
            with self.subTest(size=size):
                use = context_use(Usage(1000, size, False, None))
                self.assertEqual((use.size, use.percent, use.nearly_full), (None, None, False))

    def test_negative_tokens_count_as_none(self):
        self.assertEqual(context_use(Usage(-1, 100, False, None)).tokens, 0)


class LimitStateTests(unittest.TestCase):
    def state(self, reached=True, resets_at=None, now=NOW):
        return limit_state(Usage(1, 100, reached, resets_at), now)

    def test_no_limit_means_no_reset_time_is_reported(self):
        state = self.state(reached=False, resets_at='2026-10-05T15:00:00Z')
        self.assertEqual((state.reached, state.resets_at, state.blocking), (False, None, False))

    def test_reached_without_reset_time_is_blocking_forever(self):
        for now in (NOW, '2099-01-01T00:00:00Z'):
            with self.subTest(now=now):
                state = self.state(now=now)
                self.assertEqual((state.blocking, state.available_again, state.resets_at), (True, False, None))

    def test_reset_time_in_the_future_blocks_and_at_or_after_it_does_not(self):
        reset = '2026-10-05T15:00:00Z'
        self.assertTrue(self.state(resets_at=reset).blocking)
        self.assertEqual(self.state(resets_at=reset, now=reset).blocking, False)
        self.assertTrue(self.state(resets_at=reset, now='2026-10-05T16:00:00Z').available_again)

    def test_a_reset_time_that_cannot_be_read_is_not_used(self):
        for value in ('tomorrow', '2026-10-05T15:00:00', ''):  # no zone, so not a usable time
            with self.subTest(value=value):
                state = self.state(resets_at=value)
                self.assertEqual((state.resets_at, state.blocking), (None, True))


class ClockTimeTests(unittest.TestCase):
    def test_time_of_day_in_the_users_zone(self):
        zone = timezone(timedelta(hours=2))
        self.assertEqual(clock_time('2026-10-05T13:40:00Z', zone), '15:40')

    def test_other_days_carry_the_date(self):
        today = day_of(NOW)
        self.assertEqual(clock_time('2026-10-05T13:40:00Z', timezone.utc, today), '13:40')
        self.assertEqual(clock_time('2026-10-04T13:40:00Z', timezone.utc, today), '2026-10-04 13:40')

    def test_unreadable_time_is_returned_unchanged(self):
        self.assertEqual(clock_time('later', timezone.utc), 'later')
        self.assertIsNone(day_of('later'))


class ServiceNotesTests(WorkingAcrossBase):
    def test_a_chat_with_no_tokens_has_no_context_note(self):
        self.write('claude', make_turn('first', at(13, 0), at(13, 1)))
        self.assertEqual(self.usage.side('claude', self.chats['claude']).notes, ())

    def test_without_a_partner_the_full_chat_note_suggests_only_a_brief(self):
        self.write('claude', make_turn('first', at(13, 0), at(13, 1)))
        self.adapters['claude'].usage_values[self.chats['claude']] = Usage(190000, 200000, False, None)
        ids = [ref.id for ref in self.usage.side('claude', self.chats['claude']).notes]
        self.assertEqual(ids, ['context.in_use', 'context.nearly_full_alone'])


if __name__ == '__main__':
    unittest.main()
