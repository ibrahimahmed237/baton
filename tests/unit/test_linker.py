"""Confirmed link metadata, ordered identity alignment and creation rollback."""
from dataclasses import asdict, replace
from copy import deepcopy
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from baton.adapters.fake import FakeAdapter
from baton.adapters.fake.facts import CLAUDE_LIKE, CODEX_LIKE, OPENCODE_LIKE, CURSOR_LIKE
from baton.domain.capabilities import Visibility, WriteWindow
from baton.domain.errors import ChatChanged, NotAvailable, AlreadyLinked
from baton.domain.model import Message, Turn, PROMPT, REPLY
from baton.ledger.sqlite_store import Ledger
from baton.ports.clock import FixedClock
from baton.services.applier import Applier
from baton.services.linker import Linker
from tests.adapters.suite import turns

FACTS = {'claude':CLAUDE_LIKE,'codex':CODEX_LIKE,'opencode':OPENCODE_LIKE,'cursor':CURSOR_LIKE}


class LinkerTests(unittest.TestCase):
    def setUp(self):
        self.store = Ledger(':memory:')
        self.clock = FixedClock('2026-10-05T00:00:00Z')
        self.adapters = {side:FakeAdapter(facts,side) for side,facts in FACTS.items()}
        self.source = self.adapters['claude'].build_chat(turns(),name='source',folder='/project')
        self.linker = Linker(self.store,self.adapters,self.clock)

    def tearDown(self):
        self.store.close()

    def test_all_twelve_directed_pairs_create_and_link_public_history(self):
        for source in FACTS:
            for target in FACTS:
                if source == target: continue
                with self.subTest(source=source,target=target):
                    chat = self.adapters[source].build_chat(turns())
                    plan = self.linker.plan_link(source,chat,target)
                    result = self.linker.apply(plan,plan.plan_id)
                    self.assertTrue(result.applied,result)
                    fresh = Applier(self.store,self.adapters,self.clock).refresh(result.link_id)
                    self.assertEqual(len(fresh['turns']),3)
                    self.assertEqual(fresh['status'].side(target).agent_has,3)
                    expected_shows = 3 if FACTS[target].new_chat_visible == Visibility.AT_ONCE else 0
                    self.assertEqual(fresh['status'].side(target).chat_shows,expected_shows)
                    self.assertEqual(len(self.adapters[target].reader.read(result.chat_id)),3)

    def test_existing_alignment_counts_duplicate_occurrences_only_once(self):
        source = self.adapters['claude']
        duplicated = [turns()[0],replace(turns()[0],prompt=replace(turns()[0].prompt,id='repeat')),turns()[1]]
        source.chats[self.source] = duplicated
        target = self.adapters['codex'].build_chat([replace(turns()[0],prompt=replace(turns()[0].prompt,id='other')),turns()[1]])
        before = deepcopy(self.adapters['codex'].reader.read(target))
        result = self.linker.apply(self.linker.plan_link('claude',self.source,'codex',target))
        rows = self.store.turns(result.link_id)
        self.assertEqual(len(rows),3)
        self.assertEqual(sum(t.states['codex']=='shown' for t in rows),2)
        self.assertEqual(sum(t.states['codex']=='waiting' for t in rows),1)
        self.assertEqual(self.adapters['codex'].reader.read(target),before)

    def test_reordered_histories_do_not_claim_every_turn_shared(self):
        self.adapters['claude'].chats[self.source] = turns()[:2]
        target = self.adapters['codex'].build_chat(list(reversed(turns()[:2])))
        result = self.linker.apply(self.linker.plan_link('claude',self.source,'codex',target))
        rows = self.store.turns(result.link_id)
        self.assertEqual(len(rows),3)
        shared = [t for t in rows if t.states['codex']=='shown']
        self.assertEqual(len(shared),1)
        source_order = [t.origin_id if t.origin=='claude' else self.store.local_ids(result.link_id,'claude').get(t.id) for t in rows if t.states['claude']!='waiting']
        target_ids = self.store.local_ids(result.link_id,'codex')
        target_order = [target_ids[t.id] for t in rows if t.states['codex']!='waiting']
        self.assertEqual(source_order,[t.id for t in turns()[:2]])
        self.assertEqual(target_order,[t.id for t in reversed(turns()[:2])])
        self.assertTrue(Applier(self.store,self.adapters,self.clock).refresh(result.link_id)['status'].decision_needed)

    def test_brief_and_attached_history_without_existing_chat_are_unavailable(self):
        for mode in ('brief','attached_history'):
            with self.assertRaises(NotAvailable): self.linker.plan_link('claude',self.source,'codex',mode=mode)
        self.assertEqual(self.store.links(),[])
        self.assertEqual(self.store.journal_entries(),[])

    def test_unknown_format_and_running_app_closed_target_never_write(self):
        for target in ('codex','cursor'):
            adapter = self.adapters[target]
            adapter.set_format(False,'unknown')
            result = self.linker.apply(self.linker.plan_copy('claude',self.source,target))
            self.assertEqual(result.error,'UnknownFormat')
            self.assertEqual(adapter.locator.chats(),[])
        self.adapters['cursor'].set_format(True,'18')
        self.adapters['cursor'].app_running = True
        result = self.linker.apply(self.linker.plan_copy('claude',self.source,'cursor'))
        self.assertEqual(result.error,'AppMustBeClosed')
        self.assertEqual(self.store.journal_entries(),[])

    def test_source_replying_refuses_incomplete_copy(self):
        self.adapters['claude'].set_condition(self.source,replying=True)
        with self.assertRaises(NotAvailable): self.linker.plan_copy('claude',self.source,'codex')

    def test_confirmation_refuses_full_reply_name_format_and_record_changes(self):
        for change in ('reply','name','format','records','token'):
            with self.subTest(change=change):
                self.setUp_fresh_source()
                plan = self.linker.plan_copy('claude',self.source,'codex')
                if change=='reply':
                    self.adapters['claude'].chats[self.source][0] = replace(turns()[0],messages=(Message('r',REPLY,'changed'),))
                if change=='name': self.adapters['claude'].writer.rename(self.source,'renamed')
                if change=='format': self.adapters['codex'].set_format(False,'new')
                if change=='records':
                    self.store.link({'opencode':self.adapters['opencode'].build_chat([]),'cursor':self.adapters['cursor'].build_chat([])},'full_copy')
                with self.assertRaises(ChatChanged): self.linker.apply(plan,'wrong' if change=='token' else plan.plan_id)
                self.assertEqual(self.adapters['codex'].locator.chats(),[])

    def setUp_fresh_source(self):
        self.store.close()
        self.setUp()

    def test_readback_failure_rolls_back_created_chat_and_link(self):
        adapter = self.adapters['codex']
        create = adapter.writer.create
        def bad(*args):
            result = create(*args)
            adapter.chats[result.chat_id][0] = replace(turns()[0],messages=())
            return result
        adapter.writer.create = bad
        result = self.linker.apply(self.linker.plan_link('claude',self.source,'codex'))
        self.assertEqual(result.error,'ChatChanged')
        self.assertEqual(adapter.locator.chats(),[])
        self.assertEqual(self.store.links(),[])
        self.assertEqual(self.store.journal_entries()[0]['state'],'taken_back')

    def test_metadata_failure_rolls_back_link_and_created_chat_atomically(self):
        self.store.db.execute("create trigger fail_link before insert on turn_states begin select raise(abort,'fail'); end")
        result = self.linker.apply(self.linker.plan_link('claude',self.source,'codex'))
        self.assertFalse(result.applied)
        self.assertEqual(self.store.links(),[])
        self.assertEqual(self.adapters['codex'].locator.chats(),[])
        self.assertEqual(self.store.journal_entries()[0]['state'],'taken_back')

    def test_relink_metadata_failure_keeps_old_link_and_chats(self):
        created = self.linker.apply(self.linker.plan_link('claude',self.source,'codex'))
        before = self.store.get_link(created.link_id)
        old_chat = deepcopy(self.adapters['codex'].reader.read(created.chat_id))
        target = self.adapters['codex'].build_chat([])
        self.store.db.execute("create trigger fail_link before insert on turn_states begin select raise(abort,'fail'); end")
        result = self.linker.apply(self.linker.plan_relink(created.link_id,'codex',target))
        self.assertFalse(result.applied)
        self.assertEqual(self.store.get_link(created.link_id),before)
        self.assertEqual(self.adapters['codex'].reader.read(created.chat_id),old_chat)
        self.assertEqual(self.adapters['codex'].reader.read(target),[])

    def test_copy_visibility_is_durable_monotonic_and_date_aware(self):
        result = self.linker.apply(self.linker.plan_copy('claude',self.source,'cursor'))
        target = self.adapters['cursor']
        for value in ('', 'bad', '2026-10-05T00:00:01', '2026-10-05T00:00:00Z', '2026-10-04T23:59:59Z'):
            target.set_condition(result.chat_id,app_started_at=value)
            self.assertEqual(self.linker.copy_status('cursor',result.chat_id)['needs'],('relaunch_to_see',))
        target.set_condition(result.chat_id,app_started_at='2026-10-05T00:00:01Z')
        self.assertTrue(self.linker.copy_status('cursor',result.chat_id)['shown'])
        for value in ('','2026-10-04T00:00:00Z'):
            target.set_condition(result.chat_id,app_started_at=value)
            restarted = Linker(self.store,self.adapters,self.clock)
            self.assertEqual(restarted.copy_status('cursor',result.chat_id)['needs'],())

    def test_full_copy_reconstructs_attached_history_preserves_turn_ids_and_future_delivery(self):
        target = self.adapters['codex'].build_chat([])
        linked = self.linker.apply(self.linker.plan_link('claude',self.source,'codex',target,'attached_history'))
        applier = Applier(self.store,self.adapters,self.clock)
        ids = [t.id for t in self.store.turns(linked.link_id)]
        applier.record_attached(linked.link_id,'codex',ids,'first-message')
        local = Turn(Message('local',PROMPT,'local question'),(Message('r',REPLY,'local answer'),))
        self.adapters['codex'].chats[target].append(local)
        applier.refresh(linked.link_id)
        recorded = self.store.turns(linked.link_id)
        self.store.set_pinned(linked.link_id,recorded[0].id,True)
        before_target = deepcopy(self.adapters['codex'].reader.read(target))
        result = self.linker.apply(self.linker.plan_full_copy(linked.link_id,'codex'))
        self.assertTrue(result.applied,result)
        self.assertEqual(result.link_id,linked.link_id)
        self.assertEqual(self.adapters['codex'].reader.read(target),before_target)
        fresh = applier.refresh(linked.link_id)
        self.assertEqual(len(fresh['turns']),4)
        self.assertEqual([t.id for t in fresh['turns']],[t.id for t in recorded])
        self.assertTrue(fresh['turns'][0].pinned)
        self.assertEqual(fresh['status'].side('codex').chat_shows,4)
        self.assertEqual(fresh['status'].side('claude').waiting,1)
        self.assertTrue(applier.apply(applier.preview(linked.link_id)).applied)
        self.assertEqual(len(applier.refresh(linked.link_id)['turns']),4)
        newer = Turn(Message('newer',PROMPT,'later on twin'))
        self.adapters['codex'].chats[result.chat_id].append(newer)
        applier.refresh(linked.link_id)
        self.assertTrue(applier.apply(applier.preview(linked.link_id)).applied)
        self.assertEqual(len(applier.refresh(linked.link_id)['turns']),5)

    def test_suggestions_use_content_skip_linked_and_preserve_reordered_match_count(self):
        target = self.adapters['codex'].build_chat(list(reversed(turns())))
        candidates = self.linker.suggestions()
        self.assertEqual(len(candidates),1)
        self.assertEqual(candidates[0]['matched_turns'],1)
        self.linker.apply(self.linker.plan_link('claude',self.source,'codex',target))
        self.assertEqual(self.linker.suggestions(),[])

    def test_pending_create_recovery_leaves_no_link_to_deleted_chat(self):
        entry = self.linker.journal.begin(None,'codex',None,'create')
        result = self.adapters['codex'].writer.create(turns(),'uncommitted','')
        restarted = Linker(self.store,self.adapters,self.clock)
        self.assertEqual(restarted.recovery[0]['id'],entry)
        self.assertEqual(self.adapters['codex'].locator.chats(),[])
        self.assertEqual(self.store.links(),[])

    def test_plain_copy_from_linked_attached_side_has_hidden_history_and_keeps_link(self):
        target = self.adapters['codex'].build_chat([])
        linked = self.linker.apply(self.linker.plan_link('claude',self.source,'codex',target,'attached_history'))
        applier = Applier(self.store,self.adapters,self.clock)
        applier.record_attached(linked.link_id,'codex',[t.id for t in self.store.turns(linked.link_id)],'first')
        local = Turn(Message('local',PROMPT,'local question'))
        self.adapters['codex'].chats[target].append(local)
        applier.refresh(linked.link_id)
        old_link = self.store.get_link(linked.link_id)
        for destination in ('claude','opencode'):
            plan = self.linker.plan_copy('codex',target,destination)
            self.assertEqual(set(plan.observations),{'claude','codex',destination})
            self.assertEqual(len(plan.turns),4)
            copied = self.linker.apply(plan)
            self.assertTrue(copied.applied,copied)
            self.assertEqual(len(self.adapters[destination].reader.read(copied.chat_id)),4)
            self.assertEqual(self.store.get_link(linked.link_id),old_link)
            self.assertEqual(self.adapters['codex'].reader.read(target),[local])
        stale = self.linker.plan_copy('codex',target,'opencode')
        self.adapters['claude'].chats[self.source][0] = replace(turns()[0],messages=())
        with self.assertRaises(ChatChanged): self.linker.apply(stale)

    def test_copy_visibility_survives_receipt_pruning_and_new_creation(self):
        first = self.linker.apply(self.linker.plan_copy('claude',self.source,'cursor'))
        self.clock.value = '2026-11-06T00:00:00Z'
        self.assertEqual(self.linker.journal.prune(),1)
        self.assertEqual(Linker(self.store,self.adapters,self.clock).copy_status('cursor',first.chat_id)['needs'],('relaunch_to_see',))
        self.adapters['cursor'].set_condition(first.chat_id,app_started_at='2026-11-06T00:00:01Z')
        self.assertTrue(self.linker.copy_status('cursor',first.chat_id)['shown'])
        self.linker.journal.prune()
        self.store.db.execute('delete from journal')
        self.store.db.commit()
        self.adapters['cursor'].set_condition(first.chat_id,app_started_at='')
        restarted = Linker(self.store,self.adapters,self.clock)
        self.assertTrue(restarted.copy_status('cursor',first.chat_id)['shown'])
        second = restarted.apply(restarted.plan_copy('claude',self.source,'cursor'))
        self.assertTrue(second.applied,second)
        self.assertEqual(restarted.copy_status('cursor',second.chat_id)['needs'],('relaunch_to_see',))

    def test_linked_copy_refuses_unrecorded_native_turn_until_refresh(self):
        linked = self.linker.apply(self.linker.plan_link('claude',self.source,'codex'))
        native = Turn(Message('new-native',PROMPT,'completed after refresh'))
        self.adapters['codex'].chats[linked.chat_id].append(native)
        with self.assertRaises(ChatChanged):
            self.linker.plan_copy('codex',linked.chat_id,'opencode')
        with self.assertRaises(ChatChanged):
            self.linker.plan_full_copy(linked.link_id,'codex')
        Applier(self.store,self.adapters,self.clock).refresh(linked.link_id)
        self.assertEqual(len(self.linker.plan_copy('codex',linked.chat_id,'opencode').turns),4)
        self.assertEqual(len(self.linker.plan_full_copy(linked.link_id,'codex').turns),4)

    def test_full_copy_transaction_failure_preserves_link_turns_and_old_chat(self):
        linked = self.linker.apply(self.linker.plan_link('claude',self.source,'codex'))
        plan = self.linker.plan_full_copy(linked.link_id,'codex')
        before_link = self.store.get_link(linked.link_id)
        before_turns = self.store.turns(linked.link_id)
        before_chats = deepcopy(self.adapters['codex'].chats)
        self.store.db.execute("create trigger fail_copy before update on turn_states begin select raise(abort,'fail'); end")
        result = self.linker.apply(plan)
        self.assertFalse(result.applied)
        self.assertEqual(self.store.get_link(linked.link_id),before_link)
        self.assertEqual(self.store.turns(linked.link_id),before_turns)
        self.assertEqual(self.adapters['codex'].chats,before_chats)

    def test_journal_commit_failure_rolls_back_new_link_metadata_and_chat(self):
        self.store.db.execute("create trigger fail_journal before update on journal when new.state='committed' begin select raise(abort,'fail'); end")
        result = self.linker.apply(self.linker.plan_link('claude',self.source,'codex'))
        self.assertFalse(result.applied)
        self.assertEqual(self.store.links(),[])
        self.assertEqual(self.adapters['codex'].locator.chats(),[])
        self.assertEqual(self.store.journal_entries()[0]['state'],'taken_back')
        self.assertEqual(self.store.db.execute('select count(*) from created_copies').fetchone()[0],0)

    def test_source_changed_during_creation_rolls_back_before_link_commit(self):
        adapter = self.adapters['codex']
        create = adapter.writer.create
        def source_changed(*args):
            result = create(*args)
            self.adapters['claude'].chats[self.source][0] = replace(turns()[0],messages=())
            return result
        adapter.writer.create = source_changed
        result = self.linker.apply(self.linker.plan_link('claude',self.source,'codex'))
        self.assertEqual(result.error,'ChatChanged')
        self.assertEqual(adapter.locator.chats(),[])
        self.assertEqual(self.store.links(),[])
        self.assertEqual(self.store.journal_entries()[0]['state'],'taken_back')

    def test_canonical_copy_refuses_keep_or_skip_change_during_payload_record_read(self):
        for action in ('keep','skip','order'):
            with self.subTest(action=action):
                self.setUp_fresh_source()
                target = self.adapters['codex'].build_chat([])
                linked = self.linker.apply(self.linker.plan_link('claude',self.source,'codex',target,'attached_history'))
                read = self.store.turns
                calls = [0]
                def changing(link_id):
                    values = read(link_id)
                    calls[0] += 1
                    if calls[0] == 2:
                        if action=='keep': self.store.keep_back(link_id,values[0].id,self.clock.now())
                        elif action=='skip': self.store.skip(link_id,values[0].id,'codex',self.clock.now())
                        else: self.store.set_order(link_id,[t.id for t in reversed(values)])
                    return values
                self.store.turns = changing
                with self.assertRaises(ChatChanged):
                    self.linker.plan_copy('codex',target,'opencode')
                self.store.turns = read
                payload = self.linker.plan_copy('codex',target,'opencode').turns
                self.assertEqual(len(payload),3 if action=='order' else 2)
                if action=='order':
                    self.assertEqual(payload[0].prompt.text,turns()[-1].prompt.text)
                self.assertEqual(self.adapters['opencode'].locator.chats(),[])

    def test_missing_chat_unlink_changes_only_metadata_and_never_calls_writer(self):
        linked = self.linker.apply(self.linker.plan_link('claude',self.source,'codex'))
        target = self.adapters['codex']
        target.chats.pop(linked.chat_id)
        target.refs.pop(linked.chat_id)
        target.conditions.pop(linked.chat_id)
        with ExitStack() as spies:
            for adapter in self.adapters.values():
                for method in ('prepare','create','add','place','cut','rename','take_back'):
                    spies.enter_context(patch.object(adapter.writer,method,side_effect=AssertionError('unexpected_write')))
            plan = self.linker.plan_unlink(linked.link_id)
            self.assertEqual(plan.observations['codex']['missing_chat_id'],linked.chat_id)
            self.assertTrue(self.linker.apply(plan).applied)
        self.assertEqual(self.store.links(),[])
        self.assertEqual(self.adapters['claude'].reader.read(self.source),turns())

    def test_missing_chat_reappearance_refuses_old_unlink_preview(self):
        linked = self.linker.apply(self.linker.plan_link('claude',self.source,'codex'))
        target = self.adapters['codex']
        target.set_condition(linked.chat_id,exists=False)
        plan = self.linker.plan_unlink(linked.link_id)
        target.set_condition(linked.chat_id,exists=True)
        with self.assertRaises(ChatChanged): self.linker.apply(plan)
        self.assertIsNotNone(self.store.link_for('codex',linked.chat_id))
        self.assertTrue(self.linker.apply(self.linker.plan_unlink(linked.link_id)).applied)

    def test_link_and_copy_still_refuse_missing_source_chat(self):
        self.adapters['claude'].set_condition(self.source,exists=False)
        with self.assertRaises(NotAvailable): self.linker.plan_copy('claude',self.source,'codex')
        with self.assertRaises(NotAvailable): self.linker.plan_link('claude',self.source,'codex')
        self.assertEqual(self.store.links(),[])
        self.assertEqual(self.store.journal_entries(),[])

    def test_unlink_does_not_read_chat_files_even_when_registry_refs_remain(self):
        linked = self.linker.apply(self.linker.plan_link('claude',self.source,'codex'))
        before = deepcopy({side:adapter.chats for side,adapter in self.adapters.items()})
        with ExitStack() as spies:
            for adapter in self.adapters.values():
                spies.enter_context(patch.object(adapter.reader,'read',side_effect=OSError('unparseable_file')))
                for method in ('prepare','create','add','place','cut','rename','take_back'):
                    spies.enter_context(patch.object(adapter.writer,method,side_effect=AssertionError('unexpected_write')))
            plan = self.linker.plan_unlink(linked.link_id)
            self.assertTrue(all(o.get('metadata_only') and 'turns' not in o for o in plan.observations.values()))
            self.assertTrue(self.linker.apply(plan).applied)
        self.assertEqual({side:adapter.chats for side,adapter in self.adapters.items()},before)
        self.assertEqual(self.store.links(),[])
