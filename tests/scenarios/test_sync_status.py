"""S1–S12: observed conversation effects and truthful per-side states."""
from dataclasses import replace
import unittest
from functools import wraps

from baton.adapters.fake import FakeAdapter
from baton.adapters.fake.facts import CLAUDE_LIKE, CODEX_LIKE, OPENCODE_LIKE, CURSOR_LIKE
from baton.domain.capabilities import Visibility
from baton.domain.errors import DecisionNeeded
from baton.domain.model import Message, Turn, PROMPT, REPLY, TOOL_CALL
from baton.ledger.sqlite_store import Ledger
from baton.ports.clock import FixedClock
from baton.services.applier import Applier, ApplyStep
from tests.adapters.suite import turns


FACT_SETS = (CLAUDE_LIKE, CODEX_LIKE, OPENCODE_LIKE, CURSOR_LIKE)
HELD_FACTS = (CLAUDE_LIKE, CODEX_LIKE, CURSOR_LIKE)
DEFERRED_ADD_FACTS = (CLAUDE_LIKE, OPENCODE_LIKE, CURSOR_LIKE)
RELAUNCH_CREATE_FACTS = (CLAUDE_LIKE, CURSOR_LIKE)

# Applicability is about facts, not the tool identity used by a made-up chat.
# S1/S2/S4b/S8: all except ANY_TIME (that tool writes instead of waiting).
# S3: AFTER_RELAUNCH and ON_REOPEN_CHAT (AT_ONCE needs no later visibility proof).
# S4: AT_ONCE added turns only; S10: AFTER_RELAUNCH created chats only.
# S5/S6/S7/S9/S11/S12: all four; the generic delivery test covers other S4 outcomes.
SCENARIO_FACTS = {
    'S1': HELD_FACTS, 'S2': HELD_FACTS, 'S3': DEFERRED_ADD_FACTS,
    'S4': (CODEX_LIKE,), 'S4b': HELD_FACTS, 'S5': FACT_SETS,
    'S6': FACT_SETS, 'S7': FACT_SETS, 'S8': HELD_FACTS,
    'S9': FACT_SETS, 'S10': RELAUNCH_CREATE_FACTS,
    'S11': FACT_SETS, 'S12': FACT_SETS,
}


def scenario(number, side='claude'):
    """Run a named acceptance scenario with every applicable target fact set."""
    def decorate(test):
        @wraps(test)
        def run(self):
            for facts in SCENARIO_FACTS[number]:
                with self.subTest(scenario=number, window=facts.write_window):
                    self.use_facts(side, facts)
                    test(self)
        return run
    return decorate


class SyncStatusScenarios(unittest.TestCase):
    def setUp(self):
        self.store = Ledger(':memory:')
        self.clock = FixedClock('2026-01-01T01:00:00Z')
        self.adapters = {'claude': FakeAdapter(CLAUDE_LIKE, 'claude'),
                         'codex': FakeAdapter(CODEX_LIKE, 'codex')}
        self.chats = {s: a.build_chat([]) for s,a in self.adapters.items()}
        self.link = self.store.link(self.chats, 'full_copy', self.clock.now())
        self.applier = Applier(self.store, self.adapters, self.clock)

    def tearDown(self):
        self.store.close()

    def use_facts(self, side, facts):
        self.store.close()
        self.setUp()
        self.adapters[side].facts = facts
        self.adapters[side].set_format(True, facts.checked_versions[0])

    def seed(self, side, values):
        self.adapters[side].chats[self.chats[side]].extend(values)
        return self.store.record_turns(self.link.id, side, values)

    def status(self, side):
        return self.applier.refresh(self.link.id)['status'].side(side)

    @scenario('S1')
    def test_S1_open_chat_has_waiting_turns_and_relaunch_alternative(self):
        self.adapters['claude'].set_condition(self.chats['claude'], open=True, app_running=True)
        self.seed('codex', turns()[:2])
        plan = self.applier.preview(self.link.id)
        self.assertEqual(plan.steps[0].action, 'attach')
        self.assertIn('close_sync_reopen', plan.steps[0].alternatives)
        status = self.status('claude')
        self.assertEqual((status.waiting,status.waiting_reason), (2,'chat_open'))
        self.assertEqual(self.adapters['claude'].reader.read(self.chats['claude']), [])
        self.assertEqual(self.status('codex').agent_has, 2)

    @scenario('S2')
    def test_S2_hook_acknowledgment_attaches_without_claiming_visible_messages(self):
        self.adapters['claude'].set_condition(self.chats['claude'], open=True, app_running=True)
        ids = self.seed('codex', turns()[:2])
        self.applier.apply(self.applier.preview(self.link.id))
        self.assertEqual(self.status('claude').waiting, 2)
        self.applier.record_attached(self.link.id, 'claude', ids, 'sent-message')
        status = self.status('claude')
        self.assertEqual((status.agent_has,status.chat_shows,status.attached,status.waiting),(2,0,2,0))
        self.assertEqual(status.needs, ())
        self.assertEqual(self.store.history(self.link.id)[0].detail['message_id'], 'sent-message')

    @scenario('S3')
    def test_S3_relaunch_after_add_proves_deferred_turns_shown(self):
        target = self.adapters['claude']
        # First recreate S1's held state; closing for sync precedes the next start.
        target.set_condition(self.chats['claude'], open=True, app_running=True)
        self.seed('codex', turns()[:2])
        target.set_condition(self.chats['claude'], open=False, app_running=False)
        result = self.applier.apply(self.applier.preview(self.link.id))
        self.assertTrue(result.applied)
        status = self.status('claude')
        self.assertEqual((status.agent_has,status.added,status.chat_shows),(2,2,0))
        need = 'reopen_chat_to_see' if self.adapters['claude'].facts.added_turn_visible == Visibility.ON_REOPEN_CHAT else 'relaunch_to_see'
        self.assertEqual(status.needs, (need,))
        self.adapters['claude'].set_condition(self.chats['claude'], app_started_at='2026-01-01T01:00:01Z')
        status = self.status('claude')
        self.assertEqual((status.agent_has,status.chat_shows,status.added),(2,2,0))
        self.assertTrue(all(t.states['claude']=='shown' for t in self.store.turns(self.link.id)))

    @scenario('S4', 'codex')
    def test_S4_released_destination_shows_added_turn_immediately(self):
        self.seed('claude', turns()[:1])
        self.adapters['codex'].set_condition(self.chats['codex'], open=False)
        self.assertTrue(self.applier.apply(self.applier.preview(self.link.id)).applied)
        self.assertEqual((self.status('codex').agent_has,self.status('codex').chat_shows),(1,1))
        self.assertEqual(len(self.adapters['codex'].reader.read(self.chats['codex'])),1)

    @scenario('S4b', 'codex')
    def test_S4b_held_destination_never_written(self):
        self.seed('claude', turns()[:1])
        self.adapters['codex'].set_condition(self.chats['codex'], open=True, app_running=True)
        result = self.applier.apply(self.applier.preview(self.link.id))
        self.assertEqual(result.completed[0].action, 'attach')
        self.assertEqual((self.status('codex').waiting,self.status('codex').waiting_reason),(1,'chat_open'))
        self.assertEqual(self.adapters['codex'].reader.read(self.chats['codex']),[])

    @scenario('S5')
    def test_S5_initial_attached_history_waits_even_before_closed_chat_first_prompt(self):
        self.store.db.execute("update links set mode='attached_history' where id=?", (self.link.id,))
        values = [replace(turns()[0],prompt=replace(turns()[0].prompt,id=f'p{i}')) for i in range(12)]
        self.seed('codex', values)
        self.adapters['claude'].set_condition(self.chats['claude'], open=False)
        plan = self.applier.preview(self.link.id)
        self.assertEqual(plan.steps[0].action, 'attach')
        self.assertEqual(plan.steps[0].reason, 'initial_history')
        self.applier.apply(plan)
        status = self.status('claude')
        self.assertEqual((status.waiting,status.attached_on_next_message),(12,12))
        self.assertEqual(status.needs, ())
        self.assertEqual(self.adapters['claude'].reader.read(self.chats['claude']),[])

    @scenario('S6')
    def test_S6_first_message_attaches_initial_history_for_each_fact_set(self):
        self.store.db.execute("update links set mode='attached_history' where id=?", (self.link.id,))
        values = [replace(turns()[0],prompt=replace(turns()[0].prompt,id=f'p{i}')) for i in range(12)]
        ids = self.seed('codex', values)
        self.assertEqual(self.applier.preview(self.link.id).steps[0].action, 'attach')
        self.applier.record_attached(self.link.id, 'claude', ids, 'first')
        status = self.status('claude')
        self.assertEqual((status.agent_has,status.chat_shows,status.attached,status.waiting),(12,0,12,0))
        self.assertEqual(self.adapters['claude'].reader.read(self.chats['claude']), [])

    @scenario('S7')
    def test_S7_conflict_blocks_both_sides(self):
        self.seed('claude',turns()[:1])
        self.seed('codex',turns()[1:2])
        plan = self.applier.preview(self.link.id)
        self.assertTrue(plan.decision_needed)
        with self.assertRaises(DecisionNeeded): self.applier.apply(plan)
        for side in self.link.sides:
            self.assertEqual(self.status(side).waiting_reason,'decision_needed')
            self.assertEqual(len(self.adapters[side].reader.read(self.chats[side])),1)
        self.assertEqual(self.store.journal_entries(),[])

    @scenario('S8', 'codex')
    def test_S8_missing_hooks_hold_and_never_mark_attached(self):
        self.seed('claude',turns()[:1])
        self.adapters['codex'].set_condition(self.chats['codex'],open=True,app_running=True,hooks_ready=False)
        result = self.applier.apply(self.applier.preview(self.link.id))
        self.assertEqual(result.completed[0].action,'hold')
        self.assertEqual(self.status('codex').waiting_reason,'hooks_not_ready')
        self.assertEqual(self.status('codex').attached,0)
        self.assertEqual(self.store.journal_entries(),[])

    @scenario('S9')
    def test_S9_bypassed_turn_returns_to_waiting_and_is_delivered_again(self):
        self.seed('codex',turns()[:1])
        self.applier.apply(self.applier.preview(self.link.id))
        self.adapters['claude'].chats[self.chats['claude']].clear()
        status = self.status('claude')
        self.assertEqual((status.agent_has,status.chat_shows,status.waiting),(0,0,1))
        self.assertEqual(self.store.history(self.link.id)[0].kind,'not_confirmed')
        self.applier.apply(self.applier.preview(self.link.id))
        self.assertEqual(len(self.adapters['claude'].reader.read(self.chats['claude'])),1)
        self.assertEqual(len(self.store.turns(self.link.id)),1)

    @scenario('S10')
    def test_S10_created_chat_requires_relaunch_until_observed_start(self):
        self.seed('codex',turns()[:1])
        step = self.applier.preview(self.link.id).steps[0]
        create = ApplyStep('claude','create',step.turn_ids,step.turns,name='twin')
        result = self.applier.apply(self.applier.prepare(self.link.id,[create],self.link.chats))
        chat = result.completed[0].chat_id
        self.assertEqual(self.store.get_link(self.link.id).chat('claude'), chat)
        self.chats['claude'] = chat
        self.assertEqual(self.status('claude').needs,('relaunch_to_see',))
        self.adapters['claude'].set_condition(chat,app_started_at='2026-01-01T01:00:01Z')
        self.assertEqual(self.status('claude').chat_shows,1)

    @scenario('S11', 'codex')
    def test_S11_names_are_read_fresh_after_rename(self):
        self.adapters['codex'].writer.rename(self.chats['codex'],'new name')
        fresh = self.applier.refresh(self.link.id)
        self.assertEqual(fresh['names'],{'claude':'chat','codex':'new name'})

    @scenario('S12')
    def test_S12_conversation_supplies_full_public_reply_and_expandable_tool_activity(self):
        reply = 'long answer ' * 300
        original = Turn(Message('p',PROMPT,'task'), (
            Message('secret','reasoning','private'),
            Message('c1',TOOL_CALL,tool='run',tool_input={'command':'test'}),
            Message('c2',TOOL_CALL,tool='write',tool_input={'path':'file'}),
            Message('r',REPLY,reply)))
        self.seed('claude',[original])
        rows = self.applier.conversation(self.link.id)
        self.assertEqual(rows[0]['reply'],reply)
        self.assertEqual(len(rows[0]['tool_activity']),2)
        self.assertNotIn('private',repr(rows))
        # D4 asserts preview shortening/expansion; C2 later serializes this public data.

    def test_delivery_and_visibility_on_each_fact_set(self):
        for facts in (CLAUDE_LIKE,CODEX_LIKE,OPENCODE_LIKE,CURSOR_LIKE):
            with self.subTest(window=facts.write_window):
                store = Ledger(':memory:')
                try:
                    source = FakeAdapter(CODEX_LIKE,'codex')
                    target = FakeAdapter(facts,'claude')
                    chats = {'codex':source.build_chat(turns()[:1]),'claude':target.build_chat([])}
                    link = store.link(chats,'full_copy',self.clock.now())
                    store.record_turns(link.id,'codex',turns()[:1])
                    applier = Applier(store,{'claude':target,'codex':source},self.clock)
                    result = applier.apply(applier.preview(link.id))
                    self.assertTrue(result.applied)
                    self.assertEqual(len(target.reader.read(chats['claude'])),1)
                    status = applier.refresh(link.id)['status'].side('claude')
                    self.assertEqual(status.agent_has,1)
                    from baton.domain.capabilities import Visibility
                    self.assertEqual(status.chat_shows, int(facts.added_turn_visible==Visibility.AT_ONCE))
                    target.set_condition(chats['claude'],app_started_at='not-a-date')
                    self.assertEqual(applier.refresh(link.id)['status'].side('claude').chat_shows,status.chat_shows)
                    target.set_condition(chats['claude'],app_started_at='2026-01-01T00:59:59Z')
                    self.assertEqual(applier.refresh(link.id)['status'].side('claude').chat_shows,status.chat_shows)
                    target.set_condition(chats['claude'],app_started_at='2026-01-01T01:00:01Z')
                    self.assertEqual(applier.refresh(link.id)['status'].side('claude').chat_shows,1)
                    self.assertEqual(applier.preview(link.id).steps,())
                    self.assertEqual(len(store.turns(link.id)),1)
                finally: store.close()

    def test_initial_history_unknown_format_holds_closed_and_attaches_open(self):
        self.store.db.execute("update links set mode='attached_history' where id=?",(self.link.id,))
        self.seed('codex',turns()[:1])
        target = self.adapters['claude']
        target.set_format(False,'new')
        closed = self.applier.preview(self.link.id)
        self.assertEqual((closed.steps[0].action,closed.steps[0].reason),('hold','format_unknown'))
        target.set_condition(self.chats['claude'],open=True,hooks_ready=True)
        opened = self.applier.preview(self.link.id)
        self.assertEqual((opened.steps[0].action,opened.steps[0].reason),('attach','format_unknown'))
        self.assertTrue(self.applier.apply(opened).applied)
        self.assertEqual(target.reader.read(self.chats['claude']),[])
        self.assertEqual(self.store.journal_entries(),[])

    def test_on_reopen_user_seen_evidence_is_selective_and_hook_never_proves_shown(self):
        target = self.adapters['claude']
        target.facts = OPENCODE_LIKE
        target.set_format(True,OPENCODE_LIKE.checked_versions[0])
        self.seed('codex',turns()[:2])
        self.applier.apply(self.applier.preview(self.link.id))
        ids = [t.id for t in self.store.turns(self.link.id)]
        self.assertEqual(self.applier.mark_seen(self.link.id,'claude',ids[:1]),1)
        self.assertEqual([t.states['claude'] for t in self.store.turns(self.link.id)],['shown','added'])
        self.seed('codex',turns()[2:])
        third = self.store.turns(self.link.id)[-1].id
        self.applier.record_attached(self.link.id,'claude',[third],'hook-message')
        self.assertEqual([t.states['claude'] for t in self.store.turns(self.link.id)],['shown','added','attached'])
