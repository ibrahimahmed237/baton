"""CP1 note templates render complete contract values and stable actions."""
import unittest
from baton.notes.catalogue import CATALOGUE, get


class NoteCatalogueTest(unittest.TestCase):
    def test_every_note_renders_all_fields_for_each_tool(self):
        for tool in ("Claude", "Codex", "OpenCode", "Cursor"):
            for note in CATALOGUE.values():
                with self.subTest(tool=tool, note=note.id):
                    values = {field: tool if field == "tool" else "sample" for field in note.fields}
                    result = note.to_dict(values)
                    self.assertEqual(result["id"], note.id)
                    self.assertEqual(result["values"], values)
                    for text in (result["text"], result["status_line"] or "", *(item["label"] for item in result["buttons"])):
                        self.assertNotIn("{", text)
                    for button in result["buttons"]:
                        self.assertTrue(button["id"])
                        self.assertIsInstance(button["primary"], bool)

    def test_missing_value_refuses_partial_note(self):
        with self.assertRaises(KeyError):
            get("format.unknown_version").render({"tool": "Example"})

    def test_delivery_alternatives_have_stable_actions(self):
        self.assertEqual(get("new_chat.relaunch").buttons[0].id, "close_sync_reopen")
        self.assertEqual(get("write.release").buttons[0].id, "add_now")

    def test_templates_do_not_hard_code_a_tool_name(self):
        for note in CATALOGUE.values():
            for name in ("Claude", "Codex", "OpenCode", "Cursor"):
                self.assertNotIn(name, note.template)

    def test_idle_release_offer_is_separate_from_held_or_replying_offer(self):
        generic = get("write.chat_open").to_dict({"tool": "Codex", "n": 2})
        releasable = get("write.chat_open_release").to_dict({"tool": "Claude", "n": 2})
        replying = get("write.when_idle").to_dict({"tool": "Claude", "n": 2})
        self.assertEqual([b["id"] for b in releasable["buttons"]], ["close_sync_reopen", "add_now"])
        self.assertEqual(releasable["buttons"][1]["label"], "Add them now")
        self.assertNotIn("add_now", [b["id"] for b in generic["buttons"]])
        self.assertNotIn("add_now", [b["id"] for b in replying["buttons"]])


class UI8PresentationCatalogueTests(unittest.TestCase):
    def test_ui8_fixture_wording_is_exactly_from_catalogue(self):
        """Receipt, Settings and Quit notes may not diverge in the fixture UI."""
        import json
        from pathlib import Path
        from baton.notes.catalogue import get
        root = Path(__file__).resolve().parents[2] / "app" / "Fixtures"
        prefixes = ("screen.received_", "screen.conversation_guide", "settings.", "quit.")
        checked = 0
        for path in root.glob("*.json"):
            data = json.loads(path.read_text())
            if not isinstance(data, dict):
                continue
            for note in data.get("notes", []):
                if note["id"].startswith(prefixes):
                    self.assertEqual(note, get(note["id"]).to_dict(note["values"]), str(path))
                    checked += 1
        self.assertGreater(checked, 100)


    def test_fixture_receipts_stop_before_first_waiting_turn(self):
        """A receipt must never claim a turn whose earlier history is still waiting."""
        import json
        from pathlib import Path
        root = Path(__file__).resolve().parents[2] / "app" / "Fixtures"
        for path in root.glob("status.*.json"):
            status = json.loads(path.read_text())
            for tool, side in status.get("sides", {}).items():
                reached = side.get("synced_up_to")
                if reached:
                    self.assertFalse(any(turn["seq"] <= reached["seq"] and turn["states"].get(tool) == "waiting"
                                         for turn in status.get("turns", [])), (path.name, tool))

    def test_receipts_do_not_claim_every_earlier_turn_after_a_skip(self):
        """A merge can skip an earlier turn while the latest agent turn advances."""
        cases = (
            ("screen.received_both", {}),
            ("screen.received_one", {"tool": "Claude"}),
            ("screen.received_hidden_tool", {"tool": "Claude", "seq": 3}),
        )
        for note_id, values in cases:
            with self.subTest(note=note_id):
                text = get(note_id).render(values).template
                self.assertNotIn("every earlier turn", text)
                self.assertNotIn("all history", text)
                self.assertNotIn("latest turn", text)
