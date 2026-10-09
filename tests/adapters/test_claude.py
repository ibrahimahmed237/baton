"""Claude native filesystem/registry tests; no live apps or real chat paths."""
import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from baton.adapters.claude import ClaudeAdapter
from baton.domain.errors import AppMustBeClosed, ChatChanged, ChatReplying, UnknownFormat
from baton.domain.model import Message, Turn, PROMPT, TOOL_TEXT, REPLY
from baton.ports.tool import WriteReceipt
from tests.adapters.suite import AdapterSuite, turns
from tests.fixtures.claude.build import build, FixtureProcess

class ClaudeSuite(AdapterSuite, unittest.TestCase):
    def make_adapter(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.process = FixtureProcess(self.root)
        adapter = ClaudeAdapter(self.root, process=self.process, command=lambda *a, **k: SimpleNamespace(returncode=0, stdout='{"loggedIn": true}'), context_sizes={'test-model': 100000}, hook_entrypoints_available=lambda: True)
        self.process.adapter = adapter
        adapter.hooks.install()
        return adapter
    def build_chat(self, values):
        chat = build(self.root, values)
        self.process.visible[chat] = list(values)
        return chat
    def insert_text(self, chat, message):
        path = self.adapter.locator.session_path(chat)
        records = [json.loads(l) for l in path.read_text().splitlines()]
        # A native hook attachment lives on the parent chain without becoming a prompt.
        path.write_text(path.read_text() + json.dumps({'type': 'attachment', 'uuid': message.id,
            'parentUuid': records[-1]['uuid'], 'attachment': {'type': 'hook_additional_context', 'content': message.text}}) + '\n')
    def set_condition(self, chat, **values):
        self.process.is_running = values.get('app_running', self.process.is_running)
        path, entry = self.adapter.locator.entry(chat)
        if values.get('exists') is False: path.unlink(); self.process.pids.clear(); return
        registry = self.root / '.claude/sessions'; registry.mkdir(parents=True, exist_ok=True)
        self.process.pids.clear()
        if values.get('open', False):
            self.process.pids.add(1234)
            (registry/'1234.json').write_text(json.dumps({'pid': 1234, 'sessionId': entry['cliSessionId'], 'status': 'busy' if values.get('replying') else 'idle'}))
    def set_format(self, known, version):
        path = self.adapter.locator.session_path(self.chat)
        records = [json.loads(l) for l in path.read_text().splitlines()]
        for r in records: r['version'] = version if known else 'unsupported'
        path.write_text(''.join(json.dumps(r)+'\n' for r in records))
    def configure_usage(self, chat):
        path = self.adapter.locator.session_path(chat)
        records = [json.loads(l) for l in path.read_text().splitlines()]
        path.write_text(path.read_text()+json.dumps({'type':'assistant','uuid':'quota','parentUuid':records[-1]['uuid'],
            'isApiErrorMessage':True,'apiErrorStatus':429,'error':'rate_limit','quotaLimits':{'resetsAt':1767225600},
            'message':{'content':[]},'version':'2.1.284'})+'\n')
        return self.adapter.reader.usage(chat)
    def visible_turns(self, chat): return self.process.visible.get(chat)

class ClaudeSafety(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.process = FixtureProcess(self.root)
        self.adapter = ClaudeAdapter(self.root, process=self.process, hook_entrypoints_available=lambda: True)
        self.process.adapter = self.adapter
        self.chat = build(self.root, turns())
    def test_restore_native_bytes_and_fresh_receipt_recovery(self):
        path = self.adapter.locator.session_path(self.chat)
        original = path.read_bytes()
        cut = self.adapter.writer.cut(self.chat, '')
        self.assertEqual(path.read_bytes(), b'')
        pre = self.adapter.writer.prepare(self.chat, 'restore')
        restored = self.adapter.writer.restore(cut.receipt)
        self.assertEqual(path.read_bytes(), original)
        self.adapter.writer.take_back(pre)
        self.assertEqual(path.read_bytes(), b'')
        self.adapter.writer.restore(cut.receipt)
        self.assertEqual(path.read_bytes(), original)

    def test_rename_refuses_running_app_with_idle_closed_chat(self):
        self.process.is_running = True
        with self.assertRaises(AppMustBeClosed): self.adapter.writer.rename(self.chat, 'changed')
    def test_stale_append_receipt_preserves_later_native_writes(self):
        a = self.adapter.writer.add(self.chat, [Turn(Message('extra', PROMPT, 'extra'))])
        self.adapter.writer.add(self.chat, [Turn(Message('later', PROMPT, 'later'))])
        before = self.adapter.locator.session_path(self.chat).read_bytes()
        with self.assertRaises(ChatChanged): self.adapter.writer.take_back(a.receipt)
        self.assertEqual(self.adapter.locator.session_path(self.chat).read_bytes(), before)
    def test_prewrite_recovery_new_writer_json_receipt(self):
        pre = self.adapter.writer.prepare(self.chat, 'add')
        self.adapter.writer.add(self.chat, [Turn(Message('extra', PROMPT, 'extra'))])
        other = ClaudeAdapter(self.root, process=self.process)
        receipt = WriteReceipt(**json.loads(json.dumps(asdict(pre))))
        other.writer.take_back(receipt); other.writer.take_back(receipt)
        self.assertEqual(other.reader.read(self.chat), turns())
    def test_prewrite_partial_create_recovery(self):
        pre = self.adapter.writer.prepare(None, 'create')
        result = self.adapter.writer.create(turns(), 'copy', '/other')
        self.adapter.locator.entry(result.chat_id)[0].unlink()
        other = ClaudeAdapter(self.root, process=self.process)
        other.writer.take_back(WriteReceipt(**json.loads(json.dumps(asdict(pre)))))
        self.assertFalse(other.state.condition(result.chat_id).exists)
    def test_stable_sidebar_id_follows_session_move(self):
        old = self.adapter.locator.session_path(self.chat)
        new = old.with_name('new-session.jsonl'); new.write_bytes(old.read_bytes())
        path, entry = self.adapter.locator.entry(self.chat)
        entry['cliSessionId']='new-session'; path.write_text(json.dumps(entry))
        self.assertEqual(self.adapter.reader.read(self.chat), turns())
        self.assertEqual(self.adapter.locator.session_path(self.chat), new)
    def test_dead_branch_compaction_and_hook_attachments(self):
        path = self.adapter.locator.session_path(self.chat)
        records = [json.loads(l) for l in path.read_text().splitlines()]
        records += [{'uuid':'dead','parentUuid':'a3','type':'user','message':{'content':'dead'}},
            {'uuid':'compact','parentUuid':None,'logicalParentUuid':'a3','type':'system','subtype':'compact_boundary'},
            {'uuid':'hook','parentUuid':'compact','type':'attachment','attachment':{'type':'hook_additional_context','content':'injected'}}]
        path.write_text(''.join(json.dumps(r)+'\n' for r in records))
        self.assertEqual(self.adapter.reader.read(self.chat), turns())
    def test_tool_text_and_incomplete_prompt_roundtrip(self):
        values=[Turn(Message('p4',PROMPT,'question'),(Message('t4',TOOL_TEXT,'[Tool 1: read]\ntext'), Message('a4',REPLY,'answer'))),Turn(Message('p5',PROMPT,'incomplete'))]
        result=self.adapter.writer.create(values,'copy','/folder')
        self.assertEqual(self.adapter.reader.read(result.chat_id),values)
        native=[json.loads(l) for l in self.adapter.locator.session_path(result.chat_id).read_text().splitlines()]
        self.assertEqual(native[1]['message']['content'],[{'type':'text','text':'[Tool 1: read]\ntext'}])
    def test_unknown_record_shape_blocks_write_without_blocking_read(self):
        path=self.adapter.locator.session_path(self.chat)
        recs=[json.loads(l) for l in path.read_text().splitlines()]; del recs[0]['parentUuid']
        path.write_text(''.join(json.dumps(r)+'\n' for r in recs))
        self.assertIsInstance(self.adapter.reader.read(self.chat),list)
        with self.assertRaises(UnknownFormat): self.adapter.writer.add(self.chat,[])
    def test_busy_release_does_not_signal(self):
        registry=self.root/'.claude/sessions';registry.mkdir(parents=True)
        self.process.pids.add(1234)
        (registry/'1234.json').write_text(json.dumps({'pid':1234,'sessionId':'fixture_session','status':'busy'}))
        with self.assertRaises(ChatReplying): self.adapter.app.release(self.chat)
        self.assertEqual(self.process.calls,[])
    def test_hooks_preserve_unrelated_settings_and_entries(self):
        path=self.adapter.hooks.path;path.parent.mkdir(parents=True,exist_ok=True)
        original={'permissions':{'allow':['Read']},'hooks':{'Stop':[{'hooks':[{'type':'command','command':'other'}]}]}}
        path.write_text(json.dumps(original));self.adapter.hooks.install();self.adapter.hooks.install()
        value=json.loads(path.read_text());self.assertEqual(len(value['hooks']['Stop']),2)
        self.adapter.hooks.uninstall();value=json.loads(path.read_text())
        self.assertEqual(value['permissions'],original['permissions']);self.assertEqual(value['hooks']['Stop'],original['hooks']['Stop'])
        output=json.loads(self.adapter.hooks.attach_reply('context','notice'))
        self.assertEqual(output['hookSpecificOutput']['additionalContext'],'context')
        self.assertEqual(self.adapter.hooks.turn_end_reply(),'')
    def test_runner_ephemeral_read_only_and_login(self):
        calls=[]
        def command(args,**kwargs):
            calls.append((args,kwargs));return SimpleNamespace(returncode=0,stdout='{"loggedIn":true}' if 'auth' in args else 'brief')
        adapter=ClaudeAdapter(self.root,process=self.process,command=command)
        self.assertEqual(adapter.runner.ask('summarize','/fixture'),'brief')
        argv=calls[-1][0]
        self.assertIn('--no-session-persistence',argv);self.assertIn('Read,Grep,Glob',argv)
        self.assertNotIn('resume',argv);self.assertNotIn('fixture_session',argv)
        adapter.runner.command=lambda *a,**k:SimpleNamespace(returncode=1,stdout='')
        self.assertFalse(adapter.runner.available().ok)

    def test_publish_crash_recovers_with_prewrite_receipt_in_fresh_adapter(self):
        import os
        pre = self.adapter.writer.prepare(None, 'create')
        replacement = os.replace
        count = 0
        def publish(source, destination):
            nonlocal count
            count += 1
            if count == 2: raise RuntimeError('simulated interruption')
            return replacement(source, destination)
        # Interrupt after the native session is published but before its sidebar.
        # Suppress in-process rollback to model process loss, not exception cleanup.
        with patch('baton.adapters.claude.writer.os.replace', side_effect=publish), patch.object(self.adapter.writer, 'take_back'):
            with self.assertRaises(RuntimeError): self.adapter.writer.create(turns(), 'copy', '/new')
        manifest=json.loads(Path(pre.data['intent']).read_text())
        self.assertTrue(any(Path(p).exists() for p in manifest['after']))
        other=ClaudeAdapter(self.root,process=self.process)
        other.writer.take_back(WriteReceipt(**json.loads(json.dumps(asdict(pre)))))
        self.assertTrue(all(not Path(p).exists() for p in manifest['after']))
        self.assertEqual(other.reader.read(self.chat),turns())
    def test_prewrite_receipt_refuses_outside_edit_without_touching_other_files(self):
        pre=self.adapter.writer.prepare(self.chat,'rename')
        self.adapter.writer.rename(self.chat,'planned')
        path,entry=self.adapter.locator.entry(self.chat)
        entry['title']='outside';path.write_text(json.dumps(entry))
        snapshot={str(p):p.read_bytes() for p in (path,self.adapter.locator.session_path(self.chat))}
        with self.assertRaises(ChatChanged): self.adapter.writer.take_back(pre)
        self.assertEqual({p:Path(p).read_bytes() for p in snapshot},snapshot)
    def test_atomic_append_preserves_all_prior_bytes_including_dead_branches(self):
        path=self.adapter.locator.session_path(self.chat)
        original=path.read_bytes()
        dead={'uuid':'deadbranch','parentUuid':'a2','isSidechain':True,'type':'assistant','version':'2.1.284','message':{'content':[{'type':'text','text':'dead'}]}}
        path.write_bytes(original+json.dumps(dead).encode()+b'\n')
        before=path.read_bytes()
        self.adapter.writer.add(self.chat,[Turn(Message('extra',PROMPT,'more'))])
        self.assertTrue(path.read_bytes().startswith(before))
        self.assertEqual(self.adapter.reader.read(self.chat)[-1].id,'extra')
    def test_native_usage_cache_sum_and_unknown_model_size(self):
        path=self.adapter.locator.session_path(self.chat)
        records=[json.loads(l) for l in path.read_text().splitlines()]
        records[-1]['message']['usage']={'input_tokens':10,'cache_creation_input_tokens':20,'cache_read_input_tokens':30,'output_tokens':4}
        path.write_text(''.join(json.dumps(r)+'\n' for r in records))
        self.assertEqual(self.adapter.reader.usage(self.chat).tokens,64)
        self.assertIsNone(self.adapter.reader.usage(self.chat).size)
        self.adapter.context_sizes={'test-model':200000}
        self.assertEqual(self.adapter.reader.usage(self.chat).size,200000)
    def test_app_started_time_uses_process_launch_not_hook_calls(self):
        from baton.adapters.claude.app import SystemProcess
        output='Mon Oct  5 09:00:00 2026 /Applications/Claude.app/Contents/MacOS/Claude\n'
        with patch('baton.adapters.claude.app.subprocess.run',return_value=SimpleNamespace(stdout=output)) as command:
            stamp=SystemProcess().started_at()
        self.assertTrue(stamp.startswith('2026-10-05T'))
        self.assertTrue(stamp.endswith('Z'))
        self.assertIn('lstart=,command=',command.call_args.args[0])
    def test_recovery_refuses_live_registry_even_if_sidebar_missing(self):
        pre=self.adapter.writer.prepare(None,'create')
        result=self.adapter.writer.create(turns(),'copy','/new')
        sid=pre.data['session_id']
        self.adapter.locator.entry(result.chat_id)[0].unlink()
        registry=self.root/'.claude/sessions';registry.mkdir(parents=True)
        self.process.pids.add(1234)
        (registry/'1234.json').write_text(json.dumps({'pid':1234,'sessionId':sid,'status':'idle'}))
        from baton.domain.errors import ChatHeld
        with self.assertRaises(ChatHeld): self.adapter.writer.take_back(pre)

    def test_malformed_tail_remains_readable_but_blocks_writes(self):
        path=self.adapter.locator.session_path(self.chat)
        path.write_bytes(path.read_bytes()+b'{malformed}\n')
        self.assertEqual(self.adapter.reader.read(self.chat),turns())
        before=path.read_bytes()
        with self.assertRaises(UnknownFormat): self.adapter.writer.add(self.chat,[])
        self.assertEqual(path.read_bytes(),before)
    def test_prepared_cut_recovery_restores_exact_native_bytes(self):
        path=self.adapter.locator.session_path(self.chat);before=path.read_bytes()
        pre=self.adapter.writer.prepare(self.chat,'cut')
        self.adapter.writer.cut(self.chat,'a1')
        fresh=ClaudeAdapter(self.root,process=self.process)
        fresh.writer.take_back(WriteReceipt(**json.loads(json.dumps(asdict(pre)))))
        self.assertEqual(path.read_bytes(),before)

    def test_missing_hook_entrypoints_refuse_install_without_changing_settings(self):
        adapter=ClaudeAdapter(self.root,process=self.process,hook_entrypoints_available=lambda:False)
        path=adapter.hooks.path
        self.assertFalse(adapter.hooks.install().ok)
        self.assertFalse(path.exists())
    def test_release_refuses_reused_pid_identity(self):
        registry=self.root/'.claude/sessions';registry.mkdir(parents=True)
        self.process.pids.add(1234)
        (registry/'1234.json').write_text(json.dumps({'pid':1234,'sessionId':'fixture_session','status':'idle'}))
        self.process.owns_session=lambda pid,sid:False
        from baton.domain.errors import NotAvailable
        with self.assertRaises(NotAvailable):self.adapter.app.release(self.chat)
        self.assertEqual(self.process.calls,[])
    def test_system_process_identity_checks_session_and_executable(self):
        from baton.adapters.claude.app import SystemProcess
        for output,expected in (('/path/claude --resume fixture_session',True),('/path/claude --resume unrelated',False),('/bin/other --resume fixture_session',False),('/path/claude --resume',False)):
            with self.subTest(output=output),patch('baton.adapters.claude.app.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout=output)):
                self.assertEqual(SystemProcess().owns_session(1234,'fixture_session'),expected)

    def test_native_append_parent_and_prompt_positions_continue(self):
        created=self.adapter.writer.create(turns()[:2],'copy','/project')
        result=self.adapter.writer.add(created.chat_id,turns()[2:])
        records=[json.loads(l) for l in self.adapter.locator.session_path(created.chat_id).read_text().splitlines()]
        prompts=[r for r in records if r.get('origin',{}).get('kind')=='human']
        self.assertEqual([p['turnPosition']['promptIndex'] for p in prompts],[1,2,3])
        self.assertEqual(prompts[-1]['parentUuid'],'a2')
        tool=next(r for r in records if r.get('uuid')=='c1')
        self.assertEqual(tool['message']['stop_reason'],'tool_use')
        self.assertEqual(tool['message']['content'][0]['id'],'c1')

    def test_archived_unknown_target_blocks_every_write_without_mutation(self):
        entry_path, entry = self.adapter.locator.entry(self.chat)
        entry['isArchived'] = True
        entry_path.write_text(json.dumps(entry))
        chat_path = self.adapter.locator.session_path(self.chat)
        records = [json.loads(line) for line in chat_path.read_text().splitlines()]
        for record in records: record['version'] = 'unsupported'
        chat_path.write_text(''.join(json.dumps(record)+'\n' for record in records))
        before = (chat_path.read_bytes(), entry_path.read_bytes())
        self.assertFalse(self.adapter.state.format_version().known)
        for operation in (lambda: self.adapter.writer.add(self.chat, []),
                          lambda: self.adapter.writer.cut(self.chat, 'p1'),
                          lambda: self.adapter.writer.rename(self.chat, 'changed'),
                          lambda: self.adapter.writer.create([], 'new', '/new-project')):
            with self.subTest(operation=operation), self.assertRaises(UnknownFormat): operation()
        self.assertEqual(before, (chat_path.read_bytes(), entry_path.read_bytes()))

    def test_recover_create_intent_before_project_directory_exists(self):
        prepared = self.adapter.writer.prepare(None, 'create')
        with patch.object(self.adapter.writer, '_check', side_effect=[None, UnknownFormat()]):
            with self.assertRaises(UnknownFormat): self.adapter.writer.create([], 'new', '/never-created')
        intent = Path(prepared.data['intent'])
        self.assertTrue(intent.exists())
        other = ClaudeAdapter(self.root, process=self.process)
        receipt = WriteReceipt(**json.loads(json.dumps(asdict(prepared))))
        other.writer.take_back(receipt)
        self.assertFalse(intent.exists())
        self.assertFalse(other.state.condition(prepared.chat_id).exists)
        self.assertEqual(other.reader.read(self.chat), turns())

if __name__=='__main__': unittest.main()

class ClaudeUndoIntegration(unittest.TestCase):
    """Exact native cut/restore through the engine, using only temporary fixtures."""
    def test_undo_restore_and_restore_failure_keep_exact_bytes(self):
        from baton.adapters.fake import FakeAdapter
        from baton.adapters.fake.facts import CODEX_LIKE
        from baton.ledger.sqlite_store import Ledger
        from baton.ports.clock import FixedClock
        from baton.services.linker import Linker
        from baton.services.applier import Applier
        from baton.services.undo import Undo
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        root = Path(temp.name); process = FixtureProcess(root)
        target = ClaudeAdapter(root, process=process)
        process.adapter = target
        chat = build(root, turns()[:1])
        source = FakeAdapter(CODEX_LIKE, 'codex')
        other = source.build_chat(target.reader.read(chat))
        adapters = {'claude': target, 'codex': source}
        store = Ledger(':memory:'); self.addCleanup(store.close)
        clock = FixedClock('2026-10-05T01:00:00Z')
        linker = Linker(store, adapters, clock)
        linked = linker.apply(linker.plan_link('codex', other, 'claude', chat))
        self.assertTrue(linked.applied, linked)
        source.chats[other] += turns()[1:]
        applier = Applier(store, adapters, clock)
        applier.refresh(linked.link_id)
        self.assertTrue(applier.apply(applier.preview(linked.link_id)).applied)
        event = next(e.id for e in store.history(linked.link_id) if e.kind == 'add')
        path = target.locator.session_path(chat)
        original = path.read_bytes()
        service = Undo(store, adapters, clock)
        undone = service.apply(service.plan(linked.link_id, event))
        self.assertTrue(undone.applied, undone)
        truncated = path.read_bytes()
        with patch.object(store, 'complete_undo', side_effect=RuntimeError):
            failed = service.apply(service.restore(linked.link_id, undone.event_id))
        self.assertFalse(failed.applied)
        self.assertFalse(failed.rollback_errors)
        self.assertEqual(path.read_bytes(), truncated)
        restored = service.apply(service.restore(linked.link_id, undone.event_id))
        self.assertTrue(restored.applied, restored)
        self.assertEqual(path.read_bytes(), original)
