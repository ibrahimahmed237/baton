"""Q15 streaming regressions on independently built temporary rows only."""
from contextlib import closing
import json
import sqlite3
import unittest

from baton.domain.errors import ChatChanged, ChatHeld, ChatReplying
from baton.domain.model import Message, Turn, PROMPT, REPLY
from tests.adapters.test_opencode import make, saved
from tests.fixtures.opencode import build as fx


class OpenCodeStreamingTests(unittest.TestCase):
    def setUp(self):
        self.root, self.adapter, self.process = make(self)
        self.chat = fx.build(self.root, [], chat="ses_native")
        self.process.is_running = True
        fx.insert_message(self.root, self.chat, "user", "user", fx.EARLY,
                          [{"type": "text", "text": "native question"}], model=fx.MODEL)
        fx.insert_message(self.root, self.chat, "reply", "assistant", fx.EARLY + 10,
                          [{"type": "text", "text": "first half"}], parentID="user", tokens={"total": 12})
        self.copy = Turn(Message("baton-user", PROMPT, "copied question"),
                         (Message("baton-reply", REPLY, "copied answer"),))

    def finish(self):
        at = int(self.adapter.now().timestamp() * 1000) + 1000
        fx.run_sql(self.root, "INSERT INTO part VALUES(?,?,?,?,?,?)",
                   ("late-part", "reply", self.chat, at, at,
                    json.dumps({"type": "text", "text": "second half", "messageID": "reply"})))
        fx.run_sql(self.root, "UPDATE message SET time_updated=?,data=json_set(data,'$.finish','stop','$.time.completed',?,'$.tokens.total',34) WHERE id='reply'", (at, at))
        # A continuation assistant can be created after Baton's user message.
        fx.insert_message(self.root, self.chat, "continuation", "assistant", at + 1,
                          [{"type": "text", "text": "native final", "messageID": "continuation"}],
                          parentID="user", finish="stop", tokens={"total": 56})
        fx.run_sql(self.root, "UPDATE session SET time_updated=? WHERE id=?", (at + 2, self.chat))

    def test_streaming_add_keeps_both_turns_usage_and_exact_rollback(self):
        self.assertTrue(self.adapter.state.condition(self.chat).replying)
        prepared = self.adapter.writer.prepare(self.chat, "add")
        result = self.adapter.writer.add(self.chat, [self.copy])
        self.assertTrue(self.adapter.state.condition(self.chat).replying)
        self.finish()
        expected = saved(self.adapter, self.chat)
        before = prepared.data["before"]
        after = result.receipt.data["after"]
        for table in ("message", "part"):
            added = {r["id"] for r in after[table]} - {r["id"] for r in before[table]}
            expected[table] = [r for r in expected[table] if r["id"] not in added]
        values = self.adapter.reader.read(self.chat)
        self.assertEqual([t.id for t in values], ["user", self.copy.id])
        self.assertEqual([m.text for m in values[0].messages], ["first half", "second half", "native final"])
        self.assertEqual(values[1], self.copy)
        self.assertEqual(self.adapter.reader.usage(self.chat).tokens, 56)
        self.assertFalse(self.adapter.state.condition(self.chat).replying)
        # Test recovery from the durable intent, not only the post-write receipt.
        self.adapter.writer.take_back(prepared)
        self.assertEqual(saved(self.adapter, self.chat), expected)
        self.assertEqual(self.adapter.reader.read(self.chat), [values[0]])

    def test_baton_replies_have_native_finished_fields_in_add_and_create(self):
        result = self.adapter.writer.add(self.chat, [self.copy])
        created = self.adapter.writer.create([self.copy], "copy", "folder")
        for chat in (self.chat, created.chat_id):
            rows, _ = self.adapter.reader.rows(chat)
            baton = [json.loads(r["data"]) for r in rows if json.loads(r["data"]).get("batonWritten")]
            self.assertTrue(baton)
            for data in baton:
                self.assertEqual(data["finish"], "stop")
                self.assertEqual(data["time"]["completed"], data["time"]["created"])
        self.assertFalse(self.adapter.state.condition(created.chat_id).replying)
        self.finish()
        self.assertFalse(self.adapter.state.condition(self.chat).replying)
        self.adapter.writer.take_back(result.receipt)

    def test_replying_still_refuses_all_existing_row_edits(self):
        result = self.adapter.writer.add(self.chat, [self.copy])
        before = saved(self.adapter, self.chat)
        for operation in (lambda: self.adapter.writer.take_back(result.receipt),
                          lambda: self.adapter.writer.cut(self.chat, "user"),
                          lambda: self.adapter.writer.place(self.chat, [], "user"),
                          lambda: self.adapter.writer.rename(self.chat, "renamed"),
                          lambda: self.adapter.writer.prepare(self.chat, "restore")):
            with self.assertRaises(ChatReplying):
                operation()
        self.assertEqual(saved(self.adapter, self.chat), before)

    def test_streaming_rollback_refuses_changed_baton_or_unrelated_rows(self):
        for sql in ("UPDATE part SET data=json_set(data,'$.text','edited') WHERE message_id IN (SELECT id FROM message WHERE json_extract(data,'$.batonWritten')=1)",
                    "UPDATE session SET title='edited'",
                    "UPDATE part SET data=json_set(data,'$.text','edited') WHERE message_id='user'",
                    "DELETE FROM part WHERE id='reply-part-0'",
                    "UPDATE part SET message_id='reply' WHERE message_id='user'",
                    "INSERT INTO message VALUES('outside-user','ses_native',999,999,'{\"role\":\"user\"}')"):
            with self.subTest(sql=sql):
                self.setUp()
                result = self.adapter.writer.add(self.chat, [self.copy])
                self.finish()
                fx.run_sql(self.root, sql)
                before = saved(self.adapter, self.chat)
                with self.assertRaises(ChatChanged):
                    self.adapter.writer.take_back(result.receipt)
                self.assertEqual(saved(self.adapter, self.chat), before)

    def test_restore_cut_still_refuses_while_replying(self):
        self.finish()
        cut = self.adapter.writer.cut(self.chat, "").receipt
        self.adapter.chat_status = lambda _: {"busy": True}
        before = saved(self.adapter, self.chat)
        with self.assertRaises(ChatReplying):
            self.adapter.writer.restore(cut)
        self.assertEqual(saved(self.adapter, self.chat), before)

    def test_add_compare_and_lock_guards_still_apply_during_reply(self):
        self.adapter.writer.prepare(self.chat, "add")
        fx.run_sql(self.root, "UPDATE part SET data=json_set(data,'$.text','progress') WHERE message_id='reply'")
        before = saved(self.adapter, self.chat)
        with self.assertRaises(ChatChanged):
            self.adapter.writer.add(self.chat, [self.copy])
        self.assertEqual(saved(self.adapter, self.chat), before)
        with closing(sqlite3.connect(fx.database(self.root), timeout=0)) as db:
            db.execute("BEGIN IMMEDIATE")
            with self.assertRaises(ChatHeld):
                self.adapter.writer.add(self.chat, [self.copy])
            db.rollback()

    def test_cut_keeps_late_native_reply_with_its_parent_user(self):
        self.adapter.writer.add(self.chat, [self.copy])
        self.finish()
        native = self.adapter.reader.read(self.chat)[0]
        before = saved(self.adapter, self.chat)
        result = self.adapter.writer.cut(self.chat, "user")
        self.assertEqual(self.adapter.reader.read(self.chat), [native])
        self.adapter.writer.take_back(result.receipt)
        self.assertEqual(saved(self.adapter, self.chat), before)

    def test_assistant_parent_beats_timestamp_and_orphans_are_not_guessed(self):
        # The reader resolves parents even if an assistant row precedes its user.
        fx.run_sql(self.root, "UPDATE message SET time_created=? WHERE id='reply'", (fx.EARLY - 10,))
        fx.insert_message(self.root, self.chat, "orphan", "assistant", fx.EARLY + 20,
                          [{"type": "text", "text": "must not attach"}], finish="stop")
        values = self.adapter.reader.read(self.chat)
        self.assertEqual(len(values), 1)
        self.assertEqual([m.text for m in values[0].messages], ["first half"])

    def test_reply_updates_in_place_survive_rollback_without_session_update(self):
        result = self.adapter.writer.add(self.chat, [self.copy])
        fx.run_sql(self.root, "UPDATE part SET data=json_set(data,'$.text','completed in place'),time_updated=time_updated+1 WHERE message_id='reply'")
        fx.run_sql(self.root, "UPDATE message SET data=json_set(data,'$.finish','stop','$.tokens.total',78),time_updated=time_updated+1 WHERE id='reply'")
        expected = saved(self.adapter, self.chat)
        for table in ("message", "part"):
            original_ids = {r["id"] for r in result.receipt.data["before"][table]}
            expected[table] = [r for r in expected[table] if r["id"] in original_ids]
        expected["session"] = result.receipt.data["before"]["session"]
        self.adapter.writer.take_back(result.receipt)
        self.assertEqual(saved(self.adapter, self.chat), expected)
        self.assertEqual(self.adapter.reader.read(self.chat)[0].reply_text, "completed in place")
        self.assertEqual(self.adapter.reader.usage(self.chat).tokens, 78)

    def test_cut_rollback_cannot_overwrite_later_native_progress(self):
        self.finish()
        result = self.adapter.writer.cut(self.chat, "user")
        fx.run_sql(self.root, "UPDATE part SET data=json_set(data,'$.text','outside') WHERE message_id='reply'")
        before = saved(self.adapter, self.chat)
        with self.assertRaises(ChatChanged):
            self.adapter.writer.take_back(result.receipt)
        self.assertEqual(saved(self.adapter, self.chat), before)
