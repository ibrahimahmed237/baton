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


from tests.adapters.test_opencode import make, saved


class OpenCodeDetailsTests(unittest.TestCase):
    def setUp(self):
        self.root, self.adapter, self.process = make(self)
        self.chat = fx.build(self.root, turns())

    def test_native_id_shape_and_direction(self):
        first = new_id("msg", fx.EARLY)
        later = new_id("msg", fx.EARLY + 1)
        chat_first = new_id("ses", fx.EARLY, True)
        chat_later = new_id("ses", fx.EARLY + 1, True)
        self.assertRegex(first, r"^msg_[0-9a-f]{12}[0-9A-Za-z]{14}$")
        self.assertLess(first, later)
        self.assertGreater(chat_first, chat_later)

    def test_injected_runner_reports_damaged_and_read_only_launch(self):
        calls = []
        def command(args, **options):
            calls.append((args, options))
            return SimpleNamespace(returncode=0, stdout='1.0' if '--version' in args else '{"type":"text","part":{"text":"answer"}}\n')
        runner = OpenCodeAdapter(self.root, command=command, binary="/fixture/opencode").runner
        self.assertTrue(runner.available().ok)
        self.assertEqual(runner.ask("question", "folder"), "answer")
        permission = json.loads(calls[-1][1]["env"]["OPENCODE_CONFIG_CONTENT"])["permission"]
        self.assertEqual(permission["*"], "deny")
        with self.assertRaises(NotAvailable):
            runner.ask("question", "folder", read_only=False)
        for error in (OSError("damaged"), subprocess.TimeoutExpired("fixture", 5)):
            def damaged(*a, **k):
                raise error
            runner.command = damaged
            finding = runner.available()
            self.assertFalse(finding.ok)
            self.assertEqual(finding.values["reason"], "reinstall")

    def test_project_external_edit_blocks_create_take_back(self):
        self.adapter.project_for_folder = lambda folder: "new-first-commit"
        result = self.adapter.writer.create([], "new", "/new/project")
        fx.run_sql(self.root, "UPDATE project SET sandboxes='[1]' WHERE id='new-first-commit'")
        with self.assertRaises(ChatChanged):
            self.adapter.writer.take_back(result.receipt)
        self.assertTrue(self.adapter.state.condition(result.chat_id).exists)

    def test_model_template_is_scoped_and_no_project_command_is_run_by_default(self):
        adapter = OpenCodeAdapter(self.root, allowed_chat_ids=(self.chat,))
        with no_processes():
            result = adapter.writer.create([], "copy", "/fixture/project")
            self.assertTrue(adapter.state.condition(result.chat_id).exists)
            with self.assertRaises(NotAvailable):
                adapter.writer.create([], "unknown project", "/not/known")

    def test_create_and_add_native_times_are_monotonic_and_use_turn_times(self):
        values = [Turn(Message("old-first", PROMPT, "first", "2020-01-01T00:00:00Z"),
                       (Message("old-reply", REPLY, "answer", "2020-01-01T00:00:01Z"),))]
        result = self.adapter.writer.create(values, "old copy", "folder")
        rows = fx.run_sql(self.root, "SELECT time_created FROM message WHERE session_id=? ORDER BY time_created", (result.chat_id,))
        self.assertEqual(rows, [(1577836800000,), (1577836801000,)])
        self.adapter.writer.add(result.chat_id, [Turn(Message("older", PROMPT, "late", "2019-01-01T00:00:00Z"))])
        rows = fx.run_sql(self.root, "SELECT time_created FROM message WHERE session_id=? ORDER BY time_created", (result.chat_id,))
        self.assertEqual(rows[-1][0], 1577836801001)
        self.assertEqual(self.adapter.reader.read(result.chat_id)[-1].started_at, "2019-01-01T00:00:00Z")

    def test_dense_native_placement_preserves_existing_public_messages(self):
        fx.build(self.root, [], chat="ses_native")
        for i in range(3):
            fx.insert_message(self.root, "ses_native", "native-" + str(i), "user", fx.EARLY + i,
                              [{"type": "text", "text": str(i)}], model=fx.MODEL)
        before = self.adapter.reader.read("ses_native")
        placed = Turn(Message("placed", PROMPT, "insert", "2030-01-01T00:00:00Z"))
        receipt = self.adapter.writer.place("ses_native", [placed], "native-1")
        self.assertEqual(self.adapter.reader.read("ses_native"), [before[0], placed, *before[1:]])
        times = fx.run_sql(self.root, "SELECT time_created FROM message WHERE session_id='ses_native' ORDER BY time_created")
        self.assertTrue(all(a[0] < b[0] for a, b in zip(times, times[1:])))
        self.adapter.writer.take_back(receipt.receipt)
        self.assertEqual(self.adapter.reader.read("ses_native"), before)

    def test_interleaved_tool_result_stays_after_intermediate_reply(self):
        value = Turn(Message("interleaved", PROMPT, "do it"), (
            Message("call", TOOL_CALL, tool="bash", tool_input={"command": "ls"}, call_id="native-call"),
            Message("progress", REPLY, "working"),
            Message("result", TOOL_RESULT, "done", call_id="native-call"),
            Message("final", REPLY, "finished")))
        result = self.adapter.writer.create([value], "interleaved", "folder")
        self.assertEqual(self.adapter.reader.read(result.chat_id), [value])
        rows = fx.run_sql(self.root, "SELECT data FROM part WHERE session_id=?", (result.chat_id,))
        native_tools = [json.loads(r[0]) for r in rows if json.loads(r[0]).get("type") == "tool"]
        self.assertEqual(len(native_tools), 1)
        self.assertEqual(native_tools[0]["state"]["output"], "done")
        self.assertEqual(native_tools[0]["state"]["status"], "completed")

    def test_receipt_root_can_be_injected_under_batons_folder(self):
        adapter = OpenCodeAdapter(self.root, allowed_chat_ids=(self.chat,), rollback_root=self.root / "baton/rollback")
        result = adapter.writer.rename(self.chat, "new")
        self.assertEqual(len(list((self.root / "baton/rollback").glob("*.json"))), 1)
        adapter.writer.take_back(result.receipt)
        self.assertEqual(adapter.locator.name(self.chat), "fixture")

    def test_duplicate_public_message_identity_refuses_before_mutation(self):
        before = saved(self.adapter, self.chat)
        value = Turn(Message("new-prompt", PROMPT, "new"), (Message("a1", REPLY, "duplicate"),))
        with self.assertRaises(ValueError):
            self.adapter.writer.add(self.chat, [value])
        self.assertEqual(saved(self.adapter, self.chat), before)

    def test_symlinked_receipt_is_refused_before_reading_it(self):
        result = self.adapter.writer.rename(self.chat, "new")
        path = next((self.root / ".baton-rollback/opencode").glob("*.json"))
        other = self.root / "other.json"
        path.rename(other)
        path.symlink_to(other)
        with self.assertRaises(NotAvailable):
            self.adapter.writer.take_back(result.receipt)
        self.assertEqual(self.adapter.locator.name(self.chat), "new")

    def test_reading_and_writing_work_while_another_sqlite_connection_is_open(self):
        with closing(sqlite3.connect(fx.database(self.root))) as app_db:
            app_db.execute("PRAGMA journal_mode=WAL")
            self.process.is_running = True
            result = self.adapter.writer.add(self.chat, [Turn(Message("wal-prompt", PROMPT, "live fake"))])
            self.assertEqual(self.adapter.reader.read(self.chat)[-1].id, "wal-prompt")
            self.assertEqual(app_db.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.adapter.writer.take_back(result.receipt)
            self.assertEqual(self.adapter.reader.read(self.chat), turns())

    def test_hook_reply_is_plain_context_and_turn_end_is_empty(self):
        self.assertEqual(self.adapter.hooks.attach_reply("history", "notice"), "notice\n\nhistory")
        self.assertEqual(self.adapter.hooks.attach_reply("", None), "")
        self.assertEqual(self.adapter.hooks.turn_end_reply(), "")

    def test_runner_data_and_config_stay_below_injected_root(self):
        calls = []
        def command(args, **options):
            calls.append(options)
            return SimpleNamespace(returncode=0, stdout='1.0' if '--version' in args else '')
        adapter = OpenCodeAdapter(self.root, command=command, binary="/fixture/opencode")
        adapter.runner.ask("question", "folder")
        environment = calls[-1]["env"]
        for key in ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME"):
            self.assertTrue(Path(environment[key]).is_relative_to(self.root))
