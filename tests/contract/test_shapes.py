"""C1: the shared objects have exactly the fields of CONTRACT.md, and the wiring keeps the contract's rules."""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from baton.adapters.fake import FakeAdapter
from baton.adapters.fake.facts import CLAUDE_LIKE, CODEX_LIKE
from baton.cli import output
from baton.cli.commands import CommandRegistry
from baton.cli.main import main
from baton.cli.wiring import build
from baton.domain.conditions import SideCondition
from baton.domain.errors import AlreadyDelivered, BatonError, ChatChanged, SetupIncomplete
from baton.domain.link import LedgerTurn
from baton.domain.model import Message, PROMPT, REPLY, TOOL_CALL, Turn
from baton.ports.clock import FixedClock
from baton.ports.tool import ChatRef, Usage
from baton.services.status import SideStatus
from baton.services.journal import Journal
from unittest.mock import patch
from tests.adapters.suite import turns

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "app" / "Fixtures"

NOTE = {"id", "tone", "values", "text", "buttons", "status_line"}
BUTTON = {"id", "label", "primary"}
CHAT = {"tool", "tool_label", "id", "name", "folder", "updated_at", "linked", "link_id"}
CONDITION = {"exists", "open", "replying", "hooks_ready", "app_running", "app_started_at", "format_known"}
TURN = {"id", "seq", "origin", "first_line", "started_at", "ended_at", "tokens", "pinned", "states"}
SIDE = {"tool", "tool_label", "chat", "condition", "total", "agent_has", "chat_shows", "added", "attached",
        "waiting", "kept_elsewhere", "skipped", "synced_up_to", "waiting_reason", "next_message", "usage",
        "since_you_left", "notes"}
STEP = {"tool", "tool_label", "action", "turns", "reason", "needs", "notes"}
PLAN = {"plan_id", "applied", "link_id", "steps", "decision_needed", "notes"}


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def ledger_turn(**values) -> LedgerTurn:
    defaults = dict(id=41, seq=14, origin="codex", origin_id="x", started_at="2026-10-04T14:00:00Z",
                    ended_at="2026-10-04T14:01:00Z", first_line="Fix the failing test", size=6400,
                    pinned=False, states={"claude": "waiting", "codex": "written_here"})
    return LedgerTurn(**{**defaults, **values})


def side_status(**values) -> SideStatus:
    defaults = dict(side="claude", total=16, agent_has=14, chat_shows=12, added=0, attached=2, waiting=2,
                    kept_elsewhere=0, skipped=0, synced_up_to=ledger_turn(), waiting_reason="chat_open",
                    attached_on_next_message=2, attached_tokens=3200)
    return SideStatus(**{**defaults, **values})


class SharedObjectShapes(unittest.TestCase):
    def test_note_has_exactly_its_fields_and_the_catalogue_wording(self):
        result = output.note("new_chat.relaunch", {"tool": "claude"})
        self.assertEqual(set(result), NOTE)
        self.assertEqual(set(fixture("note.sample.json")), NOTE)
        self.assertEqual(result["id"], "new_chat.relaunch")
        self.assertEqual(result["tone"], "info")
        self.assertEqual(result["status_line"], "Relaunch Claude to see this chat")
        self.assertEqual(result["buttons"][0], {"id": "close_sync_reopen", "label": "Close Claude, sync, reopen",
                                                "primary": True})
        for button in result["buttons"]:
            self.assertEqual(set(button), BUTTON)

    def test_note_without_buttons_or_status_line(self):
        result = output.note("status.in_sync")
        self.assertEqual((result["buttons"], result["status_line"], result["values"]), ([], None, {}))

    def test_note_values_naming_a_coding_app_carry_its_label(self):
        result = output.note("status.ahead", {"tool": "codex", "n": 2})
        self.assertEqual(result["values"], {"tool": "Codex", "n": 2})
        self.assertEqual(result["text"], "Codex is 2 turns ahead")
        merged = output.note("merge.header", {"first_tool": "claude", "first_count": 2,
                                              "second_tool": "opencode", "second_count": 1})
        self.assertEqual((merged["values"]["first_tool"], merged["values"]["second_tool"]), ("Claude", "OpenCode"))
        self.assertIn("OpenCode has 1", merged["text"])

    def test_every_tool_has_its_display_label(self):
        labels = {tool: output.chat(tool, "c", "n", "", "")["tool_label"] for tool in ("claude", "codex", "opencode", "cursor")}
        self.assertEqual(labels, {"claude": "Claude", "codex": "Codex", "opencode": "OpenCode", "cursor": "Cursor"})
        self.assertEqual(output.note("screen.continue", {"tool": "cursor"})["text"], "Continue in Cursor")

    def test_a_tool_call_name_is_not_a_coding_app_label(self):
        result = output.note("mapping.tool_call", {"n": 1, "tool": "claude", "input": "{}", "text": ""})
        self.assertEqual(result["values"]["tool"], "claude")
        self.assertTrue(result["text"].startswith("Tool call 1: claude"))

    def test_labelling_twice_changes_nothing(self):
        values = output.app_labels("status.ahead", {"tool": "claude"})
        self.assertEqual(output.app_labels("status.ahead", values), values)

    def test_missing_value_is_an_error_unless_lenient(self):
        with self.assertRaises(KeyError):
            output.note("status.ahead", {"tool": "claude"})
        self.assertEqual(output.note("status.ahead", {"tool": "claude"}, lenient=True)["text"], "Claude is  turns ahead")

    def test_chat_has_exactly_its_fields(self):
        result = output.chat_from_ref("claude", ChatRef("local_3b2", "Session sync tool", "/work", "2026-10-04T14:05:00Z"),
                                      linked=True, link_id=3)
        self.assertEqual(set(result), CHAT)
        self.assertEqual(set(fixture("chat.sample.json")) | {"link_id"}, CHAT)
        self.assertEqual((result["tool"], result["tool_label"], result["linked"], result["link_id"]),
                         ("claude", "Claude", True, 3))

    def test_unknown_times_are_empty_strings_because_the_app_models_need_strings(self):
        # app/Sources/BatonKit/Models/Shared.swift: Chat.updatedAt and Turn.startedAt are String,
        # Turn.endedAt is String?.
        self.assertEqual(output.chat("codex", "c", "n", "f", "")["updated_at"], "")
        self.assertEqual(output.chat("claude", "gone", "Old name", "/work", "")["updated_at"], "")
        result = output.turn(ledger_turn(started_at="", ended_at=""))
        self.assertEqual((result["started_at"], result["ended_at"]), ("", None))
        for value in (output.chat("codex", "c", "n", "f", ""), result):
            self.assertIsInstance(value.get("updated_at", value.get("started_at")), str)

    def test_missing_chat_keeps_its_last_known_name(self):
        result = output.chat("claude", "gone", "Old name", "/work", "")
        self.assertEqual((result["id"], result["name"], result["linked"], result["link_id"]), ("gone", "Old name", False, None))

    def test_condition_has_the_documented_and_the_cp1_fields(self):
        result = output.side_condition(SideCondition(open=True))
        self.assertEqual(set(result), CONDITION)
        self.assertLessEqual(set(fixture("side-condition.sample.json")), set(result))
        self.assertEqual((result["exists"], result["open"], result["app_started_at"]), (True, True, ""))

    def test_turn_has_exactly_its_fields(self):
        result = output.turn(ledger_turn())
        self.assertEqual(set(result), TURN)
        self.assertEqual(set(fixture("turn.without-messages.json")), TURN)
        self.assertEqual((result["id"], result["tokens"], result["origin"]), (41, 1600, "codex"))
        self.assertEqual(result["states"], {"claude": "waiting", "codex": "written_here"})

    def test_turn_with_messages_only_when_asked(self):
        result = output.turn(ledger_turn(ended_at=""), [
            Message("p", PROMPT, "Fix it"), Message("c", TOOL_CALL, "list", tool="grep"), Message("r", REPLY, "Done")])
        self.assertEqual(set(result), TURN | {"messages"})
        self.assertEqual(set(fixture("turn.sample.json")), TURN | {"messages"})
        self.assertEqual(result["messages"], [{"kind": "prompt", "text": "Fix it"},
                                              {"kind": "tool_call", "text": "list", "tool": "grep"},
                                              {"kind": "reply", "text": "Done"}])
        self.assertIsNone(result["ended_at"])
        self.assertIsInstance(result["started_at"], str)
        self.assertEqual(output.turn(ledger_turn(), [])["messages"], [])

    def test_usage_has_percent_and_limit(self):
        free = output.side_usage(Usage(164000, 200000, False, None))
        self.assertEqual(free, {"tokens": 164000, "size": 200000, "percent": 82.0, "limit": None})
        self.assertEqual(set(fixture("side.sample.json")["usage"]), set(free))
        unknown = output.side_usage(Usage(10, None, True, None))
        self.assertEqual((unknown["size"], unknown["percent"], unknown["limit"]), (None, None, {"resets_at": None}))
        self.assertEqual(output.side_usage(Usage(1, 2, True, "2026-10-05T01:00:00Z"))["limit"],
                         {"resets_at": "2026-10-05T01:00:00Z"})

    def test_side_has_exactly_its_fields(self):
        note = output.note("status.in_sync")
        result = output.side(side_status(), chat_info=output.chat("claude", "c", "n", "", ""),
                             condition=SideCondition(), usage=output.side_usage(Usage(1, 2, False, None)),
                             since=output.since_you_left(4, 6, 9, "2026-10-04T13:00:00Z"), notes=[note])
        self.assertEqual(set(result), SIDE)
        self.assertEqual(set(fixture("side.sample.json")), SIDE)
        self.assertEqual(set(result["next_message"]), {"turns", "tokens"})
        self.assertEqual(result["next_message"], {"turns": 2, "tokens": 3200})
        self.assertEqual(set(result["since_you_left"]), {"turns", "files", "commands", "since"})
        self.assertEqual((result["tool"], result["tool_label"], result["waiting_reason"]), ("claude", "Claude", "chat_open"))
        self.assertEqual(set(result["synced_up_to"]), TURN)
        self.assertEqual(result["notes"], [note])

    def test_side_without_position_reason_or_news(self):
        result = output.side(side_status(synced_up_to=None, waiting_reason="", waiting=0, attached_on_next_message=0,
                                         attached_tokens=0),
                             chat_info=output.chat("claude", "c", "n", "", ""), condition=SideCondition(exists=False),
                             usage=output.side_usage(Usage(0, None, False, None)))
        self.assertEqual((result["synced_up_to"], result["waiting_reason"], result["since_you_left"], result["notes"]),
                         (None, None, None, []))
        self.assertFalse(result["condition"]["exists"])

    def test_step_has_exactly_its_fields(self):
        result = output.step("cursor", "create", [3, 4], reason="x", needs=("app_closed",),
                             notes=[output.note("tag.new_chat")])
        self.assertEqual(set(result), STEP)
        self.assertEqual(set(fixture("step.sample.json")), STEP)
        self.assertEqual((result["tool_label"], result["turns"], result["needs"]), ("Cursor", [3, 4], ["app_closed"]))

    def test_plan_has_exactly_its_fields_and_keeps_a_commands_own(self):
        result = output.plan("p_1", 3, [output.step("claude", "add", [1])], notes=[output.note("status.in_sync")])
        self.assertEqual(set(result), PLAN)
        self.assertEqual(set(fixture("plan.sample.json")), PLAN)
        self.assertEqual((result["applied"], result["decision_needed"], result["link_id"]), (False, False, 3))
        self.assertEqual(set(output.plan("p_2", None, [], ends_at=None, removes=[])), PLAN | {"ends_at", "removes"})
        self.assertIsNone(output.plan("p_2", None, [])["link_id"])
        self.assertTrue(output.plan("p_2", 1, [], applied=True)["applied"])

    def test_everything_dumps_to_json(self):
        json.dumps(output.side(side_status(), chat_info=output.chat("claude", "c", "n", "", ""),
                               condition=SideCondition(), usage=output.side_usage(Usage(1, 2, False, None))))


class ErrorObjects(unittest.TestCase):
    def test_a_refusal_is_its_name_in_snake_case_with_its_note(self):
        result = output.error(ChatChanged())
        self.assertEqual(set(result), {"error"})
        self.assertEqual(set(result["error"]), {"kind", "note"})
        self.assertEqual(result["error"]["kind"], "chat_changed")
        self.assertEqual(set(result["error"]["note"]), NOTE)
        self.assertEqual(result["error"]["note"]["id"], "write.chat_changed")

    def test_the_note_is_filled_from_the_values_given(self):
        result = output.error(ChatChanged(), {"tool": "codex"})
        self.assertEqual(result["error"]["note"]["values"], {"tool": "Codex"})

    def test_a_note_value_missing_does_not_hide_the_refusal(self):
        result = output.error(AlreadyDelivered(4, "codex", "2026-10-05T00:00:00Z"))
        self.assertEqual(result["error"]["kind"], "already_delivered")
        self.assertEqual(result["error"]["note"]["id"], "keep.too_late")

    def test_an_error_without_a_catalogue_note_gets_the_plain_note_not_exception_prose(self):
        for failure in (SetupIncomplete("hooks are missing at /secret/path"), BatonError("plain")):
            with self.assertLogs("baton.cli.output", "WARNING") as logged:
                result = output.error(failure)["error"]["note"]
            self.assertEqual(set(result), NOTE)
            self.assertEqual(result["id"], "error.unexpected")
            self.assertEqual(result["tone"], "danger")
            self.assertNotIn(str(failure), result["text"])
            self.assertIn(str(failure), logged.output[0])

    def test_a_crash_is_internal_with_the_plain_note_and_no_details(self):
        result = output.internal_error(ValueError("boom at /secret/path"))
        self.assertEqual(set(result["error"]), {"kind", "note"})
        self.assertEqual(result["error"]["kind"], "internal")
        self.assertEqual(result["error"]["note"], output.note("error.unexpected"))
        self.assertNotIn("boom", json.dumps(result))


def run(root, *argv, clock=None, adapters=None):
    """Run the command line on a temporary Baton folder and return (exit status, parsed output)."""
    out = io.StringIO()
    status = main(list(argv), engine_factory=lambda: build(root, clock=clock, adapters=adapters), stdout=out)
    return status, json.loads(out.getvalue())


class LinksOnAnEmptyHome(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)

    def test_links_prints_an_empty_list(self):
        out = io.StringIO()
        status = main(["links", "--json"], engine_factory=lambda: build(self.root), stdout=out)
        self.assertEqual((status, out.getvalue()), (0, '{"links": []}\n'))

    def test_the_same_with_the_flag_before_the_command(self):
        self.assertEqual(run(self.root, "--json", "links"), (0, {"links": []}))

    def test_a_link_is_listed_with_its_summary(self):
        adapters = {"claude": FakeAdapter(CLAUDE_LIKE, "claude"), "codex": FakeAdapter(CODEX_LIKE, "codex")}
        engine = build(self.root, adapters=adapters)
        a = adapters["claude"].build_chat(turns(), name="Orchard")
        b = adapters["codex"].build_chat(turns(), name="Orchard")
        link = engine.store.link({"claude": a, "codex": b}, "full_copy", "2026-10-05T00:00:00Z")
        engine.close()
        status, result = run(self.root, "links", adapters=adapters)
        self.assertEqual(status, 0)
        (summary,) = result["links"]
        self.assertEqual(set(summary), {"link_id", "sides", "mode", "paused", "headline", "in_sync", "decision_needed"})
        self.assertEqual((summary["link_id"], summary["mode"], summary["paused"]), (link.id, "full_copy", False))
        self.assertEqual(set(summary["sides"]), {"claude", "codex"})
        self.assertEqual(set(summary["sides"]["claude"]), CHAT)
        self.assertEqual((summary["sides"]["claude"]["name"], summary["sides"]["claude"]["link_id"]), ("Orchard", link.id))
        self.assertEqual(set(summary["headline"]), NOTE)

    def test_listing_never_recovers_a_pending_native_write(self):
        adapters = {"claude": FakeAdapter(CLAUDE_LIKE, "claude"), "codex": FakeAdapter(CODEX_LIKE, "codex")}
        engine = build(self.root, adapters=adapters)
        source = adapters["claude"].build_chat(turns())
        target = adapters["codex"].build_chat([])
        link = engine.store.link({"claude": source, "codex": target}, "full_copy")
        engine.store.record_turns(link.id, "claude", turns())
        entry = Journal(engine.store, adapters, engine.clock).begin(link.id, "codex", target, "add")
        adapters["codex"].writer.add(target, turns()[:1])
        engine.close()
        with patch.object(adapters["codex"].writer, "take_back", side_effect=AssertionError("read must not write")):
            code, result = run(self.root, "links", adapters=adapters)
        self.assertEqual(code, 0)
        self.assertEqual(result["links"][0]["link_id"], link.id)
        self.assertEqual(adapters["codex"].reader.read(target), turns()[:1])
        check = build(self.root, adapters=adapters)
        self.addCleanup(check.close)
        self.assertEqual(check.store.journal_entry(entry)["state"], "begun")

    def linked_pair(self):
        adapters = {"claude": FakeAdapter(CLAUDE_LIKE, "claude"), "codex": FakeAdapter(CODEX_LIKE, "codex")}
        chat = adapters["claude"].build_chat(turns(), name="Orchard", folder="/work")
        engine = build(self.root, adapters=adapters)
        plan = engine.linker.plan_link("claude", chat, "codex")
        result = engine.linker.apply(plan, plan.plan_id)
        self.assertTrue(result.applied, result)
        engine.close()
        return adapters, chat, result

    def test_a_link_in_sync_says_so_after_reading_the_chats(self):
        adapters, chat, result = self.linked_pair()
        (summary,) = run(self.root, "links", adapters=adapters)[1]["links"]
        self.assertEqual((summary["in_sync"], summary["headline"]["id"]), (True, "status.in_sync"))

    def test_a_chat_that_moved_on_since_the_rows_were_written_is_not_reported_in_sync(self):
        adapters, chat, result = self.linked_pair()
        adapters["claude"].chats[chat].append(Turn(Message("p9", PROMPT, "new"), (Message("a9", REPLY, "ok"),)))
        (summary,) = run(self.root, "links", adapters=adapters)[1]["links"]
        self.assertFalse(summary["in_sync"])
        self.assertEqual(summary["headline"]["id"], "status.ahead")
        self.assertEqual(summary["headline"]["values"], {"tool": "Claude", "n": 1})

    def test_a_missing_chat_is_not_reported_in_sync(self):
        adapters, chat, result = self.linked_pair()
        del adapters["codex"].chats[result.chat_id]
        del adapters["codex"].refs[result.chat_id]
        (summary,) = run(self.root, "links", adapters=adapters)[1]["links"]
        self.assertFalse(summary["in_sync"])
        self.assertEqual(summary["headline"]["id"], "side.missing")
        self.assertEqual(summary["sides"]["codex"]["updated_at"], "")
        self.assertEqual(summary["sides"]["codex"]["id"], result.chat_id)

    def test_the_command_line_runs_as_a_module_and_honours_baton_home(self):
        fake_home = self.root / "somebody"
        fake_home.mkdir()
        baton_home = self.root / "baton home"
        environment = {**os.environ, "BATON_HOME": str(baton_home), "HOME": str(fake_home)}
        environment.pop("BATON_TOOLS_HOME", None)
        done = subprocess.run([sys.executable, "-m", "baton.cli.main", "links", "--json"], cwd=ROOT, env=environment,
                              capture_output=True, text=True, check=False)
        self.assertEqual((done.returncode, done.stdout, done.stderr), (0, '{"links": []}\n', ""))
        self.assertTrue((baton_home / "baton.sqlite").is_file())
        self.assertEqual(list(fake_home.iterdir()), [])


class ConfirmingAPlan(unittest.TestCase):
    """--dry-run shows a plan and --confirm carries out exactly that plan, or refuses (ChatChanged)."""
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.clock = FixedClock("2026-10-05T10:00:00Z")
        self.adapters = {"claude": FakeAdapter(CLAUDE_LIKE, "claude"), "codex": FakeAdapter(CODEX_LIKE, "codex")}
        self.chat = self.adapters["claude"].build_chat(turns(), name="source", folder="/work")
        self.fingerprints = []
        self.registry = CommandRegistry()

        @self.registry.command("probe", "plan a copy", plan=True,
                               arguments=lambda parser: parser.add_argument("--chat", required=True))
        def probe(ctx, args):
            planned = {}

            def plan_again(arguments):
                planned["plan"] = ctx.engine.linker.plan_link("claude", arguments["chat"], "codex")
                return planned["plan"].plan_id
            if ctx.confirm:
                ctx.confirmed(plan_again)
                result = ctx.engine.linker.apply(planned["plan"], planned["plan"].plan_id)
                return output.plan(ctx.confirm, result.link_id, [], applied=result.applied, chat_id=result.chat_id)
            plan = plan_again({"chat": args.chat})
            self.fingerprints.append(plan)
            shown = ctx.remember(plan, {"chat": args.chat})
            return output.plan(shown, None, [output.step("codex", "create", [])])

    def call(self, *argv):
        out = io.StringIO()
        status = main(list(argv), registry=self.registry, stdout=out, engine_factory=lambda: build(
            self.root, clock=self.clock, adapters=self.adapters))
        return status, json.loads(out.getvalue())

    def show(self, flag="--dry-run"):
        status, plan = self.call("probe", "--chat", self.chat, flag)
        self.assertEqual(status, 0)
        self.assertEqual((plan["applied"], set(plan)), (False, PLAN))
        self.assertTrue(plan["plan_id"].startswith("p_"))
        return plan["plan_id"]

    def confirm(self, plan_id):
        return self.call("probe", "--chat", self.chat, "--confirm", plan_id)

    def links(self):
        engine = build(self.root, adapters=self.adapters)
        try:
            return engine.store.links()
        finally:
            engine.close()

    def assertRefused(self, plan_id):
        status, result = self.confirm(plan_id)
        self.assertEqual(status, 0)
        self.assertEqual(result["error"]["kind"], "chat_changed")
        self.assertEqual(result["error"]["note"]["id"], "write.chat_changed")
        self.assertEqual(self.links(), [])
        self.assertEqual(len(self.adapters["codex"].chats), 0)

    def test_an_unchanged_plan_creates_the_chat_and_the_link_for_real(self):
        plan_id = self.show()
        self.assertEqual(self.links(), [])
        status, result = self.confirm(plan_id)
        self.assertEqual((status, result["applied"]), (0, True))
        (link,) = self.links()
        self.assertEqual((link.id, link.chat("claude"), link.chat("codex")), (result["link_id"], self.chat, result["chat_id"]))
        created = self.adapters["codex"].reader.read(result["chat_id"])
        # Codex does not replay tool calls, so only the prompts and replies are compared.
        self.assertEqual([(t.prompt.text, t.reply_text) for t in created],
                         [(t.prompt.text, t.reply_text) for t in turns()])
        self.assertEqual(len(created), 3)

    def test_the_confirmation_id_is_not_the_service_fingerprint_and_is_new_for_every_preview(self):
        first, second = self.show(), self.show()
        self.assertEqual(len(self.fingerprints), 2)
        self.assertEqual(self.fingerprints[0], self.fingerprints[1])
        self.assertNotIn(first, self.fingerprints)
        self.assertNotEqual(first, second)

    def test_a_second_preview_does_not_replace_or_revive_the_first(self):
        first = self.show()
        second = self.show()
        self.assertEqual(self.confirm(first)[1]["applied"], True)
        # The chat now has a twin: the second preview is stale (planning it again is refused), and the
        # first, already used, is not revived by the second one having the same fingerprint.
        self.assertRefusedAfterApply(second, "already_linked")
        self.assertRefusedAfterApply(first, "chat_changed")

    def assertRefusedAfterApply(self, plan_id, kind="chat_changed"):
        status, result = self.confirm(plan_id)
        self.assertEqual((status, result["error"]["kind"]), (0, kind))
        self.assertEqual(len(self.links()), 1)

    def test_the_first_call_without_a_flag_shows_a_plan_too(self):
        status, plan = self.call("probe", "--chat", self.chat)
        self.assertEqual((status, plan["applied"]), (0, False))

    def test_a_chat_that_changed_since_is_refused(self):
        plan_id = self.show()
        self.adapters["claude"].chats[self.chat].append(turns()[0])
        self.assertRefused(plan_id)

    def test_a_refused_plan_stays_refused_after_the_chat_changes_back(self):
        plan_id = self.show()
        chat = self.adapters["claude"].chats[self.chat]
        chat.append(turns()[0])
        self.assertRefused(plan_id)
        chat.pop()
        self.assertRefused(plan_id)

    def test_a_plan_shown_less_than_ten_minutes_ago_is_carried_out(self):
        plan_id = self.show()
        self.clock.value = "2026-10-05T10:09:59Z"
        status, result = self.confirm(plan_id)
        self.assertEqual((status, result["applied"]), (0, True))

    def test_a_plan_older_than_ten_minutes_is_refused(self):
        plan_id = self.show()
        self.clock.value = "2026-10-05T10:20:00Z"
        self.assertRefused(plan_id)

    def test_exactly_ten_minutes_is_too_late(self):
        plan_id = self.show()
        self.clock.value = "2026-10-05T10:10:00Z"
        self.assertRefused(plan_id)

    def test_an_unknown_or_malformed_plan_id_is_refused(self):
        for plan_id in ("p_unknown", "../../etc/passwd", "p_/x", "x"):
            with self.subTest(plan_id=plan_id):
                self.assertRefused(plan_id)
        self.assertEqual(list(self.root.rglob("passwd*")), [])

    def test_a_plan_is_confirmed_once(self):
        plan_id = self.show()
        self.assertEqual(self.confirm(plan_id)[1]["applied"], True)
        self.assertRefusedAfterApply(plan_id)

    def test_a_damaged_plan_file_is_a_refusal_not_a_crash(self):
        plan_id = self.show()
        (self.root / "plans" / (plan_id + ".json")).write_text('{"plan_id": "p_other"}')
        self.assertRefused(plan_id)

    def test_the_plan_survives_between_two_runs_in_a_private_folder(self):
        plan_id = self.show()
        path = self.root / "plans" / (plan_id + ".json")
        self.assertTrue(path.is_file())
        self.assertEqual((path.parent.stat().st_mode & 0o777, path.stat().st_mode & 0o777), (0o700, 0o600))

    def test_dry_run_and_confirm_together_are_a_usage_error(self):
        status, result = self.call("probe", "--chat", self.chat, "--dry-run", "--confirm", "p_x")
        self.assertEqual((status, result["error"]["kind"]), (2, "usage"))


if __name__ == "__main__":
    unittest.main()
