"""The shared contract exercised by every chat adapter."""
from baton.domain.capabilities import HookNeed, Visibility, WriteWindow
from baton.domain.errors import AppMustBeClosed, ChatChanged, ChatHeld, NotAvailable, UnknownFormat
from baton.domain.model import Message, Turn, PROMPT, REPLY, TOOL_CALL, TOOL_RESULT
from baton.ports.tool import ToolAdapter


def turns() -> list[Turn]:
    """Build real prompts, replies and a tool call with stable ids."""
    return [Turn(Message("p1", PROMPT, "first", "2026-01-01T00:00:00Z"), (
        Message("c1", TOOL_CALL, tool="write", tool_input={"path": "file.py"}),
        Message("r1", TOOL_RESULT, "done", call_id="c1"), Message("a1", REPLY, "reply"))),
        Turn(Message("p2", PROMPT, "second"), (Message("a2", REPLY, "answer"),)),
        Turn(Message("p3", PROMPT, "third"), (Message("a3", REPLY, "finished"),))]


class AdapterSuite:
    """Supply make_adapter and fixture helpers to run these eleven checks."""
    def setUp(self):
        self.adapter = self.make_adapter()
        self.assertIsInstance(self.adapter, ToolAdapter)
        self.turns = turns()
        self.chat = self.build_chat(self.turns)

    def test_reads_turns(self):
        self.assertEqual(self.adapter.reader.read(self.chat), self.turns)
        self.assertEqual(self.adapter.reader.files_changed(self.turns[0]), ["file.py"])

    def test_skips_inserted_text(self):
        self.insert_text(self.chat, Message("inserted", PROMPT, "attached context"))
        self.assertEqual(self.adapter.reader.read(self.chat), self.turns)

    def test_round_trip(self):
        result = self.adapter.writer.create(self.turns, "copy", "folder")
        self.assertEqual(self.adapter.reader.read(result.chat_id), self.turns)
        self.assertEqual(list(result.local_ids), [turn.id for turn in self.turns])
        ref = self.adapter.locator.resolve(result.chat_id)
        self.assertEqual((ref.name, ref.folder), ("copy", "folder"))
        self.assertIn(ref, self.adapter.locator.chats())

    def test_second_read_adds_nothing(self):
        first = self.adapter.reader.read(self.chat)
        self.assertEqual(self.adapter.reader.read(self.chat), first)
        self.assertEqual([turn.id for turn in first], [turn.id for turn in self.turns])

    def test_create_then_add(self):
        result = self.adapter.writer.create(self.turns[:1], "copy", "folder")
        added = self.adapter.writer.add(result.chat_id, self.turns[1:])
        self.assertEqual(self.adapter.reader.read(result.chat_id), self.turns)
        self.assertEqual(list(added.local_ids), [turn.id for turn in self.turns[1:]])

    def test_condition(self):
        self.set_condition(self.chat, exists=True, open=True, replying=True, app_running=True)
        condition = self.adapter.state.condition(self.chat)
        self.assertTrue(all((condition.exists, condition.open, condition.replying, condition.app_running)))
        self.set_condition(self.chat, exists=False, open=False, replying=False, app_running=False)
        condition = self.adapter.state.condition(self.chat)
        self.assertFalse(any((condition.exists, condition.open, condition.replying, condition.app_running)))
        self.assertFalse(self.adapter.state.condition("missing").exists)

    def test_refuses_outside_write_window(self):
        self.set_condition(self.chat, open=True, app_running=True)
        window = self.adapter.facts.write_window
        if window == WriteWindow.ANY_TIME:
            self.adapter.writer.add(self.chat, [Turn(Message("p4", PROMPT, "more"))])
            return
        error = AppMustBeClosed if window == WriteWindow.APP_CLOSED else ChatHeld
        with self.assertRaises(error):
            self.adapter.writer.add(self.chat, [Turn(Message("p4", PROMPT, "more"))])
        # Renaming may need the whole app closed even when adding only needs a released chat.
        with self.assertRaises((error, AppMustBeClosed)):
            self.adapter.writer.rename(self.chat, "changed")
        if window == WriteWindow.APP_CLOSED:
            with self.assertRaises(error):
                self.adapter.writer.create([], "new", "")
        self.assertEqual(self.adapter.reader.read(self.chat), self.turns)

    def test_take_back(self):
        created = self.adapter.writer.create(self.turns[:1], "copy", "")
        first = self.adapter.writer.add(created.chat_id, self.turns[1:2])
        second = self.adapter.writer.add(created.chat_id, self.turns[2:])
        self.adapter.writer.take_back(second.receipt)
        self.assertEqual(self.adapter.reader.read(created.chat_id), self.turns[:2])
        self.adapter.writer.take_back(first.receipt)
        self.assertEqual(self.adapter.reader.read(created.chat_id), self.turns[:1])
        renamed = self.adapter.writer.rename(created.chat_id, "renamed")
        self.adapter.writer.take_back(renamed.receipt)
        self.assertEqual(self.adapter.locator.name(created.chat_id), "copy")
        self.adapter.writer.take_back(created.receipt)
        self.assertFalse(self.adapter.state.condition(created.chat_id).exists)

    def test_cut_or_refuse(self):
        if not self.adapter.facts.can_cut:
            with self.assertRaises(NotAvailable):
                self.adapter.writer.cut(self.chat, self.turns[0].id)
            self.assertEqual(self.adapter.reader.read(self.chat), self.turns)
            return
        result = self.adapter.writer.cut(self.chat, self.turns[0].id)
        self.assertEqual(self.adapter.reader.read(self.chat), self.turns[:1])
        self.adapter.writer.take_back(result.receipt)
        self.assertEqual(self.adapter.reader.read(self.chat), self.turns)

    def test_empty_cut_and_reversible_restore(self):
        if not self.adapter.facts.can_cut:
            return
        pre = self.adapter.writer.prepare(self.chat, 'cut')
        result = self.adapter.writer.cut(self.chat, '')
        self.assertEqual(self.adapter.reader.read(self.chat), [])
        self.adapter.writer.prepare(self.chat, 'restore')
        restored = self.adapter.writer.restore(result.receipt)
        self.assertEqual(self.adapter.reader.read(self.chat), self.turns)
        self.assertEqual(restored.receipt.kind, 'restore')
        self.adapter.writer.take_back(restored.receipt)
        self.assertEqual(self.adapter.reader.read(self.chat), [])
        self.adapter.writer.restore(result.receipt)
        self.assertEqual(self.adapter.reader.read(self.chat), self.turns)

    def test_restore_refuses_intervening_write_without_mutation(self):
        if not self.adapter.facts.can_cut:
            return
        result = self.adapter.writer.cut(self.chat, self.turns[0].id)
        self.adapter.writer.add(self.chat, self.turns[1:2])
        current = self.adapter.reader.read(self.chat)
        with self.assertRaises(ChatChanged):
            self.adapter.writer.restore(result.receipt)
        self.assertEqual(self.adapter.reader.read(self.chat), current)

    def test_unknown_version_blocks_writes(self):
        for known, version in ((False, self.adapter.facts.checked_versions[0]), (True, "unknown")):
            self.set_format(known, version)
            self.assertFalse(self.adapter.state.format_version().known)
            operations = [lambda: self.adapter.writer.create([], "new", ""),
                          lambda: self.adapter.writer.add(self.chat, []),
                          lambda: self.adapter.writer.rename(self.chat, "new"),
                          lambda: self.adapter.writer.place(self.chat, [], self.turns[0].id),
                          lambda: self.adapter.writer.cut(self.chat, self.turns[0].id)]
            for operation in operations:
                with self.assertRaises(UnknownFormat):
                    operation()
            self.assertEqual(self.adapter.reader.read(self.chat), self.turns)

    def test_facts_match_behaviour(self):
        facts = self.adapter.facts
        self.assertIn(self.adapter.state.format_version().version, facts.checked_versions)
        middle = Turn(Message("middle", PROMPT, "between"))
        if facts.can_place:
            result = self.adapter.writer.place(self.chat, [middle], self.turns[1].id)
            self.assertEqual(self.adapter.reader.read(self.chat), [self.turns[0], middle, *self.turns[1:]])
            self.adapter.writer.take_back(result.receipt)
            self.assertEqual(self.adapter.reader.read(self.chat), self.turns)
        else:
            with self.assertRaises(NotAvailable):
                self.adapter.writer.place(self.chat, [middle], self.turns[1].id)
        self.set_condition(self.chat, open=True)
        if facts.can_release_chat:
            self.adapter.app.release(self.chat)
            self.assertFalse(self.adapter.state.condition(self.chat).open)
        else:
            with self.assertRaises(NotAvailable):
                self.adapter.app.release(self.chat)
        self.set_condition(self.chat, open=False)
        self.adapter.app.open(self.chat, "folder")
        self.assertEqual(self.adapter.state.condition(self.chat).open, facts.opens_at_chat)
        self.adapter.app.close()
        usage = self.configure_usage(self.chat)
        self.assertEqual(usage.size is not None, facts.context_size_known)
        self.assertEqual(usage.limit_resets_at is not None, facts.limit_has_reset_time)
        self.assertTrue(usage.limit_reached)
        self.assertEqual(self.adapter.hooks.check().ok, facts.hooks_need == HookNeed.NONE)
        self.assertEqual(self.adapter.hooks.check().values["need"], facts.hooks_need.value)
        self.assertIsInstance(facts.replays_tool_calls, bool)
        self.assertEqual(self.adapter.reader.read(self.chat)[0].messages, self.turns[0].messages)
        created = self.adapter.writer.create(self.turns[:1], "visible", "")
        self.assertEqual(self.visible_turns(created.chat_id) is not None,
                         facts.new_chat_visible == Visibility.AT_ONCE)
        self.adapter.app.open(None, "folder")
        self.assertEqual(self.visible_turns(created.chat_id), self.turns[:1])
        self.adapter.app.close()
        self.adapter.writer.add(created.chat_id, self.turns[1:])
        expected = self.turns if facts.added_turn_visible == Visibility.AT_ONCE else self.turns[:1]
        self.assertEqual(self.visible_turns(created.chat_id), expected)
        if facts.added_turn_visible == Visibility.ON_REOPEN_CHAT:
            self.set_condition(created.chat_id, open=True)
        else:
            self.adapter.app.open(None, "folder")
        self.assertEqual(self.visible_turns(created.chat_id), self.turns)

    def test_prepared_receipts_precede_mutation_and_take_back(self):
        import json
        from dataclasses import asdict
        from baton.ports.tool import WriteReceipt
        prepared = self.adapter.writer.prepare(self.chat, "add")
        self.assertEqual(self.adapter.reader.read(self.chat), self.turns)
        prepared = WriteReceipt(**json.loads(json.dumps(asdict(prepared))))
        extra = Turn(Message("p4", PROMPT, "more"))
        self.adapter.writer.add(self.chat, [extra])
        self.adapter.writer.take_back(prepared)
        self.adapter.writer.take_back(prepared)
        self.assertEqual(self.adapter.reader.read(self.chat), self.turns)
        before = self.adapter.locator.chats()
        prepared = self.adapter.writer.prepare(None, "create")
        self.assertEqual(self.adapter.locator.chats(), before)
        result = self.adapter.writer.create([], "new", "")
        self.assertEqual(result.chat_id, prepared.chat_id)
        self.adapter.writer.take_back(prepared)
        self.adapter.writer.take_back(prepared)
        self.assertEqual(self.adapter.locator.chats(), before)
