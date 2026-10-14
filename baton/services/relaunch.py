"""Confirmed close, settle, write and reopen using app/chat ports."""
from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from hashlib import sha256
from datetime import datetime, timedelta
import json
from time import monotonic, sleep

from ..domain.capabilities import Visibility, WriteWindow
from ..domain.errors import ChatChanged, ChatReplying, DecisionNeeded, NotAvailable
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

    def __getattr__(self, name):
        """Keep public write identities while retaining the lifecycle receipt."""
        if name in ('chat_id', 'link_id', 'event_id', 'needs', 'rollback_error', 'pending_entry'):
            return getattr(self.write_result, name)
        raise AttributeError(name)


class _ReplyRefusal(ChatReplying):
    def __init__(self, notes, write_result=None):
        self.notes, self.write_result = notes, write_result


class _IdleWriter:
    """Guard every native mutation, including rollback."""
    def __init__(self, writer, guard):
        self.writer, self.guard = writer, guard

    def __getattr__(self, name):
        method = getattr(self.writer, name)
        if name not in ('create', 'add', 'place', 'cut', 'restore', 'rename', 'take_back'):
            return method
        def write(*args, **kwargs):
            self.guard()
            return method(*args, **kwargs)
        return write


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

    def plan_relaunch(self, tool, *, when_idle=False, then_sync=None, rename=None, _lifecycle_only=False, _reopen_ref=None):
        """Preview the exact writes and lifecycle, naming all replying chats."""
        if tool not in self.adapters or (rename is not None and then_sync is not None):
            raise NotAvailable()
        running = self.adapters[tool].app.running()
        chats = self._chats(tool)
        replying = tuple(self.adapters[tool].locator.resolve(c) for c, value in chats.items()
                         if value['condition']['replying'] is not False)
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
        if link_id is None and not _lifecycle_only:
            deliveries = tuple(self._sync_plan(tool, link.id)
                               for link in self.store.links() if tool in link.sides and not link.paused)
            writes = tuple(step for item in deliveries for step in item.steps)
        # A closed app needs only sync; Q13 never introduces a relaunch then.
        reopen = running or link_id is None
        steps = ((ApplyStep(tool, 'close'), ApplyStep(tool, 'wait_until_still')) if running else ())
        steps += writes + ((ApplyStep(tool, 'reopen'),) if reopen else ())
        notes = tuple(NoteRef('relaunch.replying_unknown' if chats[ref.id]['condition']['replying'] is None else 'relaunch.wait_reply' if when_idle else 'relaunch.replying_safe',
                             {'tool': tool, 'title': ref.name}) for ref in replying)
        if not notes:
            notes = (NoteRef('relaunch.order' if running else 'relaunch.closed_open' if reopen else 'relaunch.closed_sync', {'tool': tool}),)
        facts = asdict(self.adapters[tool].facts)
        facts = {key: getattr(value, 'value', value) for key, value in facts.items()}
        expires_at = (datetime.fromisoformat(self.clock.now()) + self.idle_timeout).isoformat() if when_idle else ''
        ref = self.adapters[tool].locator.resolve(linked[tool]) if tool in linked else _reopen_ref
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

    def apply(self, plan, *, write=None):
        """Execute the approved plan after fresh state and record checks."""
        adapter = self.adapters[plan.tool]
        if plan.when_idle and datetime.fromisoformat(self.clock.now()) >= datetime.fromisoformat(plan.expires_at):
            return RelaunchResult(plan.plan_id, False, error='IdleTimeout',
                                  notes=(NoteRef('relaunch.idle_timeout', {'tool': plan.tool}),))
        if plan.decision_needed:
            return RelaunchResult(plan.plan_id, False, error='ChatReplying', notes=plan.notes)
        replying = tuple(ref for ref in adapter.locator.chats() if adapter.state.condition(ref.id).replying is not False)
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
                if any(adapter.state.condition(ref.id).replying is not False for ref in adapter.locator.chats()):
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
                    unsafe = self._reply_refusals(plan.tool, current)
                    if unsafe:
                        return self._reopen(plan, False, 'ChatReplying', None, notes=unsafe)
                    still = not adapter.app.running() and all(
                        not v['condition']['open'] and v['condition']['replying'] is False for v in current.values())
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
            unsafe = self._reply_refusals(plan.tool, self._chats(plan.tool))
            if unsafe:
                return self._reopen(plan, False, 'ChatReplying', None, notes=unsafe)
            if write is not None:
                write_result = self._write_idle((plan.tool,), write)
                return self._reopen(plan, write_result.applied, getattr(write_result, 'error', ''), write_result)
            fresh_plans = tuple(self.preview.prepare(item.link_id, item.steps,
                                    {s: snap['chat_id'] for s, snap in item.snapshots.items()})
                                for item in plan.deliveries)
            for fresh in fresh_plans:
                if fresh.steps:
                    unsafe = self._reply_refusals(plan.tool, self._chats(plan.tool))
                    if unsafe:
                        return self._reopen(plan, False, 'ChatReplying', write_result, tuple(completed), notes=unsafe)
                    if all(s.action == 'rename' for s in fresh.steps):
                        self._write_idle((plan.tool,), lambda: Names(self.store, self.adapters, self.clock).apply(fresh))
                    else:
                        write_result = self._write_idle((plan.tool,), lambda: Applier(
                            self.store, self.adapters, self.clock, self.elapsed, self.wait).apply(fresh))
                        if not write_result.applied:
                            return self._reopen(plan, False, write_result.error, write_result, tuple(completed))
                    completed.append(fresh.link_id)
            return self._reopen(plan, True, '', write_result, tuple(completed))
        except _ReplyRefusal as error:
            receipt = error.write_result if error.write_result is not None else write_result
            return self._reopen(plan, False, 'ChatReplying', receipt,
                                tuple(completed), notes=error.notes)
        except Exception as error:
            if write_started or closed or (close_started and not adapter.app.running()):
                return self._reopen(plan, False, type(error).__name__, write_result, tuple(completed))
            raise

    def _guard_idle(self, tools):
        """The single positive-idle gate, including every chat in affected apps."""
        notes = tuple(note for tool in dict.fromkeys(tools)
                      for note in self._reply_refusals(tool, {
                          ref.id: {'ref': asdict(ref), 'condition': asdict(
                              self.adapters[tool].state.condition(ref.id))}
                          for ref in self.adapters[tool].locator.chats()}))
        if notes:
            raise _ReplyRefusal(notes)

    def _write_idle(self, tools, action):
        """Check after rebasing and again immediately before each native write.

        Some write services catch exceptions for rollback. Retain the named
        refusal here too so their generic failure receipts cannot hide it.
        """
        tools = tuple(dict.fromkeys(tools))
        self._guard_idle(tools)
        refused = []
        def guard():
            try:
                self._guard_idle(tools)
            except _ReplyRefusal as error:
                refused.extend(n for n in error.notes if n not in refused)
                raise
        writers = {tool: self.adapters[tool].writer for tool in tools}
        try:
            for tool, writer in writers.items():
                self.adapters[tool].writer = _IdleWriter(writer, guard)
            result = action()
            if refused:
                raise _ReplyRefusal(tuple(refused), result)
            return result
        finally:
            for tool, writer in writers.items():
                self.adapters[tool].writer = writer

    def _reply_refusals(self, tool, chats):
        """Require positive idle evidence and name every unsafe chat."""
        return tuple(NoteRef('relaunch.replying_unknown' if value['condition']['replying'] is None
                             else 'relaunch.replying_safe', {'tool': tool, 'title': value['ref']['name']})
                     for value in chats.values() if value['condition']['replying'] is not False)

    def _reopen(self, plan, applied, error, write_result, completed=(), notes=()):
        if isinstance(write_result, RelaunchResult):
            notes += tuple(n for n in write_result.notes if n not in notes)
        notes = notes + ((NoteRef('relaunch.partial', {'tool': plan.tool, 'n': len(completed)}),) if completed and not applied else ())
        if error and not applied and not any(n.id in ('relaunch.close_failed', 'relaunch.close_timeout', 'relaunch.replying_unknown', 'relaunch.replying_safe') for n in notes):
            notes += (NoteRef('relaunch.write_failed', {'tool': plan.tool}),)
        if not any(s.action == 'reopen' for s in plan.steps):
            return RelaunchResult(plan.plan_id, applied, error=error, notes=notes, write_result=write_result,
                                  completed_links=completed,
                                  reopen_error=getattr(write_result, 'reopen_error', ''))
        adapter = self.adapters[plan.tool]
        try:
            receipt = write_result
            while isinstance(receipt, RelaunchResult) and receipt.write_result is not None:
                receipt = receipt.write_result
            created = getattr(receipt, 'chat_id', '')
            chat_id = created if created and adapter.facts.opens_at_chat else plan.reopen_chat_id
            adapter.app.open(chat_id or None, plan.reopen_folder)
            if not adapter.app.running():
                raise NotAvailable()
        except Exception:
            return RelaunchResult(plan.plan_id, applied, error='ReopenFailed',
                notes=notes + (NoteRef('relaunch.reopen_failed_partial' if completed and not applied else
                                      'relaunch.reopen_failed' if applied else 'relaunch.reopen_failed_no_write',
                               {'tool': plan.tool}),), write_result=write_result, completed_links=completed, reopen_error='ReopenFailed')
        inner_failed = isinstance(write_result, RelaunchResult) and bool(write_result.reopen_error)
        return RelaunchResult(plan.plan_id, applied, opened=not inner_failed, error=error, notes=notes,
                              write_result=write_result, completed_links=completed,
                              reopen_error=write_result.reopen_error if inner_failed else '')


    def plan_brief_creation(self, briefs, token):
        """Bind an immutable creation artifact to a destination lifecycle."""
        payload = self.store.brief_plan(token)['payload']
        artifact = self.store.brief_artifact(payload['artifact_id'])
        request = artifact['request']
        briefs._validate_request(request)
        side = request['to']
        from ..ports.tool import ChatRef
        planned = briefs._plan_object(token, 'create', request, artifact['writer'], [], artifact)
        return self.plan_relaunch(side, _lifecycle_only=True,
            _reopen_ref=ChatRef('', planned.name, planned.folder, ''))

    def apply_brief_creation(self, plan, briefs, token):
        """Consume creation consent once and rebase only approved closure evidence."""
        payload = self.store.brief_plan(token)['payload']
        artifact = self.store.brief_artifact(payload['artifact_id'])
        briefs._validate_request(artifact['request'])
        self._validate(plan)
        if plan.decision_needed:
            return RelaunchResult(plan.plan_id, False, error='ChatReplying', notes=plan.notes)
        created = datetime.fromisoformat(payload['created_at'])
        now = datetime.fromisoformat(self.clock.now())
        if now < created or now - created > timedelta(minutes=10):
            raise ChatChanged()
        self.store.consume_brief_plan(token, 'create')
        def validate(original):
            request = deepcopy(original)
            target = request.get('target_observation')
            if target is not None:
                fresh = briefs._target_observation(plan.tool)
                normalized = {**fresh, 'running': target['running']}
                if json.dumps(normalized, sort_keys=True) != json.dumps(target, sort_keys=True):
                    raise ChatChanged()
                request['target_observation'] = fresh
            for side, earlier in request['snapshots'].items():
                if side != plan.tool:
                    continue
                fresh = self.preview._snapshot(side, earlier['chat_id'])
                normalized = deepcopy(fresh)
                for key in ('open', 'replying', 'app_running', 'app_started_at'):
                    normalized['condition'][key] = earlier['condition'][key]
                # JSON comparison accepts the store's tuple/list round trip only.
                if json.dumps(normalized, sort_keys=True) != json.dumps(earlier, sort_keys=True):
                    raise ChatChanged()
                request['snapshots'][side] = fresh
            briefs._validate_request(request)
        result = self.apply(plan, write=lambda: briefs._create(token, artifact, validate=validate))
        return result


@dataclass(frozen=True)
class ActionRelaunchPlan:
    """Bind a write preview to every app lifecycle it needs."""
    plan_id: str
    kind: str
    operation: object
    lifecycles: tuple[RelaunchPlan, ...]


def _action_id(kind, operation, lifecycles):
    data = {'kind': kind, 'operation': asdict(operation),
            'lifecycles': [asdict(p) for p in lifecycles]}
    return 'p_' + sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class RelaunchActions(Relaunch):
    """Reuse the relaunch lifecycle around creation, delivery and undo."""
    def plan_action(self, operation, kind):
        if kind == 'link':
            if operation.action not in ('create', 'full_copy'):
                return operation
            sides = (operation.target,)
        else:
            if getattr(operation, 'decision_needed', False):
                return operation
            sides = tuple(dict.fromkeys(s.side for s in operation.steps if s.action != 'move_link'))
        if any(not self.adapters[side].state.format_version().known for side in sides):
            return operation
        selected = []
        for side in sides:
            adapter = self.adapters[side]
            facts = adapter.facts
            # NOT_HELD + AT_ONCE is Q13: a running app keeps recent chats loaded.
            close = adapter.app.running() and facts.write_window != WriteWindow.ANY_TIME
            if kind == 'undo' and facts.can_release_chat and all(
                    self.adapters[side].state.condition(v['chat_id']).replying is False
                    for v in operation.snapshots.values() if v.get('side', side) == side):
                close = False
            create = kind == 'link' or kind == 'undo' and any(
                s.side == side and s.action == 'create_shorter' for s in operation.steps)
            if close or create and facts.new_chat_visible == Visibility.AFTER_RELAUNCH:
                from ..ports.tool import ChatRef
                if kind == 'link':
                    ref = ChatRef('', operation.name, operation.folder, '')
                else:
                    ref = self.adapters[side].locator.resolve(operation.snapshots[side]['chat_id'])
                selected.append(self.plan_relaunch(side, _lifecycle_only=True, _reopen_ref=ref))
        if not selected:
            return operation
        if kind == 'sync':
            steps = tuple(step for step in operation.steps if step.side not in {p.tool for p in selected})
            steps += tuple(step for p in selected for step in self._sync_steps(p.tool, operation.link_id))
            operation = self.preview.prepare(operation.link_id, steps,
                {s: v['chat_id'] for s, v in operation.snapshots.items()}, operation.decision_needed)
        lifecycles = tuple(selected)
        return ActionRelaunchPlan(_action_id(kind, operation, lifecycles), kind, operation, lifecycles)

    def _after_close(self, wrapped):
        operation = wrapped.operation
        selected = {p.tool for p in wrapped.lifecycles}
        def checked(earlier, current, side):
            normalized = deepcopy(current)
            if side in selected:
                if 'running' in normalized:
                    normalized['running'] = earlier['running']
                if 'condition' in normalized:
                    for key in ('open', 'replying', 'app_running', 'app_started_at'):
                        normalized['condition'][key] = earlier['condition'][key]
            if normalized != earlier:
                raise ChatChanged()
            return current
        if wrapped.kind == 'link':
            from .linker import Linker, _fingerprint
            service = Linker(self.store, self.adapters, self.clock)
            if service._records() != operation.records:
                raise ChatChanged()
            observed = {s: checked(v, service._observe(s, v.get('ref', {}).get('id')), s)
                        for s, v in operation.observations.items()}
            fresh = replace(operation, observations=observed)
            data = asdict(fresh)
            data.pop('plan_id')
            return replace(fresh, plan_id=_fingerprint(data))
        snapshots = {}
        for key, earlier in operation.snapshots.items():
            side = earlier.get('side', key)
            current = self.preview._snapshot(side, earlier['chat_id'])
            if 'side' in earlier:
                current['side'] = side
            snapshots[key] = checked(earlier, current, side)
        if wrapped.kind == 'undo':
            from .undo import UndoPreview
            preview = UndoPreview(self.store, self.adapters, self.clock)
            if preview._record(operation.link_id) != operation.record:
                raise ChatChanged()
            fresh = replace(operation, snapshots=snapshots)
            return replace(fresh, plan_id=preview._fingerprint(fresh))
        fresh = self.preview.prepare(operation.link_id, operation.steps,
            {s: v['chat_id'] for s, v in snapshots.items()}, operation.decision_needed)
        if fresh.record != operation.record:
            raise ChatChanged()
        return fresh

    def apply_action(self, wrapped, apply):
        if not isinstance(wrapped, ActionRelaunchPlan):
            return apply(wrapped)
        if wrapped.plan_id != _action_id(wrapped.kind, wrapped.operation, wrapped.lifecycles):
            raise ChatChanged()
        self._after_close(wrapped)
        for lifecycle in wrapped.lifecycles:
            self._validate(lifecycle)
            if lifecycle.decision_needed:
                return RelaunchResult(wrapped.plan_id, False, error='ChatReplying', notes=lifecycle.notes)
        def perform(index):
            if index == len(wrapped.lifecycles):
                fresh = self._after_close(wrapped)
                tools = ((fresh.target,) if wrapped.kind == 'link' else
                         tuple(s.side for s in fresh.steps if s.action != 'move_link'))
                return self._write_idle(tools, lambda: apply(fresh))
            return self.apply(wrapped.lifecycles[index], write=lambda: perform(index + 1))
        result = perform(0)
        return replace(result, plan_id=wrapped.plan_id)
