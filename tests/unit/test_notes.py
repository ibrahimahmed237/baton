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
