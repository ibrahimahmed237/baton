import tempfile
import unittest
from pathlib import Path

from baton.adapters.claude import reader as claude_reader
from baton.domain.model import REPLY, TOOL_CALL, TOOL_RESULT
from tests.fixtures.builders import ClaudeChat


class ClaudeReaderTest(unittest.TestCase):
    def read(self, chat: ClaudeChat):
        with tempfile.TemporaryDirectory() as tmp:
            return claude_reader.read_chat(chat.write(Path(tmp) / "chat.jsonl"))

    def test_reads_prompts_replies_and_tools_as_turns(self):
        chat = ClaudeChat()
        first = chat.prompt("add login")
        chat.thinking()
        chat.tool_call("Edit", {"file_path": "login.ts"}, "call-1")
        chat.tool_result("call-1", "ok")
        chat.reply("Login added.")
        chat.prompt("add logout")
        chat.reply("Logout added.")

        turns = self.read(chat)

        self.assertEqual([t.prompt.text for t in turns], ["add login", "add logout"])
        self.assertEqual(turns[0].id, first["uuid"])
        self.assertEqual([m.kind for m in turns[0].messages], [TOOL_CALL, TOOL_RESULT, REPLY])
        call, result, _ = turns[0].messages
        self.assertEqual((call.tool, call.tool_input, call.call_id), ("Edit", {"file_path": "login.ts"}, "call-1"))
        self.assertEqual((result.call_id, result.text), ("call-1", "ok"))
        self.assertEqual(turns[0].reply_text, "Login added.")
        self.assertEqual(turns[1].reply_text, "Logout added.")

    def test_records_claude_writes_for_itself_are_not_prompts(self):
        chat = ClaudeChat()
        chat.prompt("real question")
        chat.reply("answer")
        chat.prompt("<command-name>/model</command-name>", origin=None)
        chat.prompt("<local-command-stdout>Set model</local-command-stdout>", origin=None)
        chat.prompt("<local-command-caveat>Caveat</local-command-caveat>", origin=None, isMeta=True)
        chat.prompt("<task-notification>done</task-notification>", origin="task-notification")
        chat.prompt("[Request interrupted by user]", origin=None)
        chat.prompt("Continue from where you left off.", origin=None, isMeta=True)
        chat.reply("still the first turn")

        turns = self.read(chat)

        self.assertEqual([t.prompt.text for t in turns], ["real question"])
        self.assertEqual(turns[0].reply_text, "still the first turn")

    def test_a_message_sent_from_another_chat_starts_a_turn(self):
        chat = ClaudeChat()
        chat.prompt("remember APRICOT-4")
        chat.reply("noted")
        chat.prompt("Another Claude session sent a message: list the codewords", origin="peer", isMeta=True)
        chat.reply("APRICOT-4")

        turns = self.read(chat)

        self.assertEqual([t.reply_text for t in turns], ["noted", "APRICOT-4"])
        self.assertTrue(turns[1].prompt.text.startswith("Another Claude session"))

    def test_older_records_without_origin_still_count_as_prompts(self):
        chat = ClaudeChat()
        chat.prompt("typed in an older version", origin=None)
        chat.reply("answer")

        self.assertEqual([t.prompt.text for t in self.read(chat)], ["typed in an older version"])

    def test_reminders_wrapped_around_a_prompt_are_removed(self):
        chat = ClaudeChat()
        chat.prompt_blocks("<system-reminder>\nrules\n</system-reminder>", "how do I link the two tools?")
        chat.reply("answer")
        chat.prompt("<system-reminder>note</system-reminder>\nsecond question")
        chat.reply("answer")

        self.assertEqual([t.prompt.text for t in self.read(chat)],
                         ["how do I link the two tools?", "second question"])

    def test_hook_attachments_and_bookkeeping_are_left_out(self):
        chat = ClaudeChat()
        chat.bookkeeping("custom-title")
        chat.prompt("add tests")
        chat.attachment("hook_additional_context", "<baton-catch-up>turn from Codex</baton-catch-up>")
        chat.attachment("hook_system_message", "Baton attached 1 turn")
        chat.bookkeeping("file-history-snapshot")
        chat.reply("Tests added.")
        chat.system("stop_hook_summary")

        turns = self.read(chat)

        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0].prompt.text, "add tests")
        self.assertEqual([m.text for m in turns[0].messages], ["Tests added."])

    def test_history_before_a_compaction_is_kept_and_the_summary_is_not_a_turn(self):
        chat = ClaudeChat()
        chat.prompt("before compaction")
        chat.reply("early answer")
        chat.compact("This session is being continued from a previous conversation...")
        chat.prompt("after compaction")
        chat.reply("late answer")

        turns = self.read(chat)

        self.assertEqual([t.prompt.text for t in turns], ["before compaction", "after compaction"])
        self.assertEqual([m.text for m in turns[0].messages], ["early answer"])

    def test_a_turn_bypassed_by_a_later_prompt_is_not_part_of_the_chat(self):
        # Seen in the spike: a turn appended while the chat was open stays in the file,
        # but the next prompt hangs off the older message and the agent never has it.
        chat = ClaudeChat()
        chat.prompt("baton test")
        last_real = chat.reply("which test?")
        chat.prompt("remember MANGO-42")
        chat.reply("noted")
        chat.prompt("what is the codeword?", parent=last_real["uuid"])
        chat.reply("I don't know a codeword.")

        self.assertEqual([t.prompt.text for t in self.read(chat)], ["baton test", "what is the codeword?"])

    def test_subagent_records_are_ignored(self):
        chat = ClaudeChat()
        chat.prompt("main question")
        answer = chat.reply("main answer")
        chat.prompt("subagent prompt", isSidechain=True, parent=None)
        chat.leaf = answer["uuid"]
        chat.bookkeeping("last-prompt")

        self.assertEqual([t.prompt.text for t in self.read(chat)], ["main question"])

    def test_an_empty_or_broken_file_reads_as_no_turns(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "chat.jsonl"
            path.write_text("not json\n\n{\"type\": \"custom-title\"}\n")
            self.assertEqual(claude_reader.read_chat(str(path)), [])


if __name__ == "__main__":
    unittest.main()
