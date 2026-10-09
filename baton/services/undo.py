"""Preview history boundaries and safely undo or restore one linked side."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from hashlib import sha256
import json
from typing import Mapping

from ..domain.capabilities import Visibility, WriteWindow
from ..domain.errors import ChatChanged, ChatHeld, ChatReplying, NotAvailable
from ..domain.link import ADDED, SHOWN, AGENT_HAS, WAITING
from ..ports.clock import Clock
from ..ports.store import RecordStore
from ..ports.tool import ToolAdapter, WriteReceipt
from .applier import Applier
from .delivery_plan import ApplyStep
from .mapping import for_created_chat
from .observations import decode_turns


@dataclass(frozen=True)
class UndoPlan:
    """An exact history boundary, removed turns, and complete observations."""
    plan_id: str
    link_id: int
    event_id: int
    operation: str
    steps: tuple[ApplyStep, ...]
    snapshots: dict
    record: dict
    removes: tuple[dict, ...]
    ends_at: dict
    detail: dict
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class UndoResult:
    """The atomic operation or its explicit recoverable failure."""
    plan_id: str
    applied: bool
    event_id: int | None = None
    error: str = ''
    notes: tuple[str, ...] = ()
    rollback_errors: tuple[dict, ...] = ()


class Undo:
    """Undo only after an unchanged preview, preserving every earlier chat."""
    def __init__(self, store: RecordStore, adapters: Mapping[str, ToolAdapter], clock: Clock):
        self.store, self.adapters, self.clock = store, adapters, clock
        self.applier = Applier(store, adapters, clock)
        self.recovery = self.applier.recovery

    def _record(self, link_id):
        record = self.applier._record(link_id)
        record['local_ids'] = {s: self.store.local_ids(link_id, s)
                               for s in self.store.get_link(link_id).sides}
        return record

    @staticmethod
    def _fingerprint(plan):
        value = asdict(plan)
        value.pop('plan_id')
        return 'p_' + sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def _finish(self, plan):
        if self._record(plan.link_id) != plan.record:
            raise ChatChanged()
        self._check_snapshots(plan.snapshots)
        return replace(plan, plan_id=self._fingerprint(plan))

    def _check_snapshots(self, snapshots):
        for key, snapshot in snapshots.items():
            try:
                fresh = self.applier._snapshot(snapshot['side'], snapshot['chat_id'])
            except KeyError:
                raise ChatChanged() from None
            fresh['side'] = snapshot['side']
            if fresh != snapshot:
                raise ChatChanged()

    def _snapshot(self, side, chat):
        return dict(self.applier._snapshot(side, chat), side=side)

    @staticmethod
    def _undo_note(facts, action):
        if action == 'cut':
            return 'undo.cut_reopen' if facts.added_turn_visible == Visibility.ON_REOPEN_CHAT else 'undo.cut'
        return 'undo.shorter_closed' if facts.write_window == WriteWindow.APP_CLOSED else 'undo.shorter'

    @staticmethod
    def _undo_needs(facts, condition, action):
        needs = ('release_chat',) if action == 'cut' and condition['open'] and facts.can_release_chat else ()
        if facts.write_window == WriteWindow.APP_CLOSED:
            needs += ('app_closed',)
        visibility = facts.added_turn_visible if action == 'cut' else facts.new_chat_visible
        if visibility == Visibility.AFTER_RELAUNCH:
            needs += ('relaunch_to_see',)
        elif visibility == Visibility.ON_REOPEN_CHAT:
            needs += ('reopen_chat_to_see',)
        return needs

    def plan(self, link_id: int, event_id: int, *, side: str = '') -> UndoPlan:
        """List everything removed from one side before any mutation happens."""
        record = self._record(link_id)
        link = self.store.get_link(link_id)
        event = next((e for e in self.store.history(link_id) if e.id == event_id), None)
        if event is None:
            raise NotAvailable()
        if event.kind == 'merge':
            return self._merge_plan(link_id, event, record)
        if link.removed_at:
            raise NotAvailable()
        side = side or event.side
        if side not in link.sides:
            raise NotAvailable()
        if event.side and event.side != side:
            raise NotAvailable()
        snapshots = {s: self._snapshot(s, c) for s, c in link.chats.items()}
        observed = decode_turns(snapshots[side]['turns'])
        rows = self.store.turns(link_id)
        ids = record['local_ids'][side]
        by_local = {local: ident for ident, local in ids.items()}
        for row in rows:
            if row.origin == side:
                by_local.setdefault(row.origin_id, row.id)
        if any(t.id not in by_local for t in observed):
            # Refresh must register native writes so their identities survive undo.
            raise ChatChanged()
        later = [e for e in self.store.history(link_id) if e.id >= event_id and e.side == side
                 and e.kind in ('add', 'added', 'delivered', 'place', 'attached', 'create')]
        delivered = {ident for e in later for ident in e.turn_ids}
        boundary = []
        attachments = []
        for index, turn in enumerate(observed):
            if by_local[turn.id] in delivered:
                boundary.append(index)
            for delivery in later:
                message_id = delivery.detail.get('message_id')
                if message_id and message_id in (turn.id, *(m.id for m in turn.messages)):
                    boundary.append(index)
                    attachments.append(by_local[turn.id])
        if not boundary:
            if not delivered:
                raise NotAvailable()
            raise ChatChanged()
        index = min(boundary)
        kept, removed = observed[:index], observed[index:]
        removed_ids = {by_local[t.id] for t in removed} | delivered
        # Include attached context even though it is not a separate native message.
        removes = tuple({'side': side, 'turn': asdict(row),
                         'only_here': row.origin == side and
                         all(row.states[s] not in AGENT_HAS for s in link.others(side))}
                        for row in rows if row.id in removed_ids)
        facts = self.adapters[side].facts
        action = 'cut' if facts.can_cut else 'create_shorter'
        needs = self._undo_needs(facts, snapshots[side]['condition'], action)
        ref = snapshots[side]['ref']
        step = ApplyStep(side, action, tuple(by_local[t.id] for t in kept),
                         tuple(kept if action == 'cut' else for_created_chat(kept, facts)),
                         needs=needs, name=ref['name'], folder=ref['folder'],
                         keep_through_local_id=kept[-1].id if kept else '')
        detail = {'side': side, 'removed_ids': sorted(removed_ids),
                  'attachments': attachments, 'earlier_chat': link.chat(side),
                  'kept_ids': list(step.turn_ids)}
        note = self._undo_note(facts, action)
        notes = (note,)
        if any(r['only_here'] for r in removes):
            notes += ('undo.only_here',)
        if kept:
            notes += ('undo.ends_at',)
        if attachments:
            notes += ('undo.attached',)
        if snapshots[side]['condition']['replying']:
            notes += ('undo.replying',)
        detail['notes_by_side'] = {side: list(notes)}
        return self._finish(UndoPlan('', link_id, event_id, 'undo', (step,), snapshots,
                                     record, removes, {side: asdict(kept[-1]) if kept else None}, detail, notes))

    def _merge_plan(self, link_id, event, record):
        link = self.store.get_link(link_id)
        prior = event.detail['before']
        snapshots = {s: self._snapshot(s, c) for s, c in link.chats.items()}
        rows = {r.id: r for r in self.store.turns(link_id)}
        steps, removes, ends, changed = [], [], {}, {}
        for write in event.detail['writes']:
            side, action = write['side'], write['action']
            if link.chat(side) != write['chat_id']:
                raise ChatChanged()
            if action == 'create':
                merged = event.detail.get('after_chats', {}).get(side)
                if (merged is None or snapshots[side]['ref'] != merged['ref'] or
                        decode_turns(snapshots[side]['turns']) != decode_turns(merged['turns'])):
                    raise ChatChanged()
                earlier = prior['link']['chats'][side]
                snapshots[side + ':earlier'] = self._snapshot(side, earlier)
                owner = self.store.link_for(side, earlier)
                if owner and owner.id != link_id:
                    raise NotAvailable()
                steps.append(ApplyStep(side, 'move_link'))
                previous_states = {r['id']: r['states'][side] for r in prior['turns']}
                earlier_turns = decode_turns(snapshots[side + ':earlier']['turns'])
                ends[side] = asdict(earlier_turns[-1]) if earlier_turns else None
                lost = [r for r in rows.values() if previous_states.get(r.id, WAITING) not in AGENT_HAS
                        and r.states[side] in AGENT_HAS]
                for row in lost:
                    previous_states.setdefault(row.id, WAITING)
                    removes.append({'side': side, 'turn': asdict(row),
                                    'only_here': row.origin == side and
                                    all(row.states[o] not in AGENT_HAS for o in link.others(side))})
                changed[side] = {'states': previous_states,
                                 'local_ids': prior['local_ids'][side],
                                 'origin_ids': {r['id']: r['origin_id'] for r in prior['turns'] if r['origin'] == side},
                                 'chat_id': earlier}
                continue
            acknowledged = []
            if action == 'attach':
                acknowledged = [e for e in self.store.history(link_id)
                                if e.id > event.id and e.kind == 'attached' and e.side == side
                                and set(e.turn_ids).intersection(write['turn_ids'])]
                if not acknowledged:
                    # Merge approval alone never writes a native message.
                    changed[side] = {'states': {r['id']: r['states'][side] for r in prior['turns']},
                                     'local_ids': prior['local_ids'][side], 'origin_ids': {},
                                     'chat_id': link.chat(side)}
                    steps.append(ApplyStep(side, 'move_link'))
                    continue
            observed = decode_turns(snapshots[side]['turns'])
            local = record['local_ids'][side]
            by_local = {value: ident for ident, value in local.items()}
            if acknowledged:
                message_ids = {e.detail.get('message_id') for e in acknowledged}
                start = next((i for i, t in enumerate(observed)
                              if message_ids.intersection((t.id, *(m.id for m in t.messages)))), None)
            else:
                start = next((i for i, t in enumerate(observed) if by_local.get(t.id) in write['turn_ids']), None)
            if start is None or any(t.id not in by_local for t in observed):
                raise ChatChanged()
            kept, removed = observed[:start], observed[start:]
            facts = self.adapters[side].facts
            undo_action = 'cut' if facts.can_cut else 'create_shorter'
            ref = snapshots[side]['ref']
            steps.append(ApplyStep(side, undo_action, tuple(by_local[t.id] for t in kept),
                tuple(kept if facts.can_cut else for_created_chat(kept, facts)),
                needs=self._undo_needs(facts, snapshots[side]['condition'], undo_action),
                name=ref['name'], folder=ref['folder'],
                keep_through_local_id=kept[-1].id if kept else ''))
            removed_ids = [by_local[t.id] for t in removed]
            removed_ids += [i for e in acknowledged for i in e.turn_ids if i not in removed_ids]
            states = {i: WAITING for i in removed_ids}
            if not facts.can_cut:
                states.update({by_local[t.id]: rows[by_local[t.id]].states[side] for t in kept})
            changed[side] = {'states': states, 'local_ids': {}, 'origin_ids': {}}
            removes += [{'side': side, 'turn': asdict(rows[i]),
                         'only_here': rows[i].origin == side and
                         all(rows[i].states[o] not in AGENT_HAS for o in link.others(side))} for i in removed_ids]
            ends[side] = asdict(kept[-1]) if kept else None
        if event.detail.get('split'):
            for side in link.sides:
                steps.append(ApplyStep(side, 'move_link'))
                changed[side] = {'states': {}, 'local_ids': {}, 'origin_ids': {}, 'chat_id': link.chat(side)}
        side_notes = {step.side: [self._undo_note(self.adapters[step.side].facts, step.action)]
                      for step in steps if step.action in ('cut', 'create_shorter')}
        for side in side_notes:
            if any(r['side'] == side and r['only_here'] for r in removes):
                side_notes[side].append('undo.only_here')
            if ends.get(side) is not None:
                side_notes[side].append('undo.ends_at')
            if any(w['side'] == side and w['action'] == 'attach' for w in event.detail['writes']):
                side_notes[side].append('undo.attached')
        detail = {'merge_changes': changed, 'notes_by_side': side_notes, 'order': [r['id'] for r in prior['turns']] +
                  [r['id'] for r in record['turns'] if r['id'] not in {t['id'] for t in prior['turns']}]}
        return self._finish(UndoPlan('', link_id, event.id, 'undo', tuple(steps), snapshots,
                                     record, tuple(removes), ends, detail, tuple(dict.fromkeys(('undo.merge', *(n for ns in side_notes.values() for n in ns))))))

    def restore(self, link_id: int, event_id: int | None = None) -> UndoPlan:
        """Preview restoring a saved cut or moving back to an untouched earlier chat."""
        if event_id is None:
            event_id = link_id
            owners = [link.id for link in self.store.links()
                      if any(e.id == event_id for e in self.store.history(link.id))]
            if len(owners) != 1:
                raise NotAvailable()
            link_id = owners[0]
        record = self._record(link_id)
        event = next((e for e in self.store.history(link_id) if e.id == event_id), None)
        if (event is None or event.kind != 'undo' or
                event.detail.get('before', {}).get('link', {}).get('removed_at')):
            raise NotAvailable()
        if any(e.kind == 'restore' and e.detail.get('target') == event_id for e in self.store.history(link_id)):
            raise NotAvailable()
        link = self.store.get_link(link_id)
        if link.removed_at:
            raise NotAvailable()
        snapshots = {s: self._snapshot(s, c) for s, c in link.chats.items()}
        steps = []
        for write in event.detail['writes']:
            side = write['side']
            if link.chat(side) != write['chat_id']:
                raise ChatChanged()
            if write['action'] == 'cut':
                cutoff = datetime.fromisoformat(event.at.replace('Z', '+00:00')) + timedelta(days=30)
                if datetime.fromisoformat(self.clock.now().replace('Z', '+00:00')) > cutoff:
                    raise NotAvailable()
                if (snapshots[side]['ref'] != event.detail['after'][side]['ref'] or
                        decode_turns(snapshots[side]['turns']) != decode_turns(event.detail['after'][side]['turns'])):
                    raise ChatChanged()
                if any(e.id > event_id and e.side == side and e.kind in ('add', 'place', 'attached', 'create')
                       for e in self.store.history(link_id)):
                    raise ChatChanged()
                entry = self.store.journal_entry(write['entry_id'])
                if entry['state'] != 'committed' or not entry['post_receipt']:
                    raise NotAvailable()
                steps.append(ApplyStep(side, 'restore', turns=tuple(decode_turns(event.detail['before_chats'][side]['turns']))))
            else:
                unchanged = event.detail['after'][side]
                if (snapshots[side]['ref'] != unchanged['ref'] or
                        decode_turns(snapshots[side]['turns']) != decode_turns(unchanged['turns'])):
                    raise ChatChanged()
                earlier = event.detail['before_chats'][side]['chat_id']
                owner = self.store.link_for(side, earlier)
                if owner and owner.id != link_id:
                    raise NotAvailable()
                snapshots[side + ':earlier'] = self._snapshot(side, earlier)
                if decode_turns(snapshots[side + ':earlier']['turns']) != decode_turns(event.detail['before_chats'][side]['turns']):
                    raise ChatChanged()
                steps.append(ApplyStep(side, 'move_link'))
        detail = {'undo_event': asdict(event)}
        return self._finish(UndoPlan('', link_id, event_id, 'restore', tuple(steps), snapshots,
                                     record, (), {}, detail, ('undo.restore' if any(s.action == 'restore' for s in steps) else 'undo.earlier_chat',)))

    def apply(self, plan: UndoPlan) -> UndoResult:
        """Carry out an exact preview with fresh guards and rollback on any failure."""
        if self.store.journal_entries(pending=True):
            raise NotAvailable()
        if self._fingerprint(plan) != plan.plan_id or self._record(plan.link_id) != plan.record:
            raise ChatChanged()
        self._check_snapshots(plan.snapshots)
        if plan.operation == 'restore':
            event = plan.detail['undo_event']
            if any(w['action'] == 'cut' for w in event['detail']['writes']):
                cutoff = datetime.fromisoformat(event['at'].replace('Z', '+00:00')) + timedelta(days=30)
                if datetime.fromisoformat(self.clock.now().replace('Z', '+00:00')) > cutoff:
                    raise NotAvailable()
        entries, writes = [], []
        working = deepcopy(plan.snapshots)
        try:
            for step in plan.steps:
                side, adapter = step.side, self.adapters[step.side]
                chat = self.store.get_link(plan.link_id).chat(side)
                before = decode_turns(working[side]['turns'])
                if adapter.state.condition(chat).replying:
                    raise ChatReplying()
                if step.action in ('cut', 'restore') and adapter.state.condition(chat).open and adapter.facts.can_release_chat:
                    released, reason = self.applier._release(step, chat, plan.link_id)
                    if released != 'add':
                        raise ChatHeld()
                    working[side] = self._snapshot(side, chat)
                    if working[side]['turns'] != plan.snapshots[side]['turns']:
                        raise ChatChanged()
                entry = None
                receipt = None
                if step.action != 'move_link':
                    action = 'create' if step.action == 'create_shorter' else step.action
                    self.applier.guard.check_write(adapter, None if action == 'create' else chat,
                        plan.link_id, expected=None if action == 'create' else before,
                        action='add' if action == 'restore' else action)
                    entry = self.applier.journal.begin(plan.link_id, side, None if action == 'create' else chat, action)
                    entries.append(entry)
                    self.applier.guard.check_write(adapter, None if action == 'create' else chat,
                        plan.link_id, expected=None if action == 'create' else before,
                        action='add' if action == 'restore' else action)
                    if action == 'restore':
                        previous = next(w for w in plan.detail['undo_event']['detail']['writes'] if w['side'] == side)
                        result = adapter.writer.restore(WriteReceipt(**previous['receipt']))
                        if adapter.reader.read(chat) != list(step.turns):
                            raise ChatChanged()
                    else:
                        result = self.applier._write(step, action, chat)
                        self.applier._verify(step, action, before, result.chat_id, result.local_ids)
                    receipt = asdict(result.receipt)
                    prepared = self.store.journal_entry(entry)
                    if (receipt['tool'], receipt['chat_id'], receipt['kind']) != (side, prepared['chat_id'], action):
                        actual = self.store.journal_begin(plan.link_id, side, result.chat_id, action, self.clock.now(), receipt)
                        entries.append(actual)
                        raise ChatChanged()
                    resulting_chat = result.chat_id
                    local = dict(zip(step.turn_ids, result.local_ids))
                    if action != 'create':
                        working[side] = self._snapshot(side, chat)
                else:
                    resulting_chat = (plan.detail['merge_changes'][side]['chat_id'] if plan.operation == 'undo' else
                                      plan.detail['undo_event']['detail']['before_chats'][side]['chat_id'])
                    local = {}
                if plan.operation == 'undo' and 'merge_changes' in plan.detail:
                    change = plan.detail['merge_changes'][side]
                    states = {int(i): v for i, v in change['states'].items()}
                    if step.action == 'create_shorter':
                        states.update({i: SHOWN if adapter.facts.new_chat_visible == Visibility.AT_ONCE else ADDED for i in step.turn_ids})
                    if step.action != 'create_shorter':
                        local = {int(i): v for i, v in change['local_ids'].items()}
                    origins = {int(i): v for i, v in change['origin_ids'].items()}
                elif plan.operation == 'undo':
                    rows = {t.id: t for t in self.store.turns(plan.link_id)}
                    states = {i: WAITING for i in plan.detail['removed_ids']}
                    if step.action == 'create_shorter':
                        states.update({i: SHOWN if adapter.facts.new_chat_visible == Visibility.AT_ONCE else ADDED for i in step.turn_ids})
                    else:
                        local = {i: value for i, value in plan.record['local_ids'][side].items()
                                 if i in states and i not in plan.detail['removed_ids']}
                else:
                    undo = plan.detail['undo_event']['detail']
                    states = {r['id']: r['states'][side] for r in undo['before']['turns']}
                    local = {int(i): value for i, value in undo['before']['local_ids'][side].items()}
                if 'merge_changes' not in plan.detail or step.action == 'create_shorter':
                    origins = {r['id']: local[r['id']] for r in plan.record['turns']
                               if r['origin'] == side and r['id'] in local}
                if plan.operation == 'restore':
                    origins = {r['id']: r['origin_id'] for r in undo['before']['turns'] if r['origin'] == side}
                writes.append({'side': side, 'action': step.action, 'chat_id': resulting_chat,
                               'states': states, 'local_ids': local, 'origin_ids': origins,
                               'entry_id': entry, 'receipt': receipt})
            self._check_snapshots(working)
            after = {w['side']: self._snapshot(w['side'], w['chat_id']) for w in writes}
            detail = {'operation': plan.operation, 'target': plan.event_id, 'before': plan.record,
                      'before_chats': plan.snapshots, 'after': after,
                      'order': plan.detail.get('order', [])}
            event = self.store.complete_undo(plan.link_id, plan.record, writes, self.clock.now(), detail)
            return UndoResult(plan.plan_id, True, event)
        except Exception as error:
            failures = []
            for entry in reversed(entries):
                self.applier.journal.fail(entry, error)
                try:
                    self.applier.journal.take_back(entry)
                except Exception as rollback:
                    failures.append({'entry_id': entry, 'error': type(rollback).__name__})
            notes = ('undo.replying',) if isinstance(error, ChatReplying) else ()
            return UndoResult(plan.plan_id, False, error=type(error).__name__, notes=notes,
                              rollback_errors=tuple(failures))
