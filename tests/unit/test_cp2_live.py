"""The CP2 live-run script on homes built in temporary folders; it is never pointed at a real home here."""
import hashlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from baton.adapters.claude import ClaudeAdapter
from baton.adapters.codex import CodexAdapter
from baton.adapters.codex.coordination import NativeCoordination
from baton.domain.model import PROMPT, REPLY, Message, Turn
from tests.adapters.suite import turns
from tests.adapters.test_codex import rollout_of, thread_row
from tests.fixtures.claude import build as claude_build
from tests.fixtures.codex import build as fx
from tests.fixtures.no_processes import no_processes

SCRIPT = Path(__file__).resolve().parents[2] / "tools" / "live" / "cp2_live.py"
_spec = importlib.util.spec_from_file_location("cp2_live", SCRIPT)
live = importlib.util.module_from_spec(_spec)
sys.modules["cp2_live"] = live
_spec.loader.exec_module(live)

CODEX_CHAT = "codex-live"
CLAUDE_CHAT = "local_live"
CLAUDE_SESSION = "sess_live"
NOW = datetime(2026, 10, 14, 9, 30, 0, tzinfo=timezone.utc)
SECRET_TURNS = [Turn(Message("p1", PROMPT, "zebra-secret-prompt", "2026-01-01T00:00:00Z"),
                     (Message("a1", REPLY, "zebra-secret-reply"),))]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class LiveScriptCase(unittest.TestCase):
    """A home with one Codex chat and one Claude chat, both named as the guard wants."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        base = Path(temp.name).resolve()
        self.root, self.repo = base / "home", base / "repo"
        self.root.mkdir()
        self.repo.mkdir()
        self.backup = base / "backups"
        fx.build(self.root, SECRET_TURNS + turns(), CODEX_CHAT, folder=str(self.repo), title=live.TITLE)
        claude_build.build(self.root, turns(), CLAUDE_CHAT, CLAUDE_SESSION, str(self.repo))
        self.set_claude_title(live.TITLE)
        self.codex_process = fx.FixtureProcess(self.root)
        self.addCleanup(self.codex_process.quit)
        self.claude_process = claude_build.FixtureProcess(self.root)
        self.wrap_add = None

    # -- the chats under test

    def codex_path(self):
        return rollout_of(self.root, CODEX_CHAT)

    def codex_state(self):
        return self.codex_path().read_bytes(), thread_row(self.root, CODEX_CHAT)

    def claude_paths(self):
        locator = ClaudeAdapter(self.root).locator
        return locator.session_path(CLAUDE_CHAT), locator.entry(CLAUDE_CHAT)[0]

    def claude_state(self):
        return tuple(path.read_bytes() for path in self.claude_paths())

    def set_claude_title(self, title):
        sidebar = next((self.root / "Library").rglob(CLAUDE_CHAT + ".json"))
        entry = json.loads(sidebar.read_text())
        entry["title"] = title
        sidebar.write_text(json.dumps(entry))

    def set_codex_title(self, title):
        fx.run_sql(self.root, "UPDATE threads SET title = ?, name = ? WHERE id = ?", (title, title, CODEX_CHAT))

    def hold_claude(self, status="idle"):
        registry = self.root / ".claude" / "sessions"
        registry.mkdir(parents=True, exist_ok=True)
        self.claude_process.pids.add(1234)
        (registry / "1234.json").write_text(json.dumps({"pid": 1234, "sessionId": CLAUDE_SESSION, "status": status}))

    # -- running the script

    def factory(self, tool, home, chat_id, injected):
        self.assertTrue(injected)
        if tool == "codex":
            adapter = CodexAdapter(home, process=self.codex_process, allowed_chat_ids=(chat_id,),
                                   coordination=NativeCoordination(), hook_entrypoints_available=lambda: True,
                                   now=fx.tick_clock())
        else:
            adapter = ClaudeAdapter(home, process=self.claude_process, hook_entrypoints_available=lambda: True)
            adapter.locator = live._OneChatLocator(adapter.root, chat_id)
        if self.wrap_add is not None:
            self.wrap_add(tool, adapter)
        return adapter

    def run_script(self, step, *, codex=False, claude=False, write=True, backup=True, extra=()):
        argv = ["--step", step, "--home", str(self.root), "--repo", str(self.repo)]
        if codex:
            argv += ["--codex-chat", CODEX_CHAT]
        if claude:
            argv += ["--claude-chat", CLAUDE_SESSION if claude == "session" else CLAUDE_CHAT]
        if write:
            argv.append("--yes-write")
        if backup:
            argv += ["--backup-dir", str(self.backup)]
        argv += list(extra)
        out, err = io.StringIO(), io.StringIO()
        with no_processes():
            code = live.main(argv, adapter_factory=self.factory, now=lambda: NOW, stdout=out, stderr=err)
        self.text = out.getvalue()
        results = [json.loads(line) for line in self.text.splitlines()]
        return code, results, err.getvalue()

    def one(self, step, **options):
        code, results, _ = self.run_script(step, **options)
        self.assertEqual(len(results), 1, self.text)
        return code, results[0]

    def snapshot_dirs(self, tool, chat):
        parent = self.backup / ("%s-%s" % (tool, chat))
        return sorted(child.name for child in parent.iterdir()) if parent.exists() else []


class GuardTests(LiveScriptCase):
    def test_other_titles_are_refused_for_every_step_and_nothing_is_written(self):
        self.set_codex_title("My real chat")
        self.set_claude_title("My real chat")
        before = (self.codex_state(), self.claude_state())
        for step in live.STEPS:
            for tool in ("codex", "claude"):
                with self.subTest(step=step, tool=tool):
                    code, result = self.one(step, **{tool: True})
                    self.assertEqual(code, 2)
                    self.assertEqual((result["refused"], result["title_ok"], result["folder_ok"]), ("guard", False, True))
                    self.assertNotIn("My real chat", self.text)
        self.assertEqual((self.codex_state(), self.claude_state()), before)
        self.assertFalse(self.backup.exists())
        self.assertFalse((self.root / ".baton-rollback").exists())

    def test_a_close_but_not_exact_title_is_refused(self):
        for title in (live.TITLE + " ", live.TITLE.lower(), "Baton test", live.TITLE + " 2"):
            self.set_codex_title(title)
            with self.subTest(title=title):
                code, result = self.one("add", codex=True)
                self.assertEqual((code, result["refused"], result["title_ok"]), (2, "guard", False))
        self.assertFalse(self.backup.exists())

    def test_rename_needs_the_plain_title_and_its_way_back_needs_the_renamed_one(self):
        code, result = self.one("rename-back", codex=True)
        self.assertEqual((code, result["refused"]), (2, "guard"))
        self.set_codex_title(live.RENAMED)
        code, result = self.one("rename", codex=True)
        self.assertEqual((code, result["refused"]), (2, "guard"))
        code, result = self.one("add", codex=True)
        self.assertEqual((code, result["refused"]), (2, "guard"))
        self.assertFalse(self.backup.exists())

    def test_a_chat_of_another_folder_is_refused_without_saying_which(self):
        other = self.repo.parent / "elsewhere"
        other.mkdir()
        fx.run_sql(self.root, "UPDATE threads SET cwd = ? WHERE id = ?", (str(other), CODEX_CHAT))
        code, result = self.one("add", codex=True)
        self.assertEqual((code, result["refused"], result["title_ok"], result["folder_ok"]), (2, "guard", True, False))
        self.assertNotIn("elsewhere", self.text)
        sidebar = self.claude_paths()[1]
        entry = json.loads(sidebar.read_text())
        entry["cwd"] = str(other)
        sidebar.write_text(json.dumps(entry))
        code, result = self.one("add", claude=True)
        self.assertEqual((code, result["refused"], result["folder_ok"]), (2, "guard", False))
        self.assertFalse(self.backup.exists())

    def test_unknown_and_malformed_ids_are_refused(self):
        argv = ["--step", "inspect", "--home", str(self.root), "--repo", str(self.repo)]
        for flag, chat in (("--codex-chat", "nobody"), ("--codex-chat", "../x"), ("--claude-chat", "nobody")):
            out = io.StringIO()
            with no_processes():
                code = live.main([*argv, flag, chat], adapter_factory=self.factory, now=lambda: NOW, stdout=out)
            self.assertEqual(code, 2, chat)
            self.assertIn(json.loads(out.getvalue())["refused"],
                          ("chat_id_not_allowed", "chat_not_found", "claude_chat_not_found_exactly_once"))

    def test_the_codex_adapter_is_scoped_to_the_one_chat_and_claude_sees_one_entry(self):
        with no_processes():
            codex = live.default_factory("codex", self.root, CODEX_CHAT, False)
            claude = live.default_factory("claude", self.root, CLAUDE_CHAT, False)
        self.assertEqual(codex.scope.original, frozenset({CODEX_CHAT}))
        self.assertIsInstance(codex.coordination, NativeCoordination)
        self.assertEqual([entry["sessionId"] for _, entry in claude.locator.entries()], [CLAUDE_CHAT])

    def test_a_broken_other_claude_chat_is_not_read(self):
        claude_build.build(self.root, turns(), "local_other", "sess_other", str(self.repo))
        next((self.root / ".claude" / "projects").rglob("sess_other.jsonl")).write_text("not json at all")
        code, result = self.one("add", claude=True)
        self.assertEqual((code, result["ok"]), (0, True), self.text)


class DryRunTests(LiveScriptCase):
    def test_a_dry_run_prints_the_plan_and_writes_nothing(self):
        self.assertEqual(self.run_script("add", codex=True, claude=True)[0], 0)
        for step in ("add", "rename", "restore", "take-back", "refuse-held"):
            before = (self.codex_state(), self.claude_state(), self.snapshot_dirs("codex", CODEX_CHAT))
            code, results, _ = self.run_script(step, codex=True, claude=True, write=False)
            if step == "refuse-held":
                self.assertEqual(code, 2)  # nothing is held, so nothing would be attempted
                continue
            self.assertEqual(code, 0, self.text)
            for result in results:
                self.assertTrue(result["dry_run"])
                self.assertTrue(result["would_read"] and result["would_write"])
                self.assertEqual(result["backup_to"], str(self.backup))
            self.assertEqual((self.codex_state(), self.claude_state(), self.snapshot_dirs("codex", CODEX_CHAT)), before)

    def test_a_dry_run_in_a_fresh_home_creates_no_folders(self):
        code, result = self.one("add", codex=True, write=False, backup=False)
        self.assertEqual(code, 0)
        self.assertEqual(result["backup_to"], str(self.repo / ".baton-spike" / "backup" / "20261014T093000Z"))
        self.assertFalse((self.repo / ".baton-spike").exists())
        self.assertFalse((self.root / ".baton-rollback").exists())
        self.assertFalse((self.root / ".codex" / "thread-writer-locks").exists())

    def test_refuse_held_is_not_attempted_without_yes_write(self):
        self.codex_process.hold(CODEX_CHAT)
        before = self.codex_state()
        code, result = self.one("refuse-held", codex=True, write=False)
        self.assertEqual((code, result["dry_run"]), (0, True))
        self.assertEqual(self.codex_state(), before)
        self.assertFalse(self.backup.exists())


class CodexStepTests(LiveScriptCase):
    def test_add_makes_the_backup_first_then_one_turn_that_reads_back(self):
        original = self.codex_state()
        seen = {}

        def wrap(tool, adapter):
            real = adapter.writer.add

            def add(chat_id, new_turns):
                snapshot = next((self.backup / ("codex-" + CODEX_CHAT)).iterdir())
                seen["backup_bytes"] = (snapshot / "rollout.bak").read_bytes()
                seen["row"] = json.loads((snapshot / "row.json").read_text())
                seen["file_still_untouched"] = self.codex_path().read_bytes() == original[0]
                return real(chat_id, new_turns)
            adapter.writer.add = add
        self.wrap_add = wrap
        code, result = self.one("add", codex=True)
        self.assertEqual((code, result["ok"]), (0, True), self.text)
        self.assertEqual(seen["backup_bytes"], original[0])
        self.assertEqual([seen["row"][name] for name in self.column_names()], list(original[1]))
        self.assertTrue(seen["file_still_untouched"])
        word = result["codeword"]
        self.assertEqual((result["turns_before"], result["turns_after"]), (4, 5))
        self.assertTrue(all(result["checks"].values()))
        with no_processes():
            adapter = self.factory("codex", self.root, CODEX_CHAT, True)
        last = adapter.reader.read(CODEX_CHAT)[-1]
        self.assertEqual((last.prompt.text, last.reply_text), ("Baton live test turn " + word, "Acknowledged " + word))
        self.assertEqual(self.snapshot_dirs("codex", CODEX_CHAT), ["01-add"])
        self.assertFalse(self.lock_file().exists())

    def columns(self):
        return fx.run_sql(self.root, "PRAGMA table_info(threads)")

    def column_names(self):
        return [row[1] for row in self.columns()]

    def lock_file(self):
        return fx.home(self.root) / "thread-writer-locks" / (CODEX_CHAT + ".lock")

    def test_add_then_take_back_leaves_the_file_byte_identical(self):
        original = self.codex_state()
        code, added = self.one("add", codex=True)
        self.assertEqual(code, 0, self.text)
        self.assertNotEqual(self.codex_state()[0], original[0])
        code, back = self.one("take-back", codex=True)
        self.assertEqual((code, back["ok"]), (0, True), self.text)
        self.assertEqual(back["bytes_equal_to_backup"], {"rollout": True, "thread_row": True})
        self.assertEqual(self.codex_state(), original)
        code, again = self.one("take-back", codex=True)
        self.assertEqual((code, again["refused"]), (2, "no_add_to_take_back"))

    def test_take_back_and_restore_find_the_newest_default_backup_folder(self):
        original = self.codex_state()
        self.assertEqual(self.one("add", codex=True, backup=False)[0], 0)
        folder = self.repo / ".baton-spike" / "backup" / "20261014T093000Z"
        self.assertTrue(folder.is_dir())
        code, back = self.one("take-back", codex=True, backup=False)
        self.assertEqual((code, back["ok"]), (0, True), self.text)
        self.assertEqual(self.codex_state(), original)

    def test_restore_puts_back_the_oldest_backup_byte_for_byte_when_not_held(self):
        original = self.codex_state()
        self.one("add", codex=True)
        self.one("add", codex=True)
        self.one("rename", codex=True)
        self.assertNotEqual(self.codex_state(), original)
        code, result = self.one("restore", codex=True)
        self.assertEqual((code, result["ok"]), (0, True), self.text)
        self.assertEqual(sorted(result["restored"]), ["rollout", "thread_row"])
        self.assertEqual(self.codex_state(), original)
        code, result = self.one("restore", codex=True)
        self.assertEqual((code, result["ok"], result["restored"]), (0, True, []))
        self.assertFalse(self.lock_file().exists())

    def test_restore_warns_when_codex_has_read_past_the_restored_file(self):
        self.one("add", codex=True)
        fx.set_index_offset(self.root, CODEX_CHAT, self.codex_path().stat().st_size)
        code, result = self.one("restore", codex=True)
        self.assertEqual(code, 0)
        self.assertEqual(result["warning"], "codex_index_is_past_the_restored_file")

    def test_a_held_chat_blocks_add_take_back_rename_and_restore(self):
        self.one("add", codex=True)
        self.codex_process.hold(CODEX_CHAT)
        before = self.codex_state()
        dirs = self.snapshot_dirs("codex", CODEX_CHAT)
        for step in ("add", "take-back", "rename", "restore"):
            with self.subTest(step=step):
                code, result = self.one(step, codex=True)
                self.assertEqual((code, result["refused"], result["problems"]), (2, "not_idle", ["held"]))
        self.assertEqual(self.codex_state(), before)
        self.assertEqual(self.snapshot_dirs("codex", CODEX_CHAT), dirs)

    def test_a_lock_taken_after_the_script_looked_still_stops_a_restore(self):
        self.one("add", codex=True)
        before = self.codex_state()

        def late(tool, adapter):
            real = adapter.state.condition

            def condition(chat_id):
                answer = real(chat_id)
                self.codex_process.hold(CODEX_CHAT)
                return answer
            adapter.state.condition = condition
        self.wrap_add = late
        code, result = self.one("restore", codex=True)
        self.assertEqual((code, result["refused"]), (2, "not_idle"))
        self.assertEqual(self.codex_state(), before)

    def test_a_replying_chat_is_refused(self):
        fx.append_event(self.root, CODEX_CHAT, {"type": "task_started", "turn_id": "live"})
        before = self.codex_state()
        code, result = self.one("add", codex=True)
        self.assertEqual((code, result["problems"]), (2, ["replying"]))
        self.assertEqual(self.codex_state(), before)
        self.assertFalse(self.backup.exists())

    def test_rename_and_its_way_back(self):
        code, result = self.one("rename", codex=True)
        self.assertEqual((code, result["ok"]), (0, True), self.text)
        self.assertEqual(thread_row(self.root, CODEX_CHAT)[self.column("title")], live.RENAMED)
        self.assertEqual(self.one("inspect", codex=True)[0], 0)
        code, result = self.one("rename-back", codex=True)
        self.assertEqual((code, result["ok"]), (0, True), self.text)
        self.assertEqual(thread_row(self.root, CODEX_CHAT)[self.column("name")], live.TITLE)
        self.assertEqual(self.snapshot_dirs("codex", CODEX_CHAT), ["01-rename", "02-rename-back"])

    def column(self, name):
        return self.column_names().index(name)

    def test_refuse_held_expects_the_refusal_and_writes_nothing(self):
        self.codex_process.hold(CODEX_CHAT)
        before = self.codex_state()
        code, result = self.one("refuse-held", codex=True)
        self.assertEqual((code, result["ok"], result["refused_with"], result["files_unchanged"]), (0, True, "ChatHeld", True))
        self.assertEqual(self.codex_state(), before)
        self.assertTrue((self.backup / ("codex-" + CODEX_CHAT) / "01-refuse-held" / "rollout.bak").is_file())

    def test_refuse_held_on_a_chat_that_is_not_held_attempts_nothing(self):
        before = self.codex_state()
        code, result = self.one("refuse-held", codex=True)
        self.assertEqual((code, result["refused"]), (2, "chat_is_not_held"))
        self.assertEqual(self.codex_state(), before)
        self.assertFalse(self.backup.exists())

    def test_inspect_reports_types_and_counts_but_no_text(self):
        fx.set_index_offset(self.root, CODEX_CHAT, 123)
        code, result = self.one("inspect", codex=True, write=False)
        self.assertEqual(code, 0, self.text)
        self.assertEqual((result["format_known"], result["held"], result["replying"], result["turn_count"], result["index_offset"]),
                         (True, False, False, 4, 123))
        self.assertEqual(result["record_types"]["event_msg/task_started"], 4)
        self.assertEqual(result["record_types"]["session_meta"], 1)
        for secret in ("zebra-secret-prompt", "zebra-secret-reply", "second", "answer", "finished"):
            self.assertNotIn(secret, self.text)
        self.assertFalse(self.backup.exists())
        self.assertFalse((self.root / ".baton-rollback").exists())
        self.codex_process.hold(CODEX_CHAT)
        self.assertTrue(self.one("inspect", codex=True)[1]["held"])

    def test_an_unexpected_error_is_printed_nothing_more_is_written_and_the_exit_is_not_zero(self):
        def explode(tool, adapter):
            def add(*args, **kwargs):
                raise RuntimeError("boom")
            adapter.writer.add = add
        self.wrap_add = explode
        claude_before = self.claude_state()
        code, results, error = self.run_script("add", codex=True, claude=True)
        self.assertEqual(code, 1)
        self.assertIn("RuntimeError: boom", error)
        self.assertEqual(len(results), 1)
        self.assertIn("RuntimeError: boom", results[0]["unexpected_error"])
        self.assertEqual(self.claude_state(), claude_before)
        self.assertEqual(self.snapshot_dirs("claude", CLAUDE_CHAT), [])


class ClaudeStepTests(LiveScriptCase):
    def test_add_then_take_back_leaves_both_files_byte_identical(self):
        original = self.claude_state()
        code, added = self.one("add", claude="session")
        self.assertEqual((code, added["ok"], added["chat"]), (0, True, CLAUDE_CHAT), self.text)
        self.assertNotEqual(self.claude_state()[0], original[0])
        code, back = self.one("take-back", claude=True)
        self.assertEqual((code, back["ok"]), (0, True), self.text)
        self.assertEqual(self.claude_state(), original)

    def test_the_backup_exists_before_the_write(self):
        original = self.claude_state()
        seen = {}

        def wrap(tool, adapter):
            real = adapter.writer.add

            def add(chat_id, new_turns):
                snapshot = next((self.backup / ("claude-" + CLAUDE_CHAT)).iterdir())
                seen["files"] = ((snapshot / "session.bak").read_bytes(), (snapshot / "sidebar.bak").read_bytes())
                return real(chat_id, new_turns)
            adapter.writer.add = add
        self.wrap_add = wrap
        self.assertEqual(self.one("add", claude=True)[0], 0)
        self.assertEqual(seen["files"], original)

    def test_a_chat_the_app_holds_is_refused_and_refuse_held_sees_it(self):
        self.hold_claude()
        before = self.claude_state()
        code, result = self.one("add", claude=True)
        self.assertEqual((code, result["problems"]), (2, ["held"]))
        code, result = self.one("refuse-held", claude=True)
        self.assertEqual((code, result["ok"], result["refused_with"]), (0, True, "ChatHeld"), self.text)
        self.assertEqual(self.claude_state(), before)

    def test_restore_after_a_rename_while_the_app_is_closed(self):
        original = self.claude_state()
        code, result = self.one("rename", claude=True)
        self.assertEqual((code, result["ok"]), (0, True), self.text)
        self.assertNotEqual(self.claude_state(), original)
        self.claude_process.is_running = True
        code, result = self.one("restore", claude=True)
        self.assertEqual((code, result["refused"]), (2, "app_running_and_sidebar_differs"))
        self.claude_process.is_running = False
        code, result = self.one("restore", claude=True)
        self.assertEqual((code, result["ok"]), (0, True), self.text)
        self.assertEqual(self.claude_state(), original)

    def test_rename_is_refused_by_the_adapter_while_the_app_runs(self):
        self.claude_process.is_running = True
        before = self.claude_state()
        code, result = self.one("rename", claude=True)
        self.assertEqual((code, result["refused"], result["error"]), (2, "adapter", "AppMustBeClosed"))
        self.assertEqual(self.claude_state(), before)

    def test_inspect_counts_record_types_only(self):
        code, result = self.one("inspect", claude=True)
        self.assertEqual(code, 0, self.text)
        self.assertEqual((result["turn_count"], result["held"], result["format_known"]), (3, False, True))
        self.assertEqual(result["record_types"], {"assistant": 4, "user": 4})
        self.assertNotIn("finished", self.text)

    def test_both_chats_in_one_call_print_one_result_each(self):
        code, results, _ = self.run_script("inspect", codex=True, claude=True)
        self.assertEqual((code, [r["tool"] for r in results]), (0, ["codex", "claude"]))


class SourceRulesTests(unittest.TestCase):
    def test_the_script_is_outside_the_package_and_uses_only_the_standard_library_and_baton(self):
        self.assertNotIn("baton", SCRIPT.relative_to(SCRIPT.parents[2]).parts[:1])
        text = SCRIPT.read_text()
        self.assertNotIn("subprocess", text)
        self.assertNotIn("import requests", text)


if __name__ == "__main__":
    unittest.main()
