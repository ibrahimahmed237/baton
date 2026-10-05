"""X1/X2: any-tool partner limits and fact-driven copy visibility."""
import unittest

from baton.domain.errors import AlreadyLinked
from tests.unit import test_linker as fixtures
from tests.adapters.suite import turns


class MoreToolsScenarios(unittest.TestCase):
    setUp = fixtures.LinkerTests.setUp
    tearDown = fixtures.LinkerTests.tearDown

    def test_X1_third_tool_cannot_create_second_link_for_same_chat(self):
        first = self.linker.apply(self.linker.plan_link('claude',self.source,'codex'))
        target = self.adapters['opencode'].build_chat([])
        with self.assertRaises(AlreadyLinked) as refusal:
            self.linker.plan_link('claude',self.source,'opencode',target)
        self.assertEqual(refusal.exception.link.id,first.link_id)
        note = self.linker.already_linked_note(refusal.exception)
        self.assertEqual(note['values']['other_name'],self.adapters['codex'].locator.name(first.chat_id))
        self.assertIn(note['values']['other_name'],note['text'])
        self.assertEqual([button['id'] for button in note['buttons']],['relink','cancel'])
        self.assertEqual(self.store.get_link(first.link_id).chat('codex'),first.chat_id)
        self.assertEqual(len(self.store.links()),1)
        self.assertEqual(self.adapters['opencode'].reader.read(target),[])

    def test_X2_copy_to_other_tool_uses_its_known_visibility_facts(self):
        source = self.adapters['codex'].build_chat(turns())
        self.adapters['opencode'].app_running = True
        plan = self.linker.plan_copy('codex',source,'opencode')
        self.assertEqual(plan.needs,())
        result = self.linker.apply(plan)
        self.assertTrue(result.applied,result)
        self.assertEqual(len(self.adapters['opencode'].reader.read(result.chat_id)),3)
        self.assertEqual(self.store.links(),[])
        self.assertEqual(self.linker.copy_status('opencode',result.chat_id)['needs'],())
