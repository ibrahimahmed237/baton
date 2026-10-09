"""Briefs: who writes the summary and what falls back to what, and what the text always carries."""
from copy import deepcopy
from pathlib import Path
from datetime import timedelta, timezone
import unittest

from baton.domain.errors import ChatChanged, NotAvailable, OrderNotAllowed
from baton.domain.model import Message, Turn, PROMPT, TOOL_CALL, TOOL_RESULT
from baton.services.brief import BriefService, OFFLINE
from baton.services.noteformat import NoteRef
from baton.services.transcripts import FolderTranscripts
from tests.scenarios.test_working_across import at, make_turn, render
from tests.scenarios.test_working_across_brief import BriefWorkingAcrossBase


class BriefBase(BriefWorkingAcrossBase):
    def setUp(self):
        super().setUp()
        turns = [make_turn(f'request {n}', at(9, n), at(9, n + 1), reply=f'answer {n}') for n in range(6)]
        self.ids = self.write('claude', *turns)
        self.sync('claude', 'codex', self.ids, turns)
        self.runners = {'claude': self.runner('claude', 'WRITTEN-BY-CLAUDE'),
                        'codex': self.runner('codex', 'WRITTEN-BY-CODEX')}

    def generate(self, to='codex', **options):
        preview = self.briefs.plan(self.link.id, to, **options)
        return self.briefs.confirm(preview) if preview.stage == 'generate' else preview

    def skipped(self, brief):
        return [note.id for note in brief.notes if note.id != 'brief.summary_receipt']


class WriterOrderTests(BriefBase):
    def test_the_destination_tool_writes_and_the_other_is_not_asked(self):
        brief = self.generate('codex')
        self.assertEqual((brief.writer, self.skipped(brief)), ('codex', []))
        self.assertEqual(self.runners['claude'].calls, [])
        prompt, folder, read_only = self.runners['codex'].calls[0]
        self.assertTrue(read_only)
        self.assertEqual(folder, '')  # the fake chats have no folder
        self.assertIn('answer 5', prompt)

    def test_a_tool_at_its_limit_is_skipped_with_a_note(self):
        self.at_limit('codex')
        brief = self.generate('codex')
        self.assertEqual((brief.writer, self.runners['codex'].calls), ('claude', []))
        self.assertEqual(self.skipped(brief), ['brief.skipped_limit', 'brief.written_by'])

    def test_a_limit_with_a_reset_time_that_has_passed_does_not_skip_the_tool(self):
        self.at_limit('codex', resets_at='2026-10-05T13:00:00Z')
        self.assertEqual(self.generate('codex').writer, 'codex')

    def test_a_limit_without_a_reset_time_skips_the_tool_however_late(self):
        self.at_limit('codex', resets_at=None)
        self.clock.value = '2099-01-01T00:00:00Z'
        self.assertEqual(self.generate('codex').writer, 'claude')

    def test_no_runner_is_skipped_with_a_note(self):
        self.adapters['codex'].runner = None
        brief = self.generate('codex')
        self.assertEqual((brief.writer, self.skipped(brief)), ('claude', ['brief.skipped_no_runner', 'brief.written_by']))

    def test_a_runner_that_is_not_ready_is_skipped_with_the_setup_note_and_is_not_run(self):
        runner = self.runner('codex', 'never', ok=False)
        brief = self.generate('codex')
        self.assertEqual((brief.writer, runner.calls), ('claude', []))
        self.assertEqual(brief.notes[0], NoteRef('setup.runner', {'tool': 'codex'}))

    def test_a_run_that_fails_falls_back_to_the_other_tool(self):
        self.runner('codex', error=RuntimeError('boom'))
        with self.assertLogs('baton.services.brief', 'ERROR'):
            brief = self.generate('codex')
        self.assertEqual((brief.writer, self.skipped(brief)), ('claude', ['brief.skipped_failed', 'brief.written_by']))

    def test_an_empty_answer_counts_as_a_failure(self):
        self.runner('codex', '   ')
        brief = self.generate('codex')
        self.assertEqual((brief.writer, self.skipped(brief)), ('claude', ['brief.skipped_failed', 'brief.written_by']))

    def test_when_both_fail_the_offline_brief_is_used_and_says_so(self):
        self.at_limit('codex')
        self.runner('claude', error=NotAvailable())
        with self.assertLogs('baton.services.brief', 'ERROR'):
            brief = self.generate('codex')
        self.assertEqual((brief.writer, self.skipped(brief)),
                         (OFFLINE, ['brief.skipped_limit', 'brief.skipped_failed', 'brief.used_offline']))
        self.assertEqual(render(brief.notes[0]).template + ' ' + render(brief.notes[2]).template,
                         'Codex couldn\'t write the brief because it has reached its usage limit. '
                         'Baton used the offline summary instead.')
        self.assertIn('request 0', brief.text)

    def test_asking_for_the_offline_brief_asks_no_one_and_says_nothing(self):
        brief = self.generate('codex', writer=OFFLINE)
        self.assertEqual((brief.writer, brief.notes), (OFFLINE, (NoteRef('brief.summary_receipt', {}),)))
        self.assertEqual([r.calls for r in self.runners.values()], [[], []])

    def test_a_named_writer_falls_back_to_offline_never_to_a_different_tool(self):
        self.runner('claude', error=RuntimeError('boom'))
        with self.assertLogs('baton.services.brief', 'ERROR'):
            brief = self.generate('codex', writer='claude')
        self.assertEqual((brief.writer, self.skipped(brief)), (OFFLINE, ['brief.skipped_failed', 'brief.used_offline']))
        self.assertEqual(self.runners['codex'].calls, [])

    def test_a_writer_outside_the_link_is_refused(self):
        with self.assertRaises(NotAvailable):
            self.generate('codex', writer='cursor')


class ContentTests(BriefBase):
    def test_a_brief_is_always_a_new_chat_and_changes_no_chat_or_record(self):
        chats = {side: deepcopy(a.chats) for side, a in self.adapters.items()}
        records = self.store.turns(self.link.id)
        for writer in (None, OFFLINE):
            brief = self.generate('codex', writer=writer)
            self.assertEqual(brief.action, 'create')
            self.assertEqual((brief.turn.prompt.kind, brief.turn.prompt.text), (PROMPT, brief.text))
            self.assertEqual(brief.turn.messages, ())
            self.assertEqual(brief.name, '[Claude] codex chat')
        self.assertEqual(chats, {side: a.chats for side, a in self.adapters.items()})
        self.assertEqual(records, self.store.turns(self.link.id))

    def test_the_title_tag_follows_the_setting(self):
        self.assertEqual(self.generate('codex', title_tag=False).name, 'codex chat')

    def test_offline_brief_has_first_prompt_pins_last_turns_files_and_the_saved_history(self):
        self.adapters['claude'].changed_files['request 1'] = ['src/a.py']
        self.store.set_pinned(self.link.id, self.ids[1], True)
        brief = self.generate('codex', writer=OFFLINE, recent_turns=2)
        text = brief.text
        originals = '\n'.join(t.prompt.text + '\n' + t.reply_text for t in brief.originals)
        self.assertTrue(text.startswith('This chat carries on work done in Claude.'))
        self.assertIn('The first request was:\nrequest 0', text)
        self.assertIn('request 1', originals)
        self.assertIn('answer 1', originals)
        self.assertEqual([t.prompt.text for t in brief.originals], ['request 1', 'request 4', 'request 5'])
        self.assertIn('- src/a.py', text)
        self.assertTrue(text.rstrip().endswith(f'The full history is saved at {brief.transcript_path}. '
                                               'Read it for any detail not above.'))

    def test_a_pinned_turn_among_the_recent_ones_appears_once(self):
        self.store.set_pinned(self.link.id, self.ids[5], True)
        brief = self.generate('codex', writer=OFFLINE, recent_turns=2)
        self.assertEqual([t.prompt.text for t in brief.originals], ['request 3', 'request 4', 'request 5'])
        self.assertEqual(sum(t.reply_text == 'answer 5' for t in brief.originals), 1)

    def test_no_recent_turns_when_none_are_asked_for(self):
        self.assertNotIn('Most recent turns:', self.generate('codex', writer=OFFLINE, recent_turns=0).text)

    def test_the_saved_history_has_every_visible_turn_in_full_with_tool_activity_as_text(self):
        call = Message('k1', TOOL_CALL, tool='shell', tool_input={'cmd': 'ls'}, call_id='k1')
        result = Message('k2', TOOL_RESULT, 'listing', call_id='k1')
        extra = Turn(Message('t-tools', PROMPT, 'list files', at(10, 0)),
                     (call, result, Message('t-reply', 'reply', 'here they are', at(10, 1))))
        self.write('claude', extra)
        self.store.keep_back(self.link.id, self.store.turns(self.link.id)[-1].id)  # not for Codex ...
        brief = self.generate('claude', writer=OFFLINE)  # ... but for Claude it is its own turn
        saved = Path(brief.transcript_path).read_text()
        self.assertEqual(Path(brief.transcript_path).parent, self.saved)
        self.assertTrue(saved.startswith('# Conversation history\n\n## Turn 1, at 09:00 in Claude'))
        for n in range(6):
            self.assertIn(f'User: request {n}\nReply: answer {n}', saved)
        self.assertIn('Tool call 1: shell', saved)
        self.assertIn('Tool result for call 1: listing', saved)
        self.assertIn('Reply: here they are', saved)

    def test_the_brief_for_the_other_tool_leaves_out_what_was_kept_back_and_what_was_skipped(self):
        kept = self.write('claude', make_turn('kept', at(10, 0), at(10, 1)))[0]
        skipped = self.write('claude', make_turn('skipped', at(10, 5), at(10, 6)))[0]
        self.store.keep_back(self.link.id, kept)
        self.store.skip(self.link.id, skipped, 'codex')
        text = self.generate('codex', writer=OFFLINE).text
        self.assertNotIn('kept', text.replace('kept back', ''))
        self.assertNotIn('skipped', text)
        self.assertIn('6. request 5', text)

    def test_contract_object(self):
        self.store.set_pinned(self.link.id, self.ids[2], True)
        brief = self.generate('codex')
        details = brief.as_contract()
        self.assertEqual((details['writer'], details['tokens'], details['pinned']), ('codex', len(brief.text) // 4, [self.ids[2]]))
        self.assertEqual(details['artifact_id'], brief.artifact_id)

    def test_times_are_in_the_users_zone(self):
        local = BriefService(self.store, self.adapters, self.clock, FolderTranscripts(self.saved),
                             lambda tool: tool, timezone(timedelta(hours=2)))
        brief = local.plan(self.link.id, 'codex', writer=OFFLINE)
        self.assertIn('11:05 in claude', Path(brief.transcript_path).read_text())

    def test_an_order_places_unsynced_turns_in_the_merged_order(self):
        mine = make_turn('from claude', at(11, 0), at(11, 1))
        theirs = make_turn('from codex', at(10, 30), at(10, 31))
        self.write('claude', mine)
        self.write('codex', theirs)
        rows = {r.first_line: r.id for r in self.store.turns(self.link.id)}
        text = self.generate('codex', writer=OFFLINE, order=[rows['from codex'], rows['from claude']]).text
        self.assertLess(text.index('2. request 1'), text.index('7. from codex'))
        self.assertLess(text.index('7. from codex'), text.index('8. from claude'))
        with self.assertRaises(OrderNotAllowed):
            self.generate('codex', order=[rows['from claude']])


class RefusalTests(BriefBase):
    def test_a_turn_not_recorded_yet_refuses_instead_of_leaving_it_out(self):
        self.adapters['claude'].chats[self.chats['claude']].append(make_turn('new', at(12, 0), at(12, 1)))
        with self.assertRaises(ChatChanged):
            self.generate('codex')

    def test_a_side_that_is_not_in_the_link_is_refused(self):
        with self.assertRaises(NotAvailable):
            self.generate('cursor')

    def test_a_removed_link_is_refused(self):
        self.store.remove_link(self.link.id, self.clock.now())
        with self.assertRaises(NotAvailable):
            self.generate('codex')

    def test_nothing_to_brief_is_refused(self):
        self.store.close()
        self.build()
        with self.assertRaises(NotAvailable):
            self.briefs.plan(self.link.id, 'codex')


class OfferTests(BriefBase):
    def test_offered_from_the_threshold_up_and_sized_roughly(self):
        tokens = sum(r.size for r in self.store.turns(self.link.id)) // 4
        self.assertIsNone(self.briefs.offer(self.link.id, 'codex', tokens + 1))
        offer = self.briefs.offer(self.link.id, 'codex', tokens)
        self.assertEqual((offer.id, offer.values['tool']), ('brief.large_chat', 'codex'))
        self.assertEqual([b.id for b in render(offer).buttons], ['write_brief', 'send_in_full'])

    def test_kept_back_turns_do_not_count_towards_what_codex_would_receive(self):
        before = sum(r.size for r in self.store.turns(self.link.id)) // 4
        kept = self.write('claude', make_turn('kept ' * 400, at(10, 0), at(10, 1)))[0]
        self.store.keep_back(self.link.id, kept)
        self.assertIsNone(self.briefs.offer(self.link.id, 'codex', before + 1))

    def test_a_large_merged_copy_has_its_own_note(self):
        offer = self.briefs.offer(self.link.id, 'codex', 1, merged_copy=True)
        self.assertEqual(offer.id, 'merge.large_copy')
        self.assertEqual(set(offer.values), {'tokens'})


if __name__ == '__main__':
    unittest.main()
