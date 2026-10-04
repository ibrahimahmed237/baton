import tempfile
import unittest
from pathlib import Path

from baton.adapters.codex import reader as codex_reader
from baton.domain.model import REPLY, TOOL_CALL, TOOL_RESULT
from tests.fixtures.builders import CodexChat


class CodexReaderTest(unittest.TestCase):
    def read(self, chat: CodexChat):
        with tempfile.TemporaryDirectory() as tmp:
            return codex_reader.read_chat(chat.write(Path(tmp) / "rollout.jsonl"))

    def test_reads_a_native_turn_and_skips_what_codex_wrote_itself(self):
        chat = CodexChat()
        chat.event("task_started", turn_id="t1")
        chat.developer("<permissions instructions>...")
        chat.user("<environment_context>cwd</environment_context>")
        chat.user("# AGENTS.md instructions for /repo")
        prompt = chat.user("add logout")
        chat.reasoning()
        answer = chat.assistant("Logout added.")
        chat.event("task_complete", turn_id="t1")

        turns = self.read(chat)

        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0].prompt.text, "add logout")
        self.assertEqual(turns[0].id, prompt["payload"]["id"])
        self.assertEqual([(m.kind, m.id, m.text) for m in turns[0].messages],
                         [(REPLY, answer["payload"]["id"], "Logout added.")])

    def test_injected_blocks_inside_a_prompt_are_removed(self):
        chat = CodexChat()
        chat.user("<external_codex_apps_open_page>{}</external_codex_apps_open_page>", "what is the codeword?")
        chat.assistant("KIWI-77.")

        self.assertEqual([t.prompt.text for t in self.read(chat)], ["what is the codeword?"])

    def test_hook_text_attached_by_baton_is_not_a_prompt(self):
        chat = CodexChat()
        chat.developer("<baton-catch-up>turn from Claude</baton-catch-up>")
        chat.user("<baton-catch-up>turn from Claude</baton-catch-up>")
        chat.user("add tests")
        chat.assistant("Tests added.")

        turns = self.read(chat)

        self.assertEqual([t.prompt.text for t in turns], ["add tests"])
        self.assertEqual([m.text for m in turns[0].messages], ["Tests added."])

    def test_reads_tool_calls_and_their_results(self):
        chat = CodexChat()
        chat.user("run the tests")
        chat.function_call("shell", {"command": ["npm", "test"]}, "call-1")
        chat.function_output("call-1", "12 passing")
        chat.custom_call("apply_patch", "*** Begin Patch", "call-2")
        chat.custom_output("call-2", {"ok": True})
        chat.assistant("All green.")

        messages = self.read(chat)[0].messages

        self.assertEqual([m.kind for m in messages], [TOOL_CALL, TOOL_RESULT, TOOL_CALL, TOOL_RESULT, REPLY])
        self.assertEqual((messages[0].tool, messages[0].tool_input, messages[0].call_id),
                         ("shell", {"command": ["npm", "test"]}, "call-1"))
        self.assertEqual((messages[1].call_id, messages[1].text), ("call-1", "12 passing"))
        self.assertEqual((messages[2].tool, messages[2].tool_input), ("apply_patch", "*** Begin Patch"))
        self.assertEqual(messages[3].text, '{"ok": true}')

    def test_turns_without_ids_are_identified_by_their_ordinal(self):
        # Turns Codex imported from Claude, and turns Baton appends, carry no message ID.
        chat = CodexChat()
        chat.event("task_started", turn_id="baton-turn-1")
        prompt = chat.user("remember PLUM-6", native=False)
        answer = chat.assistant("Noted.", native=False)
        chat.event("task_complete", turn_id="baton-turn-1")

        turn = self.read(chat)[0]

        self.assertEqual(turn.id, "ordinal-%d" % prompt["ordinal"])
        self.assertEqual(turn.messages[0].id, "ordinal-%d" % answer["ordinal"])

    def test_several_turns_keep_their_order_and_times(self):
        chat = CodexChat()
        chat.user("first")
        chat.assistant("one")
        chat.user("second")
        chat.assistant("two")

        turns = self.read(chat)

        self.assertEqual([(t.prompt.text, t.reply_text) for t in turns], [("first", "one"), ("second", "two")])
        self.assertLess(turns[0].started_at, turns[0].ended_at)
        self.assertLess(turns[0].ended_at, turns[1].started_at)

    def test_a_rollout_with_no_prompt_reads_as_no_turns(self):
        chat = CodexChat()
        chat.developer("setup")
        chat.assistant("orphan reply")

        self.assertEqual(self.read(chat), [])


if __name__ == "__main__":
    unittest.main()
