"""Relaunch approval, idle retries and lock-boundary cancellation policy."""
from dataclasses import asdict
from time import sleep
from ..ports.tool import ChatRef
from .background import Background
from .delivery_plan import ApplyStep, PreparedPlan
from .observations import decode_turns
from .relaunch import Relaunch, RelaunchPlan, RelaunchResult
from .noteformat import NoteRef


def restore_plan(data):
    def step(value):
        return ApplyStep(**{**value, 'turns': tuple(decode_turns(value['turns'])),
                           'turn_ids': tuple(value['turn_ids']), 'needs': tuple(value['needs']),
                           'alternatives': tuple(value['alternatives'])})
    def snapshot(value):
        return {**value, 'facts': {**value['facts'], 'checked_versions': tuple(value['facts']['checked_versions'])},
                'turns': [asdict(t) for t in decode_turns(value['turns'])]}
    def delivery(value):
        record = dict(value['record'])
        if record:
            record['history'] = [{**e, 'turn_ids': tuple(e['turn_ids'])} for e in record['history']]
        return PreparedPlan(**{**value, 'record': record,
            'snapshots': {s: snapshot(v) for s, v in value['snapshots'].items()},
            'steps': tuple(step(s) for s in value['steps'])})
    return RelaunchPlan(**{**data, 'facts': {**data['facts'], 'checked_versions': tuple(data['facts']['checked_versions'])},
        'chats': {c: {**v, 'turns': [asdict(t) for t in decode_turns(v['turns'])]} for c, v in data['chats'].items()},
        'steps': tuple(step(s) for s in data['steps']),
        'delivery': delivery(data['delivery']), 'deliveries': tuple(delivery(d) for d in data['deliveries']),
        'replying': tuple(ChatRef(**r) for r in data['replying']),
        'notes': tuple(NoteRef(*n) for n in data['notes'])})


def unknown_chats(engine, tool):
    return [ref for ref in engine.adapter(tool).locator.chats()
            if engine.adapter(tool).state.condition(ref.id).replying is None]


def relaunch_worker(engine, ident, render, refusal):
    background = Background(engine.store, engine.clock)
    data = engine.store.brief_artifact(ident)['request']['plan']
    planned = restore_plan(data)
    service = Relaunch(engine.store, engine.adapters, engine.clock)
    try:
        while background.status(ident)['state'] == 'pending':
            with engine.command_lock():
                if background.status(ident)['state'] != 'pending':
                    return
                unknown = unknown_chats(engine, planned.tool)
                if unknown:
                    background.finish(ident, refusal(planned.tool, unknown))
                    return
                result = service.apply(planned)
                if not result.waiting:
                    value = render(planned, result)
                    background.finish(ident, value)
                    return
            sleep(.1)
    except Exception as error:
        if background.status(ident)['state'] == 'pending':
            background.finish(ident, {'applied': False, 'error': {'kind': type(error).__name__}})


def approve(engine, planned):
    """Validate original consent and refuse unknown/replying state before scheduling."""
    unknown = unknown_chats(engine, planned.tool)
    if not unknown:
        Relaunch(engine.store, engine.adapters, engine.clock)._validate(planned)
    return unknown


def preview(engine, tool, when_idle=False, then_sync=None):
    """Resolve unknown reply state before producing a relaunch preview."""
    unknown = unknown_chats(engine, tool)
    if unknown:
        return None, unknown
    return Relaunch(engine.store, engine.adapters, engine.clock).plan_relaunch(
        tool, when_idle=when_idle, then_sync=then_sync), ()


def schedule(engine, planned):
    """Approve reply-state policy and persist a cancellable request."""
    unknown = approve(engine, planned)
    if unknown:
        return unknown, None, None
    if planned.decision_needed:
        return (), RelaunchResult(planned.plan_id, False, error='ChatReplying', notes=planned.notes), None
    ident = Background(engine.store, engine.clock).create('relaunch', {'plan': asdict(planned)})
    return (), None, ident
