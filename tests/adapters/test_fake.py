"""Run the shared adapter contract against every fake fact set."""
import unittest
from dataclasses import replace

from baton.adapters.fake import FakeAdapter, FakeBackgroundRunner
from baton.adapters.fake.facts import CLAUDE_LIKE, CODEX_LIKE, OPENCODE_LIKE, CURSOR_LIKE
from baton.domain.errors import ChatChanged, ChatReplying, NotAvailable, UnknownFormat
from baton.ports.tool import Usage
from .suite import AdapterSuite, turns


class FakeFixtures:
    """Provide fixture controls without exposing them through the ports."""
    def make_adapter(self):
        return FakeAdapter(self.facts)

    def build_chat(self, turns):
        chat = self.adapter.build_chat(turns)
        self.adapter.changed_files[turns[0].id] = ["file.py"]
        return chat

    def set_condition(self, chat_id, **values):
        self.adapter.set_condition(chat_id, **values)

    def insert_text(self, chat_id, message):
        self.adapter.insert_text(chat_id, message)

    def set_format(self, known, version):
        self.adapter.set_format(known, version)

    def configure_usage(self, chat_id):
        self.adapter.usage_values[chat_id] = Usage(50, 100, True, "2026-01-02T00:00:00Z")
        return self.adapter.reader.usage(chat_id)

    def visible_turns(self, chat_id):
        return self.adapter.visible_turns(chat_id)


class ClaudeLikeTests(FakeFixtures, AdapterSuite, unittest.TestCase):
    facts = CLAUDE_LIKE


class CodexLikeTests(FakeFixtures, AdapterSuite, unittest.TestCase):
    facts = CODEX_LIKE


class OpenCodeLikeTests(FakeFixtures, AdapterSuite, unittest.TestCase):
    facts = OPENCODE_LIKE


class CursorLikeTests(FakeFixtures, AdapterSuite, unittest.TestCase):
    facts = CURSOR_LIKE


class FakeBehaviorTests(unittest.TestCase):
    def test_fake_can_remove_an_older_append_without_losing_a_later_one(self):
        adapter = FakeAdapter()
        original = turns()
        chat = adapter.build_chat(original[:1])
        first = adapter.writer.add(chat, original[1:2])
        second = adapter.writer.add(chat, original[2:])
        adapter.writer.take_back(first.receipt)
        self.assertEqual(adapter.reader.read(chat), [original[0], original[2]])
        adapter.writer.take_back(second.receipt)
        self.assertEqual(adapter.reader.read(chat), original[:1])

    def test_runner_returns_or_raises_and_records_requests(self):
        runner = FakeBackgroundRunner("canned")
        self.assertTrue(runner.available().ok)
        self.assertEqual(runner.ask("prompt", "folder"), "canned")
        self.assertEqual(runner.calls, [("prompt", "folder", True)])
        runner.error = RuntimeError("failure")
        with self.assertRaises(RuntimeError):
            runner.ask("prompt", "folder", False)
        runner.finding = replace(runner.finding, ok=False)
        with self.assertRaises(NotAvailable):
            runner.ask("prompt", "folder")

    def test_app_records_calls_and_protects_replies(self):
        adapter = FakeAdapter(CLAUDE_LIKE)
        chat = adapter.build_chat(turns())
        adapter.set_condition(chat, open=True, replying=True, app_running=True)
        with self.assertRaises(ChatReplying):
            adapter.app.close()
        with self.assertRaises(ChatReplying):
            adapter.app.release(chat)
        self.assertTrue(adapter.app.running())
        self.assertTrue(adapter.state.condition(chat).open)
        adapter.set_condition(chat, replying=False)
        adapter.app.release(chat)
        adapter.app.close()
        adapter.app.open(chat, "folder")
        self.assertEqual(adapter.app.calls, [("close",), ("release", chat), ("running",),
                                            ("release", chat), ("close",), ("open", chat, "folder")])

    def test_receipts_are_owned_and_consumed(self):
        adapter = FakeAdapter()
        other = FakeAdapter()
        result = adapter.writer.create([], "new", "")
        with self.assertRaises(ValueError):
            other.writer.take_back(result.receipt)
        adapter.writer.take_back(result.receipt)
        with self.assertRaises(ValueError):
            adapter.writer.take_back(result.receipt)

    def test_create_undo_preserves_later_write(self):
        adapter = FakeAdapter()
        result = adapter.writer.create(turns()[:1], "new", "")
        adapter.writer.add(result.chat_id, turns()[1:])
        with self.assertRaises(ChatChanged):
            adapter.writer.take_back(result.receipt)
        self.assertEqual(adapter.reader.read(result.chat_id), turns())

    def test_cut_undo_preserves_later_add(self):
        adapter = FakeAdapter()
        chat = adapter.build_chat(turns())
        result = adapter.writer.cut(chat, "p1")
        later = turns()[0]
        later = replace(later, prompt=replace(later.prompt, id="later"))
        adapter.writer.add(chat, [later])
        adapter.writer.take_back(result.receipt)
        self.assertEqual(adapter.reader.read(chat), [*turns(), later])

    def test_unknown_format_blocks_undo(self):
        adapter = FakeAdapter()
        result = adapter.writer.create([], "new", "")
        adapter.set_format(False, "unknown")
        with self.assertRaises(UnknownFormat):
            adapter.writer.take_back(result.receipt)
        self.assertTrue(adapter.state.condition(result.chat_id).exists)

    def test_facts_can_change(self):
        adapter = FakeAdapter(CODEX_LIKE)
        chat = adapter.build_chat(turns())
        with self.assertRaises(NotAvailable):
            adapter.writer.cut(chat, "p1")
        adapter.facts = replace(adapter.facts, can_cut=True)
        adapter.writer.cut(chat, "p1")
        self.assertEqual(adapter.reader.read(chat), turns()[:1])

    def test_hooks_install_and_uninstall(self):
        adapter = FakeAdapter()
        adapter.hooks.uninstall()
        self.assertFalse(adapter.hooks.check().ok)
        self.assertFalse(adapter.hooks.install().ok)
        adapter.hooks.ready = True
        self.assertTrue(adapter.hooks.check().ok)
        self.assertEqual(adapter.hooks.attach_reply("text", None), "text")
        self.assertEqual(adapter.hooks.attach_reply("text", "notice"), "text\nnotice")
        self.assertEqual(adapter.hooks.turn_end_reply(), "{}")

    def test_create_undo_preserves_later_rename(self):
        adapter = FakeAdapter()
        result = adapter.writer.create([], "new", "")
        adapter.writer.rename(result.chat_id, "later")
        with self.assertRaises(ChatChanged):
            adapter.writer.take_back(result.receipt)
        self.assertEqual(adapter.locator.name(result.chat_id), "later")

    def test_duplicate_ids_are_rejected_without_writing(self):
        adapter = FakeAdapter()
        with self.assertRaises(ValueError):
            adapter.writer.create([turns()[0], turns()[0]], "new", "")
        self.assertEqual(adapter.locator.chats(), [])
        chat = adapter.build_chat(turns())
        with self.assertRaises(ValueError):
            adapter.writer.add(chat, turns()[:1])
        self.assertEqual(adapter.reader.read(chat), turns())
