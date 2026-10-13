"""Native carry-over checks use only generated files and injected controls."""
import json
import tempfile
import unittest
from unittest.mock import Mock, patch
from dataclasses import asdict
from pathlib import Path

from baton.adapters.claude import ClaudeAdapter
from baton.adapters.codex import CodexAdapter
from baton.adapters.opencode import OpenCodeAdapter
from baton.adapters.cursor import CursorAdapter
from baton.cli import output, wiring
from baton.domain.model import Turn, Message, PROMPT
from baton.domain.errors import ChatChanged, UnknownFormat
from baton.ports.tool import WriteReceipt
from tests.adapters.suite import turns
from tests.adapters.test_codex import new_adapter
from tests.fixtures.claude.build import build, FixtureProcess
from tests.fixtures.codex import build as fx


class NativeCarryover(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.process = FixtureProcess(self.root)
        self.claude = ClaudeAdapter(self.root, process=self.process)
        self.process.adapter = self.claude
        self.chat = build(self.root, turns())

    def test_new_claude_version_known_shape_is_writable_and_stamps_latest_chat_version(self):
        path = self.claude.locator.session_path(self.chat)
        records = [json.loads(line) for line in path.read_text().splitlines()]
        for record in records: record['version'] = '9.99.1'
        records[-1]['version'] = '9.99.2'
        path.write_text(''.join(json.dumps(r) + '\n' for r in records))
        self.assertTrue(self.claude.state.format_version().known)
        self.assertTrue(self.claude.state.format_version().new_version)
        self.assertTrue(output.side_condition(self.claude.state.condition(self.chat))['format_new_version'])
        self.claude.writer.add(self.chat, [Turn(Message('new', PROMPT, 'new'))])
        self.assertEqual(json.loads(path.read_text().splitlines()[-1])['version'], '9.99.2')

    def test_required_claude_envelope_keys_and_types_gate_writes(self):
        path = self.claude.locator.session_path(self.chat)
        original = path.read_text()
        for key in ('uuid', 'parentUuid', 'sessionId', 'type', 'timestamp', 'version', 'isSidechain', 'message'):
            records = [json.loads(line) for line in original.splitlines()]
            records[0].pop(key)
            path.write_text(''.join(json.dumps(r) + '\n' for r in records))
            with self.subTest(key=key):
                self.assertFalse(self.claude.state.format_version().known)
                with self.assertRaises(UnknownFormat): self.claude.writer.add(self.chat, [])
        path.write_text(original)
        for key, value in (('uuid', 4), ('parentUuid', []), ('sessionId', False), ('timestamp', {}), ('version', 3), ('isSidechain', 0), ('message', [])):
            records = [json.loads(line) for line in original.splitlines()]
            records[0][key] = value
            path.write_text(''.join(json.dumps(r) + '\n' for r in records))
            with self.subTest(key=key): self.assertFalse(self.claude.state.format_version().known)

    def test_new_codex_version_known_shape_is_writable_but_bad_payload_refuses(self):
        chat = fx.build(self.root, turns())
        adapter, _ = new_adapter(self, self.root)
        path = fx.rollout_file(self.root, chat)
        records = fx.read_lines(path)
        records[0]['payload']['cli_version'] = '9.99'
        fx.write_lines(path, records)
        fx.run_sql(self.root, 'UPDATE threads SET cli_version = ?', ('9.99',))
        self.assertTrue(adapter.state.target_format(chat).new_version)
        adapter.writer.add(chat, [Turn(Message('new', PROMPT, 'new'))])
        records = fx.read_lines(path)
        next(r for r in records if r['type'] == 'response_item' and r['payload'].get('role') == 'assistant')['payload']['content'] = 'broken'
        fx.write_lines(path, records)
        self.assertFalse(adapter.state.target_format(chat).known)
        with self.assertRaises(UnknownFormat): adapter.writer.add(chat, [])

    def test_release_waits_for_session_and_sidebar_to_settle_and_is_bounded(self):
        paths = (self.claude.locator.session_path(self.chat), self.claude.locator.entry(self.chat)[0])
        moment, checks = [0.0], []
        def sleep(seconds):
            moment[0] += seconds
            checks.append(seconds)
            if len(checks) <= 2:
                with paths[(len(checks) - 1) % 2].open('ab') as stream: stream.write(b' ')
        registry = self.root / '.claude/sessions'
        registry.mkdir(parents=True, exist_ok=True)
        self.process.pids.add(1234)
        (registry / '1234.json').write_text(json.dumps({'pid': 1234, 'sessionId': 'fixture_session', 'status': 'idle'}))
        self.claude.monotonic = lambda: moment[0]
        self.claude.sleep = sleep
        self.claude.app.release(self.chat)
        self.assertEqual(len(checks), 3)
        self.assertIn(("terminate", 1234), self.process.calls)
        moment[0] = 0
        def changing(seconds):
            moment[0] += seconds
            with paths[0].open('ab') as stream: stream.write(b' ')
        self.claude.sleep = changing
        with self.assertRaises(ChatChanged): self.claude.app.release(self.chat)
        self.assertLessEqual(moment[0], 3.001)

    def test_exact_rename_restore_preserves_bytes_with_live_intent_and_json_receipt(self):
        sidebar = self.claude.locator.entry(self.chat)[0]
        entry = json.loads(sidebar.read_text())
        entry['title'] = '`old title`'
        sidebar.write_text(json.dumps(entry, indent=2) + '\n')
        before = sidebar.read_bytes()
        result = self.claude.writer.rename(self.chat, 'new')
        self.assertTrue(Path(result.receipt.data['intent']).exists())
        receipt = WriteReceipt(**json.loads(json.dumps(asdict(result.receipt))))
        restored = self.claude.writer.restore(receipt)
        self.assertEqual(sidebar.read_bytes(), before)
        self.claude.writer.take_back(restored.receipt)
        self.claude.writer.take_back(receipt)
        self.assertEqual(sidebar.read_bytes(), before)

    def test_codex_restores_distinct_title_and_name_with_live_intent(self):
        chat = fx.build(self.root, turns())
        adapter, _ = new_adapter(self, self.root)
        fx.run_sql(self.root, 'UPDATE threads SET title = ?, name = ?', ('`earlier title`', 'earlier name'))
        original = adapter.locator.row(chat)
        result = adapter.writer.rename(chat, 'new')
        self.assertTrue(Path(result.receipt.data['intent']).exists())
        restored = adapter.writer.restore(WriteReceipt(**json.loads(json.dumps(asdict(result.receipt)))))
        self.assertEqual(adapter.locator.row(chat), original)
        adapter.writer.take_back(restored.receipt)
        adapter.writer.take_back(result.receipt)
        self.assertEqual(adapter.locator.row(chat), original)

    def test_wiring_owns_intents_and_clears_only_durable_verified_receipts(self):
        store_root = self.root / 'baton-store'
        engine = wiring.build(store_root, adapter_roots={'claude': self.root}, entries=wiring.TOOLS[:1])
        adapter = engine.adapters['claude']
        self.assertEqual(adapter.rollback_root, store_root / 'rollback' / 'claude')
        pre = adapter.writer.prepare(self.chat, 'rename')
        journal = engine.store.journal_begin(None, 'claude', self.chat, 'rename', engine.clock.now(), asdict(pre))
        result = adapter.writer.rename(self.chat, 'new')
        intent = Path(result.receipt.data['intent'])
        self.assertEqual(intent.parent, adapter.rollback_root)
        engine.clear_verified_intents()
        self.assertTrue(intent.exists())
        engine.store.journal_finish(journal, 'committed', engine.clock.now(), asdict(result.receipt))
        engine.close()
        self.assertFalse(intent.exists())
        again = wiring.build(store_root, adapter_roots={'claude': self.root}, entries=wiring.TOOLS[:1])
        receipt = WriteReceipt(**again.store.journal_entry(journal)['post_receipt'])
        with self.assertRaises(ChatChanged): again.adapters['claude'].writer.take_back(receipt)
        again.close()

    def test_injected_rollback_folder_outside_tool_root_keeps_crash_recovery(self):
        folder = self.root / 'baton-store' / 'rollback'
        adapter = ClaudeAdapter(self.root / 'tool', rollback_root=folder)
        chat = build(adapter.root, turns())
        prepared = adapter.writer.prepare(chat, 'rename')
        before = adapter.locator.entry(chat)[0].read_bytes()
        adapter.writer.rename(chat, 'new')
        fresh = ClaudeAdapter(adapter.root, rollback_root=folder)
        fresh.writer.take_back(WriteReceipt(**json.loads(json.dumps(asdict(prepared)))))
        self.assertEqual(fresh.locator.entry(chat)[0].read_bytes(), before)
        self.assertFalse(Path(prepared.data['intent']).exists())

    def test_setup_discloses_known_shape_from_a_new_version(self):
        path = self.claude.locator.session_path(self.chat)
        records = [json.loads(line) for line in path.read_text().splitlines()]
        for record in records: record['version'] = '9.99'
        path.write_text(''.join(json.dumps(r) + '\n' for r in records))
        engine = wiring.build(self.root / 'store', adapters={'claude': self.claude}, entries=wiring.TOOLS[:1], installation_probe=lambda _: True)
        result = output.read_setup(engine.setup_read.tools())['tools'][0]
        self.assertTrue(result['format_new_version'])
        note = next(f['note'] for f in result['findings'] if f['id'] == 'new_version')
        self.assertEqual(note['id'], 'format.new_version')
        self.assertIn('not checked yet', note['text'])
        engine.close()

    def test_codex_created_identity_recovers_from_durable_receipt_after_intent_cleanup(self):
        fx.build(self.root, turns())
        adapter, _ = new_adapter(self, self.root)
        created = adapter.writer.create(turns(), 'created', '/fixture/project')
        adapter.writer.verified(created.receipt)
        fresh, _ = new_adapter(self, self.root)
        self.assertFalse(fresh.scope.contains(created.chat_id))
        fresh.writer.verified(WriteReceipt(**json.loads(json.dumps(asdict(created.receipt)))))
        self.assertTrue(fresh.scope.contains(created.chat_id))
        with self.assertRaises(ChatChanged): fresh.writer.take_back(created.receipt)
        self.assertTrue(fresh.state.condition(created.chat_id).exists)

    def test_native_preview_readiness_never_launches_a_command(self):
        from baton.adapters.claude.runner import ClaudeRunner
        from baton.adapters.codex.runner import CodexRunner
        command = Mock()
        binary = self.root / 'fake-command'
        binary.touch()
        with patch('baton.adapters.claude.runner.shutil.which', return_value=str(binary)):
            self.assertTrue(ClaudeRunner(command).ready().ok)
        self.assertTrue(CodexRunner(command, str(binary)).ready().ok)
        command.assert_not_called()

    def test_codex_required_written_payload_shapes_gate_mutation(self):
        chat = fx.build(self.root, turns())
        adapter, _ = new_adapter(self, self.root)
        path = fx.rollout_file(self.root, chat)
        original = path.read_bytes()
        for kind, key in (('session_meta', 'cwd'), ('session_meta', 'cli_version'), ('event_msg', 'type'), ('response_item', 'role'), ('response_item', 'content')):
            records = fx.read_lines(path)
            record = next(r for r in records if r['type'] == kind)
            record['payload'].pop(key)
            fx.write_lines(path, records)
            with self.subTest(kind=kind, key=key):
                self.assertFalse(adapter.state.target_format(chat).known)
                with self.assertRaises(UnknownFormat): adapter.writer.rename(chat, 'changed')
            path.write_bytes(original)

    def test_every_chained_claude_record_requires_a_known_envelope(self):
        path = self.claude.locator.session_path(self.chat)
        original = path.read_text()
        parent = json.loads(original.splitlines()[-1])['uuid']
        envelope = dict(uuid='leaf', parentUuid=parent, type='system', sessionId=self.chat,
                        timestamp='2026-10-14T00:00:00Z')
        for kind in ('system', 'attachment'):
            for key in ('uuid', 'parentUuid', 'type', 'sessionId', 'timestamp'):
                leaf = dict(envelope, type=kind)
                leaf.pop(key)
                path.write_text(original + json.dumps(leaf) + '\n')
                with self.subTest(kind=kind, missing=key):
                    self.assertFalse(self.claude.state.format_version().known)
                    with self.assertRaises(UnknownFormat): self.claude.writer.add(self.chat, [])
        # Unknown parent records also become part of the reader's live chain.
        odd = dict(envelope, type='future_chain_record')
        leaf = dict(envelope, uuid='child', parentUuid='leaf')
        path.write_text(original + json.dumps(odd) + '\n' + json.dumps(leaf) + '\n')
        self.assertFalse(self.claude.state.format_version().known)
        leaf['parentUuid'] = None
        leaf['logicalParentUuid'] = 'leaf'
        path.write_text(original + json.dumps(odd) + '\n' + json.dumps(leaf) + '\n')
        self.assertFalse(self.claude.state.format_version().known)
        path.write_text(original + json.dumps(envelope) + '\n')
        self.assertTrue(self.claude.state.format_version().known)

    def test_claude_format_version_and_created_records_use_numeric_newest(self):
        path = self.claude.locator.session_path(self.chat)
        records = [json.loads(line) for line in path.read_text().splitlines()]
        for record in records: record['version'] = '2.9.9'
        records[0]['version'] = '2.10.1'
        records[1]['version'] = '2.1.0'
        path.write_text(''.join(json.dumps(r) + '\n' for r in records))
        self.assertEqual(self.claude.state.format_version().version, '2.10.1')
        self.claude.writer.add(self.chat, [Turn(Message('numeric-version', PROMPT, 'new'))])
        self.assertEqual(json.loads(path.read_text().splitlines()[-1])['version'], '2.10.1')
        created = self.claude.writer.create(turns(), 'new', '/fixture/project')
        written = self.claude.locator.session_path(created.chat_id)
        self.assertEqual(next(json.loads(line)['version'] for line in written.read_text().splitlines() if json.loads(line).get('type') == 'user'), '2.10.1')

    def test_real_machine_factories_require_explicit_rollback_root(self):
        for factory in (ClaudeAdapter, CodexAdapter, OpenCodeAdapter, CursorAdapter):
            with self.subTest(factory=factory.name):
                with self.assertRaisesRegex(ValueError, "^rollback_root_required$"): factory.on_this_machine(self.root)
                with self.assertRaisesRegex(ValueError, "^rollback_root_required$"): factory.on_this_machine(self.root, rollback_root=None)
                adapter = factory.on_this_machine(self.root, rollback_root=self.root / 'store' / factory.name)
                folder = adapter.rollback_locator.root if factory.name == 'cursor' else adapter.rollback_root
                self.assertEqual(folder, self.root / 'store' / factory.name)

    def test_legacy_receipts_recover_both_prepared_and_completed_writes(self):
        chat = fx.build(self.root, turns())
        codex, _ = new_adapter(self, self.root)
        for adapter, ident in ((self.claude, self.chat), (codex, chat)):
            for prepared in (True, False):
                with self.subTest(tool=adapter.name, prepared=prepared):
                    old_name = adapter.locator.name(ident)
                    pre = adapter.writer.prepare(ident, 'rename')
                    post = adapter.writer.rename(ident, 'changed').receipt
                    legacy = adapter.root / '.baton-rollback' / (pre.data['token'] + '.json')
                    legacy.parent.mkdir(exist_ok=True, mode=0o700)
                    Path(pre.data['intent']).replace(legacy)
                    receipt = pre if prepared else post
                    receipt = WriteReceipt(receipt.tool, receipt.chat_id, receipt.kind, {**receipt.data, 'intent': str(legacy)})
                    adapter.writer.take_back(receipt)
                    self.assertEqual(adapter.locator.name(ident), old_name)
                    self.assertFalse(legacy.exists())

    def test_legacy_receipts_refuse_symlink_files_and_directories(self):
        from baton.domain.errors import NotAvailable
        chat = fx.build(self.root, turns())
        codex, _ = new_adapter(self, self.root)
        for adapter, ident in ((self.claude, self.chat), (codex, chat)):
            pre = adapter.writer.prepare(ident, 'rename')
            post = adapter.writer.rename(ident, 'changed').receipt
            legacy = self.root / '.baton-rollback' / (pre.data['token'] + '.json')
            legacy.parent.mkdir(exist_ok=True)
            legacy.symlink_to(pre.data['intent'])
            receipt = WriteReceipt(post.tool, post.chat_id, post.kind, {**post.data, 'intent': str(legacy)})
            with self.assertRaises(NotAvailable): adapter.writer.take_back(receipt)
            legacy.unlink()
            legacy.parent.rmdir()
            legacy.parent.symlink_to(Path(pre.data['intent']).parent)
            with self.assertRaises(NotAvailable): adapter.writer.take_back(receipt)
            legacy.parent.unlink()
            adapter.writer.take_back(post)

    def test_codex_unknown_subtypes_disable_writing_but_known_bookkeeping_does_not(self):
        chat = fx.build(self.root, turns())
        adapter, _ = new_adapter(self, self.root)
        path = fx.rollout_file(self.root, chat)
        original = path.read_bytes()
        for kind in ('event_msg', 'response_item'):
            fx.append_event(self.root, chat, {'type': 'future_turn_boundary'}, kind)
            with self.subTest(kind=kind):
                self.assertFalse(adapter.state.target_format(chat).known)
                with self.assertRaises(UnknownFormat): adapter.writer.rename(chat, 'changed')
                self.assertEqual(adapter.reader.read(chat), list(turns()))
            path.write_bytes(original)
        for kind, subtype in (('event_msg', 'token_count'), ('response_item', 'reasoning')):
            fx.append_event(self.root, chat, {'type': subtype}, kind)
            self.assertTrue(adapter.state.target_format(chat).known)

    def test_symlinked_store_root_and_rollback_root_support_writes(self):
        store = self.root / 'store'
        store.mkdir()
        alias = self.root / 'alias'
        alias.symlink_to(store, target_is_directory=True)
        engine = wiring.build(alias, adapter_roots={'claude': self.root}, entries=wiring.TOOLS[:1])
        self.addCleanup(engine.close)
        self.assertEqual(engine.root, store)
        result = engine.adapters['claude'].writer.rename(self.chat, 'new')
        self.assertEqual(Path(result.receipt.data['intent']).parent, store / 'rollback' / 'claude')
        for factory in (ClaudeAdapter, CodexAdapter):
            self.assertEqual(factory(self.root, rollback_root=alias / factory.name).rollback_root, store / factory.name)

    def test_legacy_create_intents_recover_on_restart_and_clear_pending_journal(self):
        from baton.ledger.sqlite_store import Ledger
        from baton.ports.clock import SystemClock
        from baton.services.journal import Journal
        fx.build(self.root, turns())
        codex, _ = new_adapter(self, self.root)
        for adapter in (self.claude, codex):
            with self.subTest(tool=adapter.name):
                store = Ledger(':memory:')
                self.addCleanup(store.close)
                pre = adapter.writer.prepare(None, 'create')
                created = adapter.writer.create(turns(), 'created', '/fixture/project')
                legacy = self.root / '.baton-rollback' / (pre.data['token'] + '.json')
                legacy.parent.mkdir(exist_ok=True, mode=0o700)
                Path(pre.data['intent']).replace(legacy)
                pre = WriteReceipt(pre.tool, pre.chat_id, pre.kind, {**pre.data, 'intent': str(legacy)})
                entry = store.journal_begin(None, adapter.name, pre.chat_id, 'create', SystemClock().now(), asdict(pre))
                # A failed old recovery must be retryable with the same saved receipt.
                store.journal_finish(entry, 'failed', SystemClock().now(), error='ValueError')
                fresh = (ClaudeAdapter(self.root) if adapter.name == 'claude' else new_adapter(self, self.root)[0])
                journal = Journal(store, {adapter.name: fresh}, SystemClock())
                recovered = journal.recover()
                self.assertEqual(recovered[0]['state'], 'taken_back')
                self.assertEqual(store.journal_entries(pending=True), [])
                self.assertFalse(legacy.exists())
                self.assertFalse(fresh.state.condition(created.chat_id).exists)
                self.assertEqual(journal.recover(), [])

    def test_codex_reader_tool_shapes_are_explicitly_accepted(self):
        from baton.adapters.codex.records import record_shape_known
        for subtype in ('custom_tool_call', 'tool_search_call'):
            record = dict(timestamp='', type='response_item', payload=dict(type=subtype, id='item', name='tool', call_id='call', input='{}'))
            self.assertTrue(record_shape_known(record))
            record['payload'].pop('call_id')
            self.assertFalse(record_shape_known(record))
        for subtype in ('custom_tool_call_output', 'tool_search_output'):
            record = dict(timestamp='', type='response_item', payload=dict(type=subtype, id='item', call_id='call', output='done'))
            self.assertTrue(record_shape_known(record))
            record['payload'].pop('call_id')
            self.assertFalse(record_shape_known(record))

    def test_shared_suite_rejects_an_incorrect_new_version_flag(self):
        from tests.adapters.test_claude import ClaudeSuite
        from baton.ports.tool import FormatCheck
        suite = ClaudeSuite('test_facts_match_behaviour')
        suite.setUp()
        self.addCleanup(suite.doCleanups)
        check = FormatCheck(True, suite.adapter.facts.checked_versions[0], True)
        with patch.object(suite.adapter.state, 'format_version', return_value=check):
            with self.assertRaises(AssertionError): suite.test_facts_match_behaviour()

    def test_verified_or_missing_intents_refuse_take_back_and_restore_with_catalogue_note(self):
        chat = fx.build(self.root, turns())
        codex, _ = new_adapter(self, self.root)
        for adapter, ident in ((self.claude, self.chat), (codex, chat)):
            for clear in ('verified', 'missing'):
                with self.subTest(tool=adapter.name, clear=clear):
                    result = adapter.writer.rename(ident, 'new-' + clear)
                    receipt = WriteReceipt(**json.loads(json.dumps(asdict(result.receipt))))
                    if clear == 'verified': adapter.writer.verified(receipt)
                    else: Path(receipt.data['intent']).unlink()
                    before = (adapter.locator.entry(ident)[0].read_bytes() if adapter.name == 'claude'
                              else adapter.locator.row(ident))
                    for operation in (adapter.writer.take_back, adapter.writer.restore):
                        with self.assertRaises(ChatChanged) as raised: operation(receipt)
                        self.assertEqual(raised.exception.note_id, 'write.chat_changed')
                    after = (adapter.locator.entry(ident)[0].read_bytes() if adapter.name == 'claude'
                             else adapter.locator.row(ident))
                    self.assertEqual(after, before)

    def test_codex_restore_refuses_each_manifest_identity_mismatch_without_mutation(self):
        chat = fx.build(self.root, turns())
        adapter, _ = new_adapter(self, self.root)
        receipt = adapter.writer.rename(chat, 'new').receipt
        path = Path(receipt.data['intent'])
        original = json.loads(path.read_text())
        before = adapter.locator.row(chat)
        rollout = fx.rollout_file(self.root, chat).read_bytes()
        for key in ('token', 'chat_id', 'kind'):
            manifest = {**original, key: 'wrong'}
            path.write_text(json.dumps(manifest))
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'receipt mismatch'):
                adapter.writer.restore(receipt)
            self.assertEqual(adapter.locator.row(chat), before)
            self.assertEqual(fx.rollout_file(self.root, chat).read_bytes(), rollout)
            self.assertEqual(list(path.parent.glob('*.json')), [path])
