"""E13 safe service execution on fake AppControl, every measured fact set."""
import unittest
from dataclasses import replace
from unittest.mock import patch
from baton.adapters.fake import FakeAdapter
from baton.adapters.fake.facts import CLAUDE_LIKE, CODEX_LIKE, OPENCODE_LIKE, CURSOR_LIKE
from baton.domain.errors import ChatChanged, DecisionNeeded, NotAvailable
from baton.domain.model import Message, Turn
from baton.ledger.sqlite_store import Ledger
from baton.ports.clock import FixedClock
from baton.services.applier import Applier
from baton.services.names import Names
from baton.services.relaunch import Relaunch
from baton.notes.catalogue import get

FACTS = (CLAUDE_LIKE, CODEX_LIKE, OPENCODE_LIKE, CURSOR_LIKE)


def turn(ident='one'):
    return Turn(Message(ident, 'prompt', ident, '2026-10-14T00:00:00Z'),
                (Message(ident + '-r', 'reply', 'done', '2026-10-14T00:01:00Z'),))


class RelaunchTests(unittest.TestCase):
    def build(self, facts=CLAUDE_LIKE, running=True):
        self.store = Ledger(':memory:')
        self.addCleanup(self.store.close)
        self.adapters = {'claude': FakeAdapter(CLAUDE_LIKE, 'claude'), 'codex': FakeAdapter(facts, 'codex')}
        self.source, self.target = self.adapters['claude'], self.adapters['codex']
        self.chats = {'claude': self.source.build_chat([turn()]), 'codex': self.target.build_chat([], 'destination', '/fixture')}
        self.link = self.store.link(self.chats, 'full_copy')
        self.clock = FixedClock('2026-10-14T00:02:00Z')
        self.applier = Applier(self.store, self.adapters, self.clock)
        self.applier.refresh(self.link.id)
        self.target.set_condition(self.chats['codex'], app_running=running, open=running)
        self.ticks = 0.0
        def wait(seconds):
            self.ticks += seconds
        self.service = Relaunch(self.store, self.adapters, self.clock, lambda: self.ticks, wait)

    def setUp(self):
        self.build()

    def plan(self, **options):
        return self.service.plan_relaunch('codex', then_sync=self.link.id, **options)

    def test_every_fact_set_close_settle_write_reopen_order(self):
        for facts in FACTS:
            with self.subTest(facts=facts):
                self.build(facts)
                events = []
                oldclose, oldopen, oldadd = self.target.app.close, self.target.app.open, self.target.writer.add
                def close():
                    events.append('close')
                    oldclose()
                def wait(seconds):
                    events.append('wait')
                    self.ticks += seconds
                def add(chat, turns):
                    events.append('write')
                    self.assertFalse(self.target.app.running())
                    return oldadd(chat, turns)
                def reopen(chat, folder):
                    events.append('reopen')
                    oldopen(chat, folder)
                self.target.app.close, self.target.app.open, self.target.writer.add = close, reopen, add
                self.service.wait = wait
                plan = self.plan()
                self.assertEqual([s.action for s in plan.steps], ['close', 'wait_until_still', 'add', 'reopen'])
                self.assertEqual(events, [])
                result = self.service.apply(plan)
                self.assertTrue(result.applied)
                self.assertTrue(result.opened)
                self.assertEqual(events, ['close', 'wait', 'write', 'reopen'])
                self.assertEqual(self.target.reader.read(self.chats['codex'])[0].prompt.text, 'one')
                call = [c for c in self.target.app.calls if c[0] == 'open'][-1]
                self.assertEqual(call[1], self.chats['codex'] if facts.opens_at_chat else None)
                self.assertEqual(call[2], '/fixture')
                self.assertEqual(self.store.journal_entries()[0]['state'], 'committed')

    def test_T5_names_all_replying_chats_including_unlinked(self):
        other = self.target.build_chat([], 'other reply')
        self.target.set_condition(other, replying=True)
        self.target.set_condition(self.chats['codex'], replying=True)
        plan = self.plan()
        self.assertTrue(plan.decision_needed)
        self.assertEqual({r.name for r in plan.replying}, {'destination', 'other reply'})
        for note in plan.notes:
            rendered = get(note.id).render(note.values)
            self.assertIn(note.values['title'], rendered.template)
            self.assertEqual([b.id for b in rendered.buttons], ['when_idle', 'cancel'])
        result = self.service.apply(plan)
        self.assertEqual(result.error, 'ChatReplying')
        self.assertFalse(any(c[0] == 'close' for c in self.target.app.calls))
        self.assertEqual(self.store.journal_entries(), [])

    def test_T6_idle_variant_waits_for_every_reply_then_relaunches(self):
        other = self.target.build_chat([], 'second')
        self.target.set_condition(other, replying=True)
        self.target.set_condition(self.chats['codex'], replying=True)
        plan = self.plan(when_idle=True)
        self.assertTrue(self.service.apply(plan).waiting)
        self.target.set_condition(self.chats['codex'], replying=False)
        self.assertTrue(self.service.apply(plan).waiting)
        self.assertFalse(any(c[0] == 'close' for c in self.target.app.calls))
        self.target.set_condition(other, replying=False)
        result = self.service.apply(plan)
        self.assertTrue(result.applied)
        self.assertTrue(result.opened)

    def test_close_timeout_waits_a_minute_and_never_writes_or_opens(self):
        self.target.app.close = lambda: None
        result = self.service.apply(self.plan())
        self.assertEqual(result.error, 'CloseTimeout')
        self.assertGreaterEqual(self.ticks, 60)
        self.assertEqual(result.notes[0].id, 'relaunch.close_timeout')
        self.assertEqual(self.store.journal_entries(), [])
        self.assertFalse(any(c[0] == 'open' for c in self.target.app.calls))

    def test_delayed_graceful_close_waits_for_app_and_chat_release(self):
        self.target.app.close = lambda: None
        def wait(seconds):
            self.ticks += seconds
            if self.ticks >= .3:
                self.target.app_running = False
            if self.ticks >= .5:
                self.target.set_condition(self.chats['codex'], open=False)
        self.service.wait = wait
        self.assertTrue(self.service.apply(self.plan()).applied)
        self.assertGreaterEqual(self.ticks, .6)

    def test_changed_content_at_shutdown_refuses_write_and_reopens(self):
        original = self.target.app.close
        def close():
            original()
            self.target.chats[self.chats['codex']].append(turn('outside'))
        self.target.app.close = close
        result = self.service.apply(self.plan())
        self.assertFalse(result.applied)
        self.assertEqual(result.error, 'ChatChanged')
        self.assertIn('relaunch.write_failed', [n.id for n in result.notes])
        self.assertEqual(self.store.journal_entries(), [])
        self.assertTrue(self.target.app_running)

    def test_reply_starts_after_preview_refuses_close(self):
        plan = self.plan()
        other = self.target.build_chat([], 'new reply')
        self.target.set_condition(other, replying=True)
        result = self.service.apply(plan)
        self.assertEqual(result.error, 'ChatReplying')
        self.assertEqual(result.notes[0].values['title'], 'new reply')
        self.assertFalse(any(c[0] == 'close' for c in self.target.app.calls))

    def test_idle_completion_changes_content_requires_new_review(self):
        self.target.set_condition(self.chats['codex'], replying=True)
        plan = self.plan(when_idle=True)
        self.target.set_condition(self.chats['codex'], replying=False)
        self.target.chats[self.chats['codex']].append(turn('finished'))
        with self.assertRaises(ChatChanged):
            self.service.apply(plan)
        self.assertFalse(any(c[0] == 'close' for c in self.target.app.calls))

    def test_reopen_failure_reports_write_succeeded(self):
        self.target.app.open = lambda *args: (_ for _ in ()).throw(OSError())
        result = self.service.apply(self.plan())
        self.assertTrue(result.applied)
        self.assertFalse(result.opened)
        self.assertEqual(result.error, 'ReopenFailed')
        self.assertEqual(result.notes[0].id, 'relaunch.reopen_failed')
        self.assertEqual(len(self.target.reader.read(self.chats['codex'])), 1)

    def test_write_failure_rolls_back_then_reopens(self):
        self.target.writer.add = lambda *args: (_ for _ in ()).throw(OSError())
        result = self.service.apply(self.plan())
        self.assertFalse(result.applied)
        self.assertTrue(result.opened)
        self.assertEqual(result.error, 'OSError')
        self.assertEqual(self.store.journal_entries()[0]['state'], 'taken_back')

    def test_Q13_closed_app_syncs_without_close_or_reopen_each_fact_set(self):
        for facts in FACTS:
            self.build(facts, running=False)
            plan = self.plan()
            self.assertEqual([s.action for s in plan.steps], ['add'])
            result = self.service.apply(plan)
            self.assertTrue(result.applied)
            self.assertFalse(result.opened)
            self.assertFalse(any(c[0] in ('close', 'open') for c in self.target.app.calls))

    def test_explicit_closed_app_relaunch_syncs_then_opens(self):
        self.target.app_running = False
        self.target.set_condition(self.chats['codex'], open=False)
        plan = self.service.plan_relaunch('codex')
        self.assertEqual([s.action for s in plan.steps], ['add', 'reopen'])
        self.assertTrue(self.service.apply(plan).opened)
        self.assertEqual(self.store.journal_entries()[0]['state'], 'committed')

    def test_changed_records_or_facts_refuse_before_close(self):
        plan = self.plan()
        self.store.set_paused(self.link.id, True)
        with self.assertRaises(ChatChanged):
            self.service.apply(plan)
        self.assertFalse(any(c[0] == 'close' for c in self.target.app.calls))
        self.store.set_paused(self.link.id, False)
        plan = self.plan()
        self.target.facts = CODEX_LIKE
        with self.assertRaises(ChatChanged):
            self.service.apply(plan)

    def test_paused_unknown_format_or_conflicting_link_refuses_plan(self):
        self.store.set_paused(self.link.id, True)
        with self.assertRaises(NotAvailable):
            self.plan()
        self.store.set_paused(self.link.id, False)
        self.target.set_format(False, 'future')
        with self.assertRaises(NotAvailable):
            self.plan()
        self.target.set_format(True, self.target.facts.checked_versions[0])
        self.target.chats[self.chats['codex']].append(turn('other'))
        self.applier.refresh(self.link.id)
        with self.assertRaises(DecisionNeeded):
            self.plan()

    def test_rename_can_be_executed_between_close_and_reopen(self):
        names = Names(self.store, self.adapters, self.clock)
        rename = names.plan_rename(self.link.id, 'matched', ['codex'])
        plan = self.service.plan_relaunch('codex', rename=rename)
        self.assertEqual([s.action for s in plan.steps], ['close', 'wait_until_still', 'rename', 'reopen'])
        result = self.service.apply(plan)
        self.assertTrue(result.applied)
        self.assertTrue(result.opened)
        self.assertEqual(names.names(self.link.id)['codex'], 'matched')

    def test_modified_plan_payload_refuses_checksum(self):
        plan = self.plan()
        plan.delivery.record['link']['paused'] = True
        with self.assertRaises(ChatChanged):
            self.service.apply(plan)
        self.assertEqual(self.store.journal_entries(), [])

    def second_link(self):
        chats = {'claude': self.source.build_chat([turn('two')]),
                 'codex': self.target.build_chat([], 'second', '/fixture')}
        link = self.store.link(chats, 'full_copy')
        self.applier.refresh(link.id)
        return link, chats

    def test_app_wide_relaunch_syncs_all_unpaused_links(self):
        link, chats = self.second_link()
        plan = self.service.plan_relaunch('codex')
        self.assertEqual([s.action for s in plan.steps], ['close', 'wait_until_still', 'add', 'add', 'reopen'])
        result = self.service.apply(plan)
        self.assertTrue(result.applied)
        self.assertEqual(result.completed_links, (self.link.id, link.id))
        self.assertEqual(self.target.reader.read(chats['codex'])[0].prompt.text, 'two')
        self.assertEqual(sum(c[0] == 'close' for c in self.target.app.calls), 1)

    def test_app_wide_relaunch_leaves_paused_link_alone(self):
        link, chats = self.second_link()
        self.store.set_paused(link.id, True)
        self.assertTrue(self.service.apply(self.service.plan_relaunch('codex')).applied)
        self.assertEqual(self.target.reader.read(chats['codex']), [])

    def test_app_wide_partial_failure_reports_completed_links(self):
        link, chats = self.second_link()
        original = self.target.writer.add
        def add(chat, turns):
            if chat == chats['codex']:
                raise OSError()
            return original(chat, turns)
        self.target.writer.add = add
        result = self.service.apply(self.service.plan_relaunch('codex'))
        self.assertFalse(result.applied)
        self.assertTrue(result.opened)
        self.assertEqual(result.completed_links, (self.link.id,))
        self.assertEqual(result.notes[0].id, 'relaunch.partial')
        self.assertEqual(self.target.reader.read(chats['codex']), [])
        self.assertEqual(len(self.target.reader.read(self.chats['codex'])), 1)

    def test_close_port_failure_reports_no_write(self):
        self.target.app.close = lambda: (_ for _ in ()).throw(OSError())
        result = self.service.apply(self.plan())
        self.assertFalse(result.applied)
        self.assertEqual(result.notes[0].id, 'relaunch.close_failed')
        self.assertEqual(self.store.journal_entries(), [])

    def test_chat_never_released_times_out_even_when_app_stopped(self):
        self.target.app.close = lambda: setattr(self.target, 'app_running', False)
        result = self.service.apply(self.plan())
        self.assertEqual(result.error, 'CloseTimeout')
        self.assertEqual(self.store.journal_entries(), [])

    def test_source_changes_while_planning_refuses_stale_payload(self):
        original = self.service._sync_steps
        def steps(tool, link):
            value = original(tool, link)
            self.source.chats[self.chats['claude']].append(turn('outside'))
            return value
        self.service._sync_steps = steps
        with self.assertRaises(ChatChanged):
            self.plan()
        self.assertEqual(self.store.journal_entries(), [])

    def test_still_reads_must_be_consecutive_before_write(self):
        original = self.target.app.close
        def close():
            original()
            self.target.set_condition(self.chats['codex'], open=True)
        self.target.app.close = close
        def wait(seconds):
            self.ticks += seconds
            # File ownership settles only after a transient reopening.
            self.target.set_condition(self.chats['codex'], open=.15 < self.ticks < .25)
        self.service.wait = wait
        self.assertTrue(self.service.apply(self.plan()).applied)
        self.assertGreaterEqual(self.ticks, .4)

    def test_second_link_changed_since_app_wide_preview_refuses_all_writes(self):
        link, chats = self.second_link()
        plan = self.service.plan_relaunch('codex')
        self.source.chats[chats['claude']].append(turn('outside'))
        with self.assertRaises(ChatChanged):
            self.service.apply(plan)
        self.assertFalse(any(c[0] == 'close' for c in self.target.app.calls))
        self.assertEqual(self.store.journal_entries(), [])

    def test_apply_plan_twice_refuses_without_second_close(self):
        plan = self.plan()
        self.assertTrue(self.service.apply(plan).applied)
        closes = sum(c[0] == 'close' for c in self.target.app.calls)
        with self.assertRaises(ChatChanged):
            self.service.apply(plan)
        self.assertEqual(sum(c[0] == 'close' for c in self.target.app.calls), closes)

    def test_rename_relaunch_each_fact_set(self):
        for facts in FACTS:
            self.build(facts)
            names = Names(self.store, self.adapters, self.clock)
            rename = names.plan_rename(self.link.id, 'matched', ['codex'])
            result = self.service.apply(self.service.plan_relaunch('codex', rename=rename))
            self.assertTrue(result.applied)
            self.assertTrue(result.opened)
            self.assertEqual(names.names(self.link.id)['codex'], 'matched')

    def test_shutdown_may_clear_app_start_evidence(self):
        self.target.set_condition(self.chats['codex'], app_started_at='2026-10-14T00:00:00Z')
        original = self.target.app.close
        def close():
            original()
            self.target.set_condition(self.chats['codex'], app_started_at='')
        self.target.app.close = close
        self.assertTrue(self.service.apply(self.plan()).applied)

    def test_close_quits_then_raises_reopens_saved_context_without_writing(self):
        close = self.target.app.close
        def partial_close():
            close()
            raise OSError()
        self.target.app.close = partial_close
        result = self.service.apply(self.plan())
        self.assertFalse(result.applied)
        self.assertTrue(result.opened)
        self.assertEqual(result.notes[0].id, 'relaunch.close_failed')
        self.assertEqual([c for c in self.target.app.calls if c[0] == 'open'][-1], ('open', self.chats['codex'], '/fixture'))
        self.assertEqual(self.store.journal_entries(), [])

    def test_changed_write_and_failed_reopen_returns_both_failures(self):
        close = self.target.app.close
        def change():
            close()
            self.target.chats[self.chats['codex']].append(turn('outside'))
        self.target.app.close = change
        self.target.app.open = lambda *args: (_ for _ in ()).throw(OSError())
        result = self.service.apply(self.plan())
        self.assertFalse(result.applied)
        self.assertEqual(result.reopen_error, 'ReopenFailed')
        self.assertEqual({n.id for n in result.notes},
                         {'relaunch.write_failed', 'relaunch.reopen_failed_no_write'})
        self.assertEqual(self.store.journal_entries(), [])

    def test_write_failure_note_and_successful_reopen_return_together(self):
        self.target.writer.add = lambda *args: (_ for _ in ()).throw(OSError())
        result = self.service.apply(self.plan())
        self.assertTrue(result.opened)
        self.assertEqual(result.write_result.error, 'OSError')
        self.assertIn('relaunch.write_failed', [n.id for n in result.notes])

    def test_write_failure_note_and_failed_reopen_return_together(self):
        self.target.writer.add = lambda *args: (_ for _ in ()).throw(OSError())
        self.target.app.open = lambda *args: (_ for _ in ()).throw(OSError())
        result = self.service.apply(self.plan())
        self.assertFalse(result.opened)
        self.assertEqual(result.write_result.error, 'OSError')
        self.assertEqual(result.reopen_error, 'ReopenFailed')
        self.assertEqual({n.id for n in result.notes},
                         {'relaunch.write_failed', 'relaunch.reopen_failed_no_write'})

    def test_T6_idle_request_expiry_is_fixed_across_retries(self):
        self.target.set_condition(self.chats['codex'], replying=True)
        plan = self.plan(when_idle=True)
        self.assertEqual(plan.expires_at, '2026-10-14T00:32:00+00:00')
        for minute in (3, 15, 31):
            self.clock.value = f'2026-10-14T00:{minute:02d}:00Z'
            self.assertTrue(self.service.apply(plan).waiting)
        self.clock.value = '2026-10-14T00:32:00Z'
        for _ in range(3):
            result = self.service.apply(plan)
            self.assertFalse(result.waiting)
            self.assertEqual(result.error, 'IdleTimeout')
            self.assertEqual(result.notes[0].id, 'relaunch.idle_timeout')
            get(result.notes[0].id).render(result.notes[0].values)
        self.target.set_condition(self.chats['codex'], replying=False)
        self.assertEqual(self.service.apply(plan).error, 'IdleTimeout')
        self.assertFalse(any(c[0] in ('close', 'open') for c in self.target.app.calls))
        self.assertEqual(self.store.journal_entries(), [])

    def test_T6_injected_timeout_and_expiry_tampering(self):
        from datetime import timedelta
        self.service.idle_timeout = timedelta(seconds=5)
        plan = self.plan(when_idle=True)
        self.assertEqual(plan.expires_at, '2026-10-14T00:02:05+00:00')
        with self.assertRaises(ChatChanged):
            self.service.apply(replace(plan, expires_at='2026-10-14T00:03:00Z'))
        self.clock.value = '2026-10-14T00:02:06Z'
        self.assertEqual(self.service.apply(plan).error, 'IdleTimeout')

    def test_kept_turn_never_reaches_target_through_relaunch_sync(self):
        row = self.store.turns(self.link.id)[0]
        self.store.keep_back(self.link.id, row.id, self.clock.now())
        self.assertTrue(self.service.apply(self.plan()).applied)
        self.assertEqual(self.target.reader.read(self.chats['codex']), [])
        self.assertEqual(self.store.journal_entries(), [])

    def test_partial_shutdown_settle_timeout_reopens_without_writing(self):
        self.target.app.close = lambda: setattr(self.target, 'app_running', False)
        result = self.service.apply(self.plan())
        self.assertEqual(result.error, 'CloseTimeout')
        self.assertTrue(result.opened)
        self.assertEqual(result.notes[0].id, 'relaunch.close_timeout')
        self.assertEqual(self.store.journal_entries(), [])

    def test_rename_write_exception_returns_failure_and_reopen_result(self):
        for reopen_fails in (False, True):
            with self.subTest(reopen_fails=reopen_fails):
                self.build()
                rename = Names(self.store, self.adapters, self.clock).plan_rename(self.link.id, 'matched', ['codex'])
                plan = self.service.plan_relaunch('codex', rename=rename)
                with patch.object(self.target.writer, 'rename', side_effect=OSError()):
                    if reopen_fails:
                        with patch.object(self.target.app, 'open', side_effect=OSError()): result = self.service.apply(plan)
                    else: result = self.service.apply(plan)
                self.assertFalse(result.applied)
                self.assertEqual(result.opened, not reopen_fails)
                self.assertIn('relaunch.write_failed', [n.id for n in result.notes])
                self.assertEqual(result.reopen_error, 'ReopenFailed' if reopen_fails else '')
