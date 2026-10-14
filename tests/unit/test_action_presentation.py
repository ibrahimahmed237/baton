"""The merge service supplies explanatory notes before any command serialization."""
import unittest
from baton.domain.errors import OrderNotAllowed
from tests.contract.test_fixtures import world_for
from tests.contract.generate_fixtures import original


class ActionPresentationTests(unittest.TestCase):
    def test_service_show_has_per_side_outcomes_help_same_file_and_brief_notes(self):
        with world_for('merge-service-presentation') as w:
            w.pair(shared=1)
            w.seed('claude', [original(2), original(4)])
            w.seed('codex', [original(3)])
            w.adapters['claude'].changed_files['p4'] = ['orchard.py']
            w.adapters['codex'].changed_files['p3'] = ['orchard.py']
            value = w.engine.merger.show(3, brief_threshold_tokens=1)
            ids = [n[0] for n in value['notes']]
            self.assertEqual(ids.count('merge.merged_copy'), 2)
            self.assertIn('merge.header', ids)
            self.assertIn('merge.order_help', ids)
            self.assertIn('merge.same_file', ids)
            self.assertIn('merge.large_copy', ids)
            self.assertIn('merge.copy_relaunch', ids)
            self.assertIn('merge.copy_visible', ids)
            dont = w.engine.merger.show(3, preset='dont_reorder')
            self.assertTrue(all(v == 'keeps_chat' for v in dont['outcome'].values()))
            self.assertIn('merge.dont_reorder', [n[0] for n in dont['notes']])
            with self.assertRaises(OrderNotAllowed): w.engine.merger.show(3, preset='future_unknown')
            with self.assertRaises(OrderNotAllowed): w.engine.merger.plan(3, preset='future_unknown')
            w.condition('claude', open=True, app_running=True)
            value = w.engine.merger.plan(3, preset='claude_first')
            self.assertIn('status.next_message', [n[0] for n in value.notes])
            self.assertIn('status.chat_held', [n[0] for n in value.notes])
