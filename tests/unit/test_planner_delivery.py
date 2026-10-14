"""The eight rows of Best delivery per tool, plus safety priority boundaries."""
from dataclasses import replace
import unittest

from baton.adapters.fake import FakeAdapter
from baton.adapters.fake.facts import CLAUDE_LIKE, CODEX_LIKE, OPENCODE_LIKE, CURSOR_LIKE
from baton.domain.conditions import SideCondition
from baton.domain.link import FULL_COPY, ATTACHED_HISTORY, Link
from baton.ledger.sqlite_store import Ledger
from baton.services.planner import plan_sync
from baton.services.status import link_status
from tests.unit.test_ledger import make_turn


class DeliveryFactsTest(unittest.TestCase):
    """Each named measured fact set runs through the same generic service."""

    def setUp(self):
        self.store = Ledger(":memory:")
        self.addCleanup(self.store.close)
        self.link = self.store.link({"claude": "a", "codex": "b"}, FULL_COPY)
        self.store.record_turns(self.link.id, "claude", [make_turn("one")])

    def check(self, facts, condition, action, automatic=False, mode=FULL_COPY):
        adapter = FakeAdapter(facts)
        facts = {"claude": adapter.facts, "codex": adapter.facts}
        conditions = {"codex": condition}
        link = replace(self.link, mode=mode)
        step = plan_sync(link, self.store.turns(link.id), conditions,
                         {"codex"} if automatic else (), facts=facts).steps["codex"]
        self.assertEqual(step.action, action)
        status = link_status(link, self.store.turns(link.id), conditions, facts=facts, add_when_idle={"codex"} if automatic else ()).side("codex")
        self.assertEqual(status.attached_on_next_message, int(action == "attach"))
        return step

    def test_row_1_open_on_screen(self):
        step = self.check(OPENCODE_LIKE, SideCondition(open=True, app_running=True), "add")
        self.assertEqual(step.needs, ("reopen_chat_to_see",))

    def test_row_2_not_held(self):
        self.check(CODEX_LIKE, SideCondition(app_running=True), "add")

    def test_row_3_held(self):
        step = self.check(CODEX_LIKE, SideCondition(open=True), "attach")
        self.assertIn("close_sync_reopen", step.alternatives)

    def test_row_4_app_closed(self):
        self.check(CLAUDE_LIKE, SideCondition(), "add")

    def test_row_5_idle_automatic(self):
        step = self.check(CLAUDE_LIKE, SideCondition(open=True), "add_after_release", True)
        self.assertEqual(step.needs, ("relaunch_to_see",))

    def test_row_6_replying(self):
        self.check(CLAUDE_LIKE, SideCondition(open=True, replying=True), "attach", True)

    def test_row_7_closed(self):
        self.check(CURSOR_LIKE, SideCondition(), "add")

    def test_row_8_running(self):
        self.check(CURSOR_LIKE, SideCondition(app_running=True), "attach")

    def test_unknown_format_open_hooks_ready_attaches(self):
        step = self.check(OPENCODE_LIKE, SideCondition(open=True, format_known=False), "attach")
        self.assertEqual(step.reason, "format_unknown")

    def test_unknown_format_closed_holds(self):
        step = self.check(OPENCODE_LIKE, SideCondition(format_known=False), "hold")
        self.assertEqual(step.reason, "format_unknown")

    def test_unknown_format_without_hooks_holds(self):
        self.check(CLAUDE_LIKE, SideCondition(open=True, hooks_ready=False, format_known=False), "hold")

    def test_any_time_without_hooks_still_adds(self):
        self.check(OPENCODE_LIKE, SideCondition(open=True, hooks_ready=False), "add")

    def test_running_without_hooks_holds(self):
        self.check(CURSOR_LIKE, SideCondition(app_running=True, hooks_ready=False), "hold")

    def test_idle_manual_offers_add_now(self):
        step = self.check(CLAUDE_LIKE, SideCondition(open=True), "attach")
        self.assertIn("add_now", step.alternatives)

    def test_attached_history_never_releases(self):
        self.check(CLAUDE_LIKE, SideCondition(open=True), "attach", True, ATTACHED_HISTORY)

    def test_missing_and_paused_override_any_time(self):
        self.check(OPENCODE_LIKE, SideCondition(exists=False, open=True), "hold")
        self.store.set_paused(self.link.id, True)
        self.link = self.store.get_link(self.link.id)
        self.check(OPENCODE_LIKE, SideCondition(open=True), "hold")
