"""Codex adapter on a home folder built in a temporary directory; no real Codex, chat or process is touched."""
import json
import sqlite3
import os
import subprocess
import sys
import stat
import tempfile
import unittest
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from baton.adapters.codex import CodexAdapter
from baton.domain.errors import ChatChanged, ChatHeld, ChatReplying, NotAvailable, UnknownFormat
from baton.notes.catalogue import CATALOGUE
from baton.domain.model import PROMPT, REPLY, TOOL_CALL, TOOL_RESULT, TOOL_TEXT, Message, Turn
from baton.ports.tool import WriteReceipt
from tests.adapters.suite import AdapterSuite, turns
from tests.fixtures.codex import build as fx
from tests.fixtures.no_processes import no_processes

RESET = datetime(2026, 1, 3, tzinfo=timezone.utc)


def new_home(test):
    """A temporary home folder, cleaned up after the test."""
    temp = tempfile.TemporaryDirectory()
    test.addCleanup(temp.cleanup)
    return Path(temp.name).resolve()


def new_adapter(test, root, **options):
    """An adapter on `root` with a fixture process, a ticking clock and a command that must never run."""
    process = fx.FixtureProcess(root)
    test.addCleanup(process.quit)
    options.setdefault("command", lambda *a, **k: SimpleNamespace(returncode=0, stdout="signed in"))
    options.setdefault("binary", str(root / "codex"))
    options.setdefault("hook_entrypoints_available", lambda: True)
    options.setdefault("now", fx.tick_clock())
    options.setdefault("allowed_chat_ids", ('thread-fixture', 'newer', 'bare', 'untitled', 'gone', 'outside', 'missing'))
    options.setdefault("coordination", fx.FixtureCoordination())
    adapter = CodexAdapter(root, process=process, **options)
    return adapter, process


def rollout_bytes(root, chat):
    return fx.rollout_file(root, chat).read_bytes()


def rollout_of(root, chat):
    """The rollout file the thread row names."""
    return Path(fx.run_sql(root, "SELECT rollout_path FROM threads WHERE id = ?", (chat,))[0][0])


def thread_row(root, chat):
    rows = fx.run_sql(root, "SELECT * FROM threads WHERE id = ?", (chat,))
    return rows[0] if rows else None


class CodexSuite(AdapterSuite, unittest.TestCase):
    """The shared adapter suite, with Codex's files as the fixture."""

    def make_adapter(self):
        self.root = new_home(self)
        adapter, self.process = new_adapter(self, self.root)
        adapter.hooks.install()
        return adapter

    def build_chat(self, values):
        return fx.build(self.root, values)

    def insert_text(self, chat, message):
        # What Codex stores for text a hook attached: a developer message next to the prompt.
        text = "<baton-catch-up>%s</baton-catch-up>" % message.text
        fx.append_event(self.root, chat, {"type": "message", "role": "developer", "id": message.id,
                                          "content": [{"type": "input_text", "text": text}]}, "response_item")

    def set_condition(self, chat, **values):
        if "app_running" in values:
            self.process.is_running = values["app_running"]
        if values.get("exists") is False:
            fx.run_sql(self.root, "DELETE FROM threads WHERE id = ?", (chat,))
            self.process.release(chat)
            return
        if values.get("open", False):
            self.process.hold(chat)
        else:
            self.process.release(chat)
        path = fx.rollout_file(self.root, chat)
        unfinished = self.adapter.state.unfinished_task(path)
        if values.get("replying", False) and not unfinished:
            fx.append_event(self.root, chat, {"type": "task_started", "turn_id": "live"})
        elif not values.get("replying", False) and unfinished:
            fx.append_event(self.root, chat, {"type": "task_complete", "turn_id": "live", "last_agent_message": None})

    def set_format(self, known, version):
        if not known:
            fx.append_event(self.root, self.chat, {"note": "written by a newer Codex"}, "record_from_the_future")
        if version not in self.adapter.facts.checked_versions:
            fx.run_sql(self.root, "ALTER TABLE threads DROP COLUMN history_mode")

    def configure_usage(self, chat):
        fx.append_event(self.root, chat, fx.token_count(total=5000, used=100.0, reset=RESET.timestamp(), reached="primary"))
        return self.adapter.reader.usage(chat)

    def visible_turns(self, chat):
        """What Codex's chat view would show: it is built from the task and item events, so those must agree."""
        if thread_row(self.root, chat) is None:
            return None
        records = fx.read_lines(rollout_of(self.root, chat))
        events = [r["payload"] for r in records if r["type"] == "event_msg"]
        started = [e for e in events if e["type"] == "task_started"]
        finished = [e for e in events if e["type"] == "task_complete"]
        shown = [e["item"]["content"][0]["text"] for e in events
                 if e["type"] == "item_completed" and e["item"]["type"] == "UserMessage"]
        read = self.adapter.reader.read(chat)
        if len(started) == len(finished) == len(read) and shown == [t.prompt.text for t in read]:
            return read
        return ["the chat view and the rollout disagree"]


class CodexBoundarySafety(unittest.TestCase):
    """B2 adversarial access, exclusion, recovery and native identity checks."""

    def setUp(self):
        self.root = new_home(self)
        self.chat = fx.build(self.root, turns())
        self.adapter, self.process = new_adapter(self, self.root, allowed_chat_ids=(self.chat,))

    def snapshot(self, ident=None):
        ident = ident or self.chat
        return rollout_of(self.root, ident).read_bytes(), thread_row(self.root, ident)

    def test_default_native_coordination_refuses_even_an_explicit_allowed_chat(self):
        adapter, _ = new_adapter(self, self.root, allowed_chat_ids=(self.chat,), coordination=None)
        before = self.snapshot()
        for mutation in (lambda: adapter.writer.add(self.chat, []),
                         lambda: adapter.writer.rename(self.chat, 'unsafe'),
                         lambda: adapter.writer.create(turns(), 'unsafe', '')):
            with self.assertRaises(NotAvailable): mutation()
        self.assertEqual(before, self.snapshot())
        self.assertFalse((self.root / '.baton-rollback').exists())

    def test_empty_default_scope_denies_direct_content_and_never_lists_working_chats(self):
        adapter = CodexAdapter(self.root, process=self.process)
        self.assertEqual(adapter.locator.chats(), [])
        for read in (lambda: adapter.reader.read(self.chat), lambda: adapter.reader.usage(self.chat),
                     lambda: adapter.locator.resolve(self.chat), lambda: adapter.writer.rename(self.chat, 'x')):
            with self.assertRaises(NotAvailable): read()

    def test_unrelated_newest_poison_is_never_read_or_used_as_template(self):
        outsider = fx.build(self.root, [Turn(Message('secret', PROMPT, 'PRIVATE-OUTSIDE'))], thread='working')
        fx.run_sql(self.root, "UPDATE threads SET updated_at_ms=9999999999999,sandbox_policy='OUTSIDE' WHERE id=?", (outsider,))
        outsider_path = rollout_of(self.root, outsider)
        outsider_path.write_bytes(outsider_path.read_bytes() + b'{"type":"future","ordinal":999,"payload":{}}\n')
        opened = []
        original = Path.open
        def safe_open(path, *args, **kwargs):
            opened.append(path)
            if Path(path) == outsider_path: raise AssertionError('outside chat content read')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'open', safe_open):
            self.assertTrue(self.adapter.state.format_version().known)
            self.assertEqual([r.id for r in self.adapter.locator.chats()], [self.chat])
            result = self.adapter.writer.create(turns()[:1], 'Baton test (safe to delete)', '')
            self.assertNotIn('PRIVATE-OUTSIDE', rollout_of(self.root, result.chat_id).read_text())
            self.assertNotIn('OUTSIDE', str(thread_row(self.root, result.chat_id)))
            for read in (lambda: self.adapter.reader.read(outsider), lambda: self.adapter.reader.usage(outsider)):
                with self.assertRaises(NotAvailable): read()
        self.assertNotIn(outsider_path, opened)

    def test_close_refuses_unscoped_held_chat_without_reading_its_rollout(self):
        outsider = fx.build(self.root, turns()[:1], thread='working')
        self.process.hold(outsider)
        with patch.object(self.adapter.state, 'replying', side_effect=AssertionError('unscoped reply scan')):
            with self.assertRaises(NotAvailable): self.adapter.app.close()
        self.assertNotIn(('quit',), self.process.calls)

    def test_allowed_row_cannot_alias_an_unrelated_rollout(self):
        outsider = fx.build(self.root, turns(), thread='working')
        path = rollout_of(self.root, outsider)
        fx.run_sql(self.root, 'UPDATE threads SET rollout_path=? WHERE id=?', (str(path), self.chat))
        with patch.object(Path, 'open', side_effect=AssertionError('outside file opened')):
            for read in (lambda: self.adapter.reader.read(self.chat), lambda: self.adapter.reader.usage(self.chat),
                         lambda: self.adapter.writer.rename(self.chat, 'x')):
                with self.assertRaises((KeyError,UnknownFormat,NotAvailable)): read()

    def test_symlink_and_hardlink_aliases_are_refused_before_content_reads(self):
        original = fx.rollout_file(self.root, self.chat)
        outside = self.root / 'private.jsonl'
        outside.write_text('PRIVATE-OUTSIDE')
        for link in ('symlink', 'hardlink'):
            with self.subTest(link=link):
                original.unlink()
                if link == 'symlink': original.symlink_to(outside)
                else: os.link(outside, original)
                with self.assertRaises((KeyError,NotAvailable)): self.adapter.reader.read(self.chat)
                self.assertEqual(outside.read_text(), 'PRIVATE-OUTSIDE')

    def test_old_target_unknown_records_and_malformed_shapes_block_rename(self):
        path = fx.rollout_file(self.root, self.chat)
        before = path.read_bytes()
        for extra in ({'type':'future','ordinal':999,'payload':{}},
                      {'type':'event_msg','ordinal':0,'payload':{}},
                      {'type':'event_msg','ordinal':999,'payload':[]},
                      {'type':'event_msg','ordinal':'999','payload':{}}):
            with self.subTest(extra=extra):
                path.write_bytes(before + (json.dumps(extra)+'\n').encode())
                native = self.snapshot()
                with self.assertRaises(UnknownFormat): self.adapter.writer.rename(self.chat, 'x')
                self.assertEqual(self.snapshot(), native)
        path.write_bytes(before + b'{"type":"event_msg","ordinal":999,"payload":{"text":"\xff"}}\n')
        with self.assertRaises(UnknownFormat): self.adapter.writer.rename(self.chat, 'x')

    def test_created_rollback_refuses_any_changed_row_column_without_deleting_rollout(self):
        for column, changed in (('name','outside'), ('tokens_used',999), ('is_pinned',1)):
            with self.subTest(column=column):
                result = self.adapter.writer.create(turns()[:1], 'copy', '')
                fx.run_sql(self.root, 'UPDATE threads SET '+column+'=? WHERE id=?', (changed,result.chat_id))
                before = self.snapshot(result.chat_id)
                with self.assertRaises(ChatChanged): self.adapter.writer.take_back(result.receipt)
                self.assertEqual(self.snapshot(result.chat_id), before)
                self.assertTrue(Path(result.receipt.data['intent']).exists())

    def test_full_row_stale_append_refuses_before_any_native_mutation(self):
        self.adapter.writer.prepare(self.chat,'add')
        fx.run_sql(self.root,'UPDATE threads SET is_pinned=1 WHERE id=?',(self.chat,))
        before=self.snapshot()
        with self.assertRaises(ChatChanged): self.adapter.writer.add(self.chat,[Turn(Message('more',PROMPT,'more'))])
        self.assertEqual(self.snapshot(),before)

    def test_restart_discovers_created_descendant_and_recovers_reverse_order_writes(self):
        created=self.adapter.writer.create(turns()[:1],'copy','')
        other,_=new_adapter(self,self.root,allowed_chat_ids=(self.chat,))
        self.assertIn(created.chat_id,[r.id for r in other.locator.chats()])
        self.assertEqual(other.reader.read(created.chat_id),turns()[:1])
        added=other.writer.add(created.chat_id,turns()[1:])
        third,_=new_adapter(self,self.root,allowed_chat_ids=(self.chat,))
        third.writer.take_back(added.receipt)
        third.writer.take_back(created.receipt)
        self.assertIsNone(thread_row(self.root,created.chat_id))
        self.assertFalse(Path(created.receipt.data['rollout']['path']).exists())

    def test_created_receipt_cannot_cross_original_scope_or_forge_manifest_identity(self):
        created=self.adapter.writer.create(turns()[:1],'copy','')
        outside,_=new_adapter(self,self.root,allowed_chat_ids=('other',))
        with self.assertRaises(ValueError): outside.writer.take_back(created.receipt)
        forged=WriteReceipt('codex',self.chat,'create',created.receipt.data)
        with self.assertRaises(ValueError): self.adapter.writer.take_back(forged)
        self.assertIsNotNone(thread_row(self.root,created.chat_id))

    def test_rollback_metadata_is_private_even_with_permissive_umask(self):
        previous=os.umask(0)
        try: result=self.adapter.writer.add(self.chat,[Turn(Message('more',PROMPT,'more'))])
        finally: os.umask(previous)
        intent=Path(result.receipt.data['intent'])
        self.assertEqual(stat.S_IMODE(intent.stat().st_mode),0o600)
        self.assertEqual(stat.S_IMODE(intent.parent.stat().st_mode),0o700)

    def test_hostile_rollback_parent_symlink_never_publishes_outside_private_directory(self):
        outside=self.root/'outside';outside.mkdir()
        (self.root/'.baton-rollback').symlink_to(outside,target_is_directory=True)
        before=self.snapshot()
        with self.assertRaises(NotAvailable): self.adapter.writer.add(self.chat,[])
        self.assertEqual(list(outside.iterdir()),[])
        self.assertEqual(self.snapshot(),before)

    def test_missing_lock_is_created_and_held_continuously_against_independent_process(self):
        writer=self.adapter.writer
        lock=self.adapter.locator.locks/(self.chat+'.lock')
        self.assertFalse(lock.exists())
        attempted=[]
        def peer():
            script="import fcntl,os,sys; f=os.open(sys.argv[1],os.O_RDWR);\ntry: fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)\nexcept BlockingIOError: sys.exit(7)\nsys.exit(0)"
            result=subprocess.run([sys.executable,'-c',script,str(lock)],capture_output=True)
            attempted.append(result.returncode)
            self.assertEqual(result.returncode,7,result.stderr)
        original_check,original_row,original_revert=writer._recheck,writer._write_row,writer._revert_locked
        def checked(*a,**k): peer();return original_check(*a,**k)
        def failed(*a,**k): peer();original_row(*a,**k);raise RuntimeError('after index')
        def reverted(*a,**k): peer();return original_revert(*a,**k)
        before=self.snapshot()
        with patch.object(writer,'_recheck',side_effect=checked),patch.object(writer,'_write_row',side_effect=failed),patch.object(writer,'_revert_locked',side_effect=reverted):
            with self.assertRaises(RuntimeError): writer.add(self.chat,[Turn(Message('more',PROMPT,'more'))])
        self.assertEqual(attempted,[7,7,7])
        self.assertEqual(self.snapshot(),before)

    def test_unlinked_or_replaced_native_lock_before_mutation_refuses_zero_changes(self):
        for replace in (False,True):
            with self.subTest(replace=replace):
                before=self.snapshot();writer=self.adapter.writer;original=writer._recheck
                def changed(*a,**k):
                    original(*a,**k)
                    lock=self.adapter.locator.locks/(self.chat+'.lock');lock.unlink()
                    if replace:lock.write_text('replacement')
                with patch.object(writer,'_recheck',side_effect=changed),self.assertLogs('baton.adapters.codex.writer','ERROR'):
                    with self.assertRaises(ChatChanged):writer.add(self.chat,[Turn(Message('more',PROMPT,'more'))])
                self.assertEqual(self.snapshot(),before)

    def test_lock_replacement_after_append_keeps_intent_then_fresh_recovery_restores_exactly(self):
        writer=self.adapter.writer;before=self.snapshot();original=writer._write_row
        pre=writer.prepare(self.chat,'add')
        def replaced(*a,**k):
            lock=self.adapter.locator.locks/(self.chat+'.lock');lock.unlink();lock.write_text('replacement')
            return original(*a,**k)
        with patch.object(writer,'_write_row',side_effect=replaced),self.assertLogs('baton.adapters.codex.writer','ERROR'):
            with self.assertRaises(ChatChanged):writer.add(self.chat,[Turn(Message('more',PROMPT,'more'))])
        self.assertTrue(Path(pre.data['intent']).exists())
        other,_=new_adapter(self,self.root,allowed_chat_ids=(self.chat,))
        other.writer.take_back(pre)
        self.assertEqual(self.snapshot(),before)

    def test_guessed_trust_hash_never_reports_ready_or_reads_unverified_config(self):
        self.adapter.hooks.install();fx.trust_hooks(self.root)
        config=fx.home(self.root)/'config.toml';before=config.read_bytes()
        original=Path.read_text
        def protected(path,*a,**k):
            if Path(path)==config:raise AssertionError('unverified trust config read')
            return original(path,*a,**k)
        with patch.object(Path,'read_text',protected):
            finding=self.adapter.hooks.check()
            self.assertFalse(finding.ok);self.assertEqual(finding.note_id,'setup.trust_once')
            self.assertFalse(self.adapter.state.condition(self.chat).hooks_ready)
        self.assertEqual(config.read_bytes(),before)

    def test_invalid_history_offset_or_ordinal_preserves_native_write_and_intent(self):
        result=self.adapter.writer.add(self.chat,[Turn(Message('more',PROMPT,'more'))])
        for offset,ordinal in ((-1,0),(None,0),('bad',0),(0,-1),(0,None),(0,'bad')):
            with self.subTest(offset=offset,ordinal=ordinal):
                fx.run_sql(self.root,'INSERT OR REPLACE INTO thread_history_projection_state VALUES (?,?,?)',(self.chat,offset,ordinal),database='thread_history_1.sqlite')
                before=self.snapshot()
                with self.assertRaises(NotAvailable):self.adapter.writer.take_back(result.receipt)
                self.assertEqual(self.snapshot(),before)
                self.assertTrue(Path(result.receipt.data['intent']).exists())

    def test_native_directory_and_database_aliases_are_refused_before_sqlite_reads(self):
        for target,link in (('.codex','symlink'),('.codex/state_5.sqlite','symlink'),('.codex/state_5.sqlite','hardlink')):
            with self.subTest(target=target,link=link):
                root=new_home(self);chat=fx.build(root,turns());adapter,_=new_adapter(self,root,allowed_chat_ids=(chat,))
                original=root/target;outside=root/'outside-native'
                original.rename(outside)
                if link=='symlink':original.symlink_to(outside,target_is_directory=outside.is_dir())
                else:os.link(outside,original)
                with patch('sqlite3.connect',side_effect=AssertionError('aliased database accessed')):
                    for operation in (lambda:adapter.locator.chats(),lambda:adapter.reader.read(chat),lambda:adapter.writer.rename(chat,'x')):
                        with self.assertRaises(NotAvailable):operation()

    def test_history_database_symlink_or_hardlink_never_licenses_rollback(self):
        for link in ('symlink','hardlink'):
            with self.subTest(link=link):
                root=new_home(self);chat=fx.build(root,turns());adapter,_=new_adapter(self,root,allowed_chat_ids=(chat,))
                result=adapter.writer.add(chat,[Turn(Message('more',PROMPT,'more'))])
                original=fx.home(root)/'thread_history_1.sqlite';outside=root/'outside-index';original.rename(outside)
                if link=='symlink':original.symlink_to(outside)
                else:os.link(outside,original)
                before=rollout_of(root,chat).read_bytes(),thread_row(root,chat)
                with self.assertRaises(NotAvailable):adapter.writer.take_back(result.receipt)
                self.assertEqual((rollout_of(root,chat).read_bytes(),thread_row(root,chat)),before)
                self.assertTrue(Path(result.receipt.data['intent']).exists())

    def test_template_and_format_refuse_hardlinked_allowed_name_before_opening_content(self):
        original=fx.rollout_file(self.root,self.chat)
        outside=self.root/'private-chat.jsonl';outside.write_text('PRIVATE-OUTSIDE-INSTRUCTIONS')
        original.unlink();os.link(outside,original)
        with patch.object(Path,'open',side_effect=AssertionError('aliased content opened')):
            self.assertFalse(self.adapter.state.format_version().known)
            with self.assertRaises(UnknownFormat):self.adapter.writer.create(turns(),'copy','')
            self.assertIsNone(self.adapter.writer._template()['base_instructions'])

    def test_changed_manifest_path_cannot_redirect_rollback_to_other_content(self):
        result=self.adapter.writer.add(self.chat,[Turn(Message('more',PROMPT,'more'))])
        intent=Path(result.receipt.data['intent']);manifest=json.loads(intent.read_text())
        outside=self.root/'PRIVATE-OUTSIDE';outside.write_text('private')
        manifest['rollout']['path']=str(outside);intent.write_text(json.dumps(manifest))
        before=self.snapshot();original=Path.read_bytes
        def guarded(path,*a,**k):
            if Path(path)==outside:raise AssertionError('outside receipt path read')
            return original(path,*a,**k)
        with patch.object(Path,'read_bytes',guarded):
            with self.assertRaises(ValueError):self.adapter.writer.take_back(result.receipt)
        self.assertEqual(self.snapshot(),before);self.assertEqual(outside.read_text(),'private')

    def test_created_delete_cas_refuses_changed_row_even_if_preflight_is_wrong(self):
        result=self.adapter.writer.create(turns()[:1],'copy','')
        fx.run_sql(self.root,'UPDATE threads SET name=? WHERE id=?',('outside',result.chat_id))
        before=self.snapshot(result.chat_id)
        with patch.object(self.adapter.writer,'_row_state',return_value='after'):
            with self.assertRaises(ChatChanged):self.adapter.writer.take_back(result.receipt)
        self.assertEqual(self.snapshot(result.chat_id),before)

    def test_crash_after_rollback_file_change_preserves_intent_for_fresh_recovery(self):
        before=self.snapshot();writer=self.adapter.writer
        result=writer.add(self.chat,[Turn(Message('more',PROMPT,'more'))])
        remove=writer._remove_appended
        def interrupted(*a,**k):remove(*a,**k);raise KeyboardInterrupt()
        with patch.object(writer,'_remove_appended',side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt):writer.take_back(result.receipt)
        self.assertTrue(Path(result.receipt.data['intent']).exists())
        other,_=new_adapter(self,self.root,allowed_chat_ids=(self.chat,))
        other.writer.take_back(result.receipt)
        self.assertEqual(self.snapshot(),before)

    def test_missing_projection_database_does_not_license_rollback(self):
        result=self.adapter.writer.add(self.chat,[Turn(Message('more',PROMPT,'more'))])
        (fx.home(self.root)/'thread_history_1.sqlite').unlink()
        before=self.snapshot()
        with self.assertRaises(NotAvailable):self.adapter.writer.take_back(result.receipt)
        self.assertEqual(self.snapshot(),before)
        self.assertTrue(Path(result.receipt.data['intent']).exists())

    def test_database_side_file_aliases_are_refused_before_backend_access(self):
        outside=self.root/'outside';outside.write_text('PRIVATE-OUTSIDE')
        for suffix in ('-wal','-shm','-journal'):
            with self.subTest(suffix=suffix):
                link=fx.home(self.root)/('state_5.sqlite'+suffix);link.symlink_to(outside)
                try:
                    with patch('sqlite3.connect',side_effect=AssertionError('SQLite accessed aliased companion')):
                        with self.assertRaises(NotAvailable):self.adapter.locator.chats()
                finally:link.unlink()
        self.assertEqual(outside.read_text(),'PRIVATE-OUTSIDE')

    def test_public_sql_helper_cannot_read_unscoped_rows_or_accept_sql_suffixes(self):
        cases=(('SELECT first_user_message FROM threads',()),
               ('SELECT * FROM threads',()),
               ('SELECT * FROM threads WHERE id = ? OR 1=1',(self.chat,)),
               ('SELECT * FROM threads WHERE id = ? UNION SELECT * FROM threads',(self.chat,)),
               ('SELECT * FROM threads WHERE id = ?',('working',)),
               ('SELECT * FROM threads WHERE id = ?',(self.chat,'working')),
               ('SELECT * FROM threads WHERE id IN (?,?)',(self.chat,'working')))
        for active in (False,True):
            with self.subTest(active_transaction=active):
                self.adapter.locator._writer_connection=SimpleNamespace(execute=lambda *a,**k:self.fail('unscoped transaction read')) if active else None
                try:
                    with patch('sqlite3.connect',side_effect=AssertionError('unscoped backend read')):
                        for query,params in cases:
                            with self.assertRaises(NotAvailable):self.adapter.locator.read_rows(query,params)
                finally:self.adapter.locator._writer_connection=None
        self.assertEqual(self.adapter.locator.read_rows('SELECT * FROM threads WHERE id = ?',(self.chat,))[0]['id'],self.chat)

    def test_unverified_history_offset_column_never_licenses_truncation(self):
        result=self.adapter.writer.add(self.chat,[Turn(Message('more',PROMPT,'more'))])
        fx.run_sql(self.root,'ALTER TABLE thread_history_projection_state RENAME COLUMN next_byte_offset TO guessed_offset',database='thread_history_1.sqlite')
        before=self.snapshot()
        with self.assertRaises(NotAvailable):self.adapter.writer.take_back(result.receipt)
        self.assertEqual(self.snapshot(),before)


class CodexSafety(unittest.TestCase):
    """Behaviour the shared suite does not cover: the write window, rollback, receipts and the format guard."""

    def setUp(self):
        self.root = new_home(self)
        self.adapter, self.process = new_adapter(self, self.root)
        self.chat = fx.build(self.root, turns())

    def snapshot(self):
        return rollout_bytes(self.root, self.chat), thread_row(self.root, self.chat)

    def json_receipt(self, receipt):
        return WriteReceipt(**json.loads(json.dumps(asdict(receipt))))

    # -- the write window ---------------------------------------------------

    def test_add_to_a_held_chat_is_refused_and_writes_nothing(self):
        self.process.hold(self.chat)
        before = self.snapshot()
        with self.assertRaises(ChatHeld):
            self.adapter.writer.add(self.chat, [Turn(Message("p4", PROMPT, "more"))])
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(ChatHeld.note_id, "write.chat_open")
        self.assertFalse((self.root / ".baton-rollback").exists())

    def test_add_to_a_chat_that_is_replying_is_refused(self):
        self.process.hold(self.chat)
        fx.append_event(self.root, self.chat, {"type": "task_started", "turn_id": "live"})
        before = self.snapshot()
        with self.assertRaises(ChatReplying):
            self.adapter.writer.add(self.chat, [Turn(Message("p4", PROMPT, "more"))])
        self.assertEqual(self.snapshot(), before)

    def test_chat_released_by_codex_takes_turns_even_while_the_app_runs(self):
        self.process.is_running = True
        self.process.hold("someone-elses-chat")
        result = self.adapter.writer.add(self.chat, [Turn(Message("p4", PROMPT, "more"))])
        self.assertEqual([t.id for t in self.adapter.reader.read(self.chat)][-1], "p4")
        self.assertEqual(result.local_ids, ("p4",))

    def test_unfinished_task_in_a_chat_nobody_holds_still_counts_as_replying_and_is_not_written_to(self):
        # H1: hold detection is unverified on the real app, so a task started without a completion is
        # a reply whether or not the chat looks held. A crashed task in a closed chat is refused too
        # (accepted for now; to be decided after the live run).
        fx.append_event(self.root, self.chat, {"type": "task_started", "turn_id": "crashed"})
        condition = self.adapter.state.condition(self.chat)
        self.assertEqual((condition.open, condition.replying), (False, True))
        self.assertEqual(self.adapter.state.replying_chats(), [self.chat])
        before = self.snapshot()
        for write in (lambda: self.adapter.writer.add(self.chat, [Turn(Message("p4", PROMPT, "more"))]),
                      lambda: self.adapter.writer.rename(self.chat, "renamed")):
            with self.assertRaises(ChatReplying) as refused:
                write()
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.root / ".baton-rollback").exists())
        self.assertIn(refused.exception.note_id, CATALOGUE)

    def test_a_reply_is_refused_as_replying_before_it_is_refused_as_held(self):
        self.process.hold(self.chat)
        fx.append_event(self.root, self.chat, {"type": "task_started", "turn_id": "live"})
        with self.assertRaises(ChatReplying):
            self.adapter.writer.add(self.chat, [Turn(Message("p4", PROMPT, "more"))])
        fx.append_event(self.root, self.chat, {"type": "task_complete", "turn_id": "live", "last_agent_message": None})
        with self.assertRaises(ChatHeld):
            self.adapter.writer.add(self.chat, [Turn(Message("p4", PROMPT, "more"))])

    def test_a_finished_task_in_a_chat_nobody_holds_is_idle(self):
        fx.append_event(self.root, self.chat, {"type": "task_started", "turn_id": "done"})
        fx.append_event(self.root, self.chat, {"type": "turn_aborted", "turn_id": "done"})
        self.assertFalse(self.adapter.state.condition(self.chat).replying)
        self.assertEqual(self.adapter.state.replying_chats(), [])
        self.adapter.writer.add(self.chat, [Turn(Message("p4", PROMPT, "more"))])

    def test_an_unfinished_task_is_refused_under_the_exclusive_lease_too(self):
        # H2: with the lease set, _check used to return right after lease.check().
        writer = self.adapter.writer
        with self.adapter.coordination.exclusive(self.adapter.locator, self.chat) as lease:
            writer.lease = lease
            try:
                writer._check(self.chat)  # idle: the lease's own lock is not a reason to refuse
                fx.append_event(self.root, self.chat, {"type": "task_started", "turn_id": "live"})
                with self.assertRaises(ChatReplying):
                    writer._check(self.chat)
            finally:
                writer.lease = None

    def test_cut_and_place_and_restore_are_not_available(self):
        before = self.snapshot()
        for operation in (lambda: self.adapter.writer.cut(self.chat, "p1"),
                          lambda: self.adapter.writer.cut(self.chat, ""),
                          lambda: self.adapter.writer.place(self.chat, [], "p2"),
                          lambda: self.adapter.writer.restore(WriteReceipt("codex", self.chat, "cut", {})),
                          lambda: self.adapter.writer.prepare(self.chat, "cut")):
            with self.assertRaises(NotAvailable):
                operation()
        self.assertEqual(self.snapshot(), before)

    # -- what is written ----------------------------------------------------

    def test_appended_records_continue_the_ordinals_and_carry_the_events_codex_builds_its_view_from(self):
        old = fx.read_lines(fx.rollout_file(self.root, self.chat))
        extra = Turn(Message("p4", PROMPT, "more", "2026-01-05T00:00:00Z"),
                     (Message("a4", REPLY, "ok", "2026-01-05T00:00:01Z"),))
        self.adapter.writer.add(self.chat, [extra])
        records = fx.read_lines(fx.rollout_file(self.root, self.chat))
        new = records[len(old):]
        self.assertEqual([r["ordinal"] for r in records], list(range(len(records))))
        self.assertEqual([(r["type"], r["payload"]["type"]) for r in new],
                         [("event_msg", "task_started"), ("event_msg", "item_completed"), ("response_item", "message"),
                          ("event_msg", "item_completed"), ("response_item", "message"), ("event_msg", "task_complete")])
        self.assertEqual(new[1]["payload"]["item"]["type"], "UserMessage")
        self.assertEqual(new[3]["payload"]["item"]["type"], "AgentMessage")
        self.assertEqual(new[0]["payload"]["turn_id"], new[-1]["payload"]["turn_id"])
        self.assertEqual(new[-1]["payload"]["last_agent_message"], "ok")
        self.assertEqual([r["payload"]["id"] for r in new if r["type"] == "response_item"], ["p4", "a4"])
        self.assertEqual(new[2]["timestamp"], "2026-01-05T00:00:00Z")

    def test_append_keeps_every_earlier_byte_and_bumps_the_threads_times(self):
        before_bytes, before_row = self.snapshot()
        self.adapter.writer.add(self.chat, [Turn(Message("p4", PROMPT, "more"))])
        after_bytes, after_row = self.snapshot()
        self.assertTrue(after_bytes.startswith(before_bytes))
        names = [row[1] for row in fx.run_sql(self.root, "PRAGMA table_info(threads)")]
        changed = {name for name, a, b in zip(names, before_row, after_row) if a != b}
        self.assertEqual(changed, {"updated_at", "updated_at_ms", "recency_at", "recency_at_ms"})
        self.assertGreater(after_row[names.index("updated_at_ms")], before_row[names.index("updated_at_ms")])

    def test_duplicate_ids_are_refused_without_writing(self):
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.adapter.writer.add(self.chat, [Turn(Message("p1", PROMPT, "again"))])
        self.assertEqual(self.snapshot(), before)

    def test_created_chat_copies_settings_and_instructions_from_the_newest_user_chat(self):
        fx.insert_thread(self.root, "newer", title="newer", updated_ms=1_800_000_000_000,
                         sandbox_policy='{"type":"newest"}', rollout_path=str(fx.rollout_file(self.root, "newer")))
        fx.write_lines(fx.rollout_file(self.root, "newer"), fx.native_records(turns()[:1], "newer", "/x"))
        result = self.adapter.writer.create(turns()[:1], "copy", "/work")
        row = thread_row(self.root, result.chat_id)
        columns = [r[1] for r in fx.run_sql(self.root, "PRAGMA table_info(threads)")]
        row = dict(zip(columns, row))
        self.assertEqual((row["sandbox_policy"], row["cwd"], row["title"], row["name"]), ('{"type":"newest"}', "/work", "copy", "copy"))
        self.assertEqual((row["thread_source"], row["originator"], row["archived"]), ("user", "Codex Desktop", 0))
        self.assertEqual(row["first_user_message"], "first")
        meta = fx.read_lines(row["rollout_path"])[0]
        self.assertEqual(meta["type"], "session_meta")
        self.assertEqual(meta["payload"]["base_instructions"], fx.BASE_INSTRUCTIONS)
        self.assertEqual(meta["payload"]["id"], result.chat_id)
        self.assertTrue(Path(row["rollout_path"]).name.endswith("-%s.jsonl" % result.chat_id))
        self.assertTrue(Path(row["rollout_path"]).is_relative_to(self.root / ".codex" / "sessions"))

    def test_created_chat_without_any_chat_to_copy_is_read_only(self):
        root = new_home(self)
        adapter, _ = new_adapter(self, root)
        fx.create_databases(root)
        result = adapter.writer.create(turns()[:1], "first", "/work")
        columns = [r[1] for r in fx.run_sql(root, "PRAGMA table_info(threads)")]
        row = dict(zip(columns, thread_row(root, result.chat_id)))
        self.assertEqual((row["sandbox_policy"], row["approval_mode"]), ('{"type":"read-only"}', "on-request"))
        self.assertNotIn("base_instructions", fx.read_lines(row["rollout_path"])[0]["payload"])
        self.assertEqual(adapter.reader.read(result.chat_id), turns()[:1])

    def test_without_a_state_database_nothing_is_created(self):
        root = new_home(self)
        adapter, _ = new_adapter(self, root)
        with self.assertRaises(NotAvailable):
            adapter.writer.create([], "x", "")
        self.assertFalse((root / ".codex").exists())

    def test_tool_text_and_an_incomplete_turn_survive_the_round_trip(self):
        values = [Turn(Message("p4", PROMPT, "question", "2026-01-05T00:00:00Z"),
                       (Message("t4", TOOL_TEXT, "[Tool 1: read]\ntext", "2026-01-05T00:00:01Z"),
                        Message("a4", REPLY, "answer", "2026-01-05T00:00:02Z"))),
                  Turn(Message("p5", PROMPT, "incomplete", "2026-01-05T00:00:03Z"),
                       (Message("t5", TOOL_TEXT, "[Tool 2: read]\nmore", "2026-01-05T00:00:04Z"),))]
        result = self.adapter.writer.create(values, "copy", "/folder")
        read = self.adapter.reader.read(result.chat_id)
        self.assertEqual(read, values)
        self.assertEqual(read[1].reply_text, "")
        records = fx.read_lines(rollout_of(self.root, result.chat_id))
        assistant = [r for r in records if r["type"] == "response_item" and r["payload"].get("role") == "assistant"]
        self.assertEqual([r["payload"]["content"][0]["type"] for r in assistant], ["output_text"] * 3)
        self.assertEqual([r.get("batonMessageKind") for r in assistant], [TOOL_TEXT, None, TOOL_TEXT])

    def test_tool_calls_without_a_call_id_and_unknown_times_read_back_as_written(self):
        values = [Turn(Message("p4", PROMPT, "go"), (Message("c4", TOOL_CALL, tool="shell", tool_input={"command": ["ls"]}),
                                                      Message("r4", TOOL_RESULT, "ok", call_id=""),
                                                      Message("a4", REPLY, "done")))]
        result = self.adapter.writer.create(values, "copy", "")
        self.assertEqual(self.adapter.reader.read(result.chat_id), values)

    def test_files_changed_reads_edit_tools_and_apply_patch(self):
        patch_text = "*** Begin Patch\n*** Update File: src/a.py\n@@\n-x\n+y\n*** Add File: src/b.py\n+z\n*** End Patch"
        turn = Turn(Message("p", PROMPT, "x"), (
            Message("c1", TOOL_CALL, tool="apply_patch", tool_input=patch_text, call_id="k1"),
            Message("c2", TOOL_CALL, tool="shell", tool_input={"command": ["apply_patch", patch_text.replace("src/a", "src/c")]}, call_id="k2"),
            Message("c3", TOOL_CALL, tool="Edit", tool_input={"file_path": "d.py"}, call_id="k3"),
            Message("c4", TOOL_CALL, tool="shell", tool_input={"command": ["ls"]}, call_id="k4")))
        self.assertEqual(self.adapter.reader.files_changed(turn), ["src/a.py", "src/b.py", "src/c.py", "d.py"])

    # -- rollback -----------------------------------------------------------

    def test_create_failing_at_the_thread_row_removes_the_rollout(self):
        fx.run_sql(self.root, "CREATE TRIGGER no_threads BEFORE INSERT ON threads BEGIN SELECT RAISE(ABORT, 'no'); END")
        files = sorted(p for p in (self.root / ".codex" / "sessions").rglob("*.jsonl"))
        with self.assertRaises(sqlite3.Error):
            self.adapter.writer.create(turns(), "copy", "/new")
        self.assertEqual(sorted((self.root / ".codex" / "sessions").rglob("*.jsonl")), files)
        self.assertEqual(len(fx.run_sql(self.root, "SELECT id FROM threads")), 1)
        self.assertEqual(list((self.root / ".baton-rollback").glob("*")), [])

    def test_create_whose_rollout_does_not_read_back_is_removed_before_the_row_exists(self):
        files = sorted((self.root / ".codex" / "sessions").rglob("*.jsonl"))
        with patch("baton.adapters.codex.writer.parse_strict", side_effect=ValueError("damaged")):
            with self.assertRaises(ChatChanged):
                self.adapter.writer.create(turns(), "copy", "/new")
        self.assertEqual(sorted((self.root / ".codex" / "sessions").rglob("*.jsonl")), files)
        self.assertEqual(len(fx.run_sql(self.root, "SELECT id FROM threads")), 1)

    def test_add_failing_at_the_thread_row_cuts_the_rollout_back(self):
        fx.run_sql(self.root, "CREATE TRIGGER no_updates BEFORE UPDATE ON threads BEGIN SELECT RAISE(ABORT, 'no'); END")
        before = self.snapshot()
        with self.assertRaises(sqlite3.Error):
            self.adapter.writer.add(self.chat, [Turn(Message("p4", PROMPT, "more"))])
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(list((self.root / ".baton-rollback").glob("*")), [])

    def test_add_that_does_not_read_back_is_cut_back(self):
        before = self.snapshot()
        # A prompt Codex would take for text of its own is not read as a turn.
        with self.assertRaises(ChatChanged):
            self.adapter.writer.add(self.chat, [Turn(Message("p4", PROMPT, "<environment_context>x</environment_context>"))])
        self.assertEqual(self.snapshot(), before)

    def test_a_chat_that_changed_after_the_receipt_was_prepared_is_not_written(self):
        self.adapter.writer.prepare(self.chat, "add")
        # A finished task: the chat changed but is idle (an unfinished one is refused as a reply instead).
        fx.append_event(self.root, self.chat, {"type": "task_started", "turn_id": "codex-own"})
        fx.append_event(self.root, self.chat, {"type": "task_complete", "turn_id": "codex-own", "last_agent_message": None})
        before = self.snapshot()
        with self.assertRaises(ChatChanged):
            self.adapter.writer.add(self.chat, [Turn(Message("p4", PROMPT, "more"))])
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(list((self.root / ".baton-rollback").glob("*")), [])

    def test_a_thread_row_changed_after_the_receipt_was_prepared_is_not_written(self):
        self.adapter.writer.prepare(self.chat, "rename")
        fx.run_sql(self.root, "UPDATE threads SET name = 'outside' WHERE id = ?", (self.chat,))
        with self.assertRaises(ChatChanged):
            self.adapter.writer.rename(self.chat, "mine")
        self.assertEqual(self.adapter.locator.name(self.chat), "outside")

    def test_receipt_prepared_before_the_write_recovers_in_a_fresh_adapter(self):
        pre = self.adapter.writer.prepare(self.chat, "add")
        before = self.snapshot()
        self.adapter.writer.add(self.chat, [Turn(Message("p4", PROMPT, "more"))])
        other, _ = new_adapter(self, self.root)
        receipt = self.json_receipt(pre)
        other.writer.take_back(receipt)
        other.writer.take_back(receipt)
        self.assertEqual(self.snapshot(), before)

    def test_crash_between_rollout_and_row_is_recovered_from_the_prepared_receipt(self):
        pre = self.adapter.writer.prepare(None, "create")
        with patch.object(self.adapter.writer, "_write_row", side_effect=KeyboardInterrupt), \
                patch.object(self.adapter.writer, "_revert"):
            with self.assertRaises(KeyboardInterrupt):
                self.adapter.writer.create(turns(), "copy", "/new")
        rollout = Path(pre.data["rollout"]["path"])
        self.assertTrue(rollout.exists())
        self.assertIsNone(thread_row(self.root, pre.chat_id))
        other, _ = new_adapter(self, self.root)
        other.writer.take_back(self.json_receipt(pre))
        self.assertFalse(rollout.exists())
        self.assertEqual(list((self.root / ".baton-rollback").glob("*")), [])
        self.assertFalse(other.state.condition(pre.chat_id).exists)

    def test_half_appended_turn_is_recovered(self):
        pre = self.adapter.writer.prepare(self.chat, "add")
        before = self.snapshot()
        with patch.object(self.adapter.writer, "_verify_rollout", side_effect=KeyboardInterrupt), \
                patch.object(self.adapter.writer, "_revert"):
            with self.assertRaises(KeyboardInterrupt):
                self.adapter.writer.add(self.chat, [Turn(Message("p4", PROMPT, "more"))])
        path = fx.rollout_file(self.root, self.chat)
        path.write_bytes(path.read_bytes()[:len(before[0]) + 20])
        self.adapter.writer.take_back(self.json_receipt(pre))
        self.assertEqual(self.snapshot(), before)

    # -- taking back --------------------------------------------------------

    def test_take_back_of_the_last_append_works_while_the_index_has_not_read_past_it(self):
        before = self.snapshot()
        fx.set_index_offset(self.root, self.chat, len(before[0]))
        result = self.adapter.writer.add(self.chat, [Turn(Message("p4", PROMPT, "more"))])
        self.adapter.writer.take_back(result.receipt)
        self.assertEqual(self.snapshot(), before)

    def test_take_back_is_refused_once_codex_has_read_past_the_append(self):
        result = self.adapter.writer.add(self.chat, [Turn(Message("p4", PROMPT, "more"))])
        written = rollout_bytes(self.root, self.chat)
        fx.set_index_offset(self.root, self.chat, len(written))
        row = thread_row(self.root, self.chat)
        with self.assertRaises(NotAvailable):
            self.adapter.writer.take_back(result.receipt)
        self.assertEqual((rollout_bytes(self.root, self.chat), thread_row(self.root, self.chat)), (written, row))

    def test_take_back_is_refused_when_the_index_cannot_be_read(self):
        result = self.adapter.writer.add(self.chat, [Turn(Message("p4", PROMPT, "more"))])
        fx.run_sql(self.root, "DROP TABLE thread_history_projection_state", database="thread_history_1.sqlite")
        with self.assertRaises(NotAvailable):
            self.adapter.writer.take_back(result.receipt)

    def test_take_back_leaves_later_turns_alone(self):
        first = self.adapter.writer.add(self.chat, [Turn(Message("p4", PROMPT, "more"))])
        self.adapter.writer.add(self.chat, [Turn(Message("p5", PROMPT, "later"))])
        before = self.snapshot()
        with self.assertRaises(ChatChanged):
            self.adapter.writer.take_back(first.receipt)
        self.assertEqual(self.snapshot(), before)

    def test_take_back_is_refused_when_codex_wrote_into_the_chat_since(self):
        result = self.adapter.writer.add(self.chat, [Turn(Message("p4", PROMPT, "more"))])
        fx.append_event(self.root, self.chat, {"type": "task_started", "turn_id": "codex-own"})
        before = self.snapshot()
        with self.assertRaises(ChatChanged):
            self.adapter.writer.take_back(result.receipt)
        self.assertEqual(self.snapshot(), before)

    def test_take_back_never_writes_into_a_held_chat(self):
        result = self.adapter.writer.add(self.chat, [Turn(Message("p4", PROMPT, "more"))])
        self.process.hold(self.chat)
        before = self.snapshot()
        with self.assertRaises(ChatHeld):
            self.adapter.writer.take_back(result.receipt)
        self.assertEqual(self.snapshot(), before)

    def test_a_consumed_receipt_cannot_be_used_twice(self):
        result = self.adapter.writer.add(self.chat, [Turn(Message("p4", PROMPT, "more"))])
        self.adapter.writer.take_back(result.receipt)
        with self.assertRaises(ValueError):
            self.adapter.writer.take_back(result.receipt)

    def test_another_tools_receipt_is_refused(self):
        with self.assertRaises(ValueError):
            self.adapter.writer.take_back(WriteReceipt("claude", self.chat, "add", {}))

    # -- rename -------------------------------------------------------------

    def test_rename_sets_title_and_name_only(self):
        before = thread_row(self.root, self.chat)
        self.adapter.writer.rename(self.chat, "new name")
        names = [row[1] for row in fx.run_sql(self.root, "PRAGMA table_info(threads)")]
        changed = {n for n, a, b in zip(names, before, thread_row(self.root, self.chat)) if a != b}
        self.assertEqual(changed, {"title", "name"})
        self.assertEqual(self.adapter.locator.name(self.chat), "new name")

    def test_rename_of_a_held_chat_is_refused(self):
        self.process.hold(self.chat)
        with self.assertRaises(ChatHeld):
            self.adapter.writer.rename(self.chat, "x")
        self.assertEqual(self.adapter.locator.name(self.chat), "fixture")

    def test_rename_take_back_refuses_an_outside_rename(self):
        result = self.adapter.writer.rename(self.chat, "planned")
        fx.run_sql(self.root, "UPDATE threads SET name = 'outside' WHERE id = ?", (self.chat,))
        with self.assertRaises(ChatChanged):
            self.adapter.writer.take_back(result.receipt)
        self.assertEqual(self.adapter.locator.name(self.chat), "outside")

    # -- the format guard ---------------------------------------------------

    def test_a_threads_table_missing_a_column_blocks_writes_but_not_reads(self):
        fx.run_sql(self.root, "ALTER TABLE threads DROP COLUMN originator")
        self.assertEqual(self.adapter.state.format_version().known, False)
        self.assertEqual(self.adapter.reader.read(self.chat), turns())
        self.assertFalse(self.adapter.state.condition(self.chat).format_known)
        with self.assertRaises(UnknownFormat):
            self.adapter.writer.add(self.chat, [])

    def test_a_new_column_that_needs_a_value_blocks_creating_chats(self):
        fx.run_sql(self.root, "ALTER TABLE threads ADD COLUMN workspace TEXT NOT NULL DEFAULT 'x'")
        self.assertTrue(self.adapter.state.format_version().known)
        root = new_home(self)
        adapter, _ = new_adapter(self, root)
        fx.home(root).mkdir(parents=True)
        schema = fx.THREADS_SCHEMA.replace("agent_role TEXT", "agent_role TEXT, needed TEXT NOT NULL")
        fx.run_sql(root, schema, database="state_5.sqlite")
        self.assertFalse(adapter.state.format_version().known)
        with self.assertRaises(UnknownFormat):
            adapter.writer.create([], "x", "")

    def test_unknown_record_type_in_a_recent_rollout_blocks_writes(self):
        fx.append_event(self.root, self.chat, {"x": 1}, "record_from_the_future")
        self.assertFalse(self.adapter.state.format_version().known)
        self.assertEqual(self.adapter.reader.read(self.chat), turns())
        with self.assertRaises(UnknownFormat):
            self.adapter.writer.create([], "x", "")

    def test_a_line_codex_is_still_writing_does_not_block_other_chats(self):
        path = fx.rollout_file(self.root, self.chat)
        path.write_bytes(path.read_bytes() + b'{"type": "event_msg", "payl')
        self.assertTrue(self.adapter.state.format_version().known)
        with self.assertRaises(UnknownFormat):
            self.adapter.writer.add(self.chat, [])
        self.adapter.writer.create([], "elsewhere", "")

    def test_a_damaged_line_blocks_adding_to_that_chat_only(self):
        path = fx.rollout_file(self.root, self.chat)
        path.write_bytes(path.read_bytes() + b"{damaged}\n")
        self.assertEqual(self.adapter.reader.read(self.chat), turns())
        before = path.read_bytes()
        with self.assertRaises(UnknownFormat):
            self.adapter.writer.add(self.chat, [])
        self.assertEqual(path.read_bytes(), before)

    # -- locator, state -----------------------------------------------------

    def test_locator_lists_chats_a_user_could_link(self):
        fx.insert_thread(self.root, "archived", archived=1)
        fx.insert_thread(self.root, "sub", thread_source="subagent")
        fx.insert_thread(self.root, "helper", agent_role="worker")
        fx.insert_thread(self.root, "norollout", rollout_path="")
        fx.insert_thread(self.root, "untitled", title="first words", name=None, updated_ms=1_767_225_700_000)
        refs = {r.id: r for r in self.adapter.locator.chats()}
        self.assertEqual(sorted(refs), ["thread-fixture", "untitled"])
        self.assertEqual(refs["thread-fixture"].folder, "/fixture/project")
        self.assertEqual(refs["thread-fixture"].updated_at, "2026-01-01T00:00:00Z")
        self.assertEqual([r.id for r in self.adapter.locator.chats()][0], "untitled")

    def test_a_thread_whose_rollout_is_missing_or_outside_the_root_does_not_exist(self):
        fx.insert_thread(self.root, "gone")
        fx.insert_thread(self.root, "outside", rollout_path="/etc/hosts")
        for chat in ("gone", "outside"):
            self.assertFalse(self.adapter.state.condition(chat).exists)
            with self.assertRaises(KeyError):
                self.adapter.locator.resolve(chat)

    def test_a_lock_file_nobody_holds_does_not_mean_held(self):
        locks = self.root / ".codex" / "thread-writer-locks"
        locks.mkdir(parents=True)
        (locks / (self.chat + ".lock")).write_text("")
        self.assertFalse(self.adapter.state.condition(self.chat).open)
        self.process.hold(self.chat)
        self.assertTrue(self.adapter.state.condition(self.chat).open)
        self.assertEqual(self.adapter.state.held_chats(), [self.chat])
        self.process.release(self.chat)
        self.assertEqual(self.adapter.state.held_chats(), [])

    def test_chat_ids_cannot_point_the_lock_check_elsewhere(self):
        self.assertFalse(self.adapter.state.held("../state_5.sqlite"))
        with self.assertRaises(NotAvailable):
            self.adapter.state.condition("../x")

    def test_records_are_read_from_the_end_across_block_boundaries(self):
        from baton.adapters.codex.records import records_from_end
        path = self.root / "tail.jsonl"
        lines = [json.dumps({"type": "event_msg", "n": n, "pad": "x" * (n % 7 * 5)}) for n in range(40)]
        path.write_text("\n".join(lines) + "\n" + '{"type": "event_msg", "n": 40, "pa')
        for chunk in (1, 7, 64, 1 << 18):
            self.assertEqual([r["n"] for r in records_from_end(path, chunk=chunk)], list(range(39, -1, -1)), chunk)
        recent = [r["n"] for r in records_from_end(path, budget=200, chunk=64)]
        self.assertEqual(recent[0], 39)
        self.assertLess(len(recent), 40)

    # -- usage --------------------------------------------------------------

    def test_usage_reads_the_last_token_count(self):
        fx.append_event(self.root, self.chat, fx.token_count(total=7000, window=200000))
        usage = self.adapter.reader.usage(self.chat)
        self.assertEqual((usage.tokens, usage.size, usage.limit_reached, usage.limit_resets_at), (7000, 200000, False, None))

    def test_usage_falls_back_to_input_plus_output_and_to_the_last_event_that_has_info(self):
        event = fx.token_count()
        del event["info"]["last_token_usage"]["total_tokens"]
        fx.append_event(self.root, self.chat, event)
        fx.append_event(self.root, self.chat, {"type": "token_count", "info": None, "rate_limits": None})
        self.assertEqual(self.adapter.reader.usage(self.chat).tokens, 1234)

    def test_usage_with_no_token_count_is_zero_and_unknown(self):
        bare = fx.build(self.root, [], thread="bare")
        usage = self.adapter.reader.usage(bare)
        self.assertEqual((usage.tokens, usage.size, usage.limit_reached), (0, None, False))

    def test_a_limit_reached_names_when_it_resets_and_ends_after_that(self):
        fx.append_event(self.root, self.chat, fx.token_count(used=100.0, reset=RESET.timestamp(), reached="primary"))
        usage = self.adapter.reader.usage(self.chat)
        self.assertEqual((usage.limit_reached, usage.limit_resets_at), (True, "2026-01-03T00:00:00Z"))
        later, _ = new_adapter(self, self.root, now=lambda: datetime(2026, 1, 4, tzinfo=timezone.utc))
        self.assertFalse(later.reader.usage(self.chat).limit_reached)

    def test_the_weekly_window_decides_when_only_it_is_full(self):
        event = fx.token_count(reset=RESET.timestamp())
        event["rate_limits"]["secondary"].update(used_percent=100.0, resets_at=RESET.timestamp() + 86400)
        fx.append_event(self.root, self.chat, event)
        self.assertEqual(self.adapter.reader.usage(self.chat).limit_resets_at, "2026-01-04T00:00:00Z")

    # -- hooks --------------------------------------------------------------

    def test_hooks_are_added_beside_other_entries_and_removed_alone(self):
        path = self.adapter.hooks.path
        path.parent.mkdir(parents=True, exist_ok=True)
        original = {"other": {"keep": True}, "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "mine"}]}]}}
        path.write_text(json.dumps(original))
        self.adapter.hooks.install()
        self.adapter.hooks.install()
        value = json.loads(path.read_text())
        self.assertEqual(len(value["hooks"]["Stop"]), 2)
        self.assertEqual(len(value["hooks"]["UserPromptSubmit"]), 1)
        self.adapter.hooks.uninstall()
        self.assertEqual(json.loads(path.read_text()), {**original, "hooks": original["hooks"]})

    def test_check_reports_each_step_and_never_writes_trust(self):
        hooks = self.adapter.hooks
        finding = hooks.check()
        self.assertEqual((finding.ok, finding.note_id, finding.values["installed"]), (False, "setup.hooks", False))
        hooks.install()
        finding = hooks.check()
        self.assertEqual((finding.ok, finding.note_id, finding.values["trusted"]), (False, "setup.trust_once", False))
        self.assertFalse((self.root / ".codex" / "config.toml").exists())
        fx.trust_hooks(self.root)
        config = (self.root / ".codex" / "config.toml").read_bytes()
        self.assertEqual((hooks.check().ok, hooks.check().note_id), (False, "setup.trust_once"))
        self.assertEqual((self.root / ".codex" / "config.toml").read_bytes(), config)

    def test_trust_for_one_of_the_two_entries_is_not_enough(self):
        self.adapter.hooks.install()
        fx.trust_hooks(self.root, events=("Stop",))
        self.assertEqual(self.adapter.hooks.check().note_id, "setup.trust_once")

    def test_trust_of_someone_elses_hooks_file_does_not_count(self):
        self.adapter.hooks.install()
        (self.root / ".codex" / "config.toml").write_text(
            '[hooks.state."/elsewhere/hooks.json:userpromptsubmit:0:0"]\ntrusted_hash = "x"\n'
            '[hooks.state."/elsewhere/hooks.json:stop:0:0"]\ntrusted_hash = "x"\n')
        self.assertFalse(self.adapter.hooks.check().ok)

    def test_missing_entry_points_refuse_to_install(self):
        adapter, _ = new_adapter(self, self.root, hook_entrypoints_available=lambda: False)
        self.assertFalse(adapter.hooks.install().ok)
        self.assertFalse(adapter.hooks.path.exists())

    def test_an_unreadable_hooks_file_is_never_overwritten(self):
        path = self.adapter.hooks.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json")
        with self.assertRaises(ValueError):
            self.adapter.hooks.install()
        self.assertEqual(path.read_text(), "{not json")

    def test_hook_output_is_exactly_what_codex_accepts(self):
        hooks = self.adapter.hooks
        self.assertEqual(hooks.turn_end_reply(), "{}")
        self.assertEqual(hooks.attach_reply("", None), "{}")
        both = json.loads(hooks.attach_reply("context", "notice"))
        self.assertEqual(both, {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "context"},
                                "systemMessage": "notice"})
        self.assertNotIn("systemMessage", json.loads(hooks.attach_reply("context", None)))

    # -- runner and app -----------------------------------------------------

    def test_runner_builds_the_ephemeral_read_only_command_and_runs_it_only_through_the_injected_launcher(self):
        binary = self.root / "codex"
        binary.write_text("")
        calls = []

        def launcher(args, **kwargs):
            calls.append((args, kwargs))
            return SimpleNamespace(returncode=0, stdout="brief")
        adapter, _ = new_adapter(self, self.root, command=launcher, binary=str(binary))
        self.assertEqual(adapter.runner.ask("summarize", "/fixture"), "brief")
        args, kwargs = calls[-1]
        self.assertEqual(args, [str(binary), "exec", "--ephemeral", "-s", "read-only", "--", "summarize"])
        self.assertEqual(kwargs["cwd"], "/fixture")
        self.assertNotIn("resume", args)
        self.assertNotIn(self.chat, args)

    def test_runner_refuses_when_not_read_only_missing_or_signed_out(self):
        binary = self.root / "codex"
        binary.write_text("")
        adapter, _ = new_adapter(self, self.root, binary=str(binary))
        with self.assertRaises(NotAvailable):
            adapter.runner.ask("x", "/f", read_only=False)
        missing, _ = new_adapter(self, self.root, binary=str(self.root / "nowhere"))
        self.assertFalse(missing.runner.available().ok)
        self.assertEqual(missing.runner.available().note_id, "setup.runner")
        out, _ = new_adapter(self, self.root, binary=str(binary), command=lambda *a, **k: SimpleNamespace(returncode=1, stdout=""))
        self.assertFalse(out.runner.available().ok)
        with self.assertRaises(NotAvailable):
            out.runner.ask("x", "/f")

    def test_runner_failure_is_not_an_answer(self):
        binary = self.root / "codex"
        binary.write_text("")
        results = iter([SimpleNamespace(returncode=0, stdout=""), SimpleNamespace(returncode=2, stdout="partial")])
        adapter, _ = new_adapter(self, self.root, binary=str(binary), command=lambda *a, **k: next(results))
        with self.assertRaises(NotAvailable):
            adapter.runner.ask("x", "/f")

    def test_app_opens_the_chat_through_a_codex_link(self):
        self.adapter.app.open(self.chat, "/folder")
        self.assertEqual(self.process.calls, [("open_url", "codex://threads/" + self.chat)])
        self.assertTrue(self.adapter.state.condition(self.chat).open)
        self.adapter.app.open(None, None)
        self.assertEqual(self.process.calls[-1], ("open_app",))
        with self.assertRaises(KeyError):
            self.adapter.app.open("missing", None)

    def test_app_refuses_to_close_while_a_held_chat_is_replying(self):
        self.process.hold(self.chat)
        fx.append_event(self.root, self.chat, {"type": "task_started", "turn_id": "live"})
        self.process.is_running = True
        with self.assertRaises(ChatReplying):
            self.adapter.app.close()
        self.assertNotIn(("quit",), self.process.calls)
        fx.append_event(self.root, self.chat, {"type": "turn_aborted", "turn_id": "live"})
        self.adapter.app.close()
        self.assertEqual((self.adapter.app.running(), self.adapter.state.held_chats()), (False, []))

    def test_app_refuses_to_close_while_a_chat_nobody_holds_has_an_unfinished_task(self):
        # H1: hold detection is unverified, so closing is refused for an unheld unfinished task as well.
        fx.append_event(self.root, self.chat, {"type": "task_started", "turn_id": "crashed"})
        self.process.is_running = True
        self.assertEqual(self.adapter.state.held_chats(), [])
        with self.assertRaises(ChatReplying) as refused:
            self.adapter.app.close()
        self.assertEqual(self.process.calls, [])
        self.assertTrue(self.process.is_running)
        self.assertIn(refused.exception.note_id, CATALOGUE)

    def test_app_refuses_without_verified_global_idle_and_never_asks_to_quit(self):
        self.adapter.coordination = None
        self.process.is_running = True
        self.process.quit = lambda: None
        times = iter([0.0, 5.0, 11.0])
        with patch("baton.adapters.codex.app.time.monotonic", side_effect=lambda: next(times)), \
                patch("baton.adapters.codex.app.time.sleep"):
            with self.assertRaises(NotAvailable):
                self.adapter.app.close()

    def test_one_chat_cannot_be_released(self):
        with self.assertRaises(NotAvailable):
            self.adapter.app.release(self.chat)

    # -- containment --------------------------------------------------------

    def test_a_whole_session_never_asks_for_the_real_home_or_a_real_process(self):
        def forbidden(*args, **kwargs):
            raise AssertionError("touched the real home or a real process")
        with patch("pathlib.Path.home", side_effect=forbidden), patch("os.path.expanduser", side_effect=forbidden), \
                patch("subprocess.run", side_effect=forbidden), patch("subprocess.Popen", side_effect=forbidden):
            adapter, _ = new_adapter(self, self.root)
            created = adapter.writer.create(turns(), "copy", "/new")
            adapter.writer.add(created.chat_id, [Turn(Message("p9", PROMPT, "more"))])
            adapter.writer.rename(created.chat_id, "renamed")
            adapter.hooks.install()
            adapter.app.open(created.chat_id, None)
            adapter.app.close()
            adapter.reader.usage(created.chat_id)
        for path in (adapter.locator.state_db, adapter.locator.home, adapter.hooks.path):
            self.assertTrue(path.is_relative_to(self.root))
        written = [p for p in self.root.rglob("*") if p.is_file()]
        self.assertTrue(all(p.is_relative_to(self.root) for p in written))


class CodexBuiltWithOnlyARoot(unittest.TestCase):
    """H3: the constructor wiring uses for an injected root never reaches the real machine."""

    def test_a_bare_adapter_starts_no_process_and_opens_and_quits_nothing(self):
        from baton.adapters.codex.app import InertProcess
        from baton.adapters.codex.runner import InertRunner
        root = new_home(self)
        chat = fx.build(root, turns())
        with no_processes():
            adapter = CodexAdapter(root, allowed_chat_ids=(chat,))
            self.assertIsInstance(adapter.process, InertProcess)
            self.assertIsInstance(adapter.runner, InertRunner)
            self.assertFalse(adapter.app.running())
            condition = adapter.state.condition(chat)
            self.assertEqual((condition.exists, condition.app_running, condition.app_started_at), (True, False, ""))
            self.assertFalse(adapter.runner.available().ok)
            self.assertEqual(adapter.runner.available().note_id, "setup.runner")
            adapter.hooks.check()
            adapter.state.format_version()
            for refused in (lambda: adapter.runner.ask("q", "/f"), lambda: adapter.app.open(None, None),
                            lambda: adapter.app.open(chat, None), adapter.app.close):
                with self.assertRaises(NotAvailable):
                    refused()

    def test_a_bare_adapter_reports_nothing_installed_from_an_empty_root(self):
        root = new_home(self)
        with no_processes():
            adapter = CodexAdapter(root)
            self.assertEqual(adapter.locator.chats(), [])
            self.assertFalse(adapter.app.running())
            self.assertFalse(adapter.runner.available().ok)

    def test_the_machine_form_picks_the_real_process_control_and_launcher_without_calling_them(self):
        from baton.adapters.codex.app import SystemProcess
        from baton.adapters.codex.runner import CodexRunner
        adapter = CodexAdapter.on_this_machine(new_home(self))
        self.assertIsInstance(adapter.process, SystemProcess)
        self.assertIsInstance(adapter.runner, CodexRunner)
        self.assertIs(adapter.runner.command, subprocess.run)
        explicit = CodexAdapter.on_this_machine(new_home(self), process=fx.FixtureProcess(new_home(self)))
        self.assertNotIsInstance(explicit.process, SystemProcess)


class CodexThroughTheEngine(unittest.TestCase):
    """The engine's services drive the adapter: linking, delivery, and undo where Codex cannot cut."""

    def setUp(self):
        from baton.adapters.fake import FakeAdapter
        from baton.adapters.fake.facts import CLAUDE_LIKE
        from baton.ledger.sqlite_store import Ledger
        from baton.ports.clock import FixedClock
        self.root = new_home(self)
        self.codex, self.process = new_adapter(self, self.root)
        self.other = FakeAdapter(CLAUDE_LIKE, "claude")
        self.adapters = {"claude": self.other, "codex": self.codex}
        self.store = Ledger(":memory:")
        self.addCleanup(self.store.close)
        self.clock = FixedClock("2026-10-05T01:00:00Z")

    def link_and_deliver(self):
        from baton.services.applier import Applier
        from baton.services.linker import Linker
        chat = fx.build(self.root, turns()[:1])
        source = self.other.build_chat(self.codex.reader.read(chat))
        linker = Linker(self.store, self.adapters, self.clock)
        linked = linker.apply(linker.plan_link("claude", source, "codex", chat))
        self.assertTrue(linked.applied, linked)
        self.other.chats[source] += turns()[1:]
        applier = Applier(self.store, self.adapters, self.clock)
        applier.refresh(linked.link_id)
        delivered = applier.apply(applier.preview(linked.link_id))
        self.assertTrue(delivered.applied, delivered)
        return chat, linked

    def test_turns_written_elsewhere_are_added_to_a_released_codex_chat(self):
        chat, _ = self.link_and_deliver()
        self.assertEqual([t.prompt.text for t in self.codex.reader.read(chat)], ["first", "second", "third"])
        self.assertEqual(self.codex.state.index.read_offset(chat), 0)

    def test_undo_makes_a_shorter_chat_because_codex_cannot_cut(self):
        from baton.services.undo import Undo
        chat, linked = self.link_and_deliver()
        before = rollout_bytes(self.root, chat)
        event = next(e.id for e in self.store.history(linked.link_id) if e.kind == "add")
        service = Undo(self.store, self.adapters, self.clock)
        undone = service.apply(service.plan(linked.link_id, event))
        self.assertTrue(undone.applied, undone)
        self.assertEqual(rollout_bytes(self.root, chat), before)
        self.assertEqual(len(self.codex.locator.chats()), 2)


if __name__ == "__main__":
    unittest.main()
