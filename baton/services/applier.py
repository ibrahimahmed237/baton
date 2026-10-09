"""Confirm previews, safely deliver whole turns, and reconcile observed chats."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from time import monotonic, sleep
from typing import Callable, Collection, Mapping, Sequence

from ..domain.capabilities import Visibility
from ..domain.conditions import SideCondition
from ..domain.errors import ChatChanged, DecisionNeeded, NotAvailable
from ..domain.link import ADDED, SHOWN, ATTACHED, WAITING
from ..domain.model import Turn
from ..ports.clock import Clock
from ..ports.store import RecordStore
from ..ports.tool import ToolAdapter
from .journal import Guard, Journal
from .mapping import content_key
from .delivery_plan import ApplyStep, PreparedPlan
from .preview import PreviewBuilder
from .refresh import ChatRefresh
from .observations import condition, decode_turns, initial_history_sides, local_turn
from .status import link_status


@dataclass(frozen=True)
class StepResult:
    """The recorded outcome of one attempted side action."""
    side: str
    action: str
    chat_id: str
    turn_ids: tuple[int, ...]
    reason: str = ''
    entry_id: int | None = None


@dataclass(frozen=True)
class ApplyResult:
    """Completed steps and an explicit failure or recovery requirement."""
    plan_id: str
    applied: bool
    completed: tuple[StepResult, ...]
    error: str = ''
    failed_side: str = ''
    rollback_error: str = ''
    pending_entry: int | None = None


class Applier:
    """Execute confirmed previews and reconcile durable delivery evidence."""
    def __init__(self, store: RecordStore, adapters: Mapping[str, ToolAdapter], clock: Clock,
                 elapsed: Callable[[], float] = monotonic, wait: Callable[[float], None] = sleep):
        self.store, self.adapters, self.clock = store, adapters, clock
        self.elapsed, self.wait = elapsed, wait
        self._preview = PreviewBuilder(store, adapters)
        self._refresh = ChatRefresh(store, adapters, clock)
        self.guard = Guard(store)
        self.journal = Journal(store, adapters, clock)
        self.recovery = self.journal.recover()

    def _record(self, link_id: int | None) -> dict:
        return self._preview._record(link_id)

    def _snapshot(self, side: str, chat_id: str) -> dict:
        return self._preview._snapshot(side, chat_id)

    def prepare(self, link_id: int | None, steps: Sequence[ApplyStep],
                chats: Mapping[str, str], decision_needed: bool = False) -> PreparedPlan:
        """Fingerprint complete planned actions, chat contents and current records."""
        return self._preview.prepare(link_id, steps, chats, decision_needed)

    def _initial_history_sides(self, link, observed: Mapping[str, Sequence[Turn]]) -> tuple[str, ...]:
        return initial_history_sides(self.store, link, observed)

    def preview(self, link_id: int, add_when_idle: Collection[str] = ()) -> PreparedPlan:
        """Build delivery actions from freshly observed whole turns and facts."""
        return self._preview.preview(link_id, add_when_idle)

    _local_turn = staticmethod(local_turn)

    _turns = staticmethod(decode_turns)

    def _condition(self, side: str, chat: str) -> SideCondition:
        return condition(self.adapters, side, chat)

    def apply_confirmed(self, link_id: int, plan_id: str,
                        add_when_idle: Collection[str] = ()) -> ApplyResult:
        """Apply only when a freshly rebuilt preview still matches the confirmation."""
        plan = self.preview(link_id, add_when_idle)
        if plan.plan_id != plan_id:
            raise ChatChanged()
        return self.apply(plan)

    def _validate(self, plan: PreparedPlan) -> None:
        if self.store.journal_entries(pending=True):
            raise NotAvailable()
        if self._record(plan.link_id) != plan.record:
            raise ChatChanged()
        self._check_snapshots(plan.snapshots)
        checked = self.prepare(plan.link_id, plan.steps,
                               {s: v['chat_id'] for s, v in plan.snapshots.items()}, plan.decision_needed)
        if checked.plan_id != plan.plan_id:
            raise ChatChanged()

    def _check_snapshots(self, snapshots: Mapping[str, dict]) -> None:
        for side, snapshot in snapshots.items():
            try:
                fresh = self._snapshot(side, snapshot['chat_id'])
            except KeyError:
                raise ChatChanged() from None
            if fresh != snapshot:
                raise ChatChanged()
    def apply(self, plan: PreparedPlan) -> ApplyResult:
        """Journal, verify and record each action, stopping at the first failure."""
        self._validate(plan)
        if plan.decision_needed:
            raise DecisionNeeded()
        completed = []
        working = deepcopy(plan.snapshots)
        for step in plan.steps:
            chat = self.store.get_link(plan.link_id).chat(step.side) if plan.link_id is not None else ''
            entry = None
            action, reason = step.action, step.reason
            try:
                self._check_snapshots(working)
                if plan.link_id is not None:
                    current_link = self.store.get_link(plan.link_id)
                    if current_link.removed_at or (current_link.paused and action != 'hold'):
                        raise NotAvailable()
                if action == 'hold':
                    completed.append(StepResult(step.side, action, chat, step.turn_ids, reason))
                    continue
                if action == 'add_after_release':
                    action, reason = self._release(step, chat, plan.link_id)
                if action == 'attach':
                    condition = self._condition(step.side, chat)
                    if not condition.exists or not condition.hooks_ready:
                        raise NotAvailable()
                    if plan.link_id is not None:
                        self.store.record_event(plan.link_id, 'attach_pending', step.side,
                                                self.clock.now(), step.turn_ids, {'reason': reason})
                    completed.append(StepResult(step.side, 'attach', chat, step.turn_ids, reason))
                    continue
                if action not in ('add', 'create', 'place', 'cut') or (action == 'cut' and step.turn_ids):
                    raise NotAvailable()
                adapter = self.adapters[step.side]
                before = adapter.reader.read(chat) if action != 'create' else []
                expected = self._turns(working[step.side]['turns']) if action != 'create' else None
                self.guard.check_write(adapter, None if action == 'create' else chat,
                                       plan.link_id, expected=expected, action=action)
                entry = self.journal.begin(plan.link_id, step.side, None if action == 'create' else chat, action)
                result = self._write(step, action, chat)
                if (result.receipt.tool, result.receipt.chat_id, result.receipt.kind) != (step.side, result.chat_id, action):
                    raise ChatChanged()
                self._verify(step, action, before, result.chat_id, result.local_ids)
                visibility = adapter.facts.new_chat_visible if action == 'create' else adapter.facts.added_turn_visible
                state = SHOWN if visibility == Visibility.AT_ONCE else ADDED
                self.store.complete_write(entry, asdict(result.receipt), self.clock.now(), plan.link_id,
                                          step.side, step.turn_ids, state, action,
                                          result.local_ids if action != 'cut' else (),
                                          {'reason': reason})
                completed.append(StepResult(step.side, action, result.chat_id, step.turn_ids, reason, entry))
                if plan.link_id is not None:
                    working[step.side] = self._snapshot(step.side, result.chat_id)
            except Exception as error:
                rollback_error = ''
                pending = None
                if entry is not None:
                    self.journal.fail(entry, error)
                    try:
                        self.journal.take_back(entry)
                    except Exception as rollback:
                        rollback_error = type(rollback).__name__
                        pending = entry
                return ApplyResult(plan.plan_id, False, tuple(completed), type(error).__name__,
                                   step.side, rollback_error, pending)
        return ApplyResult(plan.plan_id, True, tuple(completed))

    def _release(self, step: ApplyStep, chat: str, link_id: int | None) -> tuple[str, str]:
        adapter = self.adapters[step.side]
        try:
            self.guard.check_release(adapter, chat, link_id)
            adapter.app.release(chat)
            deadline = self.elapsed() + 10.0
            for _ in range(101):
                if not adapter.state.condition(chat).open:
                    return 'add', ''
                remaining = deadline - self.elapsed()
                if remaining <= 0:
                    break
                self.wait(min(0.1, remaining))
            return 'attach', 'release_timeout'
        except Exception as error:
            return 'attach', 'release_failed:' + type(error).__name__

    def _write(self, step: ApplyStep, action: str, chat: str):
        writer = self.adapters[step.side].writer
        if action == 'create':
            return writer.create(step.turns, step.name, step.folder)
        if action == 'place':
            return writer.place(chat, step.turns, step.before_local_id)
        if action == 'cut':
            return writer.cut(chat, step.keep_through_local_id)
        return writer.add(chat, step.turns)

    def _verify(self, step: ApplyStep, action: str, before: list[Turn], chat: str,
                local_ids: Sequence[str]) -> None:
        after = self.adapters[step.side].reader.read(chat)
        if action == 'cut':
            index = next((i for i,t in enumerate(before) if t.id == step.keep_through_local_id), -1)
            expected = before[:index + 1]
        elif action == 'place':
            index = next((i for i,t in enumerate(before) if t.id == step.before_local_id), -1)
            if index < 0:
                raise ChatChanged()
            expected = before[:index] + list(step.turns) + before[index:]
        else:
            expected = (before if action == 'add' else []) + list(step.turns)
        if len(local_ids) != len(step.turns) and action != 'cut':
            raise ChatChanged()
        if action != 'cut':
            written = after[-len(step.turns):] if action != 'place' and step.turns else []
            if len(set(local_ids)) != len(local_ids):
                raise ChatChanged()
            # Adapters may assign local ids; compare public content, then use the returned identities.
            if action == 'place':
                written = after[index:index + len(step.turns)]
            if [content_key(t) for t in written] != [content_key(t) for t in step.turns]:
                raise ChatChanged()
        if [content_key(t) for t in after] != [content_key(t) for t in expected]:
            raise ChatChanged()
        if len({turn.id for turn in after}) != len(after):
            raise ChatChanged()
        if action == 'add' and after[:len(before)] != before:
            raise ChatChanged()
        if action == 'place' and (after[:index] != before[:index] or
                after[index + len(step.turns):] != before[index:]):
            raise ChatChanged()
        if action == 'cut' and after != expected:
            raise ChatChanged()
        if action != 'cut' and step.turns and [t.id for t in written] != list(local_ids):
            raise ChatChanged()

    def record_attached(self, link_id: int, side: str, turn_ids: Sequence[int], message_id: str) -> int:
        """Record a hook acknowledgement without inferring chat visibility."""
        if not message_id or not turn_ids or len(set(turn_ids)) != len(turn_ids):
            raise NotAvailable()
        waiting = {t.id for t in self.store.turns(link_id) if t.states.get(side) == WAITING}
        if not set(turn_ids).issubset(waiting):
            raise NotAvailable()
        link = self.store.get_link(link_id)
        condition = self._condition(side, link.chat(side))
        if link.removed_at or link.paused or not condition.exists or not condition.hooks_ready:
            raise NotAvailable()
        if link_status(link, self.store.turns(link_id),
                       {s: self._condition(s,c) for s,c in link.chats.items()},
                       facts={s: self.adapters[s].facts for s in link.sides},
                       history=self.store.history(link_id)).decision_needed:
            raise DecisionNeeded()
        return self.store.deliver(link_id, side, turn_ids, ATTACHED, 'attached', self.clock.now(),
                                  detail={'message_id': message_id})

    def refresh(self, link_id: int) -> dict:
        """Reconcile fresh names, content and visibility evidence with turn states."""
        return self._refresh.refresh(link_id)

    def mark_seen(self, link_id: int, side: str, turn_ids: Sequence[int] | None = None) -> int:
        """Accept explicit user visibility evidence only for reopen-visible chats."""
        if self.adapters[side].facts.added_turn_visible != Visibility.ON_REOPEN_CHAT:
            raise NotAvailable()
        fresh = self.refresh(link_id)
        if fresh['status'].side(side).removed_still_shown:
            self.store.record_event(link_id, 'undo_shown', side, self.clock.now())
        return self.store.mark_shown(link_id, side, turn_ids)

    def conversation(self, link_id: int) -> list[dict]:
        """Supply public full content; the app owns shortening and expanding it."""
        fresh = self.refresh(link_id)
        rows = []
        for recorded in fresh['turns']:
            original = next((t for t in fresh['messages'].get(recorded.origin, ())
                             if t.id == recorded.origin_id), None)
            rows.append({'turn': recorded, 'prompt': original.prompt.text if original else None,
                         'reply': original.reply_text if original else None,
                         'tool_activity': tuple(m for m in original.messages
                                                if m.kind not in ('prompt','reply')) if original else ()})
        return rows
