"""Confirmed close, settle, write and reopen using app/chat ports."""
from dataclasses import asdict, dataclass, replace
from hashlib import sha256
from datetime import datetime, timedelta
import json
from time import monotonic, sleep

from ..domain.errors import ChatChanged, DecisionNeeded, NotAvailable
from ..ports.clock import Clock
from ..ports.store import RecordStore
from .applier import Applier
from .delivery_plan import ApplyStep, PreparedPlan
from .mapping import for_target
from .names import Names
from .noteformat import NoteRef
from .observations import canonical_sources, condition, initial_history_sides, local_turn
from .planner import plan_sync
from .preview import PreviewBuilder


@dataclass(frozen=True)
class RelaunchPlan:
    plan_id: str
    tool: str
    link_id: int | None
    steps: tuple[ApplyStep, ...]
    replying: tuple
    when_idle: bool
    running: bool
    delivery: PreparedPlan
    chats: dict
    notes: tuple[NoteRef, ...]
    facts: dict
    deliveries: tuple[PreparedPlan, ...]
    decision_needed: bool = False
    expires_at: str = ""
    reopen_chat_id: str | None = None
    reopen_folder: str | None = None


@dataclass(frozen=True)
class RelaunchResult:
    plan_id: str
    applied: bool
    opened: bool = False
    waiting: bool = False
    error: str = ''
    notes: tuple[NoteRef, ...] = ()
    write_result: object = None
    completed_links: tuple[int, ...] = ()
    reopen_error: str = ""


class Relaunch:
    """Plan and perform a graceful app lifecycle around approved writes."""
    def __init__(self, store: RecordStore, adapters, clock: Clock,
                 elapsed=monotonic, wait=sleep, idle_timeout=timedelta(minutes=30)):
        """Use injected store, adapters and timing ports."""
        self.store, self.adapters, self.clock = store, adapters, clock
        self.elapsed, self.wait = elapsed, wait
        self.idle_timeout = idle_timeout
        self.preview = PreviewBuilder(store, adapters)

    def _chats(self, tool):
        adapter = self.adapters[tool]
        return {ref.id: {'ref': asdict(ref), 'condition': asdict(adapter.state.condition(ref.id)),
                         'turns': [asdict(t) for t in adapter.reader.read(ref.id)]}
                for ref in adapter.locator.chats()}

    def _sync_steps(self, tool, link_id):
        link = self.store.get_link(link_id)
        if tool not in link.sides or link.removed_at or link.paused:
            raise NotAvailable()
        conditions = {s: condition(self.adapters, s, c) for s, c in link.chats.items()}
        conditions[tool] = replace(conditions[tool], open=False, replying=False, app_running=False)
        facts = {s: self.adapters[s].facts for s in link.sides}
        observed = {s: self.adapters[s].reader.read(c) for s, c in link.chats.items()}
        planned = plan_sync(link, self.store.turns(link_id), conditions, facts=facts,
                            history=self.store.history(link_id),
                            initial_history_sides=initial_history_sides(self.store, link, observed))
        if planned.decision_needed:
            raise DecisionNeeded()
        step = planned.steps.get(tool)
        if not step:
            return ()
        if step.action != 'add':
            raise NotAvailable()
        sources = canonical_sources(self.store, link_id, observed)
        turns = []
        for row in step.turns:
            original = sources.get(row.id)
            if original is None or (conditions[row.origin].replying and observed[row.origin] and
                                    original.id == observed[row.origin][-1].id):
                raise NotAvailable()
            turns.append(local_turn(for_target(original, facts[tool]), link_id, row.id))
        return (ApplyStep(tool, 'add', tuple(r.id for r in step.turns), tuple(turns), needs=step.needs),)

    def _sync_plan(self, tool, link_id):
        chats = self.store.get_link(link_id).chats
        before = self.preview.prepare(link_id, (), chats)
        steps = self._sync_steps(tool, link_id)
        prepared = self.preview.prepare(link_id, steps, chats)
        if before.snapshots != prepared.snapshots or before.record != prepared.record:
            raise ChatChanged()
        return prepared

    def plan_relaunch(self, tool, *, when_idle=False, then_sync=None, rename=None):
        """Preview the exact writes and lifecycle, naming all replying chats."""
        if tool not in self.adapters or (rename is not None and then_sync is not None):
            raise NotAvailable()
        running = self.adapters[tool].app.running()
        chats = self._chats(tool)
        replying = tuple(self.adapters[tool].locator.resolve(c) for c, value in chats.items()
                         if value['condition']['replying'])
        link_id = rename.link_id if rename else then_sync
        if rename:
            if any(s.side != tool or s.action != 'rename' for s in rename.steps):
                raise NotAvailable()
            fresh = self.preview.prepare(rename.link_id, rename.steps,
                                         {s: snap['chat_id'] for s, snap in rename.snapshots.items()})
            if fresh != rename:
                raise ChatChanged()
            writes = rename.steps
        else:
            writes = ()
        linked = self.store.get_link(link_id).chats if link_id is not None else {}
        delivery = self._sync_plan(tool, link_id) if rename is None and link_id is not None else (
            self.preview.prepare(link_id, writes, linked))
        writes = delivery.steps
        deliveries = (delivery,)
        if link_id is None:
            deliveries = tuple(self._sync_plan(tool, link.id)
                               for link in self.store.links() if tool in link.sides and not link.paused)
            writes = tuple(step for item in deliveries for step in item.steps)
        # A closed app needs only sync; Q13 never introduces a relaunch then.
        reopen = running or link_id is None
        steps = ((ApplyStep(tool, 'close'), ApplyStep(tool, 'wait_until_still')) if running else ())
        steps += writes + ((ApplyStep(tool, 'reopen'),) if reopen else ())
        notes = tuple(NoteRef('relaunch.wait_reply' if when_idle else 'relaunch.replying_safe',
                             {'tool': tool, 'title': ref.name}) for ref in replying)
        if not notes:
            notes = (NoteRef('relaunch.order' if running else 'relaunch.closed_open' if reopen else 'relaunch.closed_sync', {'tool': tool}),)
        facts = asdict(self.adapters[tool].facts)
        facts = {key: getattr(value, 'value', value) for key, value in facts.items()}
        expires_at = (datetime.fromisoformat(self.clock.now()) + self.idle_timeout).isoformat() if when_idle else ''
        ref = self.adapters[tool].locator.resolve(linked[tool]) if tool in linked else None
        reopen_chat_id = ref.id if ref and self.adapters[tool].facts.opens_at_chat else None
        reopen_folder = ref.folder if ref else None
        data = {'expires_at': expires_at, 'reopen_chat_id': reopen_chat_id, 'reopen_folder': reopen_folder, 'facts': facts, 'tool': tool, 'link': link_id, 'steps': [asdict(s) for s in steps],
                'when_idle': when_idle, 'running': running, 'delivery': asdict(delivery),
                'deliveries': [asdict(item) for item in deliveries], 'chats': chats}
        ident = 'p_' + sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
        result = RelaunchPlan(ident, tool, link_id, steps, replying, when_idle, running, delivery,
                            chats, notes, facts, deliveries, bool(replying and not when_idle),
                            expires_at, reopen_chat_id, reopen_folder)
        self._validate(result)
        return result

    def _validate(self, plan, *, closed=False):
        facts = {key: getattr(value, 'value', value) for key, value in asdict(self.adapters[plan.tool].facts).items()}
        if facts != plan.facts:
            raise ChatChanged()
        data = {'expires_at': plan.expires_at, 'reopen_chat_id': plan.reopen_chat_id,
                'reopen_folder': plan.reopen_folder, 'facts': plan.facts, 'tool': plan.tool, 'link': plan.link_id,
                'steps': [asdict(s) for s in plan.steps], 'when_idle': plan.when_idle,
                'running': plan.running, 'delivery': asdict(plan.delivery),
                'deliveries': [asdict(item) for item in plan.deliveries], 'chats': plan.chats}
        if 'p_' + sha256(json.dumps(data, sort_keys=True).encode()).hexdigest() != plan.plan_id:
            raise ChatChanged()
        for item in plan.deliveries:
            if self.preview._record(item.link_id) != item.record:
                raise ChatChanged()
        if self.store.journal_entries(pending=True):
            raise NotAvailable()
        transitions = ('open', 'replying', 'app_running', 'app_started_at') if closed else (
            ('replying',) if plan.when_idle else ())
        current = self._chats(plan.tool)
        if set(current) != set(plan.chats):
            raise ChatChanged()
        for chat, earlier in plan.chats.items():
            fresh_condition = dict(current[chat]['condition'])
            for key in transitions:
                fresh_condition[key] = earlier['condition'][key]
            if (fresh_condition != earlier['condition'] or
                    current[chat]['ref'] != earlier['ref'] or current[chat]['turns'] != earlier['turns']):
                raise ChatChanged()
        for item in plan.deliveries:
            for side, earlier in item.snapshots.items():
                fresh = self.preview._snapshot(side, earlier['chat_id'])
                # Only the approved idle/closure transitions may differ.
                if side == plan.tool:
                    for key in transitions:
                        fresh['condition'][key] = earlier['condition'][key]
                if fresh != earlier:
                    raise ChatChanged()
        if not closed and self.adapters[plan.tool].app.running() != plan.running:
            raise ChatChanged()

    def apply(self, plan):
        """Execute the approved plan after fresh state and record checks."""
        adapter = self.adapters[plan.tool]
        if plan.when_idle and datetime.fromisoformat(self.clock.now()) >= datetime.fromisoformat(plan.expires_at):
            return RelaunchResult(plan.plan_id, False, error='IdleTimeout',
                                  notes=(NoteRef('relaunch.idle_timeout', {'tool': plan.tool}),))
        if plan.decision_needed:
            return RelaunchResult(plan.plan_id, False, error='ChatReplying', notes=plan.notes)
        replying = tuple(ref for ref in adapter.locator.chats() if adapter.state.condition(ref.id).replying)
        if replying:
            notes = tuple(NoteRef('relaunch.wait_reply' if plan.when_idle else 'relaunch.replying_safe',
                                 {'tool': plan.tool, 'title': ref.name}) for ref in replying)
            return RelaunchResult(plan.plan_id, False, waiting=plan.when_idle,
                                  error='' if plan.when_idle else 'ChatReplying', notes=notes)
        self._validate(plan)
        closed = False
        close_started = False
        write_started = False
        write_result = None
        completed = []
        try:
            if plan.running:
                # Recheck immediately before asking for a graceful quit.
                if any(adapter.state.condition(ref.id).replying for ref in adapter.locator.chats()):
                    raise NotAvailable()
                try:
                    close_started = True
                    adapter.app.close()
                except Exception as error:
                    notes = (NoteRef('relaunch.close_failed', {'tool': plan.tool}),)
                    if not adapter.app.running():
                        return self._reopen(plan, False, type(error).__name__, None, notes=notes)
                    return RelaunchResult(plan.plan_id, False, error=type(error).__name__, notes=notes)
                deadline = self.elapsed() + 60.0
                previous = None
                for _ in range(601):
                    current = self._chats(plan.tool)
                    still = not adapter.app.running() and all(
                        not v['condition']['open'] and not v['condition']['replying'] for v in current.values())
                    if still and current == previous:
                        closed = True
                        break
                    previous = current if still else None
                    remaining = deadline - self.elapsed()
                    if remaining <= 0:
                        break
                    self.wait(min(.1, remaining))
                if not closed:
                    notes = (NoteRef('relaunch.close_timeout', {'tool': plan.tool}),)
                    if not adapter.app.running():
                        return self._reopen(plan, False, 'CloseTimeout', None, notes=notes)
                    return RelaunchResult(plan.plan_id, False, error='CloseTimeout', notes=notes)
            write_started = True
            self._validate(plan, closed=closed)
            fresh_plans = tuple(self.preview.prepare(item.link_id, item.steps,
                                    {s: snap['chat_id'] for s, snap in item.snapshots.items()})
                                for item in plan.deliveries)
            for fresh in fresh_plans:
                if fresh.steps:
                    if all(s.action == 'rename' for s in fresh.steps):
                        Names(self.store, self.adapters, self.clock).apply(fresh)
                    else:
                        write_result = Applier(self.store, self.adapters, self.clock,
                                               self.elapsed, self.wait).apply(fresh)
                        if not write_result.applied:
                            return self._reopen(plan, False, write_result.error, write_result, tuple(completed))
                    completed.append(fresh.link_id)
            return self._reopen(plan, True, '', write_result, tuple(completed))
        except Exception as error:
            if write_started or closed or (close_started and not adapter.app.running()):
                return self._reopen(plan, False, type(error).__name__, write_result, tuple(completed))
            raise

    def _reopen(self, plan, applied, error, write_result, completed=(), notes=()):
        notes = notes + ((NoteRef('relaunch.partial', {'tool': plan.tool, 'n': len(completed)}),) if completed and not applied else ())
        if error and not applied and not any(n.id in ('relaunch.close_failed', 'relaunch.close_timeout') for n in notes):
            notes += (NoteRef('relaunch.write_failed', {'tool': plan.tool}),)
        if not any(s.action == 'reopen' for s in plan.steps):
            return RelaunchResult(plan.plan_id, applied, error=error, notes=notes, write_result=write_result, completed_links=completed)
        adapter = self.adapters[plan.tool]
        try:
            adapter.app.open(plan.reopen_chat_id, plan.reopen_folder)
            if not adapter.app.running():
                raise NotAvailable()
        except Exception:
            return RelaunchResult(plan.plan_id, applied, error='ReopenFailed',
                notes=notes + (NoteRef('relaunch.reopen_failed_partial' if completed and not applied else
                                      'relaunch.reopen_failed' if applied else 'relaunch.reopen_failed_no_write',
                               {'tool': plan.tool}),), write_result=write_result, completed_links=completed, reopen_error='ReopenFailed')
        return RelaunchResult(plan.plan_id, applied, opened=True, error=error, notes=notes,
                              write_result=write_result, completed_links=completed)
