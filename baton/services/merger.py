"""Confirmed merge decisions, preserving old chats and all-side atomic records."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from hashlib import sha256
import json
from typing import Collection, Mapping, Sequence

from ..domain.capabilities import Visibility, WriteWindow
from ..domain.errors import ChatChanged, NotAvailable, OrderNotAllowed
from ..domain.link import ADDED, SHOWN, WAITING, KEPT_BACK, SKIPPED
from ..ports.clock import Clock
from ..ports.store import RecordStore
from ..ports.tool import ToolAdapter
from . import planner, status
from .applier import Applier
from .delivery_plan import ApplyStep, PreparedPlan
from .mapping import for_target, for_created_chat, title


@dataclass(frozen=True)
class MergePlan:
    """An immutable decision fingerprint including its full delivery observations."""
    plan_id: str
    delivery: PreparedPlan
    order: tuple[int, ...]
    preset: str = ''
    keep: str = ''
    split: bool = False
    skips: tuple[tuple[int, str], ...] = ()
    same_files: tuple[dict, ...] = ()
    automatic: bool = False


@dataclass(frozen=True)
class MergeResult:
    """One completed merge event or explicit failure and pending rollback details."""
    plan_id: str
    applied: bool
    event_id: int | None = None
    error: str = ''
    rollback_errors: tuple[dict, ...] = ()


class Merger:
    """Preview and execute an explicit decision, never rewriting an existing chat."""
    def __init__(self, store: RecordStore, adapters: Mapping[str, ToolAdapter], clock: Clock):
        self.store, self.adapters, self.clock = store, adapters, clock
        self.applier = Applier(store, adapters, clock)
        self.recovery = self.applier.recovery

    def _observed(self, link_id):
        record = self.applier._record(link_id)
        link = self.store.get_link(link_id)
        if link.removed_at:
            raise NotAvailable()
        rows = self.store.turns(link_id)
        observations = {s: self.applier._snapshot(s, c) for s, c in link.chats.items()}
        originals = {s: {t.id: t for t in self.applier._turns(o['turns'])}
                     for s, o in observations.items()}
        for side, observed in originals.items():
            known = set(self.store.local_ids(link_id, side).values())
            known.update(t.origin_id for t in rows if t.origin == side)
            if not set(observed).issubset(known):
                raise ChatChanged()
        try:
            payload = {t.id: originals[t.origin][t.origin_id] for t in rows}
        except KeyError:
            raise ChatChanged() from None
        if self.applier._record(link_id) != record:
            raise ChatChanged()
        return link, rows, observations, payload

    def show(self, link_id: int, *, merge_setting: str = 'ask',
             brief_threshold_tokens: int = 150000) -> dict:
        """Return complete unsynced messages, valid presets and fact-based outcomes."""
        link, rows, observations, payload = self._observed(link_id)
        pending = planner.unsynced(rows)
        order = planner.merge_order(rows)
        changed = {}
        for turn in pending:
            for path in self.adapters[turn.origin].reader.files_changed(payload[turn.id]):
                changed.setdefault(path, []).append(turn)
        same_files = [{'file': path, 'turns': [t.id for t in values]}
                      for path, values in sorted(changed.items())
                      if len({t.origin for t in values}) > 1]
        presets = [{'id': 'by_time', 'order': [t.id for t in order]}]
        presets += [{'id': side + '_first', 'order': [t.id for t in planner.merge_order(rows, side)]}
                    for side in link.sides if any(t.origin == side for t in pending)]
        presets += [{'id': 'dont_reorder', 'order': [t.id for t in order]}]
        tokens = sum(t.size for t in rows if KEPT_BACK not in t.states.values()
                     and SKIPPED not in t.states.values()) // 4
        return {'last_shared': planner.last_shared(rows), 'unsynced': pending,
                'messages': {t.id: payload[t.id] for t in pending},
                'order': [t.id for t in order], 'presets': presets,
                'outcome': planner.outcome(order),
                'overlaps': [[a.id, b.id] for a, b in planner.overlapping(order)],
                'same_files': same_files, 'tokens': tokens,
                'offer_brief': tokens >= brief_threshold_tokens,
                'automatic_allowed': merge_setting == 'by_time' and not same_files}

    @staticmethod
    def _fingerprint(plan: MergePlan) -> str:
        data = asdict(plan)
        data.pop('plan_id')
        return 'p_' + sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def plan(self, link_id: int, *, order: Sequence[int] | None = None,
             preset: str = '', keep: str = '', split: bool = False,
             automatic: bool = False, merge_setting: str = 'ask', add_when_idle: Collection[str] = ()) -> MergePlan:
        """Confirm one order or exit; creation payload includes the shared prefix."""
        if sum((order is not None, bool(preset), bool(keep), split)) > 1:
            raise OrderNotAllowed()
        record = self.applier._record(link_id)
        link, rows, observations, payload = self._observed(link_id)
        if not split and any(o['condition']['replying'] for o in observations.values()):
            raise NotAvailable()
        pending = planner.unsynced(rows)
        if not split and len({t.origin for t in pending}) < 2:
            raise NotAvailable()
        if keep and keep not in link.sides:
            raise NotAvailable()
        choice = preset.removesuffix('_first') if preset.endswith('_first') else preset
        if order is not None:
            try:
                ordered = [next(t for t in pending if t.id == ident) for ident in order]
            except StopIteration:
                raise OrderNotAllowed() from None
        else:
            ordered = planner.merge_order(rows, choice or planner.BY_TIME)
        planner.check_order(rows, ordered)
        screen = self.show(link_id)
        if automatic and (merge_setting != 'by_time' or screen['same_files'] or choice not in ('', planner.BY_TIME)
                          or keep or split or order is not None):
            raise NotAvailable()
        skips = tuple((t.id, keep) for t in planner.turns_to_skip(rows, keep)) if keep else ()
        outcomes = planner.outcome(ordered, choice)
        queue = iter(ordered)
        pending_ids = {t.id for t in pending}
        reordered = [next(queue) if t.id in pending_ids else t for t in rows]
        steps = []
        if not split:
            for side in link.sides:
                condition = self.applier._condition(side, link.chat(side))
                facts = self.adapters[side].facts
                receiving = [t for t in ordered if t.states[side] == WAITING
                             and (not keep or t.origin == keep)]
                if keep or outcomes.get(side) == planner.KEEPS_CHAT:
                    if not receiving:
                        continue
                    action, reason, needs, alternatives = status.delivery_choice(
                        link, condition, facts, '', side in add_when_idle)
                    turns = [self.applier._local_turn(for_target(payload[t.id], facts), link_id, t.id)
                             for t in receiving]
                    steps.append(ApplyStep(side, action, tuple(t.id for t in receiving), tuple(turns),
                                           reason, needs, alternatives=alternatives))
                else:
                    visible = [t for t in reordered if t.states[side] not in (KEPT_BACK, SKIPPED)]
                    turns = [self.applier._local_turn(payload[t.id], link_id, t.id) for t in visible]
                    needs = ('app_closed',) if facts.write_window == WriteWindow.APP_CLOSED else ()
                    if facts.new_chat_visible == Visibility.AFTER_RELAUNCH:
                        needs += ('relaunch_to_see',)
                    ref = observations[side]['ref']
                    steps.append(ApplyStep(side, 'create', tuple(t.id for t in visible),
                                           tuple(for_created_chat(turns, facts)), needs=needs,
                                           name=title(ref['name'], link.others(side)[0], True), folder=ref['folder']))
        delivery = self.applier.prepare(link_id, steps, link.chats)
        if delivery.snapshots != observations or delivery.record != record:
            raise ChatChanged()
        plan = MergePlan('', delivery, tuple(t.id for t in ordered), preset, keep, split,
                         skips, tuple(screen['same_files']), automatic)
        return replace(plan, plan_id=self._fingerprint(plan))

    def merge_if_automatic(self, link_id: int, *, merge_setting: str = 'ask',
                           add_when_idle: Collection[str] = ()) -> MergeResult | None:
        """Dispatch an allowed by-time decision; same-file conflicts keep asking."""
        shown = self.show(link_id, merge_setting=merge_setting)
        if not shown['automatic_allowed']:
            return None
        plan = self.plan(link_id, automatic=True, merge_setting=merge_setting,
                         add_when_idle=add_when_idle)
        return self.apply(plan, plan.plan_id)

    def apply(self, plan: MergePlan, plan_id: str | None = None) -> MergeResult:
        """Write every side safely, then commit one durable merge event or roll back."""
        if self._fingerprint(plan) != plan.plan_id or (plan_id is not None and plan_id != plan.plan_id):
            raise ChatChanged()
        self.applier._validate(plan.delivery)
        if tuple(self.show(plan.delivery.link_id)['same_files']) != plan.same_files:
            raise ChatChanged()
        link_id = plan.delivery.link_id
        before = deepcopy(plan.delivery.record)
        before['local_ids'] = {s: self.store.local_ids(link_id, s) for s in before['link']['chats']}
        working = deepcopy(plan.delivery.snapshots)
        writes, entries, created = [], [], {}
        try:
            if self.store.get_link(link_id).paused and not plan.split:
                raise NotAvailable()
            for step in plan.delivery.steps:
                self.applier._check_snapshots(working)
                if self.applier._record(link_id) != plan.delivery.record:
                    raise ChatChanged()
                current = self.store.get_link(link_id)
                if current.paused or current.removed_at:
                    raise NotAvailable()
                adapter = self.adapters[step.side]
                chat = current.chat(step.side)
                action, reason = step.action, step.reason
                if action == 'hold':
                    raise NotAvailable()
                if action == 'add_after_release':
                    action, reason = self.applier._release(step, chat, link_id)
                    working[step.side] = self.applier._snapshot(step.side, chat)
                if action == 'attach':
                    condition = self.applier._condition(step.side, chat)
                    if not condition.exists or not condition.hooks_ready:
                        raise NotAvailable()
                    writes.append({'side': step.side, 'action': 'attach', 'turn_ids': step.turn_ids,
                                   'chat_id': chat, 'reason': reason})
                    continue
                old = self.applier._turns(working[step.side]['turns'])
                self.applier.guard.check_write(adapter, None if action == 'create' else chat,
                                                link_id, expected=old if action != 'create' else None,
                                                action=action)
                entry = self.applier.journal.begin(link_id, step.side,
                                                   None if action == 'create' else chat, action)
                entries.append(entry)
                result = self.applier._write(step, action, chat)
                if (result.receipt.tool, result.receipt.chat_id, result.receipt.kind) != (step.side, result.chat_id, action):
                    raise ChatChanged()
                prepared = self.store.journal_entry(entry)
                if result.chat_id != prepared['chat_id']:
                    # A broken adapter reservation must not make its actual write disappear from recovery.
                    actual = self.store.journal_begin(link_id, step.side, result.chat_id, action,
                                                      self.clock.now(), asdict(result.receipt))
                    entries.append(actual)
                    raise ChatChanged()
                self.applier._verify(step, action, old, result.chat_id, result.local_ids)
                visibility = adapter.facts.new_chat_visible if action == 'create' else adapter.facts.added_turn_visible
                writes.append({'side': step.side, 'action': action, 'turn_ids': step.turn_ids,
                               'chat_id': result.chat_id, 'local_ids': result.local_ids,
                               'state': SHOWN if visibility == Visibility.AT_ONCE else ADDED,
                               'entry_id': entry, 'receipt': asdict(result.receipt), 'reason': reason})
                if action == 'create':
                    created[step.side] = self.applier._snapshot(step.side, result.chat_id)
                if action != 'create':
                    working[step.side] = self.applier._snapshot(step.side, chat)
            self.applier._check_snapshots(working)
            if self.applier._record(link_id) != plan.delivery.record:
                raise ChatChanged()
            self.applier._check_snapshots(created)
            detail = {'before': before, 'writes': writes, 'preset': plan.preset,
                      'keep': plan.keep, 'split': plan.split, 'automatic': plan.automatic}
            event = self.store.complete_merge(link_id, plan.order, writes, plan.skips,
                                               self.clock.now(), detail)
            return MergeResult(plan.plan_id, True, event)
        except Exception as error:
            failures = []
            for entry in reversed(entries):
                self.applier.journal.fail(entry, error)
                try:
                    self.applier.journal.take_back(entry)
                except Exception as rollback:
                    failures.append({'entry_id': entry, 'error': type(rollback).__name__})
            return MergeResult(plan.plan_id, False, error=type(error).__name__, rollback_errors=tuple(failures))
