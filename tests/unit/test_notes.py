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
