"""Generate app fixtures from isolated, explicit semantic state recipes.

No fixture JSON is opened here. The fixed clock/identity source is installed
before construction, including before fingerprints and brief artifacts seal.
Only --output explicitly publishes files; ordinary tests use temporary roots.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from dataclasses import asdict, replace
from hashlib import sha256
from itertools import count
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

from baton.adapters.fake import FakeAdapter
from baton.adapters.fake.facts import CLAUDE_LIKE, CODEX_LIKE, OPENCODE_LIKE, CURSOR_LIKE
from baton.cli import output
from baton.cli.commands import Context, discover
from baton.cli.tools import label
from baton.cli.wiring import build
from baton.domain.errors import BatonError, ChatChanged, DecisionNeeded, NotAvailable, AlreadyLinked
from baton.domain.model import Message, Turn, PROMPT, REPLY, TOOL_CALL, TOOL_RESULT
from baton.domain.link import LedgerTurn, CHAT_SHOWS
from baton.notes.catalogue import CATALOGUE
from baton.ports.clock import FixedClock
from baton.ports.tool import Usage, SetupFinding
from baton.services.brief import BriefPlan, BriefService
from baton.services.delivery_plan import ApplyStep
from baton.services.limit_offer import LimitOffers, MemoryOffers
from baton.services.transcripts import FolderTranscripts
from tests.contract.fixture_manifest import MANIFEST, D5_TARGETS, Fixture

NOW = '2026-10-05T14:00:00Z'
LATER = '2026-10-05T14:01:00Z'
FOLDER = '/work/baton-fixtures'
FACTS = {'claude': CLAUDE_LIKE, 'codex': CODEX_LIKE, 'opencode': OPENCODE_LIKE, 'cursor': CURSOR_LIKE}
REGISTRY = discover()


def original(n, *, text=None, long=False):
    """Public fake work with private reasoning that must never be exported."""
    at = f'2026-10-05T12:{n:02d}:00Z'
    messages = [Message(f'r{n}', REPLY, 'Completed orchard work.' if not long else 'Detailed orchard work. ' * 100, at)]
    if long:
        messages = [Message(f'secret{n}', 'reasoning', 'PRIVATE_FIXTURE_REASONING'),
                    Message(f'call{n}a', TOOL_CALL, at=at, tool='shell', tool_input={'command': 'test'}, call_id='one'),
                    Message(f'result{n}a', TOOL_RESULT, 'Tests pass', at, call_id='one'),
                    Message(f'call{n}b', TOOL_CALL, at=at, tool='write', tool_input={'path': 'orchard.py'}, call_id='two'),
                    Message(f'result{n}b', TOOL_RESULT, 'Updated', at, call_id='two'), *messages]
    return Turn(Message(f'p{n}', PROMPT, text or f'Orchard task {n}', at), tuple(messages))


class VirtualTranscripts:
    """Stable visible paths backed by real private immutable temporary files.

    The virtual name is supplied to BriefService before artifact composition.
    Verification still uses FolderTranscripts' real ownership/content checks.
    """
    def __init__(self, root):
        self.backing = FolderTranscripts(root / 'transcripts')
        self.paths = {}

    def save(self, link_id, text):
        """Persist the real snapshot and return its stable presentation identity."""
        real = self.backing.save(link_id, text)
        virtual = '/baton-fixtures/transcripts/' + Path(real).name
        self.paths[virtual] = real
        return virtual

    def verify(self, path, digest):
        """Verify exactly the snapshot that the approved virtual path names."""
        self.backing.verify(self.paths[path], digest)


@contextmanager
def fixed_ids(seed):
    """Install a deterministic scoped UUID supplier before any state is built."""
    values = count(1)
    def ident():
        value = sha256(f'{seed}:{next(values)}'.encode()).hexdigest()[:32]
        return UUID(hex=value)
    with patch('baton.adapters.fake.tool.uuid4', side_effect=ident), patch('baton.services.brief.uuid4', side_effect=ident):
        yield


class World:
    """One temporary engine with four explicitly injected capability profiles."""
    def __init__(self, root):
        self.root = Path(root)
        self.clock = FixedClock(NOW)
        self.adapters = {tool: FakeAdapter(facts, tool) for tool, facts in FACTS.items()}
        for adapter in self.adapters.values():
            adapter.hooks.ready = True
            adapter.runner.text = 'Preserve the orchard decisions and finish the tests.'
        self.engine = build(self.root, clock=self.clock, adapters=self.adapters,
                            installation_probe=lambda tool: tool in self.adapters)
        self.lock = self.engine.command_lock()
        self.lock.__enter__()
        self.store = self.engine.store
        # Stable identity anchors are recipe input, never output normalization.
        # They represent old removed private records and are not visible links.
        self.store.db.execute("insert into links(id,mode,created_at,removed_at) values(2,'full_copy',?,?)", (NOW, NOW))
        self.store.db.execute("insert into turns(id,link_id,seq,origin,origin_id) values(40,2,1,'claude','archived')")
        self.store.db.commit()
        self.link = None
        self.chats = {}
        self.effect_proofs = []
        self.transcripts = VirtualTranscripts(self.root)
        self.briefs = BriefService(self.store, self.adapters, self.clock, self.transcripts, label)
        self.engine.__dict__['briefs'] = self.briefs

    def close(self):
        """Release the command lock and private ledger."""
        self.lock.__exit__(None, None, None)
        self.engine.close()

    def chat(self, tool, ident, turns=(), name='Imaginary orchard'):
        """Seed a named stable chat identity before any service observes it."""
        adapter = self.adapters[tool]
        generated = adapter.build_chat(turns, name, FOLDER)
        for collection in (adapter.chats, adapter.refs, adapter.conditions, adapter.inserted_text, adapter.visible):
            collection[ident] = collection.pop(generated)
        adapter.refs[ident] = replace(adapter.refs[ident], id=ident)
        self.store.remember_chat(tool, ident, asdict(adapter.refs[ident]))
        return ident

    def pair(self, sides=('claude', 'codex'), mode='full_copy', shared=2, prefix='sample'):
        """Create one link and genuinely align the explicitly shared native turns."""
        self.chats = {side: self.chat(side, ('sample-a' if side == sides[0] else 'sample-b') if prefix == 'sample'
                                     else f'{prefix}-{side}', [original(i) for i in range(1, shared + 1)]) for side in sides}
        plan = self.engine.linker.plan_link(sides[0], self.chats[sides[0]], sides[1], self.chats[sides[1]], mode)
        result = self.engine.linker.apply(plan, plan.plan_id)
        assert result.applied, result
        self.link = self.store.get_link(result.link_id)
        for tool, chat in self.chats.items():
            self.adapters[tool].usage_values[chat] = Usage(8000, 200000, False, None)
        assert self.link.id == 3 or prefix.startswith('d3-'), self.link
        if shared >= 2:
            self.store.set_pinned(self.link.id, self.store.turns(self.link.id)[1].id, True)
        return self.link

    def seed(self, side, turns):
        """Append completed native work and record it through the ordinary refresh."""
        adapter = self.adapters[side]
        adapter.chats[self.chats[side]].extend(deepcopy(turns))
        adapter.visible[self.chats[side]] = deepcopy(adapter.chats[self.chats[side]])
        if turns:
            adapter.refs[self.chats[side]] = replace(adapter.refs[self.chats[side]], updated_at=turns[-1].ended_at)
        self.engine.applier.refresh(self.link.id)
        return [row.id for row in self.store.turns(self.link.id) if row.origin_id in {t.id for t in turns}]

    def condition(self, tool, **kwargs):
        """Set capability observations that the real planner then consumes."""
        self.adapters[tool].set_condition(self.chats[tool], **kwargs)

    def sync(self):
        """Apply a genuine plan and assert its durable/physical delivery result."""
        plan = self.engine.applier.preview(self.link.id)
        before = deepcopy({s: a.chats for s, a in self.adapters.items()})
        result = self.engine.applier.apply(plan)
        assert result.applied, result
        for step in plan.steps:
            if step.action == 'add':
                assert len(self.adapters[step.side].reader.read(self.chats[step.side])) > len(before[step.side][self.chats[step.side]])
            elif step.action in ('hold', 'attach'):
                assert self.adapters[step.side].chats == before[step.side]
        self.effect_proofs.append((plan, result))
        return result

    def status_recipe(self, state):
        """Build S1–S12 and ancillary states by actual actions and observations."""
        if state.startswith('d7_'):
            return self.handoff(state)
        if state.startswith('d3_'):
            self.window(state)
            selected = int(state.rsplit('_', 1)[1]) if state.rsplit('_', 1)[-1].isdigit() else 3
            self.link = self.store.get_link(selected)
            self.chats = dict(self.link.chats)
            return
        name = state.removeprefix('d4_')
        if name == 'sample': name = 's1'
        if name in ('s5', 's6'):
            self.pair(mode='attached_history', shared=0)
            ids = self.seed('claude', [original(i) for i in range(1, 13)])
            if name == 's6':
                self.engine.applier.record_attached(3, 'codex', ids, 'first-private-hook-message')
                assert not self.adapters['codex'].reader.read(self.chats['codex'])
            return
        if name == 's10':
            self.pair(shared=0)
            self.seed('codex', [original(i) for i in range(1, 5)])
            planned = self.engine.linker.plan_full_copy(3, 'claude')
            result = self.engine.linker.apply(planned, planned.plan_id)
            assert result.applied
            self.link = self.store.get_link(3)
            self.chats = dict(self.link.chats)
            return
        self.pair(shared=3 if name in ('s4b', 's7', 's8', 's9') else 2)
        if name in ('s4', 's4b', 's8', 's11'):
            self.seed('claude', [original(4)] if name in ('s4b', 's8') else [original(3), original(4)])
            if name in ('s4b', 's8'):
                self.condition('codex', open=True, app_running=True, hooks_ready=name != 's8')
                self.adapters['codex'].hooks.ready = name != 's8'
            else:
                self.sync()
            if name == 's11':
                self.adapters['codex'].writer.rename(self.chats['codex'], 'Renamed orchard tests')
            return
        if name == 's12':
            self.seed('claude', [original(3), original(4, long=True)])
            self.sync()
            self.condition('codex', app_started_at=LATER)
            return
        if name == 's7':
            self.seed('claude', [original(4)])
            self.seed('codex', [original(5)])
            plan = self.engine.applier.preview(3)
            assert plan.decision_needed and all(s.action == 'hold' for s in plan.steps)
            return
        if name == 's9':
            self.seed('codex', [original(4)])
            self.sync()
            # The appended copy was bypassed, then completed native destination
            # work arrived. S7 holds both directions until an explicit merge.
            self.adapters['claude'].chats[self.chats['claude']].pop()
            self.adapters['claude'].visible[self.chats['claude']] = deepcopy(self.adapters['claude'].chats[self.chats['claude']])
            self.engine.applier.refresh(3)
            self.seed('claude', [original(5)])
            plan = self.engine.applier.preview(3)
            assert plan.decision_needed and all(s.action == 'hold' for s in plan.steps)
            assert any(e.kind == 'not_confirmed' for e in self.store.history(3))
            return
        self.seed('codex', [original(3), original(4)])
        if name in ('s2', 's3'):
            if name == 's2':
                self.condition('claude', open=True, app_running=True)
                self.sync()
                ids = [r.id for r in self.store.turns(3) if r.origin == 'codex']
                self.engine.applier.record_attached(3, 'claude', ids, 'sent-message')
                assert len(self.adapters['claude'].reader.read(self.chats['claude'])) == 2
            else:
                self.sync()
                self.condition('claude', app_started_at=LATER)
                assert self.engine.applier.refresh(3)['status'].side('claude').chat_shows == 4
            return
        self.condition('claude', open=True, app_running=True)
        if name == 'paused': self.store.set_paused(3, True, NOW)
        if name == 'missing': self.condition('claude', exists=False)
        if name == 'hooks':
            self.adapters['claude'].facts = replace(CLAUDE_LIKE, hooks_need=CODEX_LIKE.hooks_need)
            self.adapters['claude'].hooks.ready = False
            self.condition('claude', hooks_ready=False)
        if name == 'unknown':
            self.condition('claude', open=False)
            self.adapters['claude'].set_format(False, 'future-99')

    def popover(self, state):
        """Eight D2 states driven by delivery, conditions or link absence."""
        name = state.removeprefix('d2_')
        if name == 'no_links': return
        for tool in ('claude', 'codex'):
            self.chat(tool, 'recent-' + tool, [original(9)], 'Recent orchard')
        if name == 'decision_needed': return self.status_recipe('d4_s7')
        self.pair()
        if name == 'in_sync': return
        self.seed('codex', [original(3), original(4)])
        if name == 'relaunch_needed': self.sync()
        if name in ('waiting', 'paused', 'setup_incomplete'): self.condition('claude', open=True, app_running=True)
        if name == 'paused': self.store.set_paused(3, True, NOW)
        if name == 'setup_incomplete':
            self.adapters['claude'].facts = replace(CLAUDE_LIKE, hooks_need=CODEX_LIKE.hooks_need)
            self.adapters['claude'].hooks.ready = False
            self.condition('claude', hooks_ready=False)

    def window(self, state):
        """D3 empty/filled/missing with per-link status and real suggestions."""
        if 'empty' in state: return
        if 'tool_missing' in state:
            del self.adapters['cursor']
            self.engine.adapters.pop('cursor')
            return
        for ident in (3, 4, 5):
            self.pair(shared=4 if ident == 5 else 2, prefix=f'd3-{ident}')
            if ident == 3:
                self.seed('claude', [original(3)])
                self.seed('codex', [original(4)])
            if ident == 4:
                self.seed('codex', [original(3), original(4)])
                self.sync()
        for tool in self.adapters:
            self.chat(tool, 'd3-unlinked-' + tool, [original(9)], 'Unlinked orchard')
        self.link = self.store.get_link(3)
        self.chats = dict(self.link.chats)

    def dialog(self, state):
        """D5 target profiles, existing link, disabled mode and large chat."""
        name = state.removeprefix('d5_').split('_')[0]
        self.source = 'codex' if name == 'claude' else 'claude'
        values = [original(i) for i in range(1, 5)]
        if name == 'large': values[0] = original(1, text='Large public request. ' * 30000)
        self.source_chat = self.chat(self.source, 'source', values, 'Imaginary orchard')
        for tool in self.adapters:
            if tool != self.source: self.chat(tool, tool + '-existing', (), 'Existing ' + label(tool))
        if name in ('already',) or '_replace_' in state:
            target = 'codex' if self.source != 'codex' else 'claude'
            plan = self.engine.linker.plan_link(self.source, self.source_chat, target, target + '-existing')
            result = self.engine.linker.apply(plan, plan.plan_id)
            assert result.applied
            self.link = self.store.get_link(result.link_id)
            self.chats = dict(self.link.chats)
        if name == 'unavailable': self.adapters['opencode'].set_format(False, 'future-99')
        self.dialog_name = name

    def handoff(self, state):
        """D7 real usage observations and brief runner readiness policies."""
        source = 'opencode' if 'limit_no_reset' in state else 'claude'
        self.pair((source, 'codex'), shared=2)
        self.seed(source, [original(3, text='Large public orchard request. ' * 22000), original(4)])
        self.adapters[source].usage_values[self.chats[source]] = Usage(164000, 200000, False, None)
        self.adapters['codex'].usage_values[self.chats['codex']] = Usage(26000, 200000, False, None)
        if 'no_size' in state:
            self.adapters[source].facts = replace(self.adapters[source].facts, context_size_known=False)
        if 'limit' in state or 'brief_fallback' in state:
            reset = '2026-10-09T15:00:00Z' if 'limit_reset' in state else None
            self.adapters[source].usage_values[self.chats[source]] = Usage(164000, 200000, True, reset)
        if 'brief_fallback' in state:
            self.adapters['codex'].runner.finding = SetupFinding('runner', False, 'setup.runner', {})
        self.limit_source = source
        if 'unlinked' in state:
            self.adapters[source].usage_values[self.chats[source]] = Usage(164000, 200000, True, '2026-10-09T15:00:00Z')
            self.store.remove_link(3, NOW)
            self.link = None

    def read(self, command, *, tool=None, link_id=None):
        """Execute the actual read command handler with fail-on-effect ports."""
        cmd = 'merge' if command == 'merge-show' else command.replace('-', ' ')
        args = SimpleNamespace(tool=tool or 'claude', folder=None, link=link_id or (self.link.id if self.link else 3), messages=True, show=True)
        with ExitStack() as guard:
            guard.enter_context(patch('baton.services.journal.Journal.recover', side_effect=AssertionError('read recovery')))
            for adapter in self.adapters.values():
                for owner, methods in ((adapter.writer, ('prepare', 'add', 'create', 'cut', 'place', 'rename', 'restore', 'take_back')),
                                       (adapter.app, ('open', 'close', 'release')), (adapter.runner, ('ask',)),
                                       (adapter.hooks, ('install', 'uninstall'))):
                    for method in methods:
                        guard.enter_context(patch.object(owner, method, side_effect=AssertionError('read effect')))
            return REGISTRY.get(cmd).run(Context(self.engine, cmd), args)


def presentation(value, world, screen=''):
    """Add catalogue-only view labels while preserving authoritative state."""
    if 'notes' not in value and not any(key in value for key in ('links', 'chats', 'suggestions', 'events')):
        return value
    notes = value.setdefault('notes', [])
    known = {(n['id'], json.dumps(n['values'], sort_keys=True)) for n in notes}
    def add(ident, values=None):
        rendered = output.note(ident, values)
        key = (ident, json.dumps(rendered['values'], sort_keys=True))
        if key not in known:
            notes.append(rendered); known.add(key)
    for ident, definition in CATALOGUE.items():
        prefixes = (('screen.', 'empty.', 'filter.', 'message.')
                    + (('handoff.',) if screen == 'setup' else ())
                    + (('quit.',) if screen in ('setup', 'startup') else ()))
        if ident.startswith(prefixes) and not definition.fields:
            add(ident)
    for tool in world.adapters:
        for ident in ('screen.continue', 'screen.all_chats'):
            add(ident, {'tool': tool})
    if 'turns' in value and 'sides' in value:
        turns = value['turns']
        for state in sorted({state for turn in turns for state in turn['states'].values()}):
            add('turn.' + state)
        for tool, side in value['sides'].items():
            if side['synced_up_to']:
                add('status.reached', {'tool': tool, 'turn': side['synced_up_to']['id']})
                add('screen.received_one', {'tool': tool})
                add('screen.received_hidden_tool', {'tool': tool, 'seq': side['synced_up_to']['seq']})
        prefix = 0
        for turn in turns:
            if not all(turn['states'].get(tool) in CHAT_SHOWS for tool in value['sides']): break
            prefix += 1
        fold = max(0, prefix - 1) if prefix == len(turns) else prefix
        add('screen.earlier_turns', {'n': fold})
        for turn in turns:
            activity = [m for m in turn.get('messages', ()) if m['kind'] == TOOL_CALL]
            if activity: add('screen.tool_calls', {'n': len(activity), 'turn_id': turn['id']})
    return value


def delivery_plan(world, prepared, confirmation='plan.confirm_sync'):
    """Serialize service-chosen steps with their actual status notes."""
    fresh = world.engine.reads.status(prepared.link_id, True) if prepared.link_id else None
    steps = []
    for step in prepared.steps:
        notes = output.note_list(fresh['side_notes'][step.side]) if fresh else []
        facts = world.adapters[step.side].facts
        if 'app_closed' in step.needs:
            notes.append(output.note('write.app_must_close', {'tool': step.side, 'n': len(step.turn_ids)}))
        if facts == OPENCODE_LIKE and step.action == 'add':
            notes.append(output.note('write.any_time', {'n': len(step.turn_ids)}))
        steps.append(output.step(step.side, step.action, step.turn_ids, reason=step.reason, needs=step.needs, notes=notes))
    return output.plan(prepared.plan_id, prepared.link_id, steps, decision_needed=prepared.decision_needed,
                       notes=output.note_list(('merge.decision_needed',)) if prepared.decision_needed else [],
                       confirmation=output.note('plan.unavailable' if prepared.decision_needed else confirmation))


def brief_plan(plan):
    """Serialize exactly the immutable service cost or creation review."""
    notes = output.note_list(plan.notes)
    if plan.writer == 'offline' and plan.stage == 'create' and not any(n['id'] == 'brief.used_offline' for n in notes):
        notes.append(output.note('brief.used_offline'))
    return output.plan(plan.plan_id, plan.link_id,
                       [output.step(s.side, s.action, s.turn_ids, needs=s.needs) for s in plan.steps],
                       notes=notes, stage=plan.stage, brief=plan.as_contract(),
                       confirmation=output.note(*plan.confirmation))


def link_plan(world, plan, command):
    """Project a genuine Linker plan without turning refused policy into success."""
    if isinstance(plan, BriefPlan): return brief_plan(plan)
    n = len(plan.turns) if plan.turns else len(plan.observations[plan.source].get('turns', ()))
    notes = []
    if plan.action == 'unlink':
        source, target = plan.source, plan.target
        ref_a = plan.observations[source].get('ref', {})
        ref_b = plan.observations[target].get('ref', {})
        status = world.engine.applier.refresh(plan.old_link_id)['status']
        for side in status.sides:
            n = status.side(side).waiting
            if n or not notes:
                notes.append(output.note('link.remove', {'name': ref_a.get('name', ''), 'other_name': ref_b.get('name', ''), 'n': n, 'tool': side}))
        if any(status.side(side).waiting for side in status.sides):
            notes = [note for note in notes if note['values']['n']]
        confirmation = output.note('plan.confirm_unlink')
        steps = []
    else:
        target = plan.target
        if plan.mode == 'attached_history':
            notes.append(output.note('link.attached_history', {'n': n}))
        elif command == 'copy':
            notes.append(output.note('link.copy', {'tool': target, 'n': n}))
        else: notes.append(output.note('link.full_copy', {'tool': target}))
        created = plan.action in ('create', 'full_copy')
        if created:
            notes.append(output.note('new_chat.relaunch' if 'relaunch_to_see' in plan.needs else 'new_chat.at_once', {'tool': target}))
        if 'app_closed' in plan.needs:
            notes.append(output.note('write.app_must_close', {'tool': target, 'n': n}))
        confirmation = output.note('plan.confirm_copy' if command == 'copy' else 'plan.confirm_link')
        if plan.old_link_id:
            old = world.store.get_link(plan.old_link_id)
            other = old.others(plan.source)[0]
            notes.append(output.note('link.change', {'name': plan.observations[plan.source]['ref']['name'],
                            'new_name': plan.observations[target].get('ref', {}).get('name', label(target)),
                            'other_name': world.adapters[other].locator.name(old.chat(other))}))
        size = sum(len(t.prompt.text) + sum(len(m.text) for m in t.messages) for t in plan.turns) // 4
        if size >= 150000: notes.append(output.note('link.large_copy', {'tokens': str(size)}))
        steps = [output.step(target, 'create' if created else 'attach' if plan.mode == 'attached_history' else 'add',
                             plan.turn_ids, needs=plan.needs, notes=notes)]
    return output.plan(plan.plan_id, plan.old_link_id, steps, notes=notes, confirmation=confirmation)


def unavailable_plan(ident, link_id=None, *, steps=(), notes=(), **extra):
    """Explicit contract preview of an unavailable future executable command."""
    return output.plan('p_future_' + ident, link_id, steps, notes=[*notes, output.note('plan.unavailable')],
                       confirmation=output.note('plan.unavailable'), execution='unavailable', **extra)


def setup_state(world, state):
    """Construct the state family before requesting the authoritative setup read."""
    if state.startswith('d3_'): world.window(state)
    elif state.startswith('d5_'): world.dialog(state)
    result = world.read('setup')
    result.setdefault('notes', []).extend(output.note_list(('plan.unavailable', 'plan.choose_counterpart')))
    return presentation(result, world, 'setup')


def generate_one(item: Fixture, root):
    """Build one route from its declared recipe and service/provider authority."""
    with fixed_ids(item.filename):
        world = World(root)
        try:
            value = provider(item, world)
            audit_notes(value)
            # All future command samples carry machine-readable non-execution.
            if item.provider == 'future_contract':
                value['fixture_provider'] = 'future_contract'
                value['execution'] = 'unavailable'
                if 'applied' in value: assert value['applied'] is False
                if 'opened' in value: assert value['opened'] in (False, 'unavailable')
            return value
        except Exception as failure:
            failure.add_note(item.filename)
            raise
        finally:
            world.close()


def provider(item, world):
    """Route explicit recipes; never consume a historical fixture as input."""
    command, state = item.command, item.state
    requested_tool = None
    if command == 'chats' and state.count('_') >= 2 and state.rsplit('_', 1)[-1] in FACTS:
        state, requested_tool = state.rsplit('_', 1)
    if state.startswith('dfix_'): return relaunch_review_provider(item, world)
    if state.startswith(('d10_', 'd11_')): return opinion_setup_provider(item, world)
    if state.startswith('d8_'): return merge_screen_provider(item, world)
    if state.startswith('d9_'): return history_screen_provider(item, world)
    if command == 'setup': return setup_state(world, state)
    if command in ('links', 'suggestions', 'chats', 'history', 'status'):
        if state.startswith('d2_'): world.popover(state)
        elif state.startswith('d3_'): world.window(state)
        elif state.startswith('d5_'): world.dialog(state)
        elif state.startswith('d7_'): world.handoff(state)
        elif command == 'status': world.status_recipe(state)
        elif state not in ('empty',): world.status_recipe('d4_s1')
        if command == 'history' and world.link is None:
            # Empty activity is a projection of an actually empty record list.
            result = world.read('history', link_id=2)
        else:
            scoped_id = int(state.rsplit('_', 1)[1]) if command == 'status' and state.startswith('d3_filled_') else None
            if command == 'chats' and requested_tool and requested_tool not in world.adapters:
                try:
                    world.read(command, tool=requested_tool)
                except NotAvailable as failure:
                    return output.error(failure, {'tool': requested_tool})
                raise AssertionError('missing tool read must refuse')
            result = world.read(command, tool=requested_tool or getattr(world, 'source', None), link_id=scoped_id)
            if command == 'status' and state.startswith('d7_'):
                offer = world.briefs.offer(3, 'codex')
                if offer: result['notes'].append(output.note(*offer))
                return result
        return presentation(result, world, 'startup' if command == 'links' and state == 'sample' else state)
    if command == 'settings-get': return world.read(command)
    if command == 'merge-show':
        world.pair(shared=0 if state == 'no-shared' else 2)
        world.seed('claude', [original(3)])
        world.seed('codex', [original(4)])
        for tool in world.chats: world.adapters[tool].changed_files['p3' if tool == 'claude' else 'p4'] = ['orchard.py']
        return world.read(command)
    if command in ('link', 'copy', 'relink'):
        return dialog_provider(item, world)
    if command == 'brief':
        world.handoff(state)
        writer = 'offline' if state == 'd7_offline' else None
        plan = world.briefs.plan(3, 'codex', writer=writer)
        assert not any(a.runner.calls for a in world.adapters.values())
        generated = state.endswith('_generated') or 'brief_fallback' in state
        if generated and plan.stage == 'generate':
            before = deepcopy({s: a.chats for s, a in world.adapters.items()})
            plan = world.briefs.confirm(plan)
            assert before == {s: a.chats for s, a in world.adapters.items()}
            assert plan.stage == 'create' and plan.artifact_id and plan.text
        return brief_plan(plan)
    if command == 'sync':
        if state.startswith('d6_'):
            target = state.removeprefix('d6_').split('_')[0]
            source = 'codex' if target != 'codex' else 'claude'
            world.pair((target, source), shared=2)
            world.seed(source, [original(3), original(4)])
            world.condition(target, open=True, app_running=True, replying='replying' in state)
        else: world.status_recipe('d4_s1')
        plan = world.engine.applier.preview(3)
        result = delivery_plan(world, plan)
        return result
    if command == 'unlink':
        world.status_recipe('d4_s1')
        return link_plan(world, world.engine.linker.plan_unlink(3), command)
    if command == 'merge':
        world.status_recipe('d4_s7')
        planned = world.engine.merger.plan(3, preset='dont_reorder')
        return delivery_plan(world, planned.delivery)
    if command in ('undo', 'restore'): return undo_provider(item, world)
    if command == 'notify':
        world.handoff(state)
        offers = LimitOffers(world.store, {t: a.reader for t, a in world.adapters.items()}, world.clock, MemoryOffers())
        offer = offers.check(world.limit_source, world.chats[world.limit_source], to='codex')
        return {'synced': [], 'queued': [], 'offers': [output.note(*offer.note)] if offer else []}
    if command == 'continue':
        if state.startswith('d2_'): world.popover(state)
        elif state.startswith('d7_'): world.handoff(state)
        else: world.status_recipe('d4_s1')
        steps, notes = [], []
        if world.link:
            prepared = world.engine.applier.preview(3)
            projected = delivery_plan(world, prepared)
            steps, notes = projected['steps'], projected['notes']
        return unavailable_plan(state, world.link.id if world.link else None, steps=steps, notes=notes, opened=False)
    if command == 'relaunch':
        if state == 'd6_cursor_running':
            world.pair(('cursor', 'codex'), shared=2)
            world.seed('codex', [original(3), original(4)])
            world.condition('cursor', app_running=True, open=True)
            closure = [output.note('write.app_must_close', {'tool': 'cursor', 'n': 2})]
            pending = next(step.turn_ids for step in world.engine.applier.preview(3).steps if step.side == 'cursor')
            return unavailable_plan(state, 3, notes=closure,
                steps=[output.step('cursor', 'close', (), notes=closure),
                       output.step('cursor', 'add', pending, needs=('app_closed',)),
                       output.step('cursor', 'reopen', ())],
                replying=[output.chat_from_ref(tool, world.adapters[tool].refs[chat])
                          for tool, chat in world.chats.items() if world.adapters[tool].state.condition(chat).replying])
        world.status_recipe('d4_s1')
        replying = 'replying' in state or 'when_idle' in state
        if replying: world.condition('claude', replying=True)
        notes = [output.note('relaunch.replying', {'tool': 'claude', 'title': 'Imaginary orchard'})] if replying else [output.note('new_chat.relaunch', {'tool': 'claude'})]
        return unavailable_plan(state, 3, notes=notes, replying=[output.chat_from_ref('claude', world.adapters['claude'].refs[world.chats['claude']])] if replying else [])
    if command in ('ask', 'ask-add', 'open', 'catch-up', 'setup-install', 'settings-set', 'rename', 'pause', 'resume', 'keep', 'send', 'pin', 'unpin'):
        return future_provider(item, world)
    return model_provider(item, world)


def dialog_provider(item, world):
    """D5 requests carry explicit targets, modes and retained-side identities."""
    state, command = item.state, item.command
    if state == 'service_full_copy_applied':
        state, target = 'd5_claude_claude', 'claude'
    elif state.startswith('d6_new_chat_'):
        target = state.removeprefix('d6_new_chat_')
        state = ('d5_claude_' if target == 'claude' else 'd5_opencode_') + target
    elif state.startswith('d5_'):
        name = state.removeprefix('d5_').split('_')[0]
        target = (state.split('_replace_')[1] if '_replace_' in state else
                  next((t for t in FACTS if state.startswith('d5_' + name + '_' + t)), D5_TARGETS[name][0]))
    else:
        state = 'd5_opencode_codex'; target = 'codex'
    world.dialog(state)
    mode = 'attached_history' if 'attached_history' in state else 'brief' if state.endswith('_brief') else 'full_copy'
    source, chat = world.source, world.source_chat
    try:
        if command == 'copy': planned = world.engine.linker.plan_copy(source, chat, target)
        elif '_replace_' in state:
            planned = world.engine.linker.plan_full_copy(world.link.id, target)
        elif command == 'relink':
            if world.link is None:
                old_target = next(t for t in world.adapters if t != source and t != target)
                base = world.engine.linker.plan_link(source, chat, old_target, old_target + '-existing')
                changed = world.engine.linker.apply(base, base.plan_id)
                assert changed.applied
                world.link = world.store.get_link(changed.link_id)
                world.chats = dict(world.link.chats)
            planned = world.engine.linker.plan_relink(world.link.id, target,
                target + '-existing' if mode == 'attached_history' else None, from_side=source, mode=mode)
        elif world.link:
            try:
                world.engine.linker.plan_link(source, chat, target,
                    target + '-existing' if mode == 'attached_history' else None, mode)
            except AlreadyLinked as failure:
                refused = world.engine.linker.already_linked_note(failure)
                return unavailable_plan(state, world.link.id, notes=[output.note(refused['id'], refused['values'])])
            raise AssertionError('already-linked service must refuse')
        else:
            planned = world.engine.linker.plan_link(source, chat, target,
                target + '-existing' if mode == 'attached_history' else None, mode)
    except NotAvailable as failure:
        # Explicitly refused recipe inputs; never override the safety decision.
        return unavailable_plan(state, world.link.id if world.link else None,
                                notes=[output.note('format.unknown_version', {'tool': target, 'version': world.adapters[target].format.version})]
                                if not world.adapters[target].format.known else [], refusal_kind=output.snake_case(type(failure).__name__))
    result = link_plan(world, planned, command)
    if item.state.endswith('_applied'):
        before_source = deepcopy(world.adapters[source].chats[chat])
        before_target = set(world.adapters[target].chats)
        receipt = world.engine.linker.apply(planned, planned.plan_id)
        assert receipt.applied and receipt.chat_id not in before_target
        assert world.adapters[source].chats[chat] == before_source
        assert world.store.get_link(receipt.link_id).chat(target) == receipt.chat_id
        native = world.adapters[target].reader.read(receipt.chat_id)
        assert [(t.prompt.text, t.reply_text) for t in native] == [(t.prompt.text, t.reply_text) for t in planned.turns]
        result.update(applied=receipt.applied, link_id=receipt.link_id, chat_id=receipt.chat_id)
    return result


def merge_screen_provider(item, world):
    """Execute real command routes for the D8 choice and refusal scenarios."""
    world.pair(shared=1)
    state = item.state.removesuffix('_applied')
    times = {'d8_u2': (2, 3, 4), 'd8_u5': (2, 3, 4), 'd8_u4': (3, 4, 2)}.get(state, (2, 4, 3))
    first, second, other = times
    world.seed('claude', [original(first), original(second)])
    other_turn = original(other)
    if state == 'd8_u7':
        other_turn = replace(other_turn, messages=(replace(other_turn.messages[0], at='2026-10-05T12:05:00Z'),))
    world.seed('codex', [other_turn])
    if state == 'd8_u7':
        world.adapters['claude'].changed_files['p' + str(second)] = ['orchard.py']
        world.adapters['codex'].changed_files['p' + str(other)] = ['orchard.py']
        world.store.save_setting('merge', 'by_time')
    if state == 'd8_large': world.store.save_setting('brief_threshold_tokens', 1)
    if state == 'd8_u5': world.condition('claude', open=True, app_running=True)
    preset = 'dont_reorder' if state == 'd8_u6' else 'by_time'
    args = SimpleNamespace(link=3, show=item.command == 'merge-show', preset=preset,
                           order=None, keep=None, split=False, first=None)
    if state == 'd8_u3':
        ids = [t.id for t in world.store.turns(3) if t.seq > 1]
        args.preset = None; args.order = ','.join(map(str, [ids[1], ids[0], ids[2]]))
    if state == 'd8_u8' and item.command == 'merge': args.preset = None; args.keep = 'claude'
    if state == 'd8_split' and item.command == 'merge': args.preset = None; args.split = True
    try:
        result = REGISTRY.get('merge').run(Context(world.engine, 'merge', dry_run=True), args)
        if item.state.endswith('_applied'):
            result = REGISTRY.get('merge').run(Context(world.engine, 'merge', confirm=result['plan_id']), args)
            assert result['applied']
        return result
    except BatonError as error:
        return output.error(error)


def history_screen_provider(item, world):
    """History reads and undo boundaries built solely in isolated fake chats."""
    if item.command == 'history' and item.state in ('d9_all_kinds', 'd9_empty', 'd9_error'):
        if item.state == 'd9_empty': return world.read('history', link_id=2)
        if item.state == 'd9_error':
            try: return world.read('history', link_id=999)
            except BatonError as error: return output.error(error)
            except KeyError: return output.error(NotAvailable())
        world.pair(shared=1)
        # Historical input records exercise every serializer kind, including
        # unknown future bookkeeping. They are not evidence of action execution.
        kinds = ('add', 'attached', 'create', 'merge', 'undo', 'restore', 'paused',
                 'resumed', 'unlinked', 'moved', 'brief', 'attach_pending',
                 'not_confirmed', 'undo_shown', 'future_kind')
        for kind in kinds:
            world.store.record_event(3, kind, 'claude', NOW, (world.store.turns(3)[0].id,) if kind in ('add', 'attached', 'attach_pending', 'not_confirmed') else (), {'fixture_history_input': True})
        return world.read('history')
    state = item.state.removesuffix('_applied')
    action = ('restore' if state in ('d9_t9', 'd9_t10c') else 'undo') if item.command == 'history' else item.command
    if state == 'd9_u9':
        world.pair(shared=1)
        world.seed('claude', [original(2), original(4)]); world.seed('codex', [original(3)])
        args = SimpleNamespace(link=3, show=False, preset='by_time', order=None, keep=None, split=False)
        preview = REGISTRY.get('merge').run(Context(world.engine, 'merge', dry_run=True), args)
        applied = REGISTRY.get('merge').run(Context(world.engine, 'merge', confirm=preview['plan_id']), args)
        return REGISTRY.get('undo').run(Context(world.engine, 'undo', dry_run=True), SimpleNamespace(link=3, event=applied['event_id']))
    target = 'codex' if state.endswith('shorter') or state in ('d9_t8', 'd9_t9') else 'claude'
    source = 'claude' if target == 'codex' else 'codex'
    world.pair((target, source), shared=0)
    world.seed(source, [original(1)])
    world.sync()
    world.seed(source, [original(2)])
    world.sync()
    event = next(e for e in world.store.history(3) if e.kind == 'add' and e.side == target)
    world.seed(source, [original(3)])
    world.sync()
    if not (state.endswith('attached') or state == 'd9_t11'): world.seed(target, [original(4), original(5)])
    if state.endswith('attached') or state == 'd9_t11':
        ids = world.seed(source, [original(6)])
        world.condition(target, open=True, app_running=True)
        world.sync()
        # Record the actual prompt-hook receipt against the native message that
        # received it, just as the existing S2 fixture does.
        world.engine.applier.record_attached(3, target, ids, 'attached-message')
        world.seed(target, [Turn(Message('attached-message', PROMPT, 'Continue the orchard work', NOW),
                                (Message('attached-reply', REPLY, 'Finished', NOW),))])
        world.condition(target, open=False, app_running=False)
        event = next(e for e in world.store.history(3) if e.kind == 'attached' and e.side == target)
    if state in ('d9_cut', 'd9_t10', 'd9_t10c'):
        world.condition(target, open=True, app_running=True)
    if state.endswith('replying') or state == 'd9_t10b':
        world.condition(target, replying=True, open=True, app_running=True)
    if action == 'restore':
        before_source = deepcopy(world.adapters[source].chats)
        earlier = world.chats[target]
        before_target = deepcopy(world.adapters[target].chats[earlier])
        args = SimpleNamespace(link=3, event=event.id)
        preview = REGISTRY.get('undo').run(Context(world.engine, 'undo', dry_run=True), args)
        receipt_value = REGISTRY.get('undo').run(Context(world.engine, 'undo', confirm=preview['plan_id']), args)
        receipt = SimpleNamespace(applied=receipt_value['applied'], event_id=receipt_value['event_id'])
        assert receipt.applied and world.store.get_link(3).paused
        if target == 'claude': assert ('release', earlier) in world.adapters[target].app.calls
        current = world.store.get_link(3).chat(target)
        assert len(world.adapters[target].reader.read(current)) == 1
        assert world.adapters[source].chats == before_source
        if not world.adapters[target].facts.can_cut:
            assert current != earlier and world.adapters[target].chats[earlier] == before_target

    args = SimpleNamespace(link=3, event=event.id)
    if action == 'restore':
        args.event = receipt.event_id
    result = REGISTRY.get(action).run(Context(world.engine, action, dry_run=True), args)
    if item.state.endswith('_applied') or item.command == 'history':
        result = REGISTRY.get(action).run(Context(world.engine, action, confirm=result['plan_id']), args)
        assert result['applied']
    return world.read('history') if item.command == 'history' else result


def undo_provider(item, world):
    """Use real delivery history to prepare undo and restore previews."""
    target = item.state.removeprefix('d6_') if item.state.startswith('d6_') and item.state != 'd6_replying' else 'claude'
    source = 'claude' if target == 'codex' else 'codex'
    world.pair((target, source), shared=0)
    world.seed(source, [original(1), original(2)])
    world.sync()
    if item.state == 'd6_replying': world.condition(target, replying=True, open=True, app_running=True)
    event = next(e for e in world.store.history(3) if e.kind == 'add' and e.side == target)
    plan = world.engine.undo.plan(3, event.id)
    if item.command == 'restore':
        receipt = world.engine.undo.apply(plan)
        assert receipt.applied
        plan = world.engine.undo.restore(3, receipt.event_id)
    steps = [output.step(s.side, s.action, s.turn_ids, needs=s.needs) for s in plan.steps]
    notes = []
    for ident in plan.notes:
        definition = CATALOGUE[ident]
        values = {'tool': plan.steps[0].side if plan.steps else 'claude', 'n': len(plan.removes), 'days': 30}
        notes.append(output.note(ident, {k: values[k] for k in definition.fields}))
    removes = []
    rows = {r.id: r for r in world.store.turns(3)}
    for item_remove in plan.removes:
        removed = LedgerTurn(**item_remove['turn'])
        removes.append({'turn': output.turn(removed), 'only_here': bool(item_remove['only_here'])})
    return output.plan(plan.plan_id, 3, steps, notes=notes, removes=removes, ends_at=None)


def future_provider(item, world):
    """Future contract shapes show non-execution rather than fake applied results."""
    cmd = item.command
    if cmd == 'ask': return {'answer_id': '', 'answer': '', 'tokens': 0, 'seconds': 0, 'notes': [output.note('plan.unavailable')]}
    if cmd == 'open': return {'opened': 'unavailable', 'note': output.note('plan.unavailable')}
    if cmd == 'catch-up': return {'output': '', 'notes': [output.note('plan.unavailable')]}
    if cmd == 'setup-install':
        if item.state == 'd6_missing_hooks':
            world.adapters['codex'].hooks.ready = False
        result = world.read('setup')
        if item.state == 'd6_missing_hooks':
            result['notes'].append(output.note('setup.missing', {
                'missing': output.note('setup.hooks', {'tool': 'codex'})['text'],
                'effect': output.note('plan.unavailable')['text'],
                'fix': output.note('screen.setup')['text']}))
        return result
    if cmd == 'settings-set': return world.read('settings-get')
    world.status_recipe('d4_s1')
    if cmd in ('pause', 'resume'): return {'link_id': 3, 'paused': False, 'notes': [output.note('plan.unavailable')]}
    if cmd in ('keep', 'send', 'pin', 'unpin'): return {'turn': output.turn(world.store.turns(3)[0]), 'notes': [output.note('plan.unavailable')]}
    return unavailable_plan(cmd, 3)


def model_provider(item, world):
    """Shared model samples are extracted from service outputs/serializers."""
    command, state = item.command, item.state
    if command == 'chat' and state.startswith('d5_'):
        world.dialog(state)
        return output.read_chat(next(row for row in world.engine.reads.chats(world.source) if row['ref'].id == world.source_chat))
    if command == 'note': return output.note('nothing_unusual' if state == 'minimal' else 'new_chat.relaunch', {} if state == 'minimal' else {'tool': 'claude'})
    if command == 'note-button': return output.note('new_chat.relaunch', {'tool': 'claude'})['buttons'][0]
    if command in ('usage', 'usage-limit'):
        usage = output.side_usage(Usage(164000, None if state == 'unknown' else 200000,
                                      state in ('limited', 'sample') and command == 'usage-limit' or state == 'limited', '2026-10-05T18:00:00Z'))
        return usage['limit'] if command == 'usage-limit' else usage
    if command == 'settings': return world.read('settings-get')['settings']
    if command in ('setup-tool', 'setup-finding'):
        value = world.read('setup')['tools'][0]
        return value['findings'][0] if command == 'setup-finding' else value
    if command == 'brief-details':
        world.handoff('d7_context_size')
        return world.briefs.plan(3, 'codex', writer='offline').as_contract()
    if command == 'same-file':
        world.status_recipe('d4_s7')
        for side in world.chats:
            for turn in world.adapters[side].chats[world.chats[side]]: world.adapters[side].changed_files[turn.id] = ['orchard.py']
        return world.read('merge-show')['same_files'][0]
    if command == 'suggestion':
        for tool in ('claude', 'codex'): world.chat(tool, tool + '-match', [original(1)])
        return world.read('suggestions')['suggestions'][0]
    world.status_recipe('d4_s1')
    status = world.read('status')
    side = status['sides']['claude']
    if command == 'chat': return side['chat']
    if command == 'link-summary': return world.read('links')['links'][0]
    if command == 'side':
        if state == 'empty':
            # Empty shared shape is a serializer projection of computed empty status.
            from baton.services.status import link_status
            value = link_status(replace(world.link, paused=False), [], {s: a.state.condition(world.chats[s]) for s, a in world.adapters.items() if s in world.chats}, facts={s: world.adapters[s].facts for s in world.chats})
            return output.side(value.side('claude'), chat_info=side['chat'], condition=world.adapters['claude'].state.condition(world.chats['claude']), usage=output.side_usage(Usage(0, None, False, None)))
        return side
    if command == 'side-condition': return side['condition']
    if command == 'turn':
        value = status['turns'][0]
        if state == 'without-messages': value = output.turn(world.store.turns(3)[0])
        return value
    if command == 'turn-message': return status['turns'][0]['messages'][0]
    if command == 'next-message': return side['next_message']
    if command == 'since-you-left': return side['since_you_left']
    if command == 'history-event': return world.read('history')['events'][0]
    if command == 'removed-turn': return {'turn': status['turns'][0], 'only_here': True}
    prepared = world.engine.applier.preview(3)
    if command == 'step': return delivery_plan(world, prepared)['steps'][0]
    if command == 'plan':
        # Frozen model projection intentionally excludes additive confirmation.
        value = delivery_plan(world, prepared)
        return {key: value[key] for key in ('plan_id', 'applied', 'link_id', 'steps', 'decision_needed', 'notes')} | ({'link_id': None} if state == 'unlinked' else {})
    raise AssertionError((command, state))


def audit_notes(value):
    """Require recursively exact catalogue ids, filled values and all rendering."""
    if isinstance(value, dict):
        if value.get('id') in CATALOGUE or ('tone' in value and 'values' in value) or isinstance(value.get('id'), str) and ('tone' in value or 'values' in value):
            assert set(value) == {'id', 'tone', 'values', 'text', 'buttons', 'status_line'}, value
            ident = value['id']
            assert ident in CATALOGUE, ident
            assert set(CATALOGUE[ident].fields) <= value['values'].keys(), ident
            assert value == output.note(ident, value['values']), (ident, value)
        for child in value.values(): audit_notes(child)
    elif isinstance(value, list):
        for child in value: audit_notes(child)


def encoded(value):
    """Stable bytes preserve the contents sealed by the services."""
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()


def opinion_setup_provider(item, world):
    """Run D10/D11 commands on temporary fakes, without composing presentation."""
    from tests.unit.test_background import ImmediateProcess
    from baton.services.background import Background
    original_init = Background.__init__
    def deterministic_background(self, *args, **kwargs):
        original_init(self, *args, **{**kwargs, 'elapsed': lambda: 0.0})
    from tests.fixtures.no_processes import no_processes
    command, state = item.command, item.state
    plan_sequence = count(1)
    world.engine.plans.new_id = lambda: 'p_' + sha256(f'{item.filename}:{next(plan_sequence)}'.encode()).hexdigest()[:32]
    def run(name, confirm=None, **kwargs):
        args = SimpleNamespace(chat=None, source=None, tool=None, question=None, turn=None,
                               status=None, cancel=None, answer=None, add_to_chat=False, background=True)
        for key, value in kwargs.items(): setattr(args, key, value)
        return REGISTRY.get(name).run(Context(world.engine, name, dry_run=confirm is None,
                                             confirm=confirm), args)
    if command.startswith('settings-'):
        if command == 'settings-get': return world.read(command)
        return run('settings set', key='theme', value='graphite')
    if command == 'setup':
        if state == 'd11_empty': world.engine.setup_read.tool_ids = ()
        if state == 'd11_error':
            from contextlib import nullcontext
            from io import StringIO
            from baton.cli.main import main
            stream = StringIO()
            with patch.object(world.engine.setup_read, 'tools', side_effect=RuntimeError('fake setup read failure')), \
                 patch.object(world.engine, 'command_lock', return_value=nullcontext()), patch.object(world.engine, 'close'), \
                 patch('baton.cli.main.logger.exception'):
                assert main(['setup', '--json'], registry=REGISTRY, engine_factory=lambda: world.engine, stdout=stream) == 1
            return json.loads(stream.getvalue())
        if state == 'd11_codex_trust':
            world.adapters['codex'].hooks.ready = False
            with patch.object(world.adapters['codex'].hooks, 'check', return_value=SetupFinding('hooks', False, 'setup.trust_once', {})):
                return world.read('setup')
        if state == 'd11_opencode_damaged':
            world.adapters['opencode'].runner.finding = SetupFinding('runner', False, 'setup.runner_reinstall', {})
        if state == 'd11_cursor_signed_out':
            world.adapters['cursor'].runner.finding = SetupFinding('runner', False, 'setup.runner', {})
        if state == 'd11_not_installed':
            world.engine.setup_read.installation_probe = lambda tool: tool != 'cursor'
            with patch.object(world.adapters['cursor'].hooks, 'check', return_value=SetupFinding('installed', False, 'setup.not_installed', {})):
                return world.read('setup')
        if state == 'd11_unknown_format': world.adapters['codex'].set_format(False, 'new')
        if state == 'd11_missing_hooks': world.adapters['claude'].hooks.installed = False
        return world.read('setup')
    world.pair()
    if state == 'd10_limit':
        world.adapters['codex'].usage_values[world.chats['codex']] = Usage(8000, 200000, True, None)
    if state == 'd10_command_missing': world.adapters['codex'].runner = None
    if state == 'd10_signed_out':
        world.adapters['codex'].runner.finding = SetupFinding('runner', False, 'setup.runner', {})
    tasks = []
    world.engine.background_dispatch = tasks.append
    # Scoped IDs and a synchronous fake supervisor make separate roots reproducible.
    with fixed_ids(item.filename), patch('baton.services.background.uuid4', side_effect=lambda: UUID(int=71)), no_processes(), \
         patch('baton.services.background.RunnerProcess', ImmediateProcess), patch.object(Background, '__init__', deterministic_background):
        try:
            preview = run('ask', chat='claude:' + world.chats['claude'], tool='codex', question='Review this and point out problems', turn=41)
        except BatonError as failure:
            return output.error(failure)
        if state == 'd10_before': return preview
        pending = run('ask', confirm=preview['plan_id'])
        if state == 'd10_pending': return pending
        if state == 'd10_cancelled': return run('ask', cancel=pending['request_id'])
        if state == 'd10_deadline':
            world.clock.value = '2026-10-05T14:10:00Z'
            return run('ask', status=pending['request_id'])
        tasks.pop()()
        answer = run('ask', status=pending['request_id'])
        if command == 'ask': return answer
        if state == 'd10_attached': world.condition('claude', open=True)
        if state == 'd10_unavailable': world.condition('claude', replying=True)
        addition = run('ask add', answer=answer['result']['answer_id'])
        if state == 'd10_applied': return run('ask add', confirm=addition['plan_id'])
        return addition


def relaunch_review_provider(item, world):
    """Production executable/refused lifecycle previews for the app review gate."""
    from types import SimpleNamespace
    from baton.cli.commands import Context, REGISTRY
    from baton.domain.errors import BatonError
    sequence = count(1)
    world.engine.plans.new_id = lambda: 'p_' + sha256(f'{item.filename}:{next(sequence)}'.encode()).hexdigest()[:32]
    parts = item.state.split('_')
    target = parts[1]
    command = parts[2] if item.command == 'relaunch' else item.command
    condition = 'idle' if item.command == 'relaunch' else parts[2]
    source = 'codex' if target == 'claude' else 'claude'
    if command == 'link':
        chat = world.chat(source, 'review-source', [original(1), original(2)])
        world.chat(target, 'other-chat', [original(1)])
        args = SimpleNamespace(source=source + ':' + chat, to=target, mode='full_copy')
    else:
        world.pair((source, target), shared=1)
        world.seed(source, [original(2), original(3)])
        args = SimpleNamespace(link=3, to=target)
    world.adapters[target].app_running = True
    for chat in list(world.adapters[target].conditions):
        current = world.adapters[target].conditions[chat]
        world.adapters[target].conditions[chat] = replace(current, app_running=True, open=True,
            replying=None if condition == 'unknown' else condition == 'replying')
    try:
        preview = REGISTRY.get(command).run(Context(world.engine, command, dry_run=True), args)
        if item.command == 'relaunch':
            offer = next(n for n in preview['notes'] if n['values'].get('relaunch_plan_id'))
            return REGISTRY.get('relaunch').run(Context(world.engine, 'relaunch', confirm=offer['values']['relaunch_plan_id']), SimpleNamespace())
        return preview
    except BatonError as failure:
        return output.error(failure)


def generate(output_directory, *, state_root=None):
    """Generate all registered fixtures using only private temporary engine roots."""
    output_directory = Path(output_directory)
    output_directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='baton-fixture-state-', dir=state_root) as temporary:
        root = Path(temporary)
        for index, item in enumerate(MANIFEST):
            value = generate_one(item, root / str(index))
            (output_directory / item.filename).write_bytes(encoded(value))
    return tuple(item.filename for item in MANIFEST)


def main(argv=None):
    """Publish fixtures only when invoked explicitly as the generation module."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[2] / 'app' / 'Fixtures')
    args = parser.parse_args(argv)
    generated = generate(args.output)
    print(f'Generated {len(generated)} fixtures in {args.output}')

if __name__ == '__main__':
    main()


def setup_install_recipe(tool, state, root):
    """Opt-in SI preview/result recipe: real command output on isolated hook files.

    Not part of the published manifest until fixture regeneration is authorized.
    `root` must be a caller-owned temporary directory, never a real tool home.
    """
    import io
    from contextlib import nullcontext
    from baton.cli.main import main
    from baton.adapters.setup_files import SetupFiles
    from baton.services.setup_install import SetupInstall
    root = Path(root).resolve()
    command_path = root / 'home/.local/bin/baton'
    command_path.parent.mkdir(parents=True, exist_ok=True)
    command_path.write_text('#!/bin/sh\nexit 0\n')
    command_path.chmod(0o755)

    def factory():
        engine = build(root / 'store', tools_home=root / 'home', clock=FixedClock(NOW))
        engine.setup_install = SetupInstall({t: a.hooks for t, a in engine.adapters.items()},
                                           SetupFiles(engine.root, coordinate=lambda path: nullcontext()), str(command_path))
        return engine

    def invoke(words):
        out = io.StringIO()
        status = main(words, engine_factory=factory, stdout=out)
        if status != 0: raise AssertionError(out.getvalue())
        return json.loads(out.getvalue())

    preview = invoke(['setup', 'install', '--tool', tool, '--project', str(root / 'home/project'), '--json'])
    if state == 'preview': return preview
    if state == 'result':
        return invoke(['setup', 'install', '--confirm', preview['plan_id'], '--json'])
    raise ValueError('unknown SI recipe state')
