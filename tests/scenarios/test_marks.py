"""E11: V11/V12, A1 and W12–W15 use public services."""
import unittest
from baton.adapters.fake import FakeAdapter
from baton.adapters.fake.facts import OPENCODE_LIKE
from baton.domain.errors import AlreadyDelivered, DecisionNeeded
from baton.domain.model import Message, Turn
from baton.domain.link import KEPT_BACK, WAITING
from baton.ledger.sqlite_store import Ledger
from baton.ports.clock import FixedClock
from baton.services.applier import Applier
from baton.services.marks import Marks


def turn(ident):
    return Turn(Message(ident, 'prompt', ident, '2026-10-14T00:00:00Z'),
                (Message(ident + '-reply', 'reply', 'done', '2026-10-14T00:01:00Z'),))


class MarksScenarios(unittest.TestCase):
    def setUp(self):
        self.store = Ledger(':memory:')
        self.addCleanup(self.store.close)
        self.clock = FixedClock('2026-10-14T00:02:00Z')
        self.adapters = {s: FakeAdapter(OPENCODE_LIKE, s) for s in ('claude', 'codex')}
        self.chats = {s: a.build_chat([]) for s, a in self.adapters.items()}
        self.link = self.store.link(self.chats, 'full_copy')
        self.applier = Applier(self.store, self.adapters, self.clock)
        self.marks = Marks(self.store, self.clock)
        self.adapters['claude'].chats[self.chats['claude']].append(turn('one'))
        self.applier.refresh(self.link.id)
        self.ident = self.store.turns(self.link.id)[0].id

    def test_V11_later_turn_delivered_while_kept_turn_stays_here(self):
        kept = self.marks.keep(self.ident)
        self.assertEqual(kept.states['codex'], KEPT_BACK)
        self.adapters['claude'].chats[self.chats['claude']].append(turn('two'))
        self.applier.refresh(self.link.id)
        result = self.applier.apply(self.applier.preview(self.link.id))
        self.assertTrue(result.applied)
        self.assertEqual([t.prompt.text for t in self.adapters['codex'].reader.read(self.chats['codex'])], ['two'])
        status = self.applier.refresh(self.link.id)['status'].side('codex')
        self.assertEqual(status.kept_elsewhere, 1)
        self.assertEqual(self.marks.status_notes(self.link.id, 'codex')[0].id, 'keep.missing_turns')

    def test_V12_already_sent_refusal_carries_delivery_time(self):
        self.applier.apply(self.applier.preview(self.link.id))
        with self.assertRaises(AlreadyDelivered) as error:
            self.marks.keep(self.ident)
        self.assertEqual((error.exception.turn_id, error.exception.side, error.exception.at),
                         (self.ident, 'codex', self.clock.now()))

    def test_send_after_all_removes_keep_mark_without_writing_chat(self):
        self.marks.keep(self.ident)
        self.assertEqual(self.marks.send(self.ident).states['codex'], WAITING)
        self.assertEqual(self.adapters['codex'].reader.read(self.chats['codex']), [])
        self.assertTrue(self.applier.apply(self.applier.preview(self.link.id)).applied)

    def test_pin_unpin_and_filter_do_not_change_native_chats(self):
        self.assertTrue(self.marks.pin(self.ident).pinned)
        self.assertEqual([t.id for t in self.marks.pinned(self.link.id)], [self.ident])
        self.assertFalse(self.marks.unpin(self.ident).pinned)
        self.assertEqual(self.marks.pinned(self.link.id), [])
        self.assertEqual(self.store.journal_entries(), [])

    def test_pause_blocks_sync_and_attachment_resume_observes_conflict(self):
        self.assertTrue(self.marks.pause(self.link.id).paused)
        plan = self.applier.preview(self.link.id)
        self.assertTrue(all(s.action == 'hold' for s in plan.steps))
        self.applier.apply(plan)
        from baton.domain.errors import NotAvailable
        with self.assertRaises(NotAvailable):
            self.applier.record_attached(self.link.id, 'codex', [self.ident], 'message')
        self.adapters['codex'].chats[self.chats['codex']].append(turn('other'))
        self.applier.refresh(self.link.id)
        self.assertFalse(self.marks.resume(self.link.id).paused)
        with self.assertRaises(DecisionNeeded):
            self.applier.apply(self.applier.preview(self.link.id))

    def test_unknown_turn_does_not_mark_another_link(self):
        with self.assertRaises(KeyError):
            self.marks.pin(9999)

    def test_pins_survive_brief_but_keep_wins_for_destination(self):
        import tempfile
        from baton.services.brief import BriefService
        from baton.services.transcripts import FolderTranscripts
        self.marks.pin(self.ident)
        self.adapters['claude'].chats[self.chats['claude']].append(turn('two'))
        self.applier.refresh(self.link.id)
        with tempfile.TemporaryDirectory() as folder:
            briefs = BriefService(self.store, self.adapters, self.clock, FolderTranscripts(__import__('pathlib').Path(folder)), lambda s: s)
            plan = briefs.plan(self.link.id, 'codex', writer='offline', recent_turns=0)
            self.assertIn(self.ident, plan.pinned)
            self.assertIn('one', plan.text)
            self.marks.keep(self.ident)
            plan = briefs.plan(self.link.id, 'codex', writer='offline', recent_turns=0)
            self.assertNotIn(self.ident, plan.pinned)
            self.assertNotIn('1. one', plan.text)
            self.assertNotIn('\none\n', plan.text)

    def briefs(self):
        import tempfile
        from pathlib import Path
        from baton.services.brief import BriefService
        from baton.services.transcripts import FolderTranscripts
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        return BriefService(self.store, self.adapters, self.clock,
                            FolderTranscripts(Path(folder.name)), lambda s: s)

    def test_A1_paused_brief_preview_calls_no_writer_or_runner(self):
        from unittest.mock import patch
        from baton.domain.errors import NotAvailable
        briefs = self.briefs()
        self.marks.pause(self.link.id)
        target = self.adapters['codex']
        with patch.object(target.writer, 'prepare') as prepare, patch.object(target.writer, 'create') as create, patch.object(target.runner, 'ask') as ask:
            for writer in ('offline', 'codex'):
                with self.assertRaises(NotAvailable):
                    briefs.plan(self.link.id, 'codex', writer=writer)
            prepare.assert_not_called()
            create.assert_not_called()
            ask.assert_not_called()

    def test_A1_pause_after_preview_blocks_generation_and_creation(self):
        from unittest.mock import patch
        from baton.domain.errors import NotAvailable
        briefs = self.briefs()
        generate = briefs.plan(self.link.id, 'codex', writer='codex')
        create_plan = briefs.plan(self.link.id, 'codex', writer='offline')
        self.marks.pause(self.link.id)
        target = self.adapters['codex']
        with patch.object(target.writer, 'prepare') as prepare, patch.object(target.writer, 'create') as create, patch.object(target.runner, 'ask') as ask:
            result = briefs._create(create_plan.plan_id, self.store.brief_artifact(create_plan.artifact_id))
            self.assertFalse(result.applied)
            self.assertEqual(result.error, 'NotAvailable')
            for plan in (generate, create_plan):
                with self.assertRaises(NotAvailable):
                    briefs.confirm(plan)
            prepare.assert_not_called()
            create.assert_not_called()
            ask.assert_not_called()

    def test_A1_pause_during_prepare_blocks_native_brief_mutation(self):
        from unittest.mock import patch
        briefs = self.briefs()
        plan = briefs.plan(self.link.id, 'codex', writer='offline')
        target = self.adapters['codex']
        prepare = target.writer.prepare
        def pause(chat, kind):
            result = prepare(chat, kind)
            self.marks.pause(self.link.id)
            return result
        with patch.object(target.writer, 'prepare', side_effect=pause), patch.object(target.writer, 'create') as create:
            result = briefs.confirm(plan)
            self.assertFalse(result.applied)
            create.assert_not_called()
        self.assertEqual(self.adapters['codex'].reader.read(self.chats['codex']), [])

    def test_kept_turn_absent_from_agent_prompt_transcript_and_native_brief(self):
        self.marks.keep(self.ident)
        self.marks.pin(self.ident)
        self.adapters['claude'].chats[self.chats['claude']].append(turn('public'))
        self.applier.refresh(self.link.id)
        briefs = self.briefs()
        for writer in ('offline', 'codex'):
            plan = briefs.plan(self.link.id, 'codex', writer=writer, recent_turns=10)
            if plan.stage == 'generate':
                def ask(prompt, folder, read_only=True):
                    self.assertNotIn('User: one', prompt)
                    return 'safe summary'
                self.adapters['codex'].runner.ask = ask
                plan = briefs.confirm(plan)
            from pathlib import Path
            self.assertNotIn('User: one', Path(plan.transcript_path).read_text())
            self.assertNotIn(self.ident, plan.pinned)
            self.assertNotIn(self.ident, plan.turn_ids)
            result = briefs.confirm(plan)
            self.assertTrue(result.applied)
            content = self.adapters['codex'].reader.read(result.chat_id)
            self.assertFalse(any(t.prompt.text == 'one' or 'User: one' in t.prompt.text for t in content))

    def test_W13_status_shows_kept_gap_and_later_received_turn(self):
        from baton.services.read_views import ReadViews
        from baton.cli.output import read_status
        self.marks.keep(self.ident)
        self.adapters['claude'].chats[self.chats['claude']].append(turn('public'))
        self.applier.refresh(self.link.id)
        self.applier.apply(self.applier.preview(self.link.id))
        views = ReadViews(self.store, self.adapters, self.clock, lambda: {}, lambda s: s)
        shown = read_status(views.status(self.link.id))
        side = shown['sides']['codex']
        self.assertEqual((side['kept_elsewhere'], side['agent_has'], side['waiting']), (1, 1, 0))
        self.assertEqual(shown['turns'][0]['states']['codex'], 'kept_back')
        self.assertEqual(shown['turns'][1]['states']['codex'], 'added')

    def test_pause_at_last_creation_boundary_never_calls_create(self):
        from unittest.mock import patch
        briefs = self.briefs()
        plan = briefs.plan(self.link.id, 'codex', writer='offline')
        original = briefs._plan_object
        def pause(*args, **kwargs):
            result = original(*args, **kwargs)
            self.marks.pause(self.link.id)
            return result
        with patch.object(briefs, '_plan_object', side_effect=pause), patch.object(self.adapters['codex'].writer, 'create') as create:
            self.assertFalse(briefs.confirm(plan).applied)
            create.assert_not_called()

    def test_kept_turn_absent_from_digest_counts_files_and_commands(self):
        from baton.services.digest import DigestBuilder
        self.applier.apply(self.applier.preview(self.link.id))
        own = turn('own')
        self.adapters['codex'].chats[self.chats['codex']].append(own)
        self.applier.refresh(self.link.id)
        self.applier.apply(self.applier.preview(self.link.id))
        source = self.adapters['claude']
        from dataclasses import replace
        later = [replace(turn(ident), prompt=replace(turn(ident).prompt, at='2026-10-14T00:03:00Z'))
                 for ident in ('private', 'public')]
        source.chats[self.chats['claude']].extend(later)
        source.changed_files.update({'private': ['private.txt'], 'public': ['public.txt']})
        self.applier.refresh(self.link.id)
        private = next(r for r in self.store.turns(self.link.id) if r.origin_id == 'private')
        self.marks.keep(private.id)
        digest = DigestBuilder(self.store, {s: a.reader for s, a in self.adapters.items()}, self.clock, lambda s: s)
        news = digest.for_side(self.link.id, 'codex')
        self.assertEqual(news.turns, 1)
        self.assertEqual(news.files, ('public.txt',))
        self.assertNotIn('private', digest.text(news))

    def test_kept_turn_absent_from_attach_payload_and_acknowledgement(self):
        from baton.adapters.fake.facts import CLAUDE_LIKE
        from baton.domain.errors import NotAvailable
        target = self.adapters['codex']
        target.facts = CLAUDE_LIKE
        target.set_format(True, CLAUDE_LIKE.checked_versions[0])
        target.set_condition(self.chats['codex'], open=True, app_running=True)
        self.marks.keep(self.ident)
        self.adapters['claude'].chats[self.chats['claude']].append(turn('public'))
        self.applier.refresh(self.link.id)
        plan = self.applier.preview(self.link.id)
        step = next(s for s in plan.steps if s.side == 'codex')
        self.assertEqual(step.action, 'attach')
        self.assertNotIn(self.ident, step.turn_ids)
        self.assertEqual([t.prompt.text for t in step.turns], ['public'])
        with self.assertRaises(NotAvailable):
            self.applier.record_attached(self.link.id, 'codex', [self.ident], 'message')
        self.applier.record_attached(self.link.id, 'codex', list(step.turn_ids), 'message')
        self.assertEqual(self.store.turns(self.link.id)[0].states['codex'], 'kept_back')
