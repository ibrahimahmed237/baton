"""Brief consent survives engine restart through the normal service wiring."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from baton.adapters.fake import FakeAdapter, FakeBackgroundRunner
from baton.adapters.fake.facts import CODEX_LIKE, CLAUDE_LIKE
from baton.cli.wiring import build
from baton.domain.errors import ChatChanged
from baton.domain.link import SUMMARIZED
from baton.domain.model import Message, Turn, PROMPT, REPLY
from baton.ports.clock import FixedClock


class BriefWiringTests(unittest.TestCase):
    def test_initial_brief_has_no_link_until_creation_and_restarts_without_regeneration(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            clock = FixedClock('2026-10-09T12:00:00Z')
            source = FakeAdapter(CLAUDE_LIKE, 'claude')
            target = FakeAdapter(CODEX_LIKE, 'codex')
            values = [Turn(Message(f'p{i}', PROMPT, f'Orchard request {i}', clock.now()),
                           (Message(f'r{i}', REPLY, f'Orchard answer {i}', clock.now()),))
                      for i in range(4)]
            chat = source.build_chat(values, 'Baton test (safe to delete)', str(root))
            target.runner = FakeBackgroundRunner('The orchard plan is ready for review.')
            adapters = {'claude': source, 'codex': target}
            engine = build(root, adapters=adapters, clock=clock)
            try:
                with engine.command_lock():
                    preview = engine.linker.plan_link('claude', chat, 'codex', mode='brief')
                    self.assertEqual(preview.stage, 'generate')
                    self.assertEqual(target.runner.calls, [])
                    self.assertEqual(engine.store.links(), [])
                    creation = engine.linker.apply(preview)
                    self.assertEqual(creation.stage, 'create')
                    self.assertNotEqual(creation.plan_id, preview.plan_id)
                    self.assertEqual(len(target.runner.calls), 1)
                    self.assertEqual(engine.store.links(), [])
                    original_text = creation.text
            finally:
                engine.close()
            restarted = build(root, adapters=adapters, clock=clock)
            try:
                with restarted.command_lock():
                    result = restarted.briefs.confirm(creation.plan_id)
                    self.assertTrue(result.applied, result)
                    self.assertEqual(len(target.runner.calls), 1)
                    self.assertEqual(target.reader.read(result.chat_id)[0].prompt.text, original_text)
                    self.assertEqual(source.reader.read(chat), values)
                    link = restarted.store.get_link(result.link_id)
                    self.assertEqual(link.mode, 'brief')
                    self.assertEqual(link.chat('codex'), result.chat_id)
                    rows = restarted.store.turns(link.id)
                    self.assertEqual(rows[0].states['codex'], SUMMARIZED)
                    self.assertEqual(len(restarted.store.summary_coverage(link.id, 'codex')['turn_ids']), 4)
                    with self.assertRaises(ChatChanged):
                        restarted.briefs.confirm(creation.plan_id)
                    self.assertEqual(len(target.runner.calls), 1)
            finally:
                restarted.close()
