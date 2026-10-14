"""Hook orchestration through existing refresh, delivery and digest services."""
from dataclasses import replace
from ..notes.catalogue import get
from ..services.mapping import for_target
from ..services.digest import DigestBuilder
from ..cli.tools import label


def catch_up(engine, tool, call):
    link = engine.store.link_for(tool, call.chat)
    if link is None or link.paused:
        return ''
    applier = engine.applier
    applier.refresh(link.id)
    plan = applier.preview(link.id)
    if plan.decision_needed:
        return ''
    step = next((s for s in plan.steps if s.side == tool and s.action == 'attach'), None)
    if step is None:
        return ''
    # Installed OpenCode's older plugin supplies only --chat. Stable native
    # prompt identity is a conservative fallback until its generator carries ID.
    turn = call.turn
    if not turn:
        observed = engine.adapter(tool).reader.read(call.chat)
        turn = observed[-1].id if observed else 'first-message'
    if any(e.kind == 'attached' and e.side == tool and e.detail.get('message_id') == turn
           for e in engine.store.history(link.id)):
        return ''
    digest = DigestBuilder(engine.store, {s: a.reader for s, a in engine.adapters.items()}, engine.clock, label)
    turns = [for_target(t, replace(engine.adapter(tool).facts, replays_tool_calls=False)) for t in step.turns]
    blocks = [get('catch_up.turn').render({'at': t.started_at,
              'body': '\n\n'.join(m.text for m in (t.prompt, *t.messages) if m.text)}).template
              for t in turns]
    text = digest.attached_text(digest.for_side(link.id, tool), blocks)
    notice = None
    if engine.settings_read.get()['notice_on_attach']:
        other, = link.others(tool)
        notice = get('catch_up.notice_one' if len(step.turn_ids) == 1 else 'catch_up.notice').render({'n': len(step.turn_ids), 'tool': label(other),
            'titles': ', '.join('"' + t.prompt.text.splitlines()[0] + '"' for t in step.turns)}).template
    reply = engine.adapter(tool).hooks.attach_reply(text, notice)
    applier.record_attached(link.id, tool, step.turn_ids, turn)
    return reply


def notify(engine, tool, call):
    result = {'synced': [], 'queued': [], 'offers': []}
    link = engine.store.link_for(tool, call.chat)
    if link is None:
        return result
    engine.store.record_event(link.id, call.event, tool, engine.clock.now(), detail={'message_id': call.turn})
    if link.paused or call.event == 'busy':
        result['queued'].append(link.id)
        return result
    applier = engine.applier
    applier.refresh(link.id)
    plan = applier.preview(link.id)
    if not plan.decision_needed:
        for step in plan.steps:
            state = engine.adapter(step.side).state.condition(link.chat(step.side))
            # Automatic hooks never release, close, create or write a held chat.
            if step.action != 'add' or step.needs or state.open or state.replying:
                continue
            last = next((e for e in engine.store.history(link.id)
                         if e.side == step.side and e.kind in ('busy', 'idle', 'turn_end')), None)
            if last is not None and last.kind == 'busy':
                continue
            try:
                selected = applier.prepare(link.id, [step], link.chats)
                applied = applier.apply(selected)
                delivered = applied.applied
            except Exception:
                delivered = False
            if not delivered:
                from ..cli.output import note
                result['offers'].append(note('hook.delivery_failed', {'tool': step.side}))
                result['queued'].append(link.id)
                result['synced'] = [i for i in result['synced'] if i != link.id]
                break
            if link.id not in result['synced']:
                result['synced'].append(link.id)
    if link.id not in result['queued'] and (plan.decision_needed or any(t.states.get(side) in ('waiting', 'attach_pending')
                                   for t in engine.store.turns(link.id) for side in link.chats)):
        result['queued'].append(link.id)
    return result
