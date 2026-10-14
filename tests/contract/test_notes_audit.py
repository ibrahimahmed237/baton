"""E12 production notes-table assertions, using only temporary fake chats."""
from copy import deepcopy
from dataclasses import replace
import unittest
from unittest.mock import patch

from baton.cli import output
from baton.domain.errors import AlreadyDelivered, ChatChanged, NotAvailable
from baton.ports.tool import Usage, FormatCheck
from tests.contract.test_action_commands import run
from tests.contract.test_background_commands import run as background
from tests.contract.generate_fixtures import original
from tests.contract.test_fixtures import world_for

TOOLS = ('claude', 'codex', 'opencode', 'cursor')


def native(w):
    return deepcopy({s: (a.chats, a.refs, a.inserted_text) for s, a in w.adapters.items()})


def ids(value):
    return [n['id'] for n in value.get('notes', ())]


class NotesAuditTests(unittest.TestCase):
    def before(self, w, command, expected, **args):
        earlier = native(w)
        value = run(w, command, **({'messages': False, **args} if command == 'status' else args))
        for ident in expected:
            self.assertIn(ident, ids(value), value)
        self.assertEqual(native(w), earlier)
        self.assertFalse(any(c[0] in ('close', 'open', 'release') for a in w.adapters.values() for c in a.app.calls))
        return value

    def creation(self, tool, command='link', running=False):
        with world_for('e12-create') as w:
            source_tool = 'codex' if tool == 'claude' else 'claude'
            source = w.chat(source_tool, 'source', [original(1), original(2)])
            w.adapters[tool].app_running = running
            note = 'new_chat.relaunch' if tool in ('claude', 'cursor') else 'new_chat.at_once'
            expected = [note] + (['link.copy'] if command == 'copy' else [])
            return self.before(w, command, expected, source=source_tool + ':' + source, to=tool, mode='full_copy')

    def delivery(self, tool, running=False):
        w = self.enterContext(world_for('e12-delivery'))
        source = 'codex' if tool == 'claude' else 'claude'
        w.pair((source, tool), shared=1)
        w.seed(source, [original(2), original(3)])
        if running:
            w.condition(tool, open=True, app_running=True)
        return w

    def test_any_time_is_selected_by_capability_and_reports_exact_count(self):
        w = self.delivery('opencode', True)
        value = self.before(w, 'sync', ['write.any_time'], to='opencode')
        note, = [n for n in value['notes'] if n['id'] == 'write.any_time']
        self.assertEqual(note['values']['n'], 2)
        # The selection follows the facts even under an unrelated stable identifier.
        with patch.object(w.adapters['opencode'], 'facts', replace(w.adapters['opencode'].facts, write_window=w.adapters['codex'].facts.write_window)):
            fresh = run(w, 'sync', to='opencode')
            self.assertNotIn('write.any_time', ids(fresh))

    def test_q11_digest_failures_leave_status_available_and_native_unchanged(self):
        w = self.enterContext(world_for('e12-digest'))
        w.pair(shared=1)
        w.seed('codex', [original(2)])
        w.sync()
        w.seed('claude', [original(3)])
        for error in (ChatChanged(), NotAvailable(), KeyError('missing')):
            with self.subTest(error=type(error).__name__), patch('baton.services.digest.DigestBuilder.for_side', side_effect=error):
                value = self.before(w, 'status', [])
                for side in value['sides'].values():
                    self.assertIsNone(side['since_you_left'])
                    self.assertIn('digest.unavailable', ids(side))
        restored = run(w, 'status', messages=False)
        self.assertIsNotNone(restored['sides']['codex']['since_you_left'])
        self.assertNotIn('digest.unavailable', ids(restored['sides']['codex']))

    def test_q11_missing_counterpart_explains_digest(self):
        w = self.delivery('codex')
        w.adapters['claude'].chats.pop(w.chats['claude'])
        w.adapters['claude'].refs.pop(w.chats['claude'])
        value = self.before(w, 'status', [])
        for side in value['sides'].values():
            self.assertIn('digest.unavailable', ids(side))

    def test_relaunch_creation_buttons_confirm_through_relaunch_command(self):
        for tool in ('claude', 'cursor', 'codex'):
            with self.subTest(tool=tool), world_for('e12-lifecycle') as w:
                source_tool = 'codex' if tool == 'claude' else 'claude'
                source = w.chat(source_tool, 'source', [original(1)])
                w.adapters[tool].app_running = True
                value = self.before(w, 'copy', ['link.copy'], source=source_tool + ':' + source, to=tool)
                note = next(n for n in value['notes'] if 'relaunch_plan_id' in n['values'])
                token = note['values']['relaunch_plan_id']
                events = []
                adapter = w.adapters[tool]
                close, create, opening = adapter.app.close, adapter.writer.create, adapter.app.open
                def closing():
                    events.append('close'); return close()
                def creating(*args):
                    self.assertFalse(adapter.app_running)
                    events.append('create'); return create(*args)
                def reopen(*args):
                    events.append('open'); return opening(*args)
                with patch.object(adapter.app, 'close', side_effect=closing), patch.object(adapter.writer, 'create', side_effect=creating), patch.object(adapter.app, 'open', side_effect=reopen):
                    receipt = run(w, 'relaunch', confirm=token)
                self.assertTrue(receipt['applied'], receipt)
                self.assertEqual(events, ['close', 'create', 'open'])
                self.assertIn(receipt['chat_id'], adapter.chats)
                self.assertFalse(w.store.link_for(tool, receipt['chat_id']))
                with self.assertRaises(ChatChanged): run(w, 'relaunch', confirm=token)

    def test_relaunch_refuses_any_replying_or_unknown_chat_even_unlinked(self):
        for tool in ('claude', 'codex', 'cursor'):
            for state in (True, None):
                with self.subTest(tool=tool, state=state), world_for('e12-busy') as w:
                    source_tool = 'codex' if tool == 'claude' else 'claude'
                    source = w.chat(source_tool, 'source', [original(1)])
                    extra = w.chat(tool, 'unlinked-busy', [original(9)])
                    w.adapters[tool].app_running = True
                    w.adapters[tool].set_condition(extra, replying=state)
                    value = self.before(w, 'copy', ['relaunch.replying_unknown' if state is None else 'relaunch.replying_safe'], source=source_tool + ':' + source, to=tool)
                    earlier = native(w)
                    self.assertFalse(run(w, 'copy', confirm=value['plan_id'])['applied'])
                    self.assertEqual(native(w), earlier)
                    self.assertFalse(any(c[0] == 'close' for c in w.adapters[tool].app.calls))

    def test_relaunch_stale_source_refuses_before_close(self):
        with world_for('e12-stale') as w:
            source = w.chat('claude', 'source', [original(1)])
            w.adapters['cursor'].app_running = True
            value = run(w, 'copy', source='claude:' + source, to='cursor')
            w.adapters['claude'].chats[source].append(original(2))
            with self.assertRaises(ChatChanged): run(w, 'copy', confirm=value['plan_id'])
            self.assertFalse(any(c[0] == 'close' for c in w.adapters['cursor'].app.calls))

    def test_keep_pin_and_delivery_time_wording(self):
        w = self.delivery('codex')
        ident = w.store.turns(3)[-1].id
        before = native(w)
        keep = run(w, 'keep', turn=ident)
        self.assertIn('briefs and second opinions for Codex leave it out', keep['notes'][0]['text'])
        pin = run(w, 'pin', turn=ident)
        self.assertIn('unless it is kept on the other side', pin['notes'][0]['text'])
        self.assertEqual(native(w), before)
        note = output.error(AlreadyDelivered(ident, 'codex', '14:30'))['error']['note']
        self.assertEqual(note['id'], 'keep.too_late')
        self.assertEqual(note['text'], "This turn was already sent to Codex at 14:30, so it can't be kept back.")


    def test_not_installed_modes_each_explain_the_remedy(self):
        with world_for('e12-uninstalled') as w:
            with patch.object(w.engine.setup_read, 'installation_probe', return_value=False):
                before = native(w)
                value = run(w, 'setup')
                for row in value['tools']:
                    for mode in row['link_modes']:
                        self.assertFalse(mode['available'])
                        self.assertEqual(mode['reason']['id'], 'setup.not_installed')
                self.assertEqual(native(w), before)

    def test_selected_opinion_uses_exact_turn_specific_disclosure(self):
        w = self.delivery('codex')
        before = native(w)
        value = background(w, 'ask', chat='claude:' + w.chats['claude'], tool='codex',
                           question='Review', turn=w.store.turns(3)[-1].id)
        note = next(n for n in value['notes'] if n['id'] == 'ask.preview')
        self.assertTrue(note['text'].startswith('Ask Codex about this turn? Codex gets a brief of the chat, this turn in full,'))
        self.assertEqual(native(w), before)

    def test_create_now_relaunch_later_is_an_independent_executable_choice(self):
        with world_for('e12-later') as w:
            source = w.chat('codex', 'source', [original(1)])
            w.adapters['claude'].app_running = True
            value = self.before(w, 'copy', ['new_chat.relaunch'], source='codex:' + source, to='claude')
            note = next(n for n in value['notes'] if n['id'] == 'new_chat.relaunch')
            self.assertIn('sync_relaunch_later', [b['id'] for b in note['buttons']])
            receipt = run(w, 'copy', confirm=note['values']['sync_relaunch_later_plan_id'])
            self.assertTrue(receipt['applied'])
            self.assertFalse(any(c[0] in ('open', 'close') for c in w.adapters['claude'].app.calls))
            with self.assertRaises(ChatChanged): run(w, 'copy', confirm=value['plan_id'])

    def test_cursor_never_offers_creation_without_closure(self):
        with world_for('e12-no-later') as w:
            source = w.chat('claude', 'source', [original(1)])
            w.adapters['cursor'].app_running = True
            value = self.before(w, 'copy', ['new_chat.relaunch'], source='claude:' + source, to='cursor')
            note = next(n for n in value['notes'] if n['id'] == 'new_chat.relaunch')
            self.assertNotIn('sync_relaunch_later', [b['id'] for b in note['buttons']])
            self.assertNotIn('attach', [b['id'] for b in note['buttons']])

    def test_brief_later_creation_keeps_artifact_and_never_closes(self):
        with world_for('e12-brief-later') as w:
            source = w.chat('codex', 'source', [original(1)])
            for adapter in w.adapters.values(): adapter.runner = None
            w.adapters['claude'].app_running = True
            review = self.before(w, 'link', ['new_chat.relaunch'], source='codex:' + source, to='claude', mode='brief')
            artifact = deepcopy(w.store.brief_artifact(review['brief']['artifact_id']))
            note = next(n for n in review['notes'] if n['id'] == 'new_chat.relaunch')
            receipt = run(w, 'relaunch', confirm=note['values']['sync_relaunch_later_plan_id'])
            self.assertTrue(receipt['applied'], receipt)
            self.assertEqual(w.store.brief_artifact(review['brief']['artifact_id']), artifact)
            self.assertFalse(any(c[0] in ('open', 'close') for c in w.adapters['claude'].app.calls))

    def test_brief_creation_stale_source_or_unknown_target_never_closes(self):
        for unknown in (False, True):
            with self.subTest(unknown=unknown), world_for('e12-brief-stale') as w:
                source = w.chat('claude', 'source', [original(1)])
                for adapter in w.adapters.values(): adapter.runner = None
                w.adapters['cursor'].app_running = True
                if unknown:
                    extra = w.chat('cursor', 'unknown', [original(7)])
                    w.adapters['cursor'].set_condition(extra, replying=None)
                review = run(w, 'link', source='claude:' + source, to='cursor', mode='brief')
                if unknown:
                    self.assertIn('relaunch.replying_unknown', ids(review))
                    self.assertFalse(run(w, 'link', confirm=review['plan_id'])['applied'])
                else:
                    w.adapters['claude'].chats[source].append(original(2))
                    with self.assertRaises(ChatChanged): run(w, 'link', confirm=review['plan_id'])
                self.assertFalse(any(c[0] == 'close' for c in w.adapters['cursor'].app.calls))


def row_test(row, tool, variant=''):
    def test(self):
        if row in (1, 2, 3, 22) and variant != 'add':
            self.creation(tool, 'copy' if row == 22 else 'link', running=tool in ('claude', 'cursor'))
            return
        if row in (5, 10, 11):
            with world_for('e12-setup') as w:
                adapter = w.adapters[tool]
                if row == 5:
                    source_tool = 'codex' if tool == 'claude' else 'claude'
                    source = w.chat(source_tool, 'source', [original(1)])
                    with patch.object(adapter.state, 'format_version', return_value=FormatCheck(True, 'known-shape-next-release', True)):
                        self.before(w, 'copy', ['format.new_version'], source=source_tool + ':' + source, to=tool)
                    adapter.set_format(False, 'future-shape')
                    value = self.before(w, 'copy', ['format.unknown_version'], source=source_tool + ':' + source, to=tool)
                    self.assertEqual(value['confirmation']['id'], 'plan.unavailable')
                    adapter.set_format(True, adapter.facts.checked_versions[0])
                    w.pair((source_tool, tool), shared=1)
                    w.seed(source_tool, [original(3)])
                    adapter.set_format(False, 'future-shape')
                    self.before(w, 'sync', ['format.unknown_version'], to=tool)
                else:
                    adapter.hooks.installed = False
                    before = native(w)
                    value = run(w, 'setup')
                    target = next(t for t in value['tools'] if t['tool'] == tool)
                    self.assertIn('setup.hooks', [f['note']['id'] for f in target['findings']])
                    mode = next(m for m in target['link_modes'] if m['mode'] == 'attached_history')
                    self.assertFalse(mode['available'])
                    self.assertEqual(mode['reason']['id'], 'setup.hooks')
                    self.assertEqual(before, native(w))
            return
        if row == 6:
            with world_for('e12-attach') as w:
                source_tool = 'codex' if tool == 'claude' else 'claude'
                source = w.chat(source_tool, 'source', [original(1), original(2)])
                target = w.chat(tool, 'target', [])
                self.before(w, 'link', ['link.attached_history'], source=source_tool + ':' + source,
                            to=tool + ':' + target, mode='attached_history')
            return
        if row in (3, 7, 8) or row == 17 and variant == 'add':
            w = self.delivery(tool, running=row != 8 or variant == 'open')
            expected = 'write.any_time' if tool == 'opencode' else 'write.app_must_close' if tool == 'cursor' else 'write.chat_open'
            expected_ids = [expected] + (['reopen_chat_to_see'] if row == 17 else [])
            value = self.before(w, 'sync', expected_ids, to=tool)
            if tool == 'opencode':
                self.assertEqual(next(n for n in value['notes'] if n['id'] == expected)['values']['n'], 2)
            else:
                receipt = run(w, 'sync', confirm=value['plan_id'])
                self.assertTrue(receipt['applied'], receipt)
                self.assertEqual(len(w.adapters[tool].reader.read(w.chats[tool])), 3)
            return
        if row in (13, 14, 16, 17):
            w = self.delivery(tool)
            w.sync()
            event = next(e.id for e in w.store.history(3) if e.kind == 'add' and e.side == tool)
            if tool == 'cursor':
                w.condition(tool, app_running=True)
            # Existing delivery setup has no app lifecycle calls.
            for a in w.adapters.values(): a.app.calls.clear()
            expected = 'undo.cut' if tool == 'claude' else 'undo.cut_reopen' if tool == 'opencode' else 'undo.shorter_closed'
            value = self.before(w, 'undo', [expected], event=event)
            self.assertEqual(sum(len(g['removes']) for g in value['removal_groups'] if g['tool'] == tool), 2)
            if tool == 'cursor':
                self.assertTrue(run(w, 'undo', confirm=value['plan_id'])['applied'])
                self.assertEqual([c[0] for c in w.adapters[tool].app.calls if c[0] in ('close', 'open')], ['close', 'open'])
            return
        if row == 18:
            w = self.delivery(tool)
            expected = 'rename.at_once' if tool == 'opencode' else 'rename.relaunch' if tool == 'codex' else 'rename.closed'
            self.before(w, 'rename', [expected], name='New orchard name', tools=tool)
            return
        if row == 20:
            w = self.delivery(tool)
            w.adapters[tool].usage_values[w.chats[tool]] = Usage(8000, 100000, True, None)
            value = self.before(w, 'status', [], messages=False)
            self.assertIn('limit.reached', ids(value['sides'][tool]))
            self.assertEqual(value['sides'][tool]['usage']['limit'], {'resets_at': None})
            for ident in ('limit.offer_linked_no_reset', 'limit.offer_linked_no_reset_behind', 'limit.offer_unlinked_no_reset'):
                self.assertIn('It did not say when it resets.', output.note(ident, {'tool': tool, 'other_tool': 'claude'})['text'])
            return
        if row == 21:
            w = self.delivery(tool)
            # Force an insertion in both histories, requiring a merged copy.
            w.seed(tool, [original(4)])
            value = self.before(w, 'merge', ['merge.merged_copy', 'merge.copy_relaunch' if tool in ('claude', 'cursor') else 'merge.copy_visible'], preset='by_time')
            self.assertTrue(any('the link moves to it' in n['text'] for n in value['notes'] if n['id'] == 'merge.merged_copy'))
            return
        if row == 23:
            w = self.delivery(tool)
            before = native(w)
            source = next(s for s in w.chats if s != tool)
            if variant == 'ask':
                value = background(w, 'ask', chat=source + ':' + w.chats[source], tool=tool, question='Review this')
                expected = 'ask.preview'
            else:
                value = background(w, 'brief', link=3, to=tool, writer=tool)
                expected = 'brief.cost'
            self.assertIn(expected, ids(value))
            text = next(n['text'] for n in value['notes'] if n['id'] == expected)
            self.assertIn('can read the project folder', text)
            self.assertIn('cannot change anything', text)
            self.assertEqual(before, native(w))
            self.assertFalse(any(a.runner.calls for a in w.adapters.values()))
            return
        self.fail((row, tool, variant))
    return test


for _row, _tools, _variants in (
    (1, ('codex', 'opencode'), ('',)), (2, ('claude',), ('',)),
    (3, ('cursor',), ('create', 'add')), (5, TOOLS, ('',)),
    (6, TOOLS, ('',)), (7, ('claude', 'codex', 'cursor'), ('',)),
    (8, ('opencode',), ('open', 'closed')), (10, TOOLS, ('',)),
    (11, TOOLS, ('',)), (13, ('claude',), ('',)), (14, ('opencode',), ('',)),
    (16, ('cursor',), ('',)), (17, ('opencode',), ('add', 'remove')),
    (18, TOOLS, ('',)), (20, ('opencode', 'cursor'), ('',)),
    (21, TOOLS, ('',)), (22, TOOLS, ('',)), (23, TOOLS, ('ask', 'brief')),
):
    for _tool in _tools:
        for _variant in _variants:
            setattr(NotesAuditTests, f'test_row_{_row:02}_{_tool}_{_variant or "preview"}', row_test(_row, _tool, _variant))
