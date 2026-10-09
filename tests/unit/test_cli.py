"""C1: wiring, the adapter registry, the plan store and the command line's own behaviour."""
import io
import json
import os
import fcntl
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from baton.adapters.fake import FakeAdapter
from baton.adapters.fake.facts import CLAUDE_LIKE
from baton.cli import wiring
from baton.cli.commands import Command, CommandRegistry, discover
from baton.cli.main import main
from baton.cli.plans import FilePlanStore, MemoryPlanStore, PlanBook, StoredPlan
from baton.cli.tools import TOOLS, ToolEntry, label
from baton.domain.errors import ChatChanged, NotAvailable
from baton.ports.clock import FixedClock


class Temporary(unittest.TestCase):
    def setUp(self):
        # An inherited BATON_HOME or BATON_TOOLS_HOME must not steer any test.
        environment = patch.dict("os.environ")
        environment.start()
        self.addCleanup(environment.stop)
        for name in (wiring.HOME_VARIABLE, wiring.TOOLS_HOME_VARIABLE):
            os.environ.pop(name, None)
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()


class WhereBatonLives(Temporary):
    def test_default_is_application_support(self):
        self.assertEqual(wiring.resolve_root(None, {}, self.root),
                         (self.root / "Library/Application Support/Baton", False))

    def test_baton_home_overrides_the_default(self):
        self.assertEqual(wiring.resolve_root(None, {"BATON_HOME": "/x/y"}, self.root), (Path("/x/y"), True))

    def test_an_argument_beats_baton_home(self):
        self.assertEqual(wiring.resolve_root("/a", {"BATON_HOME": "/x/y"}), (Path("/a"), True))

    def test_an_empty_baton_home_is_ignored(self):
        self.assertFalse(wiring.resolve_root(None, {"BATON_HOME": ""}, self.root)[1])

    def test_tools_are_looked_for_in_the_users_home_only_by_default(self):
        default = wiring.resolve_tools_home(self.root, False, environ={}, home=Path("/Users/me"))
        explicit = wiring.resolve_tools_home(self.root, True, environ={}, home=Path("/Users/me"))
        self.assertEqual((default, explicit), (Path("/Users/me"), self.root / "tools"))

    def test_the_tools_home_can_be_chosen(self):
        self.assertEqual(wiring.resolve_tools_home(self.root, True, "/t", {}), Path("/t"))
        self.assertEqual(wiring.resolve_tools_home(self.root, True, None, {"BATON_TOOLS_HOME": "/e"}), Path("/e"))

    def test_build_creates_the_store_in_the_given_folder(self):
        engine = wiring.build(self.root / "new" / "folder")
        self.addCleanup(engine.close)
        self.assertTrue((self.root / "new/folder/baton.sqlite").is_file())
        self.assertEqual(engine.store.links(), [])

    def test_existing_storage_and_ledger_are_made_private(self):
        folder = self.root / "loose"
        folder.mkdir(mode=0o755)
        database = folder / wiring.STORE_FILE
        database.touch(mode=0o644)
        engine = wiring.build(folder, adapters={})
        self.addCleanup(engine.close)
        self.assertEqual(folder.stat().st_mode & 0o777, 0o700)
        self.assertEqual(database.stat().st_mode & 0o777, 0o600)

    def test_symlinked_storage_directory_is_refused(self):
        target = self.root / "target"
        target.mkdir(mode=0o755)
        link = self.root / "linked"
        link.symlink_to(target, target_is_directory=True)
        with self.assertRaises(OSError):
            wiring.build(link, adapters={})
        self.assertEqual(target.stat().st_mode & 0o777, 0o755)
        self.assertEqual(list(target.iterdir()), [])

    def test_symlinked_or_hardlinked_ledger_is_refused(self):
        outside = self.root / "outside"
        outside.write_text("keep this file")
        for kind in ("symlink", "hardlink"):
            with self.subTest(kind=kind):
                folder = self.root / kind
                folder.mkdir()
                database = folder / wiring.STORE_FILE
                if kind == "symlink":
                    database.symlink_to(outside)
                else:
                    os.link(outside, database)
                with self.assertRaises(OSError):
                    wiring.build(folder, adapters={})
                self.assertEqual(outside.read_text(), "keep this file")

    def test_storage_with_another_owner_is_refused_before_chmod(self):
        with patch("baton.cli.storage.os.getuid", return_value=os.getuid() + 1):
            with self.assertRaises(PermissionError):
                wiring.build(self.root, adapters={})

    def test_build_honours_baton_home_from_the_environment(self):
        engine = wiring.build(environ={"BATON_HOME": str(self.root / "home")})
        self.addCleanup(engine.close)
        self.assertEqual(engine.root, self.root / "home")
        self.assertTrue((self.root / "home/baton.sqlite").is_file())

    def test_build_reads_baton_home_from_the_real_environment(self):
        with patch.dict("os.environ", {"BATON_HOME": str(self.root / "real")}):
            engine = wiring.build()
        self.addCleanup(engine.close)
        self.assertEqual(engine.root, self.root / "real")

    def test_an_inherited_tools_home_cannot_override_a_root_passed_in_code(self):
        with patch.dict("os.environ", {wiring.TOOLS_HOME_VARIABLE: str(self.root / "real chats")}):
            engine = wiring.build(self.root / "baton")
        self.addCleanup(engine.close)
        self.assertEqual(engine.tools_home, self.root / "baton" / "tools")
        self.assertEqual(engine.adapters["claude"].root, self.root / "baton" / "tools")

    def test_the_tools_home_variable_is_honoured_for_a_trial_run_through_baton_home(self):
        environ = {wiring.HOME_VARIABLE: str(self.root / "baton"), wiring.TOOLS_HOME_VARIABLE: str(self.root / "trial")}
        engine = wiring.build(environ=environ)
        self.addCleanup(engine.close)
        self.assertEqual(engine.adapters["claude"].root, self.root / "trial")

    def test_these_tests_start_without_the_steering_variables(self):
        self.assertNotIn(wiring.HOME_VARIABLE, os.environ)
        self.assertNotIn(wiring.TOOLS_HOME_VARIABLE, os.environ)

    def test_a_temporary_root_keeps_the_adapters_out_of_the_real_home(self):
        engine = wiring.build(self.root)
        self.addCleanup(engine.close)
        self.assertEqual(engine.tools_home, self.root / "tools")
        self.assertEqual(engine.adapters["claude"].root, self.root / "tools")
        self.assertNotIn(str(Path.home()), str(engine.adapters["claude"].root))

    def test_adapter_roots_can_be_injected(self):
        engine = wiring.build(self.root, adapter_roots={"claude": self.root / "elsewhere"})
        self.addCleanup(engine.close)
        self.assertEqual(engine.adapters["claude"].root, self.root / "elsewhere")

    def test_adapters_can_be_replaced_altogether(self):
        fake = FakeAdapter(CLAUDE_LIKE, "claude")
        engine = wiring.build(self.root, adapters={"claude": fake})
        self.addCleanup(engine.close)
        self.assertEqual(engine.adapters, {"claude": fake})
        self.assertIs(engine.adapter("claude"), fake)
        with self.assertRaises(NotAvailable):
            engine.adapter("codex")

    def test_services_are_built_when_first_used_and_only_once(self):
        engine = wiring.build(self.root, adapters={"claude": FakeAdapter(CLAUDE_LIKE, "claude")})
        self.addCleanup(engine.close)
        self.assertNotIn("linker", vars(engine))
        self.assertIs(engine.linker, engine.linker)
        self.assertIs(engine.linker.store, engine.store)
        for service in (engine.applier, engine.merger, engine.undo):
            self.assertIs(service.store, engine.store)

    def test_the_clock_is_shared_with_the_services_and_the_plans(self):
        clock = FixedClock("2026-10-05T00:00:00Z")
        engine = wiring.build(self.root, clock=clock, adapters={})
        self.addCleanup(engine.close)
        self.assertIs(engine.linker.clock, clock)
        self.assertIs(engine.plans.clock, clock)


class TheAdapterRegistry(Temporary):
    def load(self, *entries):
        return wiring.load_adapters(entries, self.root / "tools")

    def test_claude_is_wired(self):
        adapters, unavailable = self.load(TOOLS[0])
        self.assertEqual((list(adapters), unavailable), (["claude"], {}))

    def test_the_four_tools_have_their_labels(self):
        self.assertEqual([entry.id for entry in TOOLS], ["claude", "codex", "opencode", "cursor"])
        self.assertEqual([entry.label for entry in TOOLS], ["Claude", "Codex", "OpenCode", "Cursor"])
        self.assertEqual(label("somewhere"), "somewhere")

    def test_a_tool_without_an_adapter_yet_is_left_out(self):
        entry = ToolEntry("codex", "Codex", "baton.adapters.not_written.tool", "CodexAdapter")
        adapters, unavailable = self.load(entry)
        self.assertEqual((adapters, unavailable), ({}, {"codex": "not built yet"}))

    def test_the_default_registry_never_fails_for_tools_still_to_come(self):
        adapters, unavailable = wiring.load_adapters(TOOLS, self.root)
        self.assertIn("claude", adapters)
        self.assertEqual(set(adapters) | set(unavailable), {"claude", "codex", "opencode", "cursor"})

    def with_module(self, adapter):
        module = types.ModuleType("baton_test_adapter_module")
        module.Adapter = adapter
        patcher = patch.dict(sys.modules, {module.__name__: module})
        patcher.start()
        self.addCleanup(patcher.stop)
        return ToolEntry("codex", "Codex", module.__name__, "Adapter", home=".codex")

    def test_an_adapter_that_exists_is_given_its_root(self):
        class Adapter:
            name = "codex"

            def __init__(self, root):
                self.root = root
        adapters, unavailable = self.load(self.with_module(Adapter))
        self.assertEqual((adapters["codex"].root, unavailable), (self.root / "tools" / ".codex", {}))

    def test_one_root_can_be_set_for_one_tool(self):
        class Adapter:
            name = "codex"

            def __init__(self, root):
                self.root = root
        adapters, _ = wiring.load_adapters([self.with_module(Adapter)], self.root, {"codex": self.root / "x"})
        self.assertEqual(adapters["codex"].root, self.root / "x")

    def test_an_adapter_that_cannot_be_built_is_reported_not_raised(self):
        class Broken:
            name = "codex"
        with self.assertLogs("baton.cli.wiring", "WARNING"):
            adapters, unavailable = self.load(self.with_module(Broken))
        self.assertEqual(adapters, {})
        self.assertTrue(unavailable["codex"].startswith("TypeError"))

    def test_ordinary_constructor_failures_leave_other_tools_available(self):
        for failure in (PermissionError, OSError, ValueError, RuntimeError):
            with self.subTest(failure=failure):
                class Broken:
                    def __init__(self, root):
                        raise failure("not usable")
                with self.assertLogs("baton.cli.wiring", "WARNING"):
                    adapters, unavailable = self.load(TOOLS[0], self.with_module(Broken))
                self.assertEqual(list(adapters), ["claude"])
                self.assertTrue(unavailable["codex"].startswith(failure.__name__))

    def test_interrupts_are_never_swallowed_as_unavailable_adapters(self):
        class Interrupted:
            def __init__(self, root):
                raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.load(self.with_module(Interrupted))

    def test_an_adapter_with_another_name_is_not_wired_as_this_tool(self):
        class Other:
            name = "cursor"

            def __init__(self, root):
                pass
        with self.assertLogs("baton.cli.wiring", "WARNING"):
            adapters, unavailable = self.load(self.with_module(Other))
        self.assertEqual(adapters, {})
        self.assertIn("cursor", unavailable["codex"])

    def test_a_module_without_the_class_is_reported(self):
        entry = ToolEntry("codex", "Codex", "baton.cli.tools", "NoSuchAdapter")
        with self.assertLogs("baton.cli.wiring", "WARNING"):
            adapters, unavailable = self.load(entry)
        self.assertEqual(adapters, {})
        self.assertIn("NoSuchAdapter", unavailable["codex"])


def stored(plan_id="p_abc", fingerprint="p_fingerprint", command="link", arguments=None, at="2026-10-05T10:00:00Z"):
    return StoredPlan(plan_id, fingerprint, command, {"from": "claude:1"} if arguments is None else arguments, at)


class ThePlanStore(Temporary):
    def stores(self):
        return {"memory": MemoryPlanStore(), "file": FilePlanStore(self.root / "plans")}

    def test_both_stores_keep_load_claim_and_delete(self):
        plan = stored()
        for name, store in self.stores().items():
            with self.subTest(store=name):
                self.assertIsNone(store.load("p_abc"))
                store.save(plan)
                self.assertEqual(store.load("p_abc"), plan)
                self.assertEqual(store.all(), [plan])
                self.assertEqual(store.claim("p_abc"), plan)
                self.assertIsNone(store.claim("p_abc"))
                store.save(plan)
                store.delete("p_abc")
                store.delete("p_abc")
                self.assertEqual((store.load("p_abc"), store.all()), (None, []))

    def test_only_one_of_many_simultaneous_claims_gets_the_plan(self):
        store = FilePlanStore(self.root / "plans")
        for round_ in range(20):
            store.save(stored("p_race%d" % round_))
            gate = threading.Barrier(8)
            winners = []

            def claim():
                gate.wait()
                winners.append(store.claim("p_race%d" % round_))
            threads = [threading.Thread(target=claim) for _ in range(8)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertEqual(len([plan for plan in winners if plan is not None]), 1, round_)
        self.assertEqual(os.listdir(self.root / "plans"), [])

    def test_the_file_store_refuses_ids_that_are_not_plan_ids(self):
        store = FilePlanStore(self.root / "plans")
        with self.assertRaises(ValueError):
            store.save(stored("../escape"))
        for operation in (store.load, store.claim):
            self.assertIsNone(operation("../escape"))
        store.delete("../escape")

    def test_the_file_store_creates_a_private_folder_and_private_files(self):
        store = FilePlanStore(self.root / "plans")
        store.save(stored())
        self.assertEqual((self.root / "plans").stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.root / "plans" / "p_abc.json").stat().st_mode & 0o777, 0o600)

    def test_a_folder_that_was_too_open_is_closed_again(self):
        (self.root / "plans").mkdir(mode=0o755)
        os.chmod(self.root / "plans", 0o755)
        FilePlanStore(self.root / "plans").save(stored())
        self.assertEqual((self.root / "plans").stat().st_mode & 0o777, 0o700)

    def test_a_plans_folder_that_is_a_link_is_refused_and_never_written_through(self):
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        FilePlanStore(elsewhere).save(stored("p_there"))
        (self.root / "plans").symlink_to(elsewhere)
        store = FilePlanStore(self.root / "plans")
        with self.assertRaises(OSError):
            store.save(stored("p_new"))
        self.assertEqual((store.load("p_there"), store.claim("p_there"), store.all()), (None, None, []))
        store.delete("p_there")
        self.assertEqual(os.listdir(elsewhere), ["p_there.json"])

    def test_a_plan_file_that_is_a_link_is_never_followed(self):
        store = FilePlanStore(self.root / "plans")
        store.save(stored("p_real"))
        outside = self.root / "outside.json"
        outside.write_text((self.root / "plans" / "p_real.json").read_text().replace("p_real", "p_link"))
        (self.root / "plans" / "p_link.json").symlink_to(outside)
        self.assertEqual((store.load("p_link"), store.claim("p_link")), (None, None))
        self.assertTrue(outside.is_file())
        self.assertEqual(os.listdir(self.root / "plans"), ["p_real.json"])

    def test_saving_over_a_link_replaces_the_link_not_its_target(self):
        store = FilePlanStore(self.root / "plans")
        store.save(stored("p_other"))
        outside = self.root / "outside.txt"
        outside.write_text("keep")
        (self.root / "plans" / "p_abc.json").symlink_to(outside)
        store.save(stored())
        self.assertEqual(outside.read_text(), "keep")
        self.assertEqual(store.load("p_abc"), stored())

    def test_a_file_that_is_not_a_valid_plan_is_not_kept(self):
        store = FilePlanStore(self.root / "plans")
        store.save(stored("p_good"))
        good = json.loads((self.root / "plans" / "p_good.json").read_text())
        broken = {
            "other id": {**good, "plan_id": "p_other"},
            "missing field": {key: value for key, value in good.items() if key != "fingerprint"},
            "extra field": {**good, "x": 1},
            "id not text": {**good, "plan_id": 5},
            "fingerprint not text": {**good, "fingerprint": ["p_x"]},
            "command not text": {**good, "command": None},
            "arguments not an object": {**good, "arguments": ["a"]},
            "time not text": {**good, "stored_at": 12},
            "not an object": ["p_good"],
        }
        for name, content in broken.items():
            with self.subTest(name):
                (self.root / "plans" / "p_bad.json").write_text(json.dumps(content))
                self.assertEqual((store.load("p_bad"), store.claim("p_bad")), (None, None))
        for text in ("{not json", "", "\x00\x01"):
            (self.root / "plans" / "p_bad.json").write_text(text)
            self.assertEqual((store.load("p_bad"), store.claim("p_bad")), (None, None))
        (self.root / "plans" / "p_bad.json").write_bytes(b"\xff\xfe")
        self.assertEqual((store.load("p_bad"), store.claim("p_bad")), (None, None))
        self.assertEqual([plan.plan_id for plan in store.all()], ["p_good"])

    def test_the_file_store_leaves_no_temporary_files(self):
        store = FilePlanStore(self.root / "plans")
        store.save(stored("p_a"))
        self.assertEqual(os.listdir(self.root / "plans"), ["p_a.json"])


class ThePlanBook(unittest.TestCase):
    def setUp(self):
        self.clock = FixedClock("2026-10-05T10:00:00Z")
        self.book = PlanBook(MemoryPlanStore(), self.clock)

    def test_lifetime_is_ten_minutes_by_default(self):
        self.assertEqual(self.book.lifetime, timedelta(minutes=10))

    def test_every_preview_gets_a_new_confirmation_id_apart_from_the_fingerprint(self):
        first = self.book.remember("p_service", "sync", {"link": 3})
        second = self.book.remember("p_service", "sync", {"link": 4})
        self.assertEqual(len({first, second, "p_service"}), 3)
        self.assertEqual(self.book.store.load(first).arguments, {"link": 3})
        self.assertEqual(self.book.store.load(second).arguments, {"link": 4})
        self.assertEqual(self.book.store.load(first).fingerprint, "p_service")

    def test_a_preview_cannot_overwrite_or_revive_another_by_having_the_same_fingerprint(self):
        first = self.book.remember("p_service", "sync", {"link": 3})
        self.book.confirm(first, "sync", lambda arguments: "p_service")
        self.book.remember("p_service", "sync", {"link": 9})
        with self.assertRaises(ChatChanged):
            self.book.confirm(first, "sync", lambda arguments: "p_service")

    def test_confirming_plans_the_stored_request_again(self):
        shown = self.book.remember("p_1", "sync", {"link": 3})
        seen = []

        def plan_again(arguments):
            seen.append(dict(arguments))
            return "p_1"
        self.assertEqual(self.book.confirm(shown, "sync", plan_again).arguments, {"link": 3})
        self.assertEqual(seen, [{"link": 3}])

    def test_a_different_fingerprint_means_the_chats_changed(self):
        shown = self.book.remember("p_1", "sync", {"link": 3})
        with self.assertRaises(ChatChanged):
            self.book.confirm(shown, "sync", lambda arguments: "p_2")

    def test_a_plan_is_used_up_by_being_claimed_whatever_happens_next(self):
        for outcome in ("stale", "changed", "crash", "done"):
            with self.subTest(outcome):
                shown = self.book.remember("p_1", "sync", {})

                def plan_again(arguments):
                    if outcome == "changed":
                        raise ChatChanged()
                    if outcome == "crash":
                        raise RuntimeError("planning broke")
                    return "p_2" if outcome == "stale" else "p_1"
                try:
                    self.book.confirm(shown, "sync", plan_again)
                except (ChatChanged, RuntimeError):
                    pass
                self.assertEqual(self.book.store.all(), [])
                with self.assertRaises(ChatChanged):
                    self.book.confirm(shown, "sync", lambda arguments: "p_1")

    def test_of_two_confirmations_only_one_plans_and_applies(self):
        shown = self.book.remember("p_1", "sync", {})
        planned = []

        def plan_again(arguments):
            planned.append(1)
            return "p_1"
        self.book.confirm(shown, "sync", plan_again)
        with self.assertRaises(ChatChanged):
            self.book.confirm(shown, "sync", plan_again)
        self.assertEqual(len(planned), 1)

    def test_another_commands_plan_cannot_be_confirmed(self):
        shown = self.book.remember("p_1", "sync", {})
        with self.assertRaises(ChatChanged):
            self.book.confirm(shown, "unlink", lambda arguments: "p_1")

    def test_an_expired_plan_is_not_even_planned_again(self):
        shown = self.book.remember("p_1", "sync", {})
        self.clock.value = "2026-10-05T10:10:00+00:00"
        with self.assertRaises(ChatChanged):
            self.book.confirm(shown, "sync", lambda arguments: self.fail("planned an expired request"))

    def test_a_plan_that_runs_out_while_it_is_planned_again_is_refused(self):
        shown = self.book.remember("p_1", "sync", {})

        def slow(arguments):
            self.clock.value = "2026-10-05T10:10:00Z"
            return "p_1"
        with self.assertRaises(ChatChanged):
            self.book.confirm(shown, "sync", slow)

    def test_remembering_drops_expired_plans(self):
        old = self.book.remember("p_old", "sync", {})
        self.clock.value = "2026-10-05T11:00:00Z"
        new = self.book.remember("p_new", "sync", {})
        self.assertEqual([plan.plan_id for plan in self.book.store.all()], [new])
        self.assertIsNone(self.book.store.load(old))

    def test_a_plan_with_an_unreadable_time_is_expired(self):
        self.book.store.save(stored("p_1", command="sync", at="yesterday"))
        with self.assertRaises(ChatChanged):
            self.book.confirm("p_1", "sync", lambda arguments: "p_fingerprint")

    def test_a_damaged_file_in_the_file_store_is_a_refusal(self):
        with tempfile.TemporaryDirectory() as folder:
            book = PlanBook(FilePlanStore(Path(folder) / "plans"), self.clock)
            shown = book.remember("p_1", "sync", {})
            (Path(folder) / "plans" / (shown + ".json")).write_text(json.dumps({"plan_id": "p_other"}))
            with self.assertRaises(ChatChanged):
                book.confirm(shown, "sync", lambda arguments: "p_1")


class TheCommandLine(Temporary):
    def setUp(self):
        super().setUp()
        self.registry = CommandRegistry()
        self.calls = []

        @self.registry.command("setup", "check every tool")
        def setup(ctx, args):
            self.calls.append(("setup", ctx.dry_run, ctx.confirm))
            return {"tools": []}

        @self.registry.command("setup install", "install hooks", arguments=lambda p: p.add_argument("--tool", required=True))
        def install(ctx, args):
            self.calls.append(("install", args.tool))
            return {"tool": args.tool}

        @self.registry.command("sync", "deliver waiting turns", plan=True,
                               arguments=lambda p: p.add_argument("--link", type=int, required=True))
        def sync(ctx, args):
            self.calls.append(("sync", args.link, ctx.dry_run, ctx.confirm))
            return {"link_id": args.link}

        @self.registry.command("catch-up", "print what the tool expects")
        def catch_up(ctx, args):
            return "plain text, not JSON"

        @self.registry.command("refuse", "an expected refusal")
        def refuse(ctx, args):
            raise ChatChanged()

        @self.registry.command("crash", "a bug")
        def crash(ctx, args):
            raise RuntimeError("bug")

    def call(self, *argv):
        out = io.StringIO()
        status = main(list(argv), registry=self.registry, stdout=out,
                      engine_factory=lambda: wiring.build(self.root, adapters={}))
        return status, out.getvalue()

    def test_a_command_prints_one_json_object(self):
        self.assertEqual(self.call("setup", "--json"), (0, '{"tools": []}\n'))

    def test_a_sub_command_is_found_next_to_its_parent_command(self):
        self.assertEqual(self.call("setup", "install", "--tool", "claude", "--json"), (0, '{"tool": "claude"}\n'))
        self.assertEqual(self.call("setup")[0], 0)
        self.assertEqual([call[0] for call in self.calls], ["install", "setup"])

    def test_dry_run_and_confirm_reach_a_plan_command(self):
        self.call("sync", "--link", "3", "--dry-run", "--json")
        self.call("sync", "--link", "3", "--confirm", "p_x")
        self.call("--dry-run", "sync", "--link", "3")
        self.call("sync", "--link", "3")
        self.assertEqual(self.calls, [("sync", 3, True, None), ("sync", 3, False, "p_x"),
                                      ("sync", 3, True, None), ("sync", 3, False, None)])

    def test_a_command_without_a_plan_takes_neither_flag(self):
        for argv in (("setup", "--dry-run"), ("setup", "--confirm", "p_1"), ("--dry-run", "setup")):
            with self.subTest(argv=argv):
                status, text = self.call(*argv)
                self.assertEqual((status, json.loads(text)["error"]["kind"]), (2, "usage"))
        self.assertEqual(self.calls, [])

    def test_a_missing_or_unknown_command_is_a_usage_error(self):
        for argv in ((), ("nothing",), ("sync",), ("sync", "--link", "x")):
            with self.subTest(argv=argv):
                status, text = self.call(*argv)
                self.assertEqual((status, json.loads(text)["error"]["kind"]), (2, "usage"))

    def test_a_command_may_print_text_instead(self):
        self.assertEqual(self.call("catch-up"), (0, "plain text, not JSON"))

    def test_an_expected_refusal_exits_zero_with_its_error_object(self):
        status, text = self.call("refuse")
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(text)["error"]["kind"], "chat_changed")

    def test_a_crash_exits_non_zero_and_is_internal(self):
        with self.assertLogs("baton.cli.main", "ERROR"):
            status, text = self.call("crash")
        self.assertEqual((status, json.loads(text)["error"]["kind"]), (1, "internal"))

    def test_the_store_is_closed_after_the_command(self):
        engines = []

        def factory():
            engines.append(wiring.build(self.root, adapters={}))
            return engines[-1]
        main(["setup"], registry=self.registry, stdout=io.StringIO(), engine_factory=factory)
        with self.assertRaises(Exception):
            engines[0].store.links()

    def test_another_process_cannot_enter_during_a_command_and_can_afterwards(self):
        probe = """
import fcntl, os, sys
fd = os.open(sys.argv[1], os.O_RDWR)
try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    print('blocked')
else:
    print('acquired')
finally:
    os.close(fd)
"""
        def try_lock():
            return subprocess.check_output([sys.executable, "-c", probe, str(self.root / "command.lock")],
                                           text=True, timeout=5).strip()
        def inside(ctx, args):
            self.assertEqual(try_lock(), "blocked")
            return {}
        self.registry.add(Command("locked", "x", inside))
        self.assertEqual(self.call("locked"), (0, "{}\n"))
        self.assertEqual(try_lock(), "acquired")

    def test_an_exception_releases_the_command_lock(self):
        with self.assertLogs("baton.cli.main", "ERROR"):
            self.call("crash")
        with (self.root / "command.lock").open("r+") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_a_symlinked_command_lock_is_refused_without_changing_its_target(self):
        target = self.root / "outside"
        target.write_text("untouched")
        (self.root / "command.lock").symlink_to(target)
        with self.assertLogs("baton.cli.main", "ERROR"):
            code, result = self.call("setup")
        self.assertEqual((code, json.loads(result)["error"]["kind"]), (1, "internal"))
        self.assertEqual(target.read_text(), "untouched")

    def test_help_prints_and_exits_zero_without_building_the_engine(self):
        def factory():
            raise AssertionError("no engine for --help")
        with patch("sys.stdout", new_callable=io.StringIO) as shown:
            status = main(["--help"], registry=self.registry, stdout=io.StringIO(), engine_factory=factory)
        self.assertEqual(status, 0)
        self.assertIn("sync", shown.getvalue())

    def test_a_command_module_that_does_not_import_prints_the_error_object_and_exits_one(self):
        out = io.StringIO()
        with patch("baton.cli.main.discover", side_effect=ImportError("broken command module /secret")):
            with self.assertLogs("baton.cli.main", "ERROR"):
                status = main(["links"], stdout=out)
        result = json.loads(out.getvalue())
        self.assertEqual((status, result["error"]["kind"], result["error"]["note"]["id"]), (1, "internal", "error.unexpected"))
        self.assertNotIn("secret", out.getvalue())

    def test_a_command_whose_arguments_cannot_be_defined_is_an_internal_error_too(self):
        def broken(parser):
            raise RuntimeError("bad argument definition")
        self.registry.add(Command("odd", "x", lambda ctx, args: {}, broken))
        out = io.StringIO()
        with self.assertLogs("baton.cli.main", "ERROR"):
            status = main(["odd"], registry=self.registry, stdout=out)
        self.assertEqual((status, json.loads(out.getvalue())["error"]["kind"]), (1, "internal"))

    def test_a_failing_engine_is_an_internal_error(self):
        def factory():
            raise OSError("disk")
        out = io.StringIO()
        with self.assertLogs("baton.cli.main", "ERROR"):
            status = main(["setup"], registry=self.registry, stdout=out, engine_factory=factory)
        result = json.loads(out.getvalue())["error"]
        self.assertEqual((status, result["kind"], result["note"]["id"]), (1, "internal", "error.unexpected"))


class TheCommandRegistry(unittest.TestCase):
    def test_a_name_can_be_registered_once(self):
        registry = CommandRegistry()
        command = Command("x", "x", lambda ctx, args: {})
        registry.add(command)
        with self.assertRaises(ValueError):
            registry.add(command)
        self.assertIs(registry.get("x"), command)
        self.assertEqual(list(registry), [command])

    def test_discovery_registers_the_commands_in_the_folder(self):
        registry = discover()
        self.assertIsNotNone(registry.get("links"))
        self.assertIs(discover(), registry)


if __name__ == "__main__":
    unittest.main()
