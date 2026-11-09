"""Compressed Codex rollouts built with stdlib zstd in temporary homes only."""
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from compression import zstd
except ImportError:
    zstd = None

from baton.adapters.codex import records
from baton.domain.errors import NotAvailable, UnknownFormat
from baton.notes.catalogue import CATALOGUE
from tests.adapters.suite import turns
from tests.adapters.test_codex import new_adapter, new_home, thread_row
from tests.fixtures.codex import build as fx
from tests.fixtures.no_processes import no_processes


@unittest.skipIf(zstd is None, 'stdlib zstd requires Python 3.14')
class CompressedCodexTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(no_processes())
        self.root = new_home(self)
        self.chat = fx.build(self.root, turns())
        self.adapter, _ = new_adapter(self, self.root)
        self.plain = fx.rollout_file(self.root, self.chat)

    def compress(self):
        return fx.compress_rollout(self.root, self.chat)

    def assert_note(self, note_id, action):
        with self.assertRaises(NotAvailable) as caught:
            action()
        self.assertEqual(caught.exception.note_id, note_id)
        self.assertIn(note_id, CATALOGUE)

    def test_fallback_reads_turns_usage_and_state_without_disk_copy(self):
        expected = self.adapter.reader.read(self.chat)
        usage = self.adapter.reader.usage(self.chat)
        path = self.compress()
        files = {p: p.read_bytes() for p in path.parent.iterdir()}
        row = thread_row(self.root, self.chat)
        self.assertEqual(self.adapter.locator.rollout_path(self.chat), path)
        self.assertTrue(self.adapter.locator.compressed(self.chat))
        self.assertEqual(self.adapter.locator.resolve(self.chat).id, self.chat)
        self.assertIn(self.chat, [r.id for r in self.adapter.locator.chats()])
        self.assertEqual(self.adapter.reader.read(self.chat), expected)
        self.assertEqual(self.adapter.reader.usage(self.chat), usage)
        self.assertTrue(self.adapter.state.target_format(self.chat).known)
        self.assertTrue(self.adapter.state.format_version().known)
        self.assertTrue(self.adapter.state.condition(self.chat).exists)
        self.assertFalse(self.adapter.state.replying(self.chat))
        self.assertEqual({p: p.read_bytes() for p in path.parent.iterdir()}, files)
        self.assertEqual(thread_row(self.root, self.chat), row)
        self.assertFalse(self.plain.exists())

    def test_compressed_fixture_and_recorded_compressed_path(self):
        other = fx.build_compressed(self.root, turns(), thread='newer')
        path = Path(str(fx.rollout_file(self.root, other)) + '.zst')
        fx.run_sql(self.root, 'UPDATE threads SET rollout_path = ? WHERE id = ?', (str(path), other))
        self.assertEqual(self.adapter.locator.rollout_path(other), path)
        self.assertEqual(len(self.adapter.reader.read(other)), len(turns()))

    def test_plain_takes_precedence_and_remains_writable(self):
        Path(str(self.plain) + '.zst').write_bytes(b'invalid unused sibling')
        self.assertEqual(self.adapter.locator.rollout_path(self.chat), self.plain)
        self.assertFalse(self.adapter.locator.compressed(self.chat))
        self.adapter.writer.rename(self.chat, 'plain still works')
        self.assertEqual(self.adapter.locator.name(self.chat), 'plain still works')

    def test_path_scope_identity_and_regular_file_rules(self):
        path = self.compress()
        raw = path.read_bytes()
        path.unlink()
        target = self.root / 'elsewhere.zst'
        target.write_bytes(raw)
        path.symlink_to(target)
        with self.assertRaises(KeyError):
            self.adapter.locator.rollout_path(self.chat)
        path.unlink()
        os.link(target, path)
        with self.assertRaises(KeyError):
            self.adapter.locator.rollout_path(self.chat)
        path.unlink()
        path.mkdir()
        with self.assertRaises(KeyError):
            self.adapter.locator.rollout_path(self.chat)
        path.rmdir()
        values = fx.native_records(turns(), 'different-id', '/fixture/project')
        path.write_bytes(zstd.compress(records.serialize(values)))
        with self.assertRaises(KeyError):
            self.adapter.locator.rollout_path(self.chat)
        self.assertFalse(self.adapter.state.target_format(self.chat).known)
        self.assertFalse(self.adapter.state.format_version().known)
        path.write_bytes(raw)
        self.adapter.scope_chats(())
        with self.assertRaises(NotAvailable):
            self.adapter.reader.read(self.chat)
        # Discovery remains metadata-only, even outside content scope.
        self.assertIn(self.chat, [r.id for r in self.adapter.locator.chats()])

    def test_compressed_path_must_stay_inside_sessions(self):
        path = self.compress()
        outside = self.root / path.name
        path.rename(outside)
        fx.run_sql(self.root, 'UPDATE threads SET rollout_path = ? WHERE id = ?', (str(outside), self.chat))
        with self.assertRaises(KeyError):
            self.adapter.locator.rollout_path(self.chat)

    def test_compressed_unfinished_task_is_detected(self):
        fx.append_event(self.root, self.chat, {'type': 'task_started', 'turn_id': 'unfinished'})
        self.compress()
        self.assertTrue(self.adapter.state.replying(self.chat))
        self.assertTrue(self.adapter.state.condition(self.chat).replying)

    def test_format_checks_reject_unknown_compressed_records(self):
        fx.append_event(self.root, self.chat, {}, kind='future_record')
        self.compress()
        self.assertFalse(self.adapter.state.target_format(self.chat).known)
        self.assertFalse(self.adapter.state.format_version().known)

    def test_corrupt_truncated_and_oversize_data_refuse(self):
        path = self.compress()
        valid = path.read_bytes()
        for raw in (b'not zstd', valid[:-1]):
            with self.subTest(raw=raw[:10]):
                path.write_bytes(raw)
                with self.assertRaises(UnknownFormat):
                    self.adapter.reader.read(self.chat)
                self.assertFalse(self.adapter.state.target_format(self.chat).known)
                self.assertFalse(self.adapter.state.format_version().known)
        path.write_bytes(zstd.compress(b' ' * 4096))
        with patch.object(records, 'MAX_ROLLOUT_BYTES', 1024):
            with self.assertRaises(UnknownFormat):
                self.adapter.reader.read(self.chat)
            self.assertFalse(self.adapter.state.target_format(self.chat).known)
        path.write_bytes(valid)
        with patch.object(records, 'MAX_ROLLOUT_BYTES', len(valid) - 1):
            with self.assertRaises(UnknownFormat):
                self.adapter.reader.usage(self.chat)
        self.assertFalse(self.plain.exists())

    def test_all_supported_writes_refuse_before_mutation(self):
        receipt = self.adapter.writer.rename(self.chat, 'renamed').receipt
        path = self.compress()
        row, raw = thread_row(self.root, self.chat), path.read_bytes()
        actions = (
            lambda: self.adapter.writer.prepare(self.chat, 'add'),
            lambda: self.adapter.writer.prepare(self.chat, 'rename'),
            lambda: self.adapter.writer.add(self.chat, turns()),
            lambda: self.adapter.writer.rename(self.chat, 'must refuse'),
            lambda: self.adapter.writer.take_back(receipt),
            lambda: self.adapter.writer.restore(receipt),
        )
        for action in actions:
            self.assert_note('write.codex_compressed', action)
            self.assertEqual(thread_row(self.root, self.chat), row)
            self.assertEqual(path.read_bytes(), raw)
            self.assertFalse(self.plain.exists())
        self.assertTrue(Path(receipt.data['intent']).exists())

    def test_prepared_add_rechecks_compression_before_publication(self):
        self.adapter.writer.prepare(self.chat, 'add')
        path = self.compress()
        raw = path.read_bytes()
        self.assert_note('write.codex_compressed', lambda: self.adapter.writer.add(self.chat, turns()))
        self.assertEqual(path.read_bytes(), raw)
        self.assertFalse(self.plain.exists())

    def test_last_write_guard_rechecks_compression(self):
        publish = self.adapter.writer._publish
        row = thread_row(self.root, self.chat)

        def compress_before_publish(*args):
            self.compress()
            return publish(*args)

        with patch.object(self.adapter.writer, '_publish', compress_before_publish):
            self.assert_note('write.codex_compressed', lambda: self.adapter.writer.add(self.chat, ()))
        self.assertEqual(thread_row(self.root, self.chat), row)
        self.assertFalse(self.plain.exists())

    def test_take_back_rechecks_compression_under_exclusion(self):
        receipt = self.adapter.writer.add(self.chat, ()).receipt
        revert = self.adapter.writer._revert
        row = thread_row(self.root, self.chat)

        def compress_before_revert(*args):
            self.compress()
            return revert(*args)

        with patch.object(self.adapter.writer, '_revert', compress_before_revert):
            self.assert_note('write.codex_compressed', lambda: self.adapter.writer.take_back(receipt))
        self.assertEqual(thread_row(self.root, self.chat), row)
        self.assertTrue(Path(receipt.data['intent']).exists())
        self.assertFalse(self.plain.exists())

    def test_create_can_use_compressed_template_without_modifying_it(self):
        path = self.compress()
        raw = path.read_bytes()
        result = self.adapter.writer.create(turns(), 'new chat', '/fixture/project')
        self.assertEqual(len(self.adapter.reader.read(result.chat_id)), len(turns()))
        meta = json.loads(self.adapter.locator.rollout_path(result.chat_id).read_bytes().splitlines()[0])
        self.assertEqual(meta['payload']['base_instructions'], fx.BASE_INSTRUCTIONS)
        self.assertEqual(path.read_bytes(), raw)
        self.assertFalse(self.plain.exists())

    def test_python_without_zstd_lists_but_refuses_content_plain_unaffected(self):
        path = self.compress()
        other = fx.build(self.root, turns(), thread='newer')
        with patch.object(records, '_zstd', None):
            self.assertIn(self.chat, [r.id for r in self.adapter.locator.chats()])
            self.assertEqual(self.adapter.locator.rollout_path(self.chat), path)
            self.assertEqual(self.adapter.locator.resolve(self.chat).id, self.chat)
            for action in (lambda: self.adapter.reader.read(self.chat),
                           lambda: self.adapter.reader.usage(self.chat),
                           lambda: self.adapter.state.replying(self.chat)):
                self.assert_note('read.codex_compressed_python', action)
            self.assertFalse(self.adapter.state.target_format(self.chat).known)
            self.assertFalse(self.adapter.state.format_version().known)
            self.assert_note('write.codex_compressed', lambda: self.adapter.writer.add(self.chat, turns()))
            self.assertEqual(len(self.adapter.reader.read(other)), len(turns()))
            self.adapter.writer.rename(other, 'plain on older Python')
            self.assertEqual(self.adapter.locator.name(other), 'plain on older Python')
        self.assertFalse(self.plain.exists())
