"""Review regressions using only scoped, temporary native-shaped data."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from baton.adapters.opencode import OpenCodeAdapter
from baton.domain.errors import ChatHeld, ChatReplying, NotAvailable
from baton.domain.model import Message, Turn, PROMPT, REPLY
from baton.notes.catalogue import get
from tests.adapters.test_opencode import make, saved
from tests.adapters.suite import turns
from tests.fixtures.opencode import build as fx
from tests.fixtures.no_processes import no_processes


class OpenCodeReviewTests(unittest.TestCase):
    def setUp(self):
        self.root, self.adapter, self.process = make(self)
        self.chat = fx.build(self.root, turns())

    def unfinished(self, ident="a3", age=601):
        now = datetime(2026, 1, 2, tzinfo=timezone.utc)
        self.adapter.now = lambda: now
        at = int((now - timedelta(seconds=age)).timestamp() * 1000)
        fx.run_sql(self.root, "UPDATE message SET data=json_remove(data,'$.finish'),time_updated=? WHERE id=?", (at, ident))
        fx.run_sql(self.root, "UPDATE part SET time_updated=? WHERE message_id=?", (at, ident))
        return int(now.timestamp() * 1000)

    def test_busy_observation_blocks_edits_but_accepts_add_and_create(self):
        self.adapter.chat_status = lambda _: {"status": "busy"}
        before = saved(self.adapter, self.chat)
        for operation in (lambda: self.adapter.writer.place(self.chat, [], "p1"),
                          lambda: self.adapter.writer.cut(self.chat, "p1"),
                          lambda: self.adapter.writer.rename(self.chat, "new"),
                          lambda: self.adapter.writer.prepare(self.chat, "restore")):
            with self.assertRaises(ChatReplying):
                operation()
        self.assertEqual(saved(self.adapter, self.chat), before)
        value = Turn(Message("new", PROMPT, "new"))
        self.adapter.writer.add(self.chat, [value])
        self.assertEqual(self.adapter.reader.read(self.chat)[-1], value)
        created = self.adapter.writer.create([value], "copy", "folder")
        self.assertEqual(self.adapter.reader.read(created.chat_id), [value])

    def test_idle_running_chat_still_accepts_add(self):
        self.process.is_running = True
        self.adapter.writer.add(self.chat, [Turn(Message("idle", PROMPT, "new"))])
        self.assertEqual(self.adapter.reader.read(self.chat)[-1].id, "idle")
        self.assertEqual(self.adapter.facts.write_window.value, "any_time")

    def test_busy_rechecked_after_prepare(self):
        self.adapter.writer.prepare(self.chat, "rename")
        self.adapter.chat_status = lambda _: {"busy": True}
        with self.assertRaises(ChatReplying):
            self.adapter.writer.rename(self.chat, "new")

    def test_busy_rechecked_under_writer_lock(self):
        observed = [0]
        def status(_):
            observed[0] += 1
            return {"busy": observed[0] >= 3}
        self.adapter.chat_status = status
        before = saved(self.adapter, self.chat)
        with self.assertRaises(ChatReplying):
            self.adapter.writer.rename(self.chat, "new")
        self.assertEqual(saved(self.adapter, self.chat), before)

    def test_usage_survives_baton_add_and_rows_are_marked(self):
        fx.run_sql(self.root, "UPDATE message SET data=json_set(data,'$.error',json(?)) WHERE id='a3'",
                   (json.dumps({"name": "RateLimitError"}),))
        before = self.adapter.reader.usage(self.chat)
        self.adapter.writer.add(self.chat, [Turn(Message("new", PROMPT, "new"), (Message("answer", REPLY, "copy"),))])
        self.assertEqual(self.adapter.reader.usage(self.chat), before)
        rows = fx.run_sql(self.root, "SELECT data FROM message WHERE id LIKE 'msg_%' AND json_extract(data,'$.role')='assistant'")
        self.assertTrue(rows)
        self.assertTrue(all(json.loads(row[0]).get("batonWritten") for row in rows))

    def test_newest_native_usage_after_baton_add_wins(self):
        self.adapter.writer.add(self.chat, [Turn(Message("new", PROMPT, "new"), (Message("answer", REPLY, "copy"),))])
        fx.insert_message(self.root, self.chat, "native-latest", "assistant", int(self.adapter.now().timestamp()*1000)+1000,
                          [{"type": "text", "text": "latest"}], finish="stop", tokens={"total": 4567})
        self.assertEqual(self.adapter.reader.usage(self.chat).tokens, 4567)

    def test_create_requires_scope_even_with_model_and_project(self):
        adapter = OpenCodeAdapter(self.root, model=fx.MODEL, project_for_folder=lambda _: "fixture-first-commit")
        before = fx.run_sql(self.root, "SELECT id FROM session")
        for operation in (lambda: adapter.writer.prepare(None, "create"),
                          lambda: adapter.writer.create([], "new", "folder")):
            with self.assertRaises(NotAvailable):
                operation()
        self.assertEqual(fx.run_sql(self.root, "SELECT id FROM session"), before)

    def test_stale_unfinished_reply_expires_only_when_stopped(self):
        self.unfinished()
        self.assertFalse(self.adapter.state.condition(self.chat).replying)
        self.adapter.writer.rename(self.chat, "recovered")
        self.adapter.app.close()
        self.process.is_running = True
        self.assertTrue(self.adapter.state.condition(self.chat).replying)
        with self.assertRaises(ChatReplying):
            self.adapter.app.close()

    def test_recent_unfinished_reply_blocks_stopped_app(self):
        self.unfinished(age=599)
        self.assertTrue(self.adapter.state.condition(self.chat).replying)
        with self.assertRaises(ChatReplying):
            self.adapter.writer.rename(self.chat, "new")

    def test_new_part_resets_unfinished_timeout(self):
        now = self.unfinished()
        fx.run_sql(self.root, "UPDATE part SET time_updated=? WHERE message_id='a3'", (now - 1000,))
        self.assertTrue(self.adapter.state.condition(self.chat).replying)

    def test_unfinished_timeout_is_injectable(self):
        self.unfinished(age=30)
        self.adapter.unfinished_timeout = 20
        self.assertFalse(self.adapter.state.condition(self.chat).replying)
        self.adapter.unfinished_timeout = 40
        self.assertTrue(self.adapter.state.condition(self.chat).replying)

    def test_unfinished_earlier_assistant_is_not_hidden_by_finished_latest(self):
        self.unfinished(ident="a1", age=1)
        self.assertTrue(self.adapter.state.condition(self.chat).replying)

    def test_close_waits_until_process_is_gone(self):
        self.process.is_running = True
        sleeps = []
        self.process.quit = lambda: self.process.calls.append(("quit",))
        def sleep(_):
            sleeps.append(True)
            if len(sleeps) == 2:
                self.process.is_running = False
        self.adapter.app.sleep = sleep
        self.adapter.app.close()
        self.assertEqual(len(sleeps), 2)
        self.assertFalse(self.process.running())

    def test_close_has_bounded_wait(self):
        self.process.is_running = True
        self.process.quit = lambda: None
        times = iter((0, 0, 11))
        self.adapter.app.monotonic = lambda: next(times)
        self.adapter.app.sleep = lambda _: None
        with self.assertRaises(NotAvailable):
            self.adapter.app.close()

    def test_reads_refuse_unscoped_chat_but_picker_lists_it(self):
        fx.build(self.root, [], chat="private")
        self.assertIn("private", [c.id for c in self.adapter.locator.chats()])
        for operation in (self.adapter.locator.row, self.adapter.locator.resolve, self.adapter.locator.name,
                          self.adapter.reader.read, self.adapter.reader.rows, self.adapter.reader.usage,
                          self.adapter.state.condition):
            with self.assertRaises(NotAvailable):
                operation("private")

    def test_files_changed_cannot_fetch_unscoped_native_message(self):
        fx.build(self.root, [], chat="private")
        fx.insert_message(self.root, "private", "private-prompt", "user", fx.EARLY,
                          [{"type": "text", "text": "private"}], summary={"diffs": [{"file": "secret.py"}]})
        self.assertEqual(self.adapter.reader.files_changed(Turn(Message("private-prompt", PROMPT, "x"))), [])

    def test_sqlite_writer_lock_maps_to_chat_held(self):
        with closing(sqlite3.connect(fx.database(self.root))) as db:
            db.execute("BEGIN IMMEDIATE")
            with self.assertRaises(ChatHeld):
                self.adapter.writer.rename(self.chat, "new")
            db.rollback()
        self.assertEqual(self.adapter.locator.name(self.chat), "fixture")

    def test_connections_close_even_if_pragma_fails(self):
        connection = SimpleNamespace(execute=lambda _: (_ for _ in ()).throw(sqlite3.OperationalError("database is locked")),
                                     close=lambda: closed.append(True))
        closed = []
        with patch("baton.adapters.opencode.locator.sqlite3.connect", return_value=connection):
            with self.assertRaises(ChatHeld):
                with self.adapter.locator.connect():
                    self.fail("must not yield")
        self.assertEqual(closed, [True])

    def test_hooks_missing_entrypoints_do_not_write(self):
        hooks = self.adapter.hooks
        with no_processes():
            finding = hooks.install()
        self.assertFalse(finding.ok)
        self.assertEqual(finding.note_id, "setup.hooks")
        self.assertFalse(hooks.path.parent.exists())
        hooks.entrypoints_available = lambda: True
        hooks.install()
        before = hooks.path.read_bytes()
        hooks.entrypoints_available = lambda: False
        self.assertEqual(hooks.install().note_id, "setup.hooks")
        self.assertEqual(hooks.path.read_bytes(), before)

    def test_plugin_commands_match_readiness_contract(self):
        hooks = self.adapter.hooks
        content = hooks.plugin_content()
        called = re.findall(r'await run\(\["([^"]+)"', content)
        self.assertEqual(tuple(called), hooks.COMMANDS)
        known = set()
        hooks.entrypoints_available = lambda: all(command in known for command in hooks.COMMANDS)
        for command in called:
            self.assertFalse(hooks.install().ok)
            self.assertFalse(hooks.path.exists())
            known.add(command)
        hooks.install()
        hooks.loaded = lambda: True
        self.assertTrue(hooks.check().ok)

    def test_plugin_failure_attaches_nothing_and_logs_once_with_ms_timeout(self):
        content = self.adapter.hooks.plugin_content()
        self.assertIn("timeout: 2000", content)  # the hook deadline of C4
        self.assertEqual(content.count("console.error("), 1)
        self.assertIn('if (error) { console.error(failureNote); resolve(""); return; }', content)
        self.assertIn('if (text.trim()) output.parts.push', content)
        self.assertIn(json.dumps(get("hooks.command_failed").template), content)

    def test_plugin_installs_in_injected_project_folder(self):
        folder = self.root / "project"
        adapter = OpenCodeAdapter(self.root, plugin_folder=folder, hook_entrypoints_available=lambda: True)
        adapter.hooks.install()
        self.assertEqual(adapter.hooks.path, folder / ".opencode/plugins/baton.js")
        self.assertTrue(adapter.hooks.path.exists())
        self.assertFalse((self.root / ".config").exists())

    def test_prompt_uses_option_separator_and_reinstall_note(self):
        calls = []
        def command(args, **options):
            calls.append((args, options))
            return SimpleNamespace(returncode=0, stdout="")
        adapter = OpenCodeAdapter(self.root, command=command, binary="fake")
        adapter.runner.ask("--dangerous-prompt", "folder")
        self.assertEqual(calls[-1][0][-2:], ["--", "--dangerous-prompt"])
        finding = self.adapter.runner.available()
        self.assertEqual(finding.note_id, "setup.runner_reinstall")
        wording = get(finding.note_id).render({"tool": "OpenCode"}).template
        self.assertIn("Reinstall", wording)
        self.assertNotIn("sign in", wording)

    def test_production_runner_preserves_native_xdg_environment(self):
        calls = []
        def command(args, **options):
            calls.append((args, options))
            return SimpleNamespace(returncode=0, stdout="")
        with no_processes():
            adapter = OpenCodeAdapter.on_this_machine(self.root, command=command, binary="fake", process=self.process, rollback_root=self.root / "rollback")
            with patch.dict(os.environ, {"XDG_DATA_HOME": "/fixture/native-data"}):
                adapter.runner.ask("question", "folder")
        self.assertEqual(calls[-1][1]["env"]["XDG_DATA_HOME"], "/fixture/native-data")
        self.assertIsNone(adapter.runner.root)

    def test_close_refuses_unscoped_chats_without_reading_them(self):
        fx.build(self.root, [], chat="private")
        with self.assertRaises(NotAvailable):
            self.adapter.app.close()
        self.assertEqual(self.process.calls, [])

    def test_native_busy_status_object_allows_add(self):
        self.adapter.chat_status = lambda _: {"status": {"type": "busy"}}
        value = Turn(Message("busy", PROMPT, "new"))
        self.adapter.writer.add(self.chat, [value])
        self.assertEqual(self.adapter.reader.read(self.chat)[-1], value)

    def test_take_back_busy_gate_runs_inside_writer_transaction(self):
        receipt = self.adapter.writer.add(self.chat, [Turn(Message("new", PROMPT, "new"))]).receipt
        before = saved(self.adapter, self.chat)
        def busy(_):
            # A second writer cannot acquire the lock while the gate runs.
            with closing(sqlite3.connect(fx.database(self.root), timeout=0)) as db:
                with self.assertRaises(sqlite3.OperationalError):
                    db.execute("BEGIN IMMEDIATE")
            return {"status": "busy"}
        self.adapter.chat_status = busy
        with self.assertRaises(ChatReplying):
            self.adapter.writer.take_back(receipt)
        self.assertEqual(saved(self.adapter, self.chat), before)
