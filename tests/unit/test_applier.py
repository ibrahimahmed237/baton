"""Confirmed plan execution, receipts, rechecks and interrupted writes."""
from dataclasses import replace
import unittest

from baton.adapters.fake import FakeAdapter
from baton.adapters.fake.facts import CLAUDE_LIKE, CODEX_LIKE
from baton.domain.errors import ChatChanged, NotAvailable
from baton.domain.model import Message, Turn, PROMPT, REPLY
from baton.ledger.sqlite_store import Ledger
from baton.ports.clock import FixedClock
from baton.services.applier import Applier, ApplyStep
from tests.adapters.suite import turns


class ApplierTests(unittest.TestCase):
    def setUp(self):
        self.store = Ledger(':memory:')
        self.clock = FixedClock('2026-01-01T01:00:00Z')
        self.adapters = {'claude': FakeAdapter(CLAUDE_LIKE, 'claude'),
                         'codex': FakeAdapter(CODEX_LIKE, 'codex')}
        self.source = self.adapters['claude'].build_chat(turns())
        self.target = self.adapters['codex'].build_chat([])
        self.link = self.store.link({'claude': self.source, 'codex': self.target}, 'full_copy', at=self.clock.now())
        self.store.record_turns(self.link.id, 'claude', turns())
        self.applier = Applier(self.store, self.adapters, self.clock)

    def tearDown(self):
        self.store.close()

    def test_preview_is_read_only_and_confirmation_adds_once(self):
        plan = self.applier.preview(self.link.id)
        self.assertEqual(self.adapters['codex'].reader.read(self.target), [])
        self.assertEqual(self.store.journal_entries(), [])
        result = self.applier.apply_confirmed(self.link.id, plan.plan_id)
        self.assertTrue(result.applied)
        self.assertEqual(len(self.adapters['codex'].reader.read(self.target)), 3)
        self.assertTrue(all(t.states['codex'] == 'shown' for t in self.store.turns(self.link.id)))
        self.assertEqual(self.applier.preview(self.link.id).steps, ())
        self.assertEqual(self.applier.refresh(self.link.id)['status'].side('codex').agent_has, 3)
        self.assertEqual(len(self.store.turns(self.link.id)), 3)
        self.assertEqual(self.store.journal_entries()[0]['state'], 'committed')

    def test_changed_source_refuses_even_when_ids_counts_and_first_lines_match(self):
        plan = self.applier.preview(self.link.id)
        source = self.adapters['claude']
        before = source.chats[self.source][0]
        source.chats[self.source][0] = replace(before, messages=(Message('a1', REPLY, 'changed full reply'),))
        with self.assertRaises(ChatChanged): self.applier.apply(plan)
        with self.assertRaises(ChatChanged): self.applier.apply_confirmed(self.link.id, plan.plan_id)
        self.assertEqual(self.adapters['codex'].reader.read(self.target), [])
        self.assertEqual(self.store.journal_entries(), [])

    def test_changed_target_and_paused_record_refuse_stale_plan(self):
        plan = self.applier.preview(self.link.id)
        self.adapters['codex'].build_chat([])
        self.adapters['codex'].chats[self.target].append(Turn(Message('local', PROMPT, 'new')))
        with self.assertRaises(ChatChanged): self.applier.apply(plan)
        self.adapters['codex'].chats[self.target].clear()
        self.store.set_paused(self.link.id, True, self.clock.now())
        with self.assertRaises(ChatChanged): self.applier.apply(plan)

    def test_readback_mismatch_rolls_back_and_leaves_waiting(self):
        original = self.applier._verify
        self.applier._verify = lambda *args: (_ for _ in ()).throw(ChatChanged())
        result = self.applier.apply(self.applier.preview(self.link.id))
        self.assertEqual(result.error, 'ChatChanged')
        self.assertEqual(self.adapters['codex'].reader.read(self.target), [])
        self.assertTrue(all(t.states['codex'] == 'waiting' for t in self.store.turns(self.link.id)))
        self.assertEqual(self.store.journal_entries()[0]['state'], 'taken_back')
        self.applier._verify = original
        self.assertTrue(self.applier.apply(self.applier.preview(self.link.id)).applied)

    def test_writer_failure_after_mutation_takes_it_back(self):
        writer = self.adapters['codex'].writer
        original = writer.add
        def broken(chat, incoming):
            original(chat, incoming)
            raise RuntimeError('crash')
        writer.add = broken
        result = self.applier.apply(self.applier.preview(self.link.id))
        self.assertEqual(result.error, 'RuntimeError')
        self.assertEqual(self.adapters['codex'].reader.read(self.target), [])
        self.assertEqual(self.store.journal_entries()[0]['state'], 'taken_back')

    def test_delivery_failure_rolls_back_atomic_transaction_and_chat(self):
        self.store.db.execute("create trigger fail_delivery before update on turn_states begin select raise(abort,'fail'); end")
        result = self.applier.apply(self.applier.preview(self.link.id))
        self.assertFalse(result.applied)
        self.assertEqual(self.adapters['codex'].reader.read(self.target), [])
        self.assertTrue(all(t.states['codex'] == 'waiting' for t in self.store.turns(self.link.id)))
        self.assertEqual(len([e for e in self.store.history(self.link.id) if e.kind == 'add']), 0)
        self.assertEqual(self.store.journal_entries()[0]['state'], 'taken_back')

    def test_create_verifies_before_commit_and_failure_removes_chat(self):
        step = ApplyStep('codex', 'create', turns=tuple(turns()), name='copy', folder='folder')
        plan = self.applier.prepare(None, [step], {'claude': self.source})
        result = self.applier.apply(plan)
        self.assertTrue(result.applied)
        chat = result.completed[0].chat_id
        self.assertEqual(self.adapters['codex'].reader.read(chat), turns())
        self.assertEqual(self.store.journal_entries()[0]['state'], 'committed')
        before = len(self.adapters['codex'].locator.chats())
        self.applier._verify = lambda *args: (_ for _ in ()).throw(ChatChanged())
        failed = self.applier.apply(self.applier.prepare(None, [step], {'claude': self.source}))
        self.assertFalse(failed.applied)
        self.assertEqual(len(self.adapters['codex'].locator.chats()), before)
        self.assertEqual(self.store.journal_entries()[-1]['state'], 'taken_back')

    def test_release_success_rechecks_write_state_after_release(self):
        # Target has release-capable facts; writes must happen only after it closes.
        target = self.adapters['codex']
        target.facts = CLAUDE_LIKE
        target.set_format(True, CLAUDE_LIKE.checked_versions[0])
        target.set_condition(self.target, open=True, app_running=True)
        plan = self.applier.preview(self.link.id, add_when_idle=['codex'])
        self.assertEqual(plan.steps[0].action, 'add_after_release')
        release = target.app.release
        def now_replying(chat):
            release(chat)
            target.set_condition(chat, replying=True)
        target.app.release = now_replying
        result = self.applier.apply(plan)
        self.assertEqual(result.error, 'ChatReplying')
        self.assertEqual(target.reader.read(self.target), [])
        self.assertEqual(self.store.journal_entries(), [])

    def test_release_timeout_falls_back_to_pending_attach_without_write(self):
        target = self.adapters['codex']
        target.facts = CLAUDE_LIKE
        target.set_format(True, CLAUDE_LIKE.checked_versions[0])
        target.set_condition(self.target, open=True)
        target.app.release = lambda chat: None
        elapsed = [0.0]
        self.applier.elapsed = lambda: elapsed[0]
        self.applier.wait = lambda seconds: elapsed.__setitem__(0, elapsed[0] + seconds)
        result = self.applier.apply(self.applier.preview(self.link.id, ['codex']))
        self.assertTrue(result.applied)
        self.assertEqual(result.completed[0].reason, 'release_timeout')
        self.assertLessEqual(elapsed[0], 10.00001)
        self.assertEqual(target.reader.read(self.target), [])
        self.assertEqual(self.store.journal_entries(), [])
        self.assertTrue(all(t.states['codex'] == 'waiting' for t in self.store.turns(self.link.id)))
        self.assertEqual(self.store.history(self.link.id)[0].detail['reason'], 'release_timeout')

    def test_release_exception_falls_back_only_when_hooks_ready(self):
        target = self.adapters['codex']
        target.facts = CLAUDE_LIKE
        target.set_format(True, CLAUDE_LIKE.checked_versions[0])
        target.set_condition(self.target, open=True)
        target.app.release = lambda chat: (_ for _ in ()).throw(RuntimeError())
        plan = self.applier.preview(self.link.id, ['codex'])
        target.set_condition(self.target, hooks_ready=False)
        with self.assertRaises(ChatChanged): self.applier.apply(plan)
        target.set_condition(self.target, hooks_ready=True)
        result = self.applier.apply(plan)
        self.assertEqual(result.completed[0].reason, 'release_failed:RuntimeError')
        self.assertEqual(target.reader.read(self.target), [])

    def test_failing_second_step_keeps_first_and_stops_third(self):
        plan = self.applier.preview(self.link.id)
        first = plan.steps[0]
        steps = [replace(first, turn_ids=first.turn_ids[:1], turns=first.turns[:1]),
                 ApplyStep('claude', 'unsupported'),
                 replace(first, turn_ids=first.turn_ids[1:], turns=first.turns[1:])]
        result = self.applier.apply(self.applier.prepare(self.link.id, steps, self.link.chats))
        self.assertFalse(result.applied)
        self.assertEqual(len(result.completed), 1)
        self.assertEqual(len(self.adapters['codex'].reader.read(self.target)), 1)
        self.assertEqual([t.states['codex'] for t in self.store.turns(self.link.id)], ['shown','waiting','waiting'])

    def test_startup_recovers_pending_write_and_blocks_after_failed_recovery(self):
        entry = self.applier.journal.begin(self.link.id, 'codex', self.target, 'add')
        self.adapters['codex'].writer.add(self.target, turns())
        self.adapters['codex'].set_condition(self.target, open=True)
        restarted = Applier(self.store, self.adapters, self.clock)
        self.assertEqual(restarted.recovery[0]['state'], 'failed')
        with self.assertRaises(NotAvailable): restarted.apply(restarted.preview(self.link.id))
        self.adapters['codex'].set_condition(self.target, open=False)
        restarted = Applier(self.store, self.adapters, self.clock)
        self.assertEqual(self.store.journal_entry(entry)['state'], 'taken_back')
        self.assertEqual(self.adapters['codex'].reader.read(self.target), [])

    def test_local_id_collision_does_not_overwrite_existing_turn(self):
        target = self.adapters['codex']
        target.chats[self.target] = [turns()[0]]
        # This already-existing p1 is kept back locally, so no conflict is created.
        ids = self.store.record_turns(self.link.id, 'codex', target.reader.read(self.target))
        self.store.keep_back(self.link.id, ids[0], self.clock.now())
        result = self.applier.apply(self.applier.preview(self.link.id))
        self.assertTrue(result.applied)
        observed = target.reader.read(self.target)
        self.assertEqual(len(observed), 4)
        self.assertEqual(len({t.id for t in observed}), 4)
        self.applier.refresh(self.link.id)
        self.assertEqual(len(self.store.turns(self.link.id)), 4)

    def test_failed_rollback_is_explicit_blocks_apply_and_startup_retries(self):
        target = self.adapters['codex']
        add = target.writer.add
        def broken(chat, incoming):
            add(chat, incoming)
            target.set_condition(chat, open=True)
            raise RuntimeError()
        target.writer.add = broken
        result = self.applier.apply(self.applier.preview(self.link.id))
        self.assertEqual((result.error,result.rollback_error),('RuntimeError','ChatHeld'))
        self.assertIsNotNone(result.pending_entry)
        self.assertEqual(self.store.journal_entry(result.pending_entry)['state'],'failed')
        self.assertEqual(len(target.reader.read(self.target)),3)
        self.assertTrue(all(t.states['codex']=='waiting' for t in self.store.turns(self.link.id)))
        with self.assertRaises(NotAvailable): self.applier.apply(self.applier.preview(self.link.id))
        target.set_condition(self.target,open=False)
        restarted = Applier(self.store,self.adapters,self.clock)
        self.assertEqual(restarted.recovery[0]['state'],'taken_back')
        self.assertEqual(target.reader.read(self.target),[])

    def test_rewriting_existing_id_during_add_is_refused_and_rolled_back(self):
        target = self.adapters['codex']
        original_turn = Turn(Message('local',PROMPT,'local'))
        target.chats[self.target] = [original_turn]
        add = target.writer.add
        def rewrite(chat, incoming):
            result = add(chat,incoming)
            target.chats[chat][0] = replace(original_turn,prompt=replace(original_turn.prompt,id='rewritten'))
            return result
        target.writer.add = rewrite
        result = self.applier.apply(self.applier.preview(self.link.id))
        self.assertEqual(result.error,'ChatChanged')
        self.assertEqual(target.reader.read(self.target),[original_turn])

    def test_hook_acknowledgment_refuses_empty_duplicate_and_cross_link_ids(self):
        for ids in ([],[1,1],[999]):
            with self.assertRaises(NotAvailable):
                self.applier.record_attached(self.link.id,'codex',ids,'message')
        self.assertEqual(len(self.store.history(self.link.id)),1)

    def test_atomic_completion_refuses_wrong_journal_link_or_side(self):
        plan = self.applier.preview(self.link.id)
        step = plan.steps[0]
        entry = self.applier.journal.begin(self.link.id,'codex',self.target,'add')
        result = self.adapters['codex'].writer.add(self.target,step.turns)
        from dataclasses import asdict
        for link_id,side,kind in ((None,'codex','add'),(self.link.id,'claude','add'),(self.link.id,'codex','create')):
            with self.assertRaises(ValueError):
                self.store.complete_write(entry,asdict(result.receipt),self.clock.now(),link_id,
                                          side,step.turn_ids,'shown',kind,result.local_ids)
        self.assertEqual(self.store.journal_entry(entry)['state'],'begun')
        self.assertTrue(all(t.states['codex']=='waiting' for t in self.store.turns(self.link.id)))
        self.applier.journal.take_back(entry)

    def test_changed_delivered_content_is_unconfirmed_without_bouncing_into_origin(self):
        self.applier.apply(self.applier.preview(self.link.id))
        target = self.adapters['codex']
        first = target.chats[self.target][0]
        target.chats[self.target][0] = replace(first,messages=(Message('changed',REPLY,'different'),))
        fresh = self.applier.refresh(self.link.id)
        self.assertEqual(fresh['status'].side('codex').waiting,1)
        self.assertEqual(len(fresh['turns']),3)
        self.assertEqual(self.store.turns(self.link.id)[0].origin,'claude')

    def test_source_replying_latest_turn_is_refused_until_idle(self):
        self.adapters['claude'].set_condition(self.source,replying=True)
        with self.assertRaises(NotAvailable): self.applier.preview(self.link.id)
        self.adapters['claude'].set_condition(self.source,replying=False)
        self.assertTrue(self.applier.apply(self.applier.preview(self.link.id)).applied)

    def test_linked_create_moves_link_in_same_transaction_as_delivery(self):
        step = self.applier.preview(self.link.id).steps[0]
        create = replace(step,action='create',name='copy')
        result = self.applier.apply(self.applier.prepare(self.link.id,[create],self.link.chats))
        self.assertTrue(result.applied)
        self.assertEqual(self.store.get_link(self.link.id).chat('codex'),result.completed[0].chat_id)
        self.assertEqual(self.adapters['codex'].reader.read(self.target),[])
        self.assertTrue(all(t.states['codex']=='shown' for t in self.store.turns(self.link.id)))
        self.assertEqual(self.store.journal_entries()[0]['state'],'committed')

    def test_multiple_steps_on_same_side_use_updated_expected_snapshot(self):
        plan = self.applier.preview(self.link.id)
        full = plan.steps[0]
        parts = [replace(full,turn_ids=full.turn_ids[:1],turns=full.turns[:1]),
                 replace(full,turn_ids=full.turn_ids[1:],turns=full.turns[1:])]
        result = self.applier.apply(self.applier.prepare(self.link.id,parts,self.link.chats))
        self.assertTrue(result.applied)
        self.assertEqual(len(result.completed),2)
        self.assertEqual(len(self.adapters['codex'].reader.read(self.target)),3)

    def test_source_change_after_earlier_step_stops_later_step(self):
        plan = self.applier.preview(self.link.id)
        full = plan.steps[0]
        parts = [replace(full,turn_ids=full.turn_ids[:1],turns=full.turns[:1]),
                 replace(full,turn_ids=full.turn_ids[1:],turns=full.turns[1:])]
        complete = self.store.complete_write
        def change_after_commit(*args,**kwargs):
            event = complete(*args,**kwargs)
            source = self.adapters['claude']
            source.chats[self.source][-1] = replace(source.chats[self.source][-1],messages=())
            return event
        self.store.complete_write = change_after_commit
        result = self.applier.apply(self.applier.prepare(self.link.id,parts,self.link.chats))
        self.assertFalse(result.applied)
        self.assertEqual(result.error,'ChatChanged')
        self.assertEqual(len(result.completed),1)
        self.assertEqual(len(self.adapters['codex'].reader.read(self.target)),1)

    def test_unknown_format_after_partial_write_reports_pending_until_recovered(self):
        target = self.adapters['codex']
        add = target.writer.add
        def broken(chat,incoming):
            add(chat,incoming)
            target.set_format(False,'new')
            raise RuntimeError()
        target.writer.add = broken
        result = self.applier.apply(self.applier.preview(self.link.id))
        self.assertEqual(result.rollback_error,'UnknownFormat')
        self.assertIsNotNone(result.pending_entry)
        self.assertEqual(self.store.journal_entry(result.pending_entry)['state'],'failed')
        target.set_format(True,CODEX_LIKE.checked_versions[0])
        restarted = Applier(self.store,self.adapters,self.clock)
        self.assertEqual(restarted.recovery[0]['state'],'taken_back')
        self.assertEqual(target.reader.read(self.target),[])

    def test_preview_refuses_source_change_between_payload_and_fingerprint_reads(self):
        source = self.adapters['claude']
        read = source.reader.read
        calls = [0]
        def changing(chat):
            calls[0] += 1
            if calls[0] == 2:
                original = source.chats[chat][0]
                source.chats[chat][0] = replace(original,messages=(Message('r',REPLY,'new answer'),))
            return read(chat)
        source.reader.read = changing
        with self.assertRaises(ChatChanged):
            self.applier.preview(self.link.id)
        self.assertEqual(self.adapters['codex'].reader.read(self.target), [])
        self.assertEqual(self.store.journal_entries(), [])

    def test_later_local_message_after_bypass_requires_decision_before_resend(self):
        self.applier.apply(self.applier.preview(self.link.id))
        target = self.adapters['codex']
        target.chats[self.target].pop(0)
        target.chats[self.target].append(Turn(Message('later',PROMPT,'new local question')))
        fresh = self.applier.refresh(self.link.id)
        self.assertEqual(fresh['turns'][0].states['codex'],'waiting')
        self.assertTrue(fresh['status'].decision_needed)
        from baton.domain.errors import DecisionNeeded
        with self.assertRaises(DecisionNeeded):
            self.applier.apply(self.applier.preview(self.link.id))

    def test_existing_reply_identity_must_not_change_during_append(self):
        target = self.adapters['codex']
        existing = Turn(Message('local',PROMPT,'local'),(Message('original-reply',REPLY,'same reply'),))
        target.chats[self.target] = [existing]
        add = target.writer.add
        def rewrite(chat,incoming):
            result = add(chat,incoming)
            target.chats[chat][0] = replace(existing,messages=(replace(existing.messages[0],id='rewritten-reply'),))
            return result
        target.writer.add = rewrite
        result = self.applier.apply(self.applier.preview(self.link.id))
        self.assertEqual(result.error,'ChatChanged')
        self.assertEqual(target.reader.read(self.target),[existing])

    def test_writer_result_and_receipt_chat_identity_must_agree(self):
        target = self.adapters['codex']
        add = target.writer.add
        def misleading(chat,incoming):
            result = add(chat,incoming)
            return replace(result,receipt=replace(result.receipt,chat_id='wrong-chat'))
        target.writer.add = misleading
        result = self.applier.apply(self.applier.preview(self.link.id))
        self.assertEqual(result.error,'ChatChanged')
        self.assertEqual(target.reader.read(self.target),[])

    def test_added_local_identity_must_not_collide_with_existing_turn(self):
        target = self.adapters['codex']
        existing = Turn(Message('local',PROMPT,'local'))
        target.chats[self.target] = [existing]
        add = target.writer.add
        def colliding(chat,incoming):
            result = add(chat,incoming)
            written = target.chats[chat][-len(incoming)]
            target.chats[chat][-len(incoming)] = replace(written,prompt=replace(written.prompt,id='local'))
            return replace(result,local_ids=('local',*result.local_ids[1:]))
        target.writer.add = colliding
        result = self.applier.apply(self.applier.preview(self.link.id))
        self.assertEqual(result.error,'ChatChanged')
        self.assertEqual(target.reader.read(self.target),[existing])

    def test_refresh_follows_compaction_alias_even_when_old_chat_is_absent(self):
        target = self.adapters['codex']
        old = self.target
        new = target.build_chat([],name='compacted chat')
        target.chats.pop(old)
        target.refs.pop(old)
        target.conditions.pop(old)
        resolve = target.locator.resolve
        target.locator.resolve = lambda chat: resolve(new if chat == old else chat)
        self.assertFalse(target.state.condition(old).exists)
        with self.assertRaises(ChatChanged):
            self.applier.preview(self.link.id)
        self.assertEqual(self.store.get_link(self.link.id).chat('codex'),old)
        fresh = self.applier.refresh(self.link.id)
        self.assertEqual(fresh['missing'],())
        self.assertEqual(fresh['names']['codex'],'compacted chat')
        self.assertEqual(fresh['link'].chat('codex'),new)
        self.assertTrue(self.applier.apply(self.applier.preview(self.link.id)).applied)
        self.assertEqual(len(target.reader.read(new)),3)
        self.assertNotIn(old,target.chats)

    def test_snapshot_reads_and_checks_the_resolved_canonical_id(self):
        source = self.adapters['claude']
        old = self.source
        new = source.build_chat(turns(),name='new canonical chat')
        source.chats.pop(old)
        source.refs.pop(old)
        source.conditions.pop(old)
        source.set_condition(new,open=True)
        resolve = source.locator.resolve
        source.locator.resolve = lambda chat: resolve(new if chat == old else chat)
        snapshot = self.applier._snapshot('claude',old)
        self.assertEqual(snapshot['chat_id'],new)
        self.assertEqual(snapshot['ref']['id'],new)
        self.assertTrue(snapshot['condition']['exists'])
        self.assertTrue(snapshot['condition']['open'])
        self.assertEqual(len(snapshot['turns']),3)


    def test_pause_or_removal_during_first_write_stops_later_steps(self):
        for remove in (False, True):
            with self.subTest(remove=remove):
                if remove:
                    self.store.set_paused(self.link.id, False, self.clock.now())
                    self.adapters['codex'].chats[self.target].clear()
                    self.store.db.execute("update turn_states set state='waiting',local_id='' where side='codex'")
                    self.store.db.commit()
                prepared = self.applier.preview(self.link.id)
                step = prepared.steps[0]
                steps = [replace(step,turn_ids=(i,),turns=(t,)) for i,t in zip(step.turn_ids,step.turns)]
                prepared = self.applier.prepare(self.link.id, steps, self.link.chats)
                original = self.adapters['codex'].writer.add
                def add(chat, values):
                    result = original(chat, values)
                    if remove:
                        self.store.remove_link(self.link.id, self.clock.now())
                    else:
                        self.store.set_paused(self.link.id, True, self.clock.now())
                    return result
                self.adapters['codex'].writer.add = add
                result = self.applier.apply(prepared)
                self.adapters['codex'].writer.add = original
                self.assertFalse(result.applied)
                self.assertEqual(result.error, 'NotAvailable')
                self.assertEqual(len(result.completed), 1)
                self.assertEqual(len(self.adapters['codex'].reader.read(self.target)), 1)

    def test_removed_link_refuses_preview_and_hook_acknowledgement(self):
        ids = [t.id for t in self.store.turns(self.link.id)]
        self.store.remove_link(self.link.id, self.clock.now())
        with self.assertRaises(NotAvailable): self.applier.preview(self.link.id)
        with self.assertRaises(NotAvailable):
            self.applier.record_attached(self.link.id, 'codex', ids, 'message')
        self.assertFalse(any(e.kind == 'attached' for e in self.store.history(self.link.id)))
