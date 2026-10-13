"""H3: a root injected in any way fences the adapters off the real machine; only the default home is real."""
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from baton.adapters.claude.app import InertProcess as ClaudeInertProcess, SystemProcess as ClaudeSystemProcess
from baton.adapters.claude.runner import ClaudeRunner, InertRunner as ClaudeInertRunner
from baton.adapters.codex.app import InertProcess as CodexInertProcess, SystemProcess as CodexSystemProcess
from baton.adapters.codex.runner import CodexRunner, InertRunner as CodexInertRunner
from baton.cli import wiring
from baton.cli.main import main
from baton.cli.tools import TOOLS, ToolEntry, installed_in
from baton.domain.errors import NotAvailable
from tests.fixtures.no_processes import no_processes


class Fenced(unittest.TestCase):
    def setUp(self):
        environment = patch.dict("os.environ")
        environment.start()
        self.addCleanup(environment.stop)
        for name in (wiring.HOME_VARIABLE, wiring.TOOLS_HOME_VARIABLE):
            os.environ.pop(name, None)
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        # The real probe must never be what answers for an injected root.
        real_probe = patch.object(wiring, "installed", side_effect=AssertionError("real installation probe"))
        real_probe.start()
        self.addCleanup(real_probe.stop)

    def assert_inert(self, adapters):
        self.assertEqual(sorted(adapters), ["claude", "codex"])
        self.assertIsInstance(adapters["claude"].process, ClaudeInertProcess)
        self.assertIsInstance(adapters["claude"].runner, ClaudeInertRunner)
        self.assertIsInstance(adapters["codex"].process, CodexInertProcess)
        self.assertIsInstance(adapters["codex"].runner, CodexInertRunner)
        for adapter in adapters.values():
            self.assertFalse(adapter.app.running())
            self.assertEqual(adapter.process.started_at(), "")
            self.assertFalse(adapter.runner.available().ok)
            self.assertEqual(adapter.runner.available().note_id, "setup.runner")
            with self.assertRaises(NotAvailable):
                adapter.runner.ask("question", "/folder")
            with self.assertRaises(NotAvailable):
                adapter.app.open(None, None)
            with self.assertRaises(NotAvailable):
                adapter.app.close()


class TheDecision(Fenced):
    def test_any_injected_root_is_sandboxed_and_only_the_default_home_is_not(self):
        cases = {
            "nothing injected": (dict(explicit_root=False), False),
            "root argument or BATON_HOME": (dict(explicit_root=True), True),
            "tools home argument": (dict(explicit_root=False, tools_home="/t"), True),
            "per-tool roots": (dict(explicit_root=False, adapter_roots={"claude": "/c"}), True),
            "empty per-tool roots": (dict(explicit_root=False, adapter_roots={}), True),
            "BATON_TOOLS_HOME": (dict(explicit_root=False, environ={wiring.TOOLS_HOME_VARIABLE: "/t"}), True),
            "BATON_TOOLS_HOME empty": (dict(explicit_root=False, environ={wiring.TOOLS_HOME_VARIABLE: ""}), False),
        }
        for name, (arguments, expected) in cases.items():
            with self.subTest(name):
                arguments.setdefault("environ", {})
                self.assertIs(wiring.is_sandboxed(**arguments), expected)

    def test_build_reports_the_decision_for_every_way_of_injecting_a_root(self):
        injected = {
            "root argument": lambda: wiring.build(self.root / "a"),
            "BATON_HOME": lambda: wiring.build(environ={wiring.HOME_VARIABLE: str(self.root / "b")}),
            "BATON_HOME and BATON_TOOLS_HOME": lambda: wiring.build(environ={
                wiring.HOME_VARIABLE: str(self.root / "c"), wiring.TOOLS_HOME_VARIABLE: str(self.root / "t")}),
            "tools home argument": lambda: wiring.build(self.root / "d", tools_home=self.root / "t2"),
            "per-tool roots": lambda: wiring.build(self.root / "e", adapter_roots={"codex": self.root / "x"}),
        }
        for name, make in injected.items():
            with self.subTest(name), no_processes():
                engine = make()
                self.addCleanup(engine.close)
                self.assertTrue(engine.sandboxed)
                self.assert_inert(engine.adapters)

    def test_load_adapters_is_inert_unless_it_is_told_it_is_on_the_real_machine(self):
        with no_processes():
            adapters, unavailable = wiring.load_adapters(TOOLS, self.root)
            self.assertEqual(list(unavailable), ["opencode", "cursor"])
            self.assert_inert(adapters)

    def test_an_adapter_class_without_a_real_form_is_built_from_its_root_either_way(self):
        built = []

        class Plain:
            name = "claude"

            def __init__(self, root):
                built.append(root)
        import sys
        import types
        module = types.ModuleType("baton_plain_adapter_module")
        module.Plain = Plain
        with patch.dict(sys.modules, {module.__name__: module}):
            entry = ToolEntry("claude", "Claude", module.__name__, "Plain")
            for sandboxed in (True, False):
                adapters, unavailable = wiring.load_adapters([entry], self.root, sandboxed=sandboxed)
                self.assertEqual((list(adapters), unavailable), (["claude"], {}))
        self.assertEqual(built, [self.root, self.root])


class TheDefaultHome(Fenced):
    def test_the_default_home_selects_the_real_implementations_without_calling_them(self):
        fake_home = self.root / "somebody"
        fake_home.mkdir()
        with patch.object(Path, "home", return_value=fake_home), no_processes():
            engine = wiring.build(environ={})
        self.addCleanup(engine.close)
        self.assertFalse(engine.sandboxed)
        self.assertEqual(engine.root, fake_home / "Library" / "Application Support" / "Baton")
        claude, codex = engine.adapters["claude"], engine.adapters["codex"]
        self.assertIsInstance(claude.process, ClaudeSystemProcess)
        self.assertIsInstance(claude.runner, ClaudeRunner)
        self.assertIsInstance(codex.process, CodexSystemProcess)
        self.assertIsInstance(codex.runner, CodexRunner)
        self.assertNotIsInstance(codex.runner, CodexInertRunner)
        # wiring.installed is the real probe's name (patched here so it cannot run): the default home picks it.
        self.assertIs(engine.installation_probe, wiring.installed)
        self.assertEqual(claude.root, fake_home)


class TheInstallationProbe(Fenced):
    def test_an_empty_root_reports_no_tool_installed(self):
        with no_processes():
            engine = wiring.build(self.root / "baton")
        self.addCleanup(engine.close)
        self.assertEqual({tool: engine.installation_probe(tool) for tool in engine.tool_ids},
                         {"claude": False, "codex": False, "opencode": False, "cursor": False})

    def test_installed_means_the_tools_own_folder_is_inside_its_root(self):
        tools = self.root / "tools"
        (tools / ".codex").mkdir(parents=True)
        elsewhere = self.root / "elsewhere"
        (elsewhere / ".claude").mkdir(parents=True)
        engine = wiring.build(self.root, adapter_roots={"claude": elsewhere})
        self.addCleanup(engine.close)
        self.assertEqual({tool: engine.installation_probe(tool) for tool in engine.tool_ids},
                         {"claude": True, "codex": True, "opencode": False, "cursor": False})
        self.assertFalse(engine.installation_probe("not-a-tool"))
        self.assertFalse(installed_in(ToolEntry("x", "X", "m", "A"), tools))

    def test_a_probe_passed_in_wins(self):
        engine = wiring.build(self.root, adapters={}, installation_probe=lambda tool: tool == "cursor")
        self.addCleanup(engine.close)
        self.assertTrue(engine.installation_probe("cursor"))
        self.assertFalse(engine.installation_probe("claude"))


class TheReadCommandsOnAnInjectedRoot(Fenced):
    def run_main(self, argv, **environment):
        out = io.StringIO()
        with patch.dict("os.environ", {wiring.HOME_VARIABLE: str(self.root / "baton"), **environment}), no_processes():
            code = main(argv, stdout=out)
        return code, json.loads(out.getvalue())

    def test_setup_chats_links_and_status_start_no_process_and_setup_finds_nothing_installed(self):
        for environment in ({}, {wiring.TOOLS_HOME_VARIABLE: str(self.root / "trial")}):
            with self.subTest(environment=environment):
                code, setup = self.run_main(["setup", "--json"], **environment)
                self.assertEqual(code, 0)
                self.assertTrue({"claude", "codex"} <= {t["tool"] for t in setup["tools"]})
                self.assertEqual([(t["tool"], t["installed"], t["ready"]) for t in setup["tools"]],
                                 [(t["tool"], False, False) for t in setup["tools"]])
                for tool in setup["tools"]:
                    for finding in tool["findings"]:
                        if finding["id"] == "runner":
                            self.assertFalse(finding["ok"])
                self.assertEqual(self.run_main(["chats", "--tool", "codex", "--json"], **environment), (0, {"chats": []}))
                self.assertEqual(self.run_main(["chats", "--tool", "claude", "--json"], **environment), (0, {"chats": []}))
                self.assertEqual(self.run_main(["links", "--json"], **environment), (0, {"links": []}))
                code, status = self.run_main(["status", "--link", "1", "--json"], **environment)
                self.assertEqual(code, 0)
                self.assertIn("error", status)
