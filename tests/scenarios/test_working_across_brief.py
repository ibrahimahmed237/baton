"""E10 brief scenarios, isolated from E9 usage/digest acceptance."""
from pathlib import Path
import tempfile
import unittest

from baton.services.brief import BriefService
from baton.services.noteformat import NoteRef
from baton.services.transcripts import FolderTranscripts
from tests.scenarios.test_working_across import WorkingAcrossBase, at, label, make_turn, render


class BriefWorkingAcrossBase(WorkingAcrossBase):
    def build(self, **facts):
        """Add brief-only storage to the shared isolated conversation fixture."""
        super().build(**facts)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.saved = Path(folder.name)
        self.briefs = BriefService(self.store, self.adapters, self.clock, FolderTranscripts(self.saved), label)


class BriefScenarios(BriefWorkingAcrossBase):
    def generate(self, *args, **kwargs):
        preview = self.briefs.plan(*args, **kwargs)
        return self.briefs.confirm(preview) if preview.stage == 'generate' else preview

    def conversation(self, count=12, special=None):
        """A long chat written in Claude and already synced to Codex; `special` replaces turns by position."""
        turns = [(special or {}).get(n) or make_turn(f'step {n}', at(9, n), at(9, n + 1), reply=f'answer {n}')
                 for n in range(count)]
        ids = self.write('claude', *turns)
        self.sync('claude', 'codex', ids, turns)
        return ids, turns

    def test_V4_claude_at_its_limit_is_not_asked_codex_writes_the_brief(self):
        self.conversation()
        self.at_limit('claude')
        claude, codex = self.runner('claude', 'from claude'), self.runner('codex', 'from codex')
        brief = self.generate(self.link.id, 'codex')
        self.assertEqual(brief.writer, 'codex')
        self.assertIn('from codex', brief.text)
        self.assertEqual((claude.calls, len(codex.calls)), ([], 1))
        self.assertEqual(brief.notes, (NoteRef('brief.skipped_limit', {'tool': 'claude'}),
                                       NoteRef('brief.summary_receipt', {})))

    def test_V4_a_hand_off_to_the_tool_at_its_limit_is_written_by_the_other_one(self):
        self.conversation()
        self.at_limit('claude')
        claude, codex = self.runner('claude', 'from claude'), self.runner('codex', 'from codex')
        brief = self.generate(self.link.id, 'claude')
        self.assertEqual((brief.writer, claude.calls), ('codex', []))
        self.assertEqual(brief.notes, (NoteRef('brief.skipped_limit', {'tool': 'claude'}),
                                       NoteRef('brief.written_by', {'tool': 'codex'}), NoteRef('brief.summary_receipt', {})))
        self.assertEqual(render(brief.notes[0]).template,
                         'Claude couldn\'t write the brief because it has reached its usage limit.')

    def test_V13_two_pinned_turns_are_in_the_brief_in_full_besides_the_summary(self):
        long_reply = 'We chose option B because of the migration. ' * 40
        pinned = {2: make_turn('decision one', at(9, 2), at(9, 3), calls=2, reply='DECISION-ONE ' + long_reply),
                  6: make_turn('decision two', at(9, 6), at(9, 7), reply='DECISION-TWO ' + long_reply)}
        ids, _ = self.conversation(special=pinned)
        for index in pinned:
            self.store.set_pinned(self.link.id, ids[index], True)
        self.runner('codex', 'SUMMARY WRITTEN BY AN AGENT')
        for writer in (None, 'offline'):
            with self.subTest(writer=writer):
                brief = self.generate(self.link.id, 'codex', writer=writer, recent_turns=2)
                self.assertEqual(brief.pinned, (ids[2], ids[6]))
                for index, replacement in pinned.items():
                    self.assertIn(replacement.prompt.text, "\n".join(t.prompt.text for t in brief.originals))
                    self.assertIn(replacement.reply_text, "\n".join(t.reply_text for t in brief.originals))  # not shortened
                self.assertEqual(sum('DECISION-ONE' in t.reply_text for t in brief.originals), 1)
                self.assertGreater(brief.pinned_tokens, 0)
                self.assertEqual(brief.writer, 'codex' if writer is None else 'offline')
                if writer is None:
                    self.assertIn('SUMMARY WRITTEN BY AN AGENT', brief.text)
                self.assertEqual(brief.as_contract()['pinned'], [ids[2], ids[6]])

    def test_V14_a_turn_pinned_and_kept_in_claude_stays_out_of_a_brief_for_codex(self):
        ids, _ = self.conversation(4)
        secret = make_turn('keep this here', at(10, 0), at(10, 1), reply='PRIVATE-REPLY')
        (kept,) = self.write('claude', secret)
        self.store.set_pinned(self.link.id, kept, True)
        self.store.keep_back(self.link.id, kept)
        runner = self.runner('codex', 'summary')
        self.runner('claude', 'summary')
        for writer in (None, 'offline'):
            with self.subTest(writer=writer):
                brief = self.generate(self.link.id, 'codex', writer=writer)
                for fragment in ('keep this here', 'PRIVATE-REPLY'):
                    self.assertNotIn(fragment, brief.text)
                    self.assertNotIn(fragment, brief.turn.prompt.text)
                self.assertEqual(brief.pinned, ())
                self.assertNotIn('PRIVATE-REPLY', Path(brief.transcript_path).read_text())
        self.assertTrue(all('PRIVATE-REPLY' not in prompt for prompt, _, _ in runner.calls))

    def test_V14_keeping_back_does_not_hide_the_turn_from_its_own_tool_but_not_from_the_other_writer(self):
        self.conversation(3)
        (kept,) = self.write('claude', make_turn('keep this here', at(10, 0), at(10, 1), reply='PRIVATE-REPLY'))
        self.store.set_pinned(self.link.id, kept, True)
        self.store.keep_back(self.link.id, kept)
        self.at_limit('claude')  # so a brief for Claude is written by Codex
        claude, codex = self.runner('claude', 'summary'), self.runner('codex', 'summary')
        brief = self.generate(self.link.id, 'claude')
        # Claude's own brief keeps its pinned turn in full ...
        self.assertEqual(brief.pinned, (kept,))
        self.assertIn('PRIVATE-REPLY', '\n'.join(t.reply_text for t in brief.originals))
        # ... but the agent that wrote it for Claude is Codex, which is never told about the turn.
        self.assertEqual(brief.writer, 'codex')
        self.assertTrue(all('PRIVATE-REPLY' not in prompt for prompt, _, _ in codex.calls))
        self.assertEqual(claude.calls, [])


if __name__ == '__main__':
    unittest.main()
