"""E10 consent, native effects, privacy, cache and recovery regression proofs."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import stat
from unittest.mock import patch

from baton.adapters.fake import FakeAdapter
from baton.adapters.fake.facts import CLAUDE_LIKE, CODEX_LIKE, OPENCODE_LIKE
from baton.domain.errors import ChatChanged, NotAvailable
from baton.domain.link import SUMMARIZED, SHOWN, ADDED, WAITING, KEPT_BACK
from baton.ledger.sqlite_store import Ledger
from baton.services.applier import Applier
from baton.services.brief import BriefService
from baton.services.digest import DigestBuilder
from baton.services.linker import Linker
from baton.services.merger import Merger
from baton.services.refresh import ChatRefresh
from baton.services.transcripts import FolderTranscripts
from baton.services.undo import Undo
from tests.unit.test_brief import BriefBase
from tests.scenarios.test_working_across import make_turn, at, label


class LifecycleTests(BriefBase):
    def artifact(self, to='codex', **options):
        preview = self.briefs.plan(self.link.id, to, **options)
        return self.briefs.confirm(preview) if preview.stage == 'generate' else preview

    def test_preview_zero_asks_discloses_each_candidate_and_bounded_total(self):
        before = deepcopy({s: a.chats for s, a in self.adapters.items()})
        preview = self.briefs.plan(self.link.id, 'codex')
        self.assertEqual(preview.stage, 'generate')
        self.assertEqual([r.calls for r in self.runners.values()], [[], []])
        self.assertEqual([item['writer'] for item in preview.candidate_estimates], ['codex', 'claude'])
        self.assertEqual(preview.estimated_tokens, sum(item['tokens'] for item in preview.candidate_estimates))
        self.assertEqual([n.id for n in preview.notes].count('brief.cost'), 2)
        self.assertIn('brief.total_cost', [n.id for n in preview.notes])
        self.assertEqual(before, {s: a.chats for s, a in self.adapters.items()})
        self.assertFalse(self.store.journal_entries())

    def test_generation_then_creation_have_distinct_single_use_tokens_and_exact_native_artifact(self):
        preview = self.briefs.plan(self.link.id, 'codex', recent_turns=2)
        created = self.briefs.confirm(preview)
        self.assertEqual(created.stage, 'create')
        self.assertNotEqual(preview.plan_id, created.plan_id)
        self.assertEqual(len(self.runners['codex'].calls), 1)
        self.clock.value = '2026-10-05T14:01:00Z'
        result = self.briefs.confirm(created)
        self.assertTrue(result.applied, result)
        self.assertEqual(result.link_id, self.link.id)
        native = self.adapters['codex'].reader.read(result.chat_id)
        self.assertEqual(native, [created.turn, *created.originals])
        self.assertEqual(native[0].prompt.at, '2026-10-05T14:00:00Z')
        self.assertEqual(len(self.runners['codex'].calls), 1)
        for token in (preview, created):
            with self.assertRaises(ChatChanged): self.briefs.confirm(token)
        self.assertEqual(self.store.journal_entries()[0]['state'], 'committed')

    def test_generation_token_replay_before_any_creation_is_refused_without_another_run(self):
        preview = self.briefs.plan(self.link.id, 'codex')
        artifact = self.briefs.confirm(preview)
        self.assertEqual(artifact.stage, 'create')
        self.assertEqual(self.store.get_link(self.link.id).chats, self.chats)
        with self.assertRaises(ChatChanged): self.briefs.confirm(preview)
        self.assertEqual(len(self.runners['codex'].calls), 1)
        self.assertFalse(self.store.journal_entries())

    def test_failed_runners_offline_artifact_consumes_generation_without_cache_or_chat_change(self):
        self.runners['codex'] = self.runner('codex', error=RuntimeError('runner failed'))
        self.runners['claude'] = self.runner('claude', error=RuntimeError('runner failed'))
        preview = self.briefs.plan(self.link.id, 'codex')
        with self.assertLogs('baton.services.brief', 'ERROR'):
            artifact = self.briefs.confirm(preview)
        self.assertEqual((artifact.stage, artifact.writer), ('create', 'offline'))
        calls = [len(self.runners[s].calls) for s in ('codex', 'claude')]
        self.assertEqual(calls, [1, 1])
        self.assertEqual(self.store.get_link(self.link.id).chats, self.chats)
        with self.assertRaises(ChatChanged): self.briefs.confirm(preview)
        self.assertEqual([len(self.runners[s].calls) for s in ('codex', 'claude')], calls)
        self.assertFalse(self.store.journal_entries())

    def test_creation_ignores_forged_client_stage_text_writer_and_turns(self):
        artifact = self.artifact()
        tampered = replace(artifact, stage='generate', text='UNAPPROVED', writer='offline', originals=())
        result = self.briefs.confirm(tampered)
        self.assertTrue(result.applied, result)
        self.assertEqual(self.adapters['codex'].reader.read(result.chat_id), [artifact.turn, *artifact.originals])
        self.assertEqual(len(self.runners['codex'].calls), 1)

    def test_create_and_generation_tokens_expire_after_ten_minutes(self):
        for writer in (None, 'offline'):
            token = self.briefs.plan(self.link.id, 'codex', writer=writer)
            self.clock.value = '2026-10-05T14:11:00Z'
            with self.assertRaises(ChatChanged): self.briefs.confirm(token)
            self.clock.value = '2026-10-05T14:00:00Z'
        self.assertEqual(self.runners['codex'].calls, [])

    def test_missing_changed_native_content_and_changed_marks_refuse_before_run_or_write(self):
        for stage in ('generate', 'create'):
            for mutation in ('prompt', 'missing', 'pin'):
                with self.subTest(stage=stage, mutation=mutation):
                    token = (self.briefs.plan(self.link.id, 'codex') if stage == 'generate'
                             else self.artifact(writer='offline'))
                    original = deepcopy(self.adapters['claude'].chats[self.chats['claude']])
                    if mutation == 'prompt':
                        turn = original[0]
                        self.adapters['claude'].chats[self.chats['claude']][0] = replace(turn, prompt=replace(turn.prompt, text='rewritten'))
                    elif mutation == 'missing': self.adapters['claude'].chats[self.chats['claude']].pop(0)
                    else: self.store.set_pinned(self.link.id, self.ids[0], True)
                    before = set(self.adapters['codex'].chats)
                    with self.assertRaises(ChatChanged): self.briefs.confirm(token)
                    self.assertEqual(set(self.adapters['codex'].chats), before)
                    self.adapters['claude'].chats[self.chats['claude']] = original
                    self.store.set_pinned(self.link.id, self.ids[0], False)
        self.assertEqual(self.runners['codex'].calls, [])

    def test_transcript_tampering_is_refused_before_prepare_or_create(self):
        artifact = self.artifact(writer='offline')
        Path(artifact.transcript_path).write_text('tampered')
        result = self.briefs.confirm(artifact)
        self.assertFalse(result.applied)
        self.assertFalse(self.store.journal_entries())
        self.assertEqual(set(self.adapters['codex'].chats), {self.chats['codex']})

    def test_offline_stage_is_create_and_never_invokes_any_runner(self):
        preview = self.briefs.plan(self.link.id, 'codex', writer='offline')
        self.assertEqual((preview.stage, preview.writer), ('create', 'offline'))
        self.assertTrue(self.briefs.confirm(preview).applied)
        self.assertEqual([r.calls for r in self.runners.values()], [[], []])

    def test_wrong_reserved_chat_receipt_is_recovered_without_an_orphan(self):
        artifact = self.artifact(writer='offline')
        writer = self.adapters['codex'].writer
        create = writer.create
        def misplaced(*args, **kwargs):
            writer._prepared_create = None
            return create(*args, **kwargs)
        with patch.object(writer, 'create', side_effect=misplaced):
            result = self.briefs.confirm(artifact)
        self.assertFalse(result.applied)
        self.assertEqual(set(self.adapters['codex'].chats), {self.chats['codex']})
        self.assertEqual(self.store.get_link(self.link.id).chats, self.chats)
        self.assertFalse(self.store.journal_entries(pending=True))
        self.assertEqual([e['state'] for e in self.store.journal_entries()], ['taken_back', 'taken_back'])

    def test_summary_is_not_shown_or_waiting_and_pinned_recent_have_separate_native_ids(self):
        self.store.set_pinned(self.link.id, self.ids[1], True)
        artifact = self.artifact(writer='offline', recent_turns=1)
        result = self.briefs.confirm(artifact)
        self.assertTrue(result.applied, result)
        refreshed = ChatRefresh(self.store, self.adapters, self.clock).refresh(self.link.id)
        rows = self.store.turns(self.link.id)
        self.assertEqual([r.states['codex'] for r in rows], [SUMMARIZED, SHOWN, SUMMARIZED, SUMMARIZED, SUMMARIZED, SHOWN])
        side = refreshed['status'].side('codex')
        self.assertEqual((side.total, side.agent_has, side.chat_shows, side.waiting), (6, 2, 2, 0))
        self.assertIsNone(side.synced_up_to)
        coverage = self.store.summary_coverage(self.link.id, 'codex')
        self.assertEqual(coverage['turn_ids'], self.ids)
        self.assertEqual(coverage['through_turn_id'], self.ids[-1])
        self.assertEqual(set(self.store.local_ids(self.link.id, 'codex')), {self.ids[1], self.ids[-1]})
        self.assertEqual(len(rows), 6)  # The synthetic opening is not an imported seventh turn.

    def test_copied_originals_clear_visibility_on_relaunch_but_summary_never_upgrades(self):
        result = self.briefs.confirm(self.artifact('claude', writer='offline', recent_turns=1))
        self.assertTrue(result.applied, result)
        refresh = ChatRefresh(self.store, self.adapters, self.clock)
        self.assertEqual(refresh.refresh(self.link.id)['status'].side('claude').added, 1)
        self.adapters['claude'].set_condition(result.chat_id, app_started_at='2026-10-05T14:01:00Z')
        state = refresh.refresh(self.link.id)['status'].side('claude')
        self.assertEqual((state.added, state.chat_shows), (0, 1))
        self.assertEqual(sum(r.states['claude'] == SUMMARIZED for r in self.store.turns(self.link.id)), 5)

    def test_after_brief_new_turns_sync_in_full_both_directions_and_digest_omits_old_summary(self):
        result = self.briefs.confirm(self.artifact('claude', writer='offline', recent_turns=0))
        self.assertTrue(result.applied, result)
        refresh = ChatRefresh(self.store, self.adapters, self.clock)
        readers = {s: a.reader for s, a in self.adapters.items()}
        digest = DigestBuilder(self.store, readers, self.clock, label)
        self.assertIsNone(digest.for_side(self.link.id, 'claude'))
        future = make_turn('fresh codex', at(14, 2), at(14, 3), calls=1)
        self.adapters['codex'].chats[self.chats['codex']].append(future)
        refresh.refresh(self.link.id)
        self.assertEqual((digest.for_side(self.link.id, 'claude').turns, digest.for_side(self.link.id, 'claude').commands), (1, 1))
        applier = Applier(self.store, self.adapters, self.clock)
        self.assertTrue(applier.apply(applier.preview(self.link.id)).applied)
        self.assertIn('fresh codex', [t.prompt.text for t in self.adapters['claude'].reader.read(result.chat_id)])
        future2 = make_turn('fresh claude', at(14, 4), at(14, 5))
        self.adapters['claude'].chats[result.chat_id].append(future2)
        refresh.refresh(self.link.id)
        self.assertTrue(applier.apply(applier.preview(self.link.id)).applied)
        self.assertIn('fresh claude', [t.prompt.text for t in self.adapters['codex'].reader.read(self.chats['codex'])])
        self.assertEqual(sum(r.states['claude'] == SUMMARIZED for r in self.store.turns(self.link.id)), 6)
        self.assertEqual(len(self.store.turns(self.link.id)), 8)
    def test_undo_boundary_before_current_summary_refuses_with_or_without_recent_excerpts(self):
        for recent in (0, 3):
            with self.subTest(recent=recent):
                # Each branch gets a fresh independent ledger/chat pair.
                fixture = BriefBase('runTest'); fixture.setUp()
                try:
                    future = make_turn('future one', at(14, 1), at(14, 2))
                    fixture.write('claude', future)
                    applier = Applier(fixture.store, fixture.adapters, fixture.clock)
                    self.assertTrue(applier.apply(applier.preview(fixture.link.id)).applied)
                    added = next(e for e in fixture.store.history(fixture.link.id) if e.kind == 'add' and e.side == 'codex')
                    preview = fixture.briefs.plan(fixture.link.id, 'codex', writer='offline', recent_turns=recent)
                    created = fixture.briefs.confirm(preview)
                    self.assertTrue(created.applied, created)
                    before = deepcopy({s: a.chats for s, a in fixture.adapters.items()})
                    coverage = fixture.store.summary_coverage(fixture.link.id, 'codex')
                    records = fixture.briefs._record(fixture.link.id)
                    journals = fixture.store.journal_entries()
                    undo = Undo(fixture.store, fixture.adapters, fixture.clock)
                    with self.assertRaises(ChatChanged): undo.plan(fixture.link.id, added.id)
                    self.assertEqual(before, {s: a.chats for s, a in fixture.adapters.items()})
                    self.assertEqual(coverage, fixture.store.summary_coverage(fixture.link.id, 'codex'))
                    self.assertEqual(records, fixture.briefs._record(fixture.link.id))
                    self.assertEqual(journals, fixture.store.journal_entries())
                    reverted = undo.apply(undo.plan(fixture.link.id, created.event_id))
                    self.assertTrue(reverted.applied, reverted)
                    old_add_undo = undo.apply(undo.plan(fixture.link.id, added.id))
                    self.assertTrue(old_add_undo.applied, old_add_undo)
                finally: fixture.doCleanups()

    def test_future_add_undo_and_restore_preserve_earlier_summary_without_changing_coverage(self):
        for facts in (CODEX_LIKE, OPENCODE_LIKE):
            with self.subTest(can_cut=facts.can_cut):
                fixture = BriefBase('runTest'); fixture.setUp()
                try:
                    fixture.adapters['codex'].facts = facts
                    artifact = fixture.briefs.plan(fixture.link.id, 'codex', writer='offline', recent_turns=0)
                    result = fixture.briefs.confirm(artifact)
                    self.assertTrue(result.applied, result)
                    expected_ids = fixture.store.summary_coverage(fixture.link.id, 'codex')['turn_ids']
                    fixture.write('claude', make_turn('AFTER-SUMMARY', at(14, 1), at(14, 2)))
                    applier = Applier(fixture.store, fixture.adapters, fixture.clock)
                    self.assertTrue(applier.apply(applier.preview(fixture.link.id)).applied)
                    event = next(e for e in fixture.store.history(fixture.link.id) if e.kind == 'add' and e.side == 'codex')
                    undo = Undo(fixture.store, fixture.adapters, fixture.clock)
                    undone = undo.apply(undo.plan(fixture.link.id, event.id))
                    self.assertTrue(undone.applied, undone)
                    current = fixture.store.get_link(fixture.link.id).chat('codex')
                    self.assertEqual(fixture.adapters['codex'].reader.read(current)[0].prompt.text, artifact.text)
                    self.assertNotIn('AFTER-SUMMARY', '\n'.join(t.prompt.text for t in fixture.adapters['codex'].reader.read(current)))
                    self.assertEqual(fixture.store.summary_coverage(fixture.link.id, 'codex')['turn_ids'], expected_ids)
                    restored = undo.apply(undo.restore(fixture.link.id, undone.event_id))
                    self.assertTrue(restored.applied, restored)
                    refresh = ChatRefresh(fixture.store, fixture.adapters, fixture.clock).refresh(fixture.link.id)
                    self.assertEqual(sum(r.states['codex'] == SUMMARIZED for r in refresh['turns']), 6)
                    self.assertEqual(refresh['turns'][-1].states['codex'], ADDED if facts.can_cut else SHOWN)
                    self.assertIn('AFTER-SUMMARY', '\n'.join(t.prompt.text for t in fixture.adapters['codex'].reader.read(fixture.store.get_link(fixture.link.id).chat('codex'))))
                    self.assertEqual(fixture.store.summary_coverage(fixture.link.id, 'codex')['turn_ids'], expected_ids)
                finally: fixture.doCleanups()


class PrivacyCacheTests(BriefBase):
    def artifact(self, to='codex', **options):
        preview = self.briefs.plan(self.link.id, to, **options)
        return self.briefs.confirm(preview) if preview.stage == 'generate' else preview

    def private(self):
        ident = self.write('claude', make_turn('PRIVATE-SENTINEL', at(10, 0), at(10, 1), reply='PRIVATE-REPLY'))[0]
        self.adapters['claude'].changed_files['PRIVATE-SENTINEL'] = ['PRIVATE-FILE']
        self.store.set_pinned(self.link.id, ident, True)
        self.store.keep_back(self.link.id, ident)
        return ident

    def test_destination_privacy_intersects_explicit_source_writer_and_automatic_fallback(self):
        kept = self.private()
        for writer in ('claude', None, 'offline'):
            with self.subTest(writer=writer):
                if writer is None: self.runner('codex', error=RuntimeError('try fallback'))
                artifact = self.artifact(writer=writer)
                for path in (artifact.text, '\n'.join(t.prompt.text + t.reply_text for t in artifact.originals), Path(artifact.transcript_path).read_text()):
                    for secret in ('PRIVATE-SENTINEL', 'PRIVATE-REPLY', 'PRIVATE-FILE'):
                        self.assertNotIn(secret, path)
                self.assertNotIn(kept, artifact.pinned)
        for adapter in self.adapters.values():
            if adapter.runner:
                self.assertTrue(all('PRIVATE-' not in prompt for prompt, _, _ in adapter.runner.calls))

    def test_private_source_snapshot_cannot_replace_earlier_destination_safe_path(self):
        self.private()
        destination = self.artifact(writer='offline')
        before = Path(destination.transcript_path).read_bytes()
        source = self.artifact('claude', writer='offline')
        self.assertNotEqual(source.transcript_path, destination.transcript_path)
        self.assertEqual(Path(destination.transcript_path).read_bytes(), before)
        self.assertIn('PRIVATE-REPLY', Path(source.transcript_path).read_text())
        self.assertEqual(stat.S_IMODE(Path(destination.transcript_path).stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.saved.stat().st_mode), 0o700)

    def test_unchanged_cache_reuses_without_ask_and_delta_only_updates_previous_safe_summary(self):
        runner = self.runner('codex', 'SAFE-BASE-SUMMARY')
        first = self.artifact()
        cached = self.briefs.plan(self.link.id, 'codex')
        self.assertEqual((cached.stage, cached.summary), ('create', first.summary))
        self.assertEqual(len(runner.calls), 1)
        self.write('claude', make_turn('DELTA-REQUEST', at(10, 1), at(10, 2), reply='DELTA-REPLY'))
        token = self.briefs.plan(self.link.id, 'codex')
        self.assertEqual(len(runner.calls), 1)
        second = self.briefs.confirm(token)
        self.assertEqual(len(runner.calls), 2)
        prompt = runner.calls[-1][0]
        self.assertIn('SAFE-BASE-SUMMARY', prompt)
        self.assertIn('DELTA-REPLY', prompt)
        self.assertNotIn('answer 0', prompt)
        self.assertNotEqual(first.transcript_path, second.transcript_path)

    def test_changed_privacy_discards_cached_summary_and_cached_fallback_does_not_skip_destination(self):
        extra = self.write('claude', make_turn('soon-private', at(10, 1), at(10, 2)))[0]
        source = self.runner('claude', 'SOURCE-OLD')
        self.adapters['codex'].runner = None
        self.artifact()
        destination = self.runner('codex', 'DEST-NEW')
        token = self.briefs.plan(self.link.id, 'codex')
        self.assertEqual((token.stage, token.writer), ('generate', 'codex'))
        generated = self.briefs.confirm(token)
        self.assertEqual((generated.writer, len(destination.calls)), ('codex', 1))
        self.store.keep_back(self.link.id, extra)
        token = self.briefs.plan(self.link.id, 'codex')
        self.assertEqual(token.stage, 'generate')
        self.briefs.confirm(token)
        self.assertNotIn('DEST-NEW', destination.calls[-1][0])
        self.assertNotIn('soon-private', destination.calls[-1][0])

    def test_later_cached_fallback_is_reused_after_destination_fails_without_second_agent_ask(self):
        self.adapters['codex'].runner = None
        source = self.runner('claude', 'CACHED-SOURCE')
        self.artifact()
        destination = self.runner('codex', error=RuntimeError('failed destination'))
        preview = self.briefs.plan(self.link.id, 'codex')
        with self.assertLogs('baton.services.brief', 'ERROR'):
            artifact = self.briefs.confirm(preview)
        self.assertEqual((artifact.writer, artifact.summary), ('claude', 'CACHED-SOURCE'))
        self.assertEqual((len(destination.calls), len(source.calls)), (1, 1))



class RecoveryTests(BriefBase):
    def setUp(self):
        super().setUp()
        path = self.saved / 'record.sqlite'
        target = Ledger(str(path))
        self.store.db.backup(target.db)
        self.store.close()
        self.store = target
        self.addCleanup(target.close)
        self.path = path
        self.briefs = BriefService(self.store, self.adapters, self.clock, FolderTranscripts(self.saved), label)

    def restart(self):
        self.store.close()
        self.store = Ledger(str(self.path))
        self.addCleanup(self.store.close)
        self.briefs = BriefService(self.store, self.adapters, self.clock, FolderTranscripts(self.saved), label)
        return self.briefs

    def artifact(self): return self.briefs.plan(self.link.id, 'codex', writer='offline')

    def test_persisted_creation_survives_restart_without_regeneration(self):
        artifact = self.artifact()
        self.restart()
        result = self.briefs.confirm(artifact.plan_id)
        self.assertTrue(result.applied, result)
        self.assertEqual(self.adapters['codex'].reader.read(result.chat_id)[0], artifact.turn)
        self.restart()
        ChatRefresh(self.store, self.adapters, self.clock).refresh(self.link.id)
        self.assertEqual(len(self.store.turns(self.link.id)), 6)
        self.assertEqual(self.store.summary_coverage(self.link.id, 'codex')['artifact_id'], artifact.artifact_id)
        self.assertEqual([r.calls for r in self.runners.values()], [[], []])

    def test_interruption_after_prepare_before_create_recovers_no_chat(self):
        artifact = self.artifact()
        with patch.object(self.adapters['codex'].writer, 'create', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt): self.briefs.confirm(artifact)
        self.assertEqual(len(self.store.journal_entries(pending=True)), 1)
        self.restart()
        self.assertEqual(self.store.journal_entries()[0]['state'], 'taken_back')
        self.assertEqual(self.store.get_link(self.link.id).chats, self.chats)
        self.assertEqual(set(self.adapters['codex'].chats), {self.chats['codex']})

    def test_interruptions_after_create_and_before_atomic_commit_recover_native_and_link(self):
        for position in ('after_create', 'verify', 'before_commit'):
            with self.subTest(position=position):
                artifact = self.artifact()
                create = self.adapters['codex'].writer.create
                if position == 'after_create':
                    def interrupt(*args, **kwargs):
                        create(*args, **kwargs); raise KeyboardInterrupt()
                    owner, name, effect = self.adapters['codex'].writer, 'create', interrupt
                elif position == 'verify':
                    read = self.adapters['codex'].reader.read
                    def interrupt(chat):
                        if chat != self.chats['codex']: raise KeyboardInterrupt()
                        return read(chat)
                    owner, name, effect = self.adapters['codex'].reader, 'read', interrupt
                else: owner, name, effect = self.store, 'complete_brief', KeyboardInterrupt
                with patch.object(owner, name, side_effect=effect):
                    with self.assertRaises(KeyboardInterrupt): self.briefs.confirm(artifact)
                self.assertEqual(len(self.adapters['codex'].chats), 2)
                self.restart()
                self.assertEqual(set(self.adapters['codex'].chats), {self.chats['codex']})
                self.assertEqual(self.store.get_link(self.link.id).chats, self.chats)
                self.assertIsNone(self.store.summary_coverage(self.link.id, 'codex'))

    def test_exception_after_atomic_finalization_never_rolls_back_committed_native_chat(self):
        artifact = self.artifact()
        finalize = self.store.complete_brief
        def after_commit(*args, **kwargs):
            finalize(*args, **kwargs); raise RuntimeError('after commit')
        with patch.object(self.store, 'complete_brief', side_effect=after_commit): result = self.briefs.confirm(artifact)
        self.assertTrue(result.applied, result)
        chat = self.store.get_link(self.link.id).chat('codex')
        self.assertEqual(result.chat_id, chat)
        self.assertIn(chat, self.adapters['codex'].chats)
        self.restart()
        self.assertIn(chat, self.adapters['codex'].chats)
        self.assertFalse(self.store.journal_entries(pending=True))

    def test_failed_generation_token_stays_consumed_after_restart(self):
        preview = self.briefs.plan(self.link.id, 'codex')
        self.store.set_pinned(self.link.id, self.ids[0], True)
        with self.assertRaises(ChatChanged): self.briefs.confirm(preview)
        self.store.set_pinned(self.link.id, self.ids[0], False)
        self.restart()
        with self.assertRaises(ChatChanged): self.briefs.confirm(preview)
        self.assertEqual(self.runners['codex'].calls, [])

    def test_brief_undo_and_restore_move_link_keep_created_chat_and_summary_states(self):
        artifact = self.artifact()
        result = self.briefs.confirm(artifact)
        self.assertTrue(result.applied, result)
        current = deepcopy(self.adapters['codex'].reader.read(result.chat_id))
        undo = Undo(self.store, self.adapters, self.clock)
        reverted = undo.apply(undo.plan(self.link.id, result.event_id))
        self.assertTrue(reverted.applied, reverted)
        self.assertEqual(self.store.get_link(self.link.id).chat('codex'), self.chats['codex'])
        self.assertEqual(self.adapters['codex'].reader.read(result.chat_id), current)
        self.assertIsNone(self.store.summary_coverage(self.link.id, 'codex'))
        restored = undo.apply(undo.restore(self.link.id, reverted.event_id))
        self.assertTrue(restored.applied, restored)
        self.restart()
        refreshed = ChatRefresh(self.store, self.adapters, self.clock).refresh(self.link.id)
        self.assertEqual(refreshed['link'].mode, 'brief')
        self.assertEqual(sum(r.states['codex'] == SUMMARIZED for r in refreshed['turns']), 3)
        self.assertEqual(refreshed['status'].side('codex').chat_shows, 3)


class NewLinkTests(BriefBase):
    def test_initial_brief_link_is_created_atomically_without_visible_preview_link(self):
        self.store.remove_link(self.link.id, self.clock.now())
        service = Linker(self.store, self.adapters, self.clock, self.briefs)
        before = deepcopy({s: a.chats for s, a in self.adapters.items()})
        preview = service.plan_link('claude', self.chats['claude'], 'codex', mode='brief')
        self.assertEqual(preview.stage, 'generate')
        self.assertFalse(self.store.links())
        self.assertEqual(self.runners['codex'].calls, [])
        artifact = service.apply(preview)
        self.assertEqual(artifact.stage, 'create')
        self.assertFalse(self.store.links())
        result = service.apply(artifact)
        self.assertTrue(result.applied, result)
        link = self.store.get_link(result.link_id)
        self.assertEqual(link.mode, 'brief')
        self.assertEqual(link.chat('claude'), self.chats['claude'])
        self.assertEqual(link.chat('codex'), result.chat_id)
        self.assertEqual(self.store.journal_entries()[0]['state'], 'committed')
        for side, chats in before.items():
            for chat, turns in chats.items(): self.assertEqual(self.adapters[side].reader.read(chat), turns)
        refresh = ChatRefresh(self.store, self.adapters, self.clock).refresh(result.link_id)
        self.assertEqual(len(refresh['turns']), 6)
        self.assertEqual(refresh['status'].side('codex').waiting, 0)
        self.assertEqual(self.store.summary_coverage(result.link_id, 'codex')['artifact_id'], artifact.artifact_id)

    def test_existing_relink_brief_preserves_earlier_partner_and_kept_turn(self):
        private = self.write('claude', make_turn('PRIVATE', at(10, 1), at(10, 2)))[0]
        self.store.keep_back(self.link.id, private)
        service = Linker(self.store, self.adapters, self.clock, self.briefs)
        preview = service.plan_relink(self.link.id, 'codex', mode='brief', from_side='claude')
        created = service.apply(preview)
        result = service.apply(created) if created.stage == 'create' else created
        self.assertTrue(result.applied, result)
        self.assertEqual(self.store.get_link(self.link.id).chat('codex'), result.chat_id)
        self.assertIn(self.chats['codex'], self.adapters['codex'].chats)
        self.assertEqual(self.store.turns(self.link.id)[-1].states['codex'], KEPT_BACK)
        self.assertNotIn('PRIVATE', self.adapters['codex'].reader.read(result.chat_id)[0].prompt.text)

    def test_relink_to_third_tool_preserves_destination_privacy_and_source_summary_coverage(self):
        private = self.write('claude', make_turn('PRIVATE-THIRD', at(10, 1), at(10, 2)))[0]
        self.store.keep_back(self.link.id, private)
        self.store.set_pinned(self.link.id, private, True)
        own = self.briefs.plan(self.link.id, 'claude', writer='offline', recent_turns=0)
        first = self.briefs.confirm(own)
        self.assertTrue(first.applied, first)
        self.adapters['opencode'] = FakeAdapter(OPENCODE_LIKE, 'opencode')
        service = Linker(self.store, self.adapters, self.clock, self.briefs)
        preview = service.plan_relink(self.link.id, 'opencode', mode='brief', from_side='claude')
        self.assertEqual(preview.stage, 'generate')
        created = service.apply(preview)
        result = service.apply(created)
        self.assertTrue(result.applied, result)
        self.assertNotEqual(result.link_id, self.link.id)
        new = self.store.get_link(result.link_id)
        self.assertEqual(new.chat('claude'), first.chat_id)
        self.assertEqual(new.chat('opencode'), result.chat_id)
        self.assertTrue(self.store.get_link(self.link.id).removed_at)
        self.assertNotIn('PRIVATE-THIRD', Path(created.transcript_path).read_text())
        self.assertNotIn('PRIVATE-THIRD', created.text)
        refresh = ChatRefresh(self.store, self.adapters, self.clock).refresh(result.link_id)
        self.assertEqual(len(refresh['turns']), 7)
        self.assertEqual(refresh['turns'][-1].states['opencode'], KEPT_BACK)
        self.assertEqual(sum(r.states['claude'] == SUMMARIZED for r in refresh['turns']), 6)
        self.assertIsNotNone(self.store.summary_coverage(result.link_id, 'claude'))

    def test_summary_opening_deletion_or_modification_never_fakes_received_history(self):
        result = self.briefs.confirm(self.briefs.plan(self.link.id, 'codex', writer='offline', recent_turns=0))
        self.assertTrue(result.applied, result)
        opening = self.adapters['codex'].chats[result.chat_id][0]
        for altered in ([], [replace(opening, prompt=replace(opening.prompt, text='changed summary'))]):
            self.adapters['codex'].chats[result.chat_id] = altered
            with self.assertRaises(ChatChanged): ChatRefresh(self.store, self.adapters, self.clock).refresh(self.link.id)
        self.adapters['codex'].chats[result.chat_id] = [opening]
        self.assertEqual(ChatRefresh(self.store, self.adapters, self.clock).refresh(self.link.id)['status'].side('codex').waiting, 0)

    def test_initial_link_failure_after_atomic_commit_returns_actual_committed_link(self):
        self.store.remove_link(self.link.id, self.clock.now())
        artifact = self.briefs.plan_new('claude', self.chats['claude'], 'codex', writer='offline')
        finalize = self.store.complete_brief_link
        def after_commit(*args, **kwargs):
            finalize(*args, **kwargs); raise RuntimeError('late')
        with patch.object(self.store, 'complete_brief_link', side_effect=after_commit): result = self.briefs.confirm(artifact)
        self.assertTrue(result.applied, result)
        self.assertIsNotNone(result.link_id)
        self.assertEqual(self.store.get_link(result.link_id).chat('codex'), result.chat_id)
