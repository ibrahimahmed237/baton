"""NativeCoordination on a home built in a temporary folder; no real Codex lock is ever touched."""
import os
import stat
import subprocess
import sys
import unittest
from unittest.mock import patch

from baton.adapters.codex import CodexAdapter
from baton.adapters.codex.coordination import NativeCoordination
from baton.domain.errors import ChatChanged, ChatHeld, NotAvailable
from baton.domain.model import PROMPT, Message, Turn
from tests.adapters.suite import turns
from tests.adapters.test_codex import new_adapter, new_home, rollout_of, thread_row
from tests.fixtures.codex import build as fx
from tests.fixtures.no_processes import no_processes

# A second process that tries to take the lock, exiting 7 when it is held.
_PEER = ("import fcntl,os,sys\n"
         "f=os.open(sys.argv[1],os.O_RDWR)\n"
         "try: fcntl.flock(f,fcntl.LOCK_SH|fcntl.LOCK_NB)\n"
         "except BlockingIOError: sys.exit(7)\n"
         "sys.exit(0)")
# A second process that holds the lock the way Codex does, until its input closes.
_HOLDER = ("import fcntl,os,sys\n"
           "f=os.open(sys.argv[1],os.O_RDWR|os.O_CREAT,0o600)\n"
           "fcntl.flock(f,fcntl.LOCK_EX)\n"
           "print('held',flush=True)\n"
           "sys.stdin.read()")


class NativeCoordinationTests(unittest.TestCase):
    def setUp(self):
        self.root = new_home(self)
        self.chat = fx.build(self.root, turns())
        self.coordination = NativeCoordination()
        self.adapter, _ = new_adapter(self, self.root, allowed_chat_ids=(self.chat,),
                                      coordination=self.coordination)
        self.lock = self.adapter.locator.locks / (self.chat + ".lock")

    def snapshot(self):
        return rollout_of(self.root, self.chat).read_bytes(), thread_row(self.root, self.chat)

    def peer(self):
        return subprocess.run([sys.executable, "-c", _PEER, str(self.lock)], capture_output=True).returncode

    def hold_from_subprocess(self):
        holder = subprocess.Popen([sys.executable, "-c", _HOLDER, str(self.lock)], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, text=True)
        self.addCleanup(holder.stdout.close)
        self.addCleanup(holder.wait)
        self.addCleanup(holder.stdin.close)
        self.assertEqual(holder.stdout.readline().strip(), "held")
        return holder

    def test_the_lock_is_taken_while_inside_and_gone_after(self):
        self.assertFalse(self.lock.exists())
        with self.coordination.exclusive(self.adapter.locator, self.chat) as lease:
            self.assertEqual(self.peer(), 7)
            info = self.lock.lstat()
            self.assertEqual(stat.S_IMODE(info.st_mode), 0o600)
            self.assertEqual(info.st_size, 0)
            lease.check()
        self.assertFalse(self.lock.exists())

    def test_the_lock_is_released_when_the_body_fails(self):
        with self.assertRaises(RuntimeError):
            with self.coordination.exclusive(self.adapter.locator, self.chat):
                raise RuntimeError("boom")
        self.assertFalse(self.lock.exists())
        with self.coordination.exclusive(self.adapter.locator, self.chat):
            pass

    def test_a_lock_file_that_was_already_there_is_left_in_place(self):
        self.lock.parent.mkdir(parents=True)
        self.lock.write_text("")
        before = self.lock.lstat().st_ino
        with self.coordination.exclusive(self.adapter.locator, self.chat):
            self.assertEqual(self.peer(), 7)
        self.assertEqual(self.lock.lstat().st_ino, before)
        self.assertEqual(self.peer(), 0)

    def test_a_lock_file_replaced_during_the_lease_fails_the_check_and_is_not_deleted(self):
        with self.coordination.exclusive(self.adapter.locator, self.chat) as lease:
            self.lock.unlink()
            self.lock.write_text("replacement")
            with self.assertRaises(ChatChanged):
                lease.check()
        self.assertEqual(self.lock.read_text(), "replacement")

    def test_a_lock_file_removed_during_the_lease_fails_the_check(self):
        with self.coordination.exclusive(self.adapter.locator, self.chat) as lease:
            self.lock.unlink()
            with self.assertRaises(ChatChanged):
                lease.check()
        self.assertFalse(self.lock.exists())

    def test_a_replaced_lock_folder_fails_the_check(self):
        with self.coordination.exclusive(self.adapter.locator, self.chat) as lease:
            folder = self.lock.parent
            folder.rename(folder.with_name("moved"))
            folder.mkdir()
            with self.assertRaises(ChatChanged):
                lease.check()
        (folder.with_name("moved") / self.lock.name).unlink(missing_ok=True)

    def test_a_lock_held_by_another_process_means_held_and_the_file_stays(self):
        self.lock.parent.mkdir(parents=True)
        holder = self.hold_from_subprocess()
        with self.assertRaises(ChatHeld):
            with self.coordination.exclusive(self.adapter.locator, self.chat):
                self.fail("must not be entered")
        self.assertTrue(self.lock.exists())
        holder.stdin.close()
        holder.wait()

    def test_a_held_chat_is_refused_and_nothing_is_written(self):
        self.lock.parent.mkdir(parents=True)
        self.hold_from_subprocess()
        before = self.snapshot()
        for mutation in (lambda: self.adapter.writer.add(self.chat, [Turn(Message("more", PROMPT, "more"))]),
                         lambda: self.adapter.writer.rename(self.chat, "renamed")):
            with self.assertRaises(ChatHeld):
                mutation()
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.root / ".baton-rollback").exists())

    def test_the_lease_is_what_refuses_a_lock_taken_after_the_writer_looked(self):
        # The writer's own held check passes; only the exclusive lock can catch a holder that arrived later.
        writer = self.adapter.writer
        self.lock.parent.mkdir(parents=True)
        self.hold_from_subprocess()
        before = self.snapshot()
        with patch.object(self.adapter.state, "held", return_value=False), self.assertRaises(ChatHeld):
            writer.add(self.chat, [Turn(Message("more", PROMPT, "more"))])
        self.assertEqual(self.snapshot(), before)

    def test_a_symlinked_lock_path_is_refused_and_its_target_is_untouched(self):
        outside = self.root / "outside.txt"
        outside.write_text("keep")
        self.lock.parent.mkdir(parents=True)
        self.lock.symlink_to(outside)
        before = self.snapshot()
        with self.assertRaises(NotAvailable):
            self.adapter.writer.add(self.chat, [Turn(Message("more", PROMPT, "more"))])
        with self.assertRaises(NotAvailable):
            with self.coordination.exclusive(self.adapter.locator, self.chat):
                self.fail("must not be entered")
        self.assertEqual(outside.read_text(), "keep")
        self.assertTrue(self.lock.is_symlink())
        self.assertEqual(self.snapshot(), before)

    def test_a_symlinked_lock_folder_is_refused(self):
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        self.lock.parent.symlink_to(elsewhere)
        with self.assertRaises(NotAvailable):
            with self.coordination.exclusive(self.adapter.locator, self.chat):
                self.fail("must not be entered")
        self.assertEqual(list(elsewhere.iterdir()), [])

    def test_a_symlinked_ancestor_is_refused_before_anything_is_created(self):
        root = new_home(self)
        elsewhere = root / "elsewhere"
        elsewhere.mkdir()
        (root / ".codex").symlink_to(elsewhere)
        adapter, _ = new_adapter(self, root, allowed_chat_ids=("abc",), coordination=NativeCoordination())
        with self.assertRaises(NotAvailable):
            with NativeCoordination().exclusive(adapter.locator, "abc"):
                self.fail("must not be entered")
        self.assertFalse((elsewhere / "thread-writer-locks").exists())

    def test_a_chat_outside_the_explicit_scope_is_refused_and_no_lock_file_is_made(self):
        with self.assertRaises(NotAvailable):
            with self.coordination.exclusive(self.adapter.locator, "someone-elses-chat"):
                self.fail("must not be entered")
        self.assertFalse((self.adapter.locator.locks / "someone-elses-chat.lock").exists())

    def test_ids_that_could_point_elsewhere_are_refused(self):
        for bad in ("../x", "a/b", "", ".."):
            with self.subTest(bad=bad), self.assertRaises(NotAvailable):
                with self.coordination.exclusive(self.adapter.locator, bad):
                    self.fail("must not be entered")

    def test_a_write_under_the_native_lock_succeeds_and_leaves_no_lock_file(self):
        before = rollout_of(self.root, self.chat).read_bytes()
        self.adapter.writer.add(self.chat, [Turn(Message("more", PROMPT, "more"))])
        self.assertGreater(len(rollout_of(self.root, self.chat).read_bytes()), len(before))
        self.assertFalse(self.lock.exists())

    def test_a_take_back_under_the_native_lock_restores_the_bytes_and_leaves_no_lock_file(self):
        before = self.snapshot()
        result = self.adapter.writer.add(self.chat, [Turn(Message("more", PROMPT, "more"))])
        self.adapter.writer.take_back(result.receipt)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.lock.exists())

    def test_a_lock_file_replaced_mid_write_is_caught_and_the_intent_is_kept(self):
        writer = self.adapter.writer
        before = self.snapshot()
        pre = writer.prepare(self.chat, "add")
        original = writer._write_row

        def replaced(*args, **kwargs):
            self.lock.unlink()
            self.lock.write_text("replacement")
            return original(*args, **kwargs)
        with patch.object(writer, "_write_row", side_effect=replaced), \
                self.assertLogs("baton.adapters.codex.writer", "ERROR"):
            with self.assertRaises(ChatChanged):
                writer.add(self.chat, [Turn(Message("more", PROMPT, "more"))])
        self.assertTrue(os.path.exists(pre.data["intent"]))
        other, _ = new_adapter(self, self.root, allowed_chat_ids=(self.chat,), coordination=NativeCoordination())
        other.writer.take_back(pre)
        self.assertEqual(self.snapshot(), before)

    def test_closing_the_app_automatically_stays_unavailable(self):
        with self.assertRaises(NotAvailable):
            with self.coordination.global_idle(self.adapter):
                self.fail("must not be entered")
        with self.assertRaises(NotAvailable):
            self.adapter.app.close()


class ProductionWiringTests(unittest.TestCase):
    def test_the_machine_form_uses_native_coordination_and_keeps_scope_empty(self):
        root = new_home(self)
        chat = fx.build(root, turns())
        with no_processes():
            adapter = CodexAdapter.on_this_machine(root)
            self.assertIsInstance(adapter.coordination, NativeCoordination)
            self.assertEqual(adapter.locator.chats(), [])
            before = rollout_of(root, chat).read_bytes()
            with self.assertRaises(NotAvailable):
                adapter.writer.add(chat, [Turn(Message("more", PROMPT, "more"))])
            self.assertEqual(rollout_of(root, chat).read_bytes(), before)
            self.assertFalse((root / ".codex" / "thread-writer-locks").exists())

    def test_the_machine_form_writes_to_an_explicitly_scoped_chat_only(self):
        root = new_home(self)
        chat = fx.build(root, turns(), "scoped")
        other = fx.build(root, turns(), "other")
        with no_processes():
            adapter = CodexAdapter.on_this_machine(root, allowed_chat_ids=(chat,), process=fx.FixtureProcess(root))
            adapter.writer.add(chat, [Turn(Message("more", PROMPT, "more"))])
            with self.assertRaises(NotAvailable):
                adapter.writer.add(other, [Turn(Message("more2", PROMPT, "more"))])

    def test_plain_and_injected_adapters_keep_no_coordination(self):
        self.assertIsNone(CodexAdapter(new_home(self)).coordination)


if __name__ == "__main__":
    unittest.main()
