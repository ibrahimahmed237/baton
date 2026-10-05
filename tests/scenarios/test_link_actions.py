"""T0–T4: confirmed link changes, pause and copy visibility."""
from copy import deepcopy
from dataclasses import replace
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from baton.domain.errors import AlreadyLinked, NotAvailable
from baton.domain.model import Message, Turn, PROMPT
from baton.services.applier import Applier
from tests.unit import test_linker as fixtures
from tests.unit.test_linker import FACTS
from tests.adapters.suite import turns


class LinkActionScenarios(unittest.TestCase):
    setUp = fixtures.LinkerTests.setUp
    tearDown = fixtures.LinkerTests.tearDown

    def test_T0_already_linked_names_existing_partner_and_confirmed_change_keeps_old_chat(self):
        for target in FACTS:
            source = 'codex' if target=='claude' else 'claude'
            with self.subTest(target=target):
                source_chat = self.adapters[source].build_chat(turns())
                first = self.linker.apply(self.linker.plan_link(source,source_chat,target))
                old = deepcopy(self.adapters[target].reader.read(first.chat_id))
                replacement = self.adapters[target].build_chat([])
                with self.assertRaises(AlreadyLinked) as refusal:
                    self.linker.plan_link(source,source_chat,target,replacement)
                self.assertEqual(refusal.exception.link.id,first.link_id)
                note = self.linker.already_linked_note(refusal.exception)
                self.assertEqual(note['values']['other_name'],self.adapters[target].locator.name(first.chat_id))
                self.assertIn(note['values']['other_name'],note['text'])
                self.assertEqual([button['id'] for button in note['buttons']],['relink','cancel'])
                changed = self.linker.apply(self.linker.plan_relink(first.link_id,target,replacement))
                self.assertTrue(changed.applied,changed)
                self.assertEqual(self.store.get_link(changed.link_id).chat(source),source_chat)
                self.assertEqual(self.store.get_link(changed.link_id).chat(target),replacement)
                self.assertIsNone(self.store.link_for(target,first.chat_id))
                self.assertEqual(self.adapters[target].reader.read(first.chat_id),old)

    def test_T1_paused_link_counts_new_finished_reply_without_delivering_or_attaching(self):
        for target in FACTS:
            source = 'codex' if target=='claude' else 'claude'
            with self.subTest(target=target):
                source_chat = self.adapters[source].build_chat(turns()[:2])
                target_chat = self.adapters[target].build_chat([])
                linked = self.linker.apply(self.linker.plan_link(source,source_chat,target,target_chat))
                self.store.set_paused(linked.link_id,True,self.clock.now())
                self.adapters[source].chats[source_chat].append(turns()[2])
                applier = Applier(self.store,self.adapters,self.clock)
                fresh = applier.refresh(linked.link_id)
                self.assertEqual((fresh['status'].side(target).waiting,fresh['status'].side(target).waiting_reason),(3,'paused'))
                plan = applier.preview(linked.link_id)
                self.assertEqual(plan.steps[0].action,'hold')
                self.assertTrue(applier.apply(plan).applied)
                with self.assertRaises(NotAvailable):
                    applier.record_attached(linked.link_id,target,[t.id for t in fresh['turns']],'message')
                self.assertEqual(self.adapters[target].reader.read(target_chat),[])

    def test_T2_remove_link_leaves_both_chats_exactly_unchanged(self):
        for target in FACTS:
            source = 'codex' if target=='claude' else 'claude'
            with self.subTest(target=target):
                source_chat = self.adapters[source].build_chat(turns())
                linked = self.linker.apply(self.linker.plan_link(source,source_chat,target))
                before = {source:deepcopy(self.adapters[source].reader.read(source_chat)),
                          target:deepcopy(self.adapters[target].reader.read(linked.chat_id))}
                with ExitStack() as spies:
                    for side in (source,target):
                        for method in ('prepare','create','add','place','cut','rename','take_back'):
                            spies.enter_context(patch.object(self.adapters[side].writer,method,
                                                             side_effect=AssertionError('unexpected_write')))
                    self.assertTrue(self.linker.apply(self.linker.plan_unlink(linked.link_id)).applied)
                self.assertIsNone(self.store.link_for(source,source_chat))
                self.assertIsNone(self.store.link_for(target,linked.chat_id))
                self.assertEqual(self.adapters[source].reader.read(source_chat),before[source])
                self.assertEqual(self.adapters[target].reader.read(linked.chat_id),before[target])

    def test_T3_unlinked_copy_has_every_turn_and_immediate_visibility(self):
        # AT_ONCE creation applies to both immediate-visibility tools.
        for target in ('codex','opencode'):
            with self.subTest(target=target):
                values = [replace(turns()[0],prompt=replace(turns()[0].prompt,id=f'p{i}')) for i in range(16)]
                self.adapters['claude'].chats[self.source] = values
                plan = self.linker.plan_copy('claude',self.source,target)
                self.assertEqual(plan.needs,())
                result = self.linker.apply(plan)
                self.assertTrue(result.applied,result)
                self.assertEqual(len(self.adapters[target].reader.read(result.chat_id)),16)
                self.assertEqual(self.store.links(),[])
                self.assertEqual(self.linker.copy_status(target,result.chat_id)['needs'],())

    def test_T4_unlinked_deferred_copy_remains_marked_until_later_app_start(self):
        for target in ('claude','cursor'):
            with self.subTest(target=target):
                source = self.adapters['codex'].build_chat(turns())
                plan = self.linker.plan_copy('codex',source,target)
                self.assertIn('relaunch_to_see',plan.needs)
                result = self.linker.apply(plan)
                self.assertTrue(result.applied,result)
                self.assertEqual(len(self.adapters[target].reader.read(result.chat_id)),3)
                self.assertEqual(self.store.links(),[])
                self.assertEqual(self.linker.copy_status(target,result.chat_id)['needs'],('relaunch_to_see',))
                self.adapters[target].set_condition(result.chat_id,app_started_at='2026-10-05T00:00:01Z')
                self.assertEqual(self.linker.copy_status(target,result.chat_id)['needs'],())
