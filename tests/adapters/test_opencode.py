"""OpenCode contract and safety tests on synthetic temporary databases only."""
from dataclasses import asdict
from contextlib import closing
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from baton.adapters.opencode import OpenCodeAdapter
from baton.adapters.opencode.records import new_id, snapshot
from baton.domain.errors import ChatChanged, ChatReplying, NotAvailable, UnknownFormat
from baton.domain.model import Message, Turn, PROMPT, REPLY, TOOL_CALL, TOOL_RESULT, TOOL_TEXT
from baton.ports.tool import WriteReceipt
from tests.adapters.suite import AdapterSuite, turns
from tests.fixtures.opencode import build as fx
from tests.fixtures.no_processes import no_processes


def make(test, **options):
    folder = tempfile.TemporaryDirectory()
    test.addCleanup(folder.cleanup)
    root = Path(folder.name).resolve()
    fx.create_database(root)
    process = fx.FixtureProcess()
    options.setdefault("process", process)
    options.setdefault("now", fx.tick_clock())
    options.setdefault("allowed_chat_ids", ("ses_fixture", "ses_other", "ses_native", "ses_child", "missing"))
    options.setdefault("model", fx.MODEL)
    options.setdefault("project_for_folder", lambda folder: "fixture-first-commit")
    adapter = OpenCodeAdapter(root, **options)
    return root, adapter, process


def saved(adapter, chat):
    with adapter.locator.connect() as db:
        return snapshot(db, chat)


class OpenCodeSuite(AdapterSuite, unittest.TestCase):
    """Run the shared suite against rows built independently of the writer."""

    def make_adapter(self):
        self.root, adapter, self.process = make(self, chat_status=lambda c: {"open": c in self.process.open_chats})
        self.shown = {}
        return adapter

    def build_chat(self, values):
        return fx.build(self.root, values)

    def insert_text(self, chat, message):
        fx.insert_message(self.root, chat, message.id, "user", fx.EARLY + 999999,
                          [{"type": "text", "synthetic": True, "text": message.text}])

    def set_condition(self, chat, **values):
        if "app_running" in values:
            self.process.is_running = values["app_running"]
        if values.get("exists") is False:
            for table in ("part", "message", "session"):
                column = "id" if table == "session" else "session_id"
                fx.run_sql(self.root, "DELETE FROM %s WHERE %s=?" % (table, column), (chat,))
            self.process.open_chats.discard(chat)
            return
        if values.get("open", False):
            self.process.open_chats.add(chat)
            self.shown[chat] = self.adapter.reader.read(chat)
        else:
            self.process.open_chats.discard(chat)
        fx.run_sql(self.root, "UPDATE message SET data=json_set(data,'$.finish',?) WHERE id=(SELECT id FROM message WHERE session_id=? AND json_extract(data,'$.role')='assistant' ORDER BY time_created DESC,id DESC LIMIT 1)",
                   (None if values.get("replying", False) else "stop", chat))

    def set_format(self, known, version):
        columns = {r[1] for r in fx.run_sql(self.root, "PRAGMA table_info(project)")}
        if known and "future_sandboxes" in columns:
            fx.run_sql(self.root, "ALTER TABLE project RENAME COLUMN future_sandboxes TO sandboxes")
        elif not known and "sandboxes" in columns:
            fx.run_sql(self.root, "ALTER TABLE project RENAME COLUMN sandboxes TO future_sandboxes")
        fx.run_sql(self.root, "UPDATE session SET version=?", (version,))

    def test_unknown_version_blocks_writes(self):
        # Q14: record shape, not a version string, controls writing.
        for known, version in ((False, "checked"), (True, "unknown"), (False, "unknown")):
            with self.subTest(known=known, version=version):
                self.set_format(known, version)
                self.assertEqual(self.adapter.state.format_version().known, known)
                self.assertEqual(fx.run_sql(self.root, "SELECT version FROM session WHERE id=?", (self.chat,)), [(version,)])
                if known:
                    result = self.adapter.writer.rename(self.chat, "accepted")
                    self.adapter.writer.take_back(result.receipt)
                    continue
                for operation in (lambda: self.adapter.writer.create([], "new", ""),
                                  lambda: self.adapter.writer.add(self.chat, []),
                                  lambda: self.adapter.writer.rename(self.chat, "new"),
                                  lambda: self.adapter.writer.place(self.chat, [], self.turns[0].id),
                                  lambda: self.adapter.writer.cut(self.chat, self.turns[0].id)):
                    with self.assertRaises(UnknownFormat):
                        operation()
                self.assertEqual(self.adapter.reader.read(self.chat), self.turns)

    def configure_usage(self, chat):
        fx.run_sql(self.root, "UPDATE message SET data=json_set(data,'$.error',json(?)) WHERE id=(SELECT id FROM message WHERE session_id=? AND json_extract(data,'$.role')='assistant' ORDER BY time_created DESC LIMIT 1)",
                   (json.dumps({"name": "APIError", "data": {"statusCode": 429}}), chat))
        return self.adapter.reader.usage(chat)

    def visible_turns(self, chat):
        # A test-side cache models the measured view; reader always sees DB changes.
        if chat not in self.shown:
            self.shown[chat] = self.adapter.reader.read(chat)
        return self.shown[chat]


class OpenCodeTests(unittest.TestCase):
    def setUp(self):
        self.root, self.adapter, self.process = make(self)
        self.chat = fx.build(self.root, turns())

    def test_scoped_writes_refuse_other_chats(self):
        fx.build(self.root, [], chat="ses_private")
        for kind in ("add", "cut", "rename", "place", "restore"):
            with self.assertRaises(NotAvailable):
                self.adapter.writer.prepare("ses_private", kind)
        with self.assertRaises(NotAvailable):
            self.adapter.reader.read("ses_private")

    def test_default_controls_are_inert(self):
        with no_processes():
            adapter = OpenCodeAdapter(self.root)
            self.assertFalse(adapter.app.running())
            self.assertFalse(adapter.runner.available().ok)
            self.assertEqual(adapter.runner.available().values["fix_id"], "reinstall")
            with self.assertRaises(NotAvailable):
                adapter.app.open(None, "folder")
            with self.assertRaises(NotAvailable):
                adapter.app.close()
            with self.assertRaises(NotAvailable):
                adapter.runner.ask("question", "folder")
            with self.assertRaises(NotAvailable):
                adapter.writer.add(self.chat, [])

    def test_known_shape_accepts_new_version_and_nullable_columns(self):
        fx.run_sql(self.root, "UPDATE session SET version='999.0'")
        fx.run_sql(self.root, "ALTER TABLE message ADD COLUMN future_field BLOB")
        self.assertTrue(self.adapter.state.format_version().known)
        result = self.adapter.writer.add(self.chat, [Turn(Message("p4", PROMPT, "new"))])
        self.assertEqual(self.adapter.reader.read(self.chat)[-1].id, "p4")
        self.adapter.writer.take_back(result.receipt)
        self.assertEqual(self.adapter.reader.read(self.chat), turns())

    def test_child_sessions_are_not_sidebar_chats(self):
        fx.build(self.root, [], chat="ses_child")
        fx.run_sql(self.root, "UPDATE session SET parent_id=? WHERE id='ses_child'", (self.chat,))
        self.assertNotIn("ses_child", [c.id for c in self.adapter.locator.chats()])
        with self.assertRaises(KeyError):
            self.adapter.locator.resolve("ses_child")

    def test_prepared_row_compare_catches_session_change(self):
        self.adapter.writer.prepare(self.chat, "add")
        fx.run_sql(self.root, "UPDATE session SET title='outside' WHERE id=?", (self.chat,))
        before = saved(self.adapter, self.chat)
        with self.assertRaises(ChatChanged):
            self.adapter.writer.add(self.chat, [Turn(Message("p4", PROMPT, "new"))])
        self.assertEqual(saved(self.adapter, self.chat), before)

    def test_prepared_compare_catches_child_change_without_session_update(self):
        self.adapter.writer.prepare(self.chat, "rename")
        fx.run_sql(self.root, "UPDATE part SET data=json_set(data,'$.text','outside') WHERE id=(SELECT id FROM part LIMIT 1)")
        before = saved(self.adapter, self.chat)
        with self.assertRaises(ChatChanged):
            self.adapter.writer.rename(self.chat, "new")
        self.assertEqual(saved(self.adapter, self.chat), before)

    def test_receipt_is_fsynced_before_native_mutation(self):
        writer = self.adapter.writer
        old = saved(self.adapter, self.chat)
        replace = writer._replace
        def observed(db, before, after):
            paths = list((self.root / ".baton-rollback/opencode").glob("*.json"))
            self.assertEqual(len(paths), 1)
            self.assertEqual(json.loads(paths[0].read_text())["before"], old)
            self.assertEqual(snapshot(db, self.chat), old)
            replace(db, before, after)
        with patch.object(writer, "_replace", side_effect=observed):
            writer.rename(self.chat, "new")

    def test_failed_transaction_is_atomic_and_prepared_receipt_recovers(self):
        writer = self.adapter.writer
        receipt = writer.prepare(self.chat, "add")
        before = saved(self.adapter, self.chat)
        replace = writer._replace
        def fail(db, old, new):
            replace(db, old, new)
            raise OSError("fixture failure")
        with patch.object(writer, "_replace", side_effect=fail):
            with self.assertRaises(OSError):
                writer.add(self.chat, [Turn(Message("p4", PROMPT, "new"))])
        self.assertEqual(saved(self.adapter, self.chat), before)
        writer.take_back(receipt)
        self.assertEqual(saved(self.adapter, self.chat), before)

    def test_exact_row_rollback_preserves_blob_and_unrelated_chat(self):
        fx.run_sql(self.root, "ALTER TABLE session ADD COLUMN extra BLOB")
        fx.run_sql(self.root, "UPDATE session SET extra=? WHERE id=?", (b"\x00\xff", self.chat))
        fx.build(self.root, [], chat="ses_other")
        before = saved(self.adapter, self.chat)
        other = saved(self.adapter, "ses_other")
        for operation in (lambda: self.adapter.writer.rename(self.chat, "renamed"),
                          lambda: self.adapter.writer.cut(self.chat, "p1"),
                          lambda: self.adapter.writer.place(self.chat, [Turn(Message("new", PROMPT, "middle"))], "p2")):
            result = operation()
            receipt = WriteReceipt(**json.loads(json.dumps(asdict(result.receipt))))
            self.adapter.writer.take_back(receipt)
            self.assertEqual(saved(self.adapter, self.chat), before)
            self.assertEqual(saved(self.adapter, "ses_other"), other)

    def test_stale_take_back_refuses_later_part_edit(self):
        result = self.adapter.writer.rename(self.chat, "new")
        fx.run_sql(self.root, "UPDATE part SET data=json_set(data,'$.text','outside') WHERE id=(SELECT id FROM part LIMIT 1)")
        before = saved(self.adapter, self.chat)
        with self.assertRaises(ChatChanged):
            self.adapter.writer.take_back(result.receipt)
        self.assertEqual(saved(self.adapter, self.chat), before)

    def test_create_project_rollback_and_restart_recovery(self):
        self.adapter.project_for_folder = lambda folder: "new-first-commit"
        pre = self.adapter.writer.prepare(None, "create")
        result = self.adapter.writer.create(turns(), "new", "/new/project")
        self.assertEqual(fx.run_sql(self.root, "SELECT worktree FROM project WHERE id='new-first-commit'"), [("/new/project",)])
        reopened = OpenCodeAdapter(self.root, allowed_chat_ids=self.adapter.allowed_chat_ids)
        reopened.writer.take_back(pre)
        self.assertFalse(reopened.state.condition(result.chat_id).exists)
        self.assertEqual(fx.run_sql(self.root, "SELECT id FROM project WHERE id='new-first-commit'"), [])
        self.assertEqual(self.adapter.reader.read(self.chat), turns())

    def test_new_project_receipt_refuses_deleting_other_project_user(self):
        self.adapter.project_for_folder = lambda folder: "new-first-commit"
        result = self.adapter.writer.create([], "new", "/new/project")
        fx.run_sql(self.root, "UPDATE session SET project_id='new-first-commit' WHERE id=?", (self.chat,))
        with self.assertRaises(ChatChanged):
            self.adapter.writer.take_back(result.receipt)
        self.assertTrue(self.adapter.state.condition(result.chat_id).exists)

    def test_native_reading_drops_reasoning_and_synthetic_parts(self):
        fx.build(self.root, [], chat="ses_native")
        fx.insert_message(self.root, "ses_native", "native-user", "user", fx.EARLY,
                          [{"type": "text", "text": "real"}, {"type": "text", "text": "secret context", "synthetic": True}],
                          model=fx.MODEL, summary={"diffs": [{"file": "native.py"}]})
        fx.insert_message(self.root, "ses_native", "native-assistant", "assistant", fx.EARLY + 10,
                          [{"type": "reasoning", "text": "hidden"},
                           {"type": "tool", "tool": "bash", "callID": "call-native", "state": {"status": "completed", "input": {"command": "ls"}, "output": "file", "time": {"end": fx.EARLY + 13}}},
                           {"type": "text", "text": "answer"}], parentID="native-user", finish="stop")
        values = self.adapter.reader.read("ses_native")
        self.assertEqual(values[0].prompt.text, "real")
        self.assertEqual([m.kind for m in values[0].messages], [TOOL_CALL, TOOL_RESULT, REPLY])
        self.assertEqual(values[0].messages[0].call_id, values[0].messages[1].call_id)
        self.assertEqual(self.adapter.reader.files_changed(values[0]), ["native.py"])
        self.assertEqual(self.adapter.reader.commands_run(values[0]), 1)

    def test_tool_text_without_reply_round_trips(self):
        value = Turn(Message("p-new", PROMPT, "incomplete"), (Message("t-new", TOOL_TEXT, "tool activity"),))
        result = self.adapter.writer.create([value], "incomplete", "folder")
        self.assertEqual(self.adapter.reader.read(result.chat_id), [value])
        self.assertEqual(self.adapter.reader.read(result.chat_id)[0].reply_text, "")

    def test_usage_without_total_sums_counts_and_has_no_reset(self):
        fx.run_sql(self.root, "UPDATE message SET data=json_set(data,'$.tokens',json(?),'$.error',json(?)) WHERE id='a3'",
                   (json.dumps({"input": 30, "output": 4, "reasoning": 2, "cache": {"read": 3, "write": 1}}), json.dumps({"data": {"statusCode": 429}})))
        usage = self.adapter.reader.usage(self.chat)
        self.assertEqual(usage.tokens, 40)
        self.assertTrue(usage.limit_reached)
        self.assertIsNone(usage.size)
        self.assertIsNone(usage.limit_resets_at)

    def test_running_and_replying_allow_add_but_block_rename_and_close(self):
        self.process.is_running = True
        fx.run_sql(self.root, "UPDATE message SET data=json_remove(data,'$.finish') WHERE id='a3'")
        self.assertTrue(self.adapter.state.condition(self.chat).replying)
        with self.assertRaises(ChatReplying):
            self.adapter.app.close()
        with self.assertRaises(ChatReplying):
            self.adapter.writer.rename(self.chat, "while running")
        self.adapter.writer.add(self.chat, [Turn(Message("allowed", PROMPT, "new"))])
        self.assertEqual(self.adapter.reader.read(self.chat)[-1].id, "allowed")
        self.assertEqual(self.adapter.locator.name(self.chat), "fixture")
        self.assertEqual(self.process.calls, [])

    def test_open_encodes_folder_and_never_uses_chat_deep_link(self):
        self.adapter.app.open(self.chat, "/fixture/a & b")
        self.assertEqual(self.process.calls, [("open_url", "opencode://open-project?directory=%2Ffixture%2Fa+%26+b")])

    def test_plugin_is_rooted_synthetic_and_requires_loaded_evidence(self):
        self.adapter.hooks.entrypoints_available = lambda: True
        self.assertFalse(self.adapter.hooks.check().values["installed"])
        finding = self.adapter.hooks.install()
        self.assertTrue(finding.values["installed"])
        self.assertFalse(finding.ok)
        self.assertEqual(finding.note_id, "setup.restart_once")
        content = self.adapter.hooks.path.read_text()
        for text in ('"chat.message"', 'synthetic: true', '"session.status"', '"busy"', '"idle"', '"catch-up"', '"notify"'):
            self.assertIn(text, content)
        self.adapter.hooks.loaded = lambda: True
        self.assertTrue(self.adapter.hooks.check().ok)
        other = self.adapter.hooks.path.parent / "other.js"
        other.write_text("fixture plugin")
        self.adapter.hooks.uninstall()
        self.assertTrue(other.exists())
        self.assertFalse(self.adapter.hooks.check().values["installed"])

    def test_plugin_refuses_replacing_another_file(self):
        self.adapter.hooks.entrypoints_available = lambda: True
        self.adapter.hooks.path.parent.mkdir(parents=True)
        self.adapter.hooks.path.write_text("user owned")
        with self.assertRaises(NotAvailable):
            self.adapter.hooks.install()
        self.adapter.hooks.uninstall()
        self.assertEqual(self.adapter.hooks.path.read_text(), "user owned")

    def test_symlink_database_and_plugin_roots_are_refused(self):
        outside = self.root / "elsewhere"
        outside.mkdir()
        path = self.root / ".opencode"
        path.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(NotAvailable):
            self.adapter.hooks.path
        fx.database(self.root).rename(outside / "database")
        fx.database(self.root).symlink_to(outside / "database")
        with self.assertRaises(NotAvailable):
            self.adapter.locator.chats()

