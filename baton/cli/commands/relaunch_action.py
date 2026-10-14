"""Expose executable lifecycle choices through ordinary single-use plan gates."""
from hashlib import sha256
from .. import output
from ..plans import StoredPlan
from .unlink import confirmed_action
from ...services.relaunch import ActionRelaunchPlan, RelaunchActions


def action_with_relaunch(ctx, request, prepare, serialize, apply, kind):
    service = RelaunchActions(ctx.engine.store, ctx.engine.adapters, ctx.engine.clock)
    def preparing(data):
        operation = prepare(data)
        return service.plan_action(operation, kind) if data.get('_relaunch', True) else operation
    def rendering(planned):
        if not isinstance(planned, ActionRelaunchPlan):
            return serialize(planned)
        value = serialize(planned.operation)
        value['plan_id'] = planned.plan_id
        value['confirmation'] = output.note('plan.unavailable' if any(p.decision_needed for p in planned.lifecycles)
                                            else 'plan.confirm_relaunch', {'tool': planned.lifecycles[0].tool})
        value['decision_needed'] = any(p.decision_needed for p in planned.lifecycles)
        if any(not v.get('format', {}).get('known', True) for v in getattr(planned.operation, 'observations', {}).values()):
            value['confirmation'] = output.note('plan.unavailable')
        for lifecycle in reversed(planned.lifecycles):
            before = [output.step(lifecycle.tool, s.action, ()) for s in lifecycle.steps
                      if s.action in ('close', 'wait_until_still')]
            after = [output.step(lifecycle.tool, 'reopen', ())]
            value['steps'] = before + value['steps'] + after
            if kind == 'link':
                ident = 'new_chat.relaunch' if 'relaunch_to_see' in planned.operation.needs else 'new_chat.running_relaunch'
                value['notes'] = [n for n in value['notes'] if n['id'] not in
                                  ('status.new_chat_relaunch', 'create.close_manually')]
            elif kind == 'sync':
                ident = 'write.app_must_close' if 'app_closed' in planned.operation.snapshots[lifecycle.tool]['facts']['write_window'] else 'write.chat_open'
            else:
                ident = 'write.app_must_close' if self_window(planned.operation, lifecycle.tool) else 'relaunch.order'
            if ident:
                count = sum(len(s.turn_ids) for s in planned.operation.steps if s.side == lifecycle.tool) if kind != 'link' else len(planned.operation.turns)
                note = output.note(ident, {'tool': lifecycle.tool, 'n': count,
                                           **({'running': lifecycle.running,
                                               'opens_at_chat': ctx.engine.adapters[lifecycle.tool].facts.opens_at_chat} if kind == 'link' else {}),
                                           'button_ids': ['cancel'] if lifecycle.decision_needed else ['close_sync_reopen', 'confirm', 'cancel']})
                value['notes'] = [n for n in value['notes'] if n['id'] != ident or n['values'].get('tool') != note['values']['tool']]
                value['notes'].append(note)
            if lifecycle.decision_needed:
                value['notes'] += [output.note(n.id, {**n.values, 'button_ids': ['cancel']})
                                   for n in lifecycle.notes] if kind == 'link' else output.note_list(lifecycle.notes)
        for step in value['steps']:
            if kind in ('sync', 'undo') and step['action'] not in ('close', 'wait_until_still', 'reopen'):
                snapshot = planned.operation.snapshots[step['tool']]
                ref = snapshot['ref']
                step['chat'] = output.chat(step['tool'], snapshot['chat_id'], ref['name'], ref['folder'], ref['updated_at'])
            step['notes'] = [n for n in value['notes'] if n['values'].get('tool') == output.label(step['tool'])]
        return value
    receipts = []
    def applying(p):
        result = service.apply_action(p, apply)
        receipts.append(result)
        return result
    value = confirmed_action(ctx, request, preparing, rendering, applying)
    if receipts and hasattr(receipts[0], 'event_id'):
        value['event_id'] = receipts[0].event_id
    if not ctx.confirm and kind == 'undo':
        stored = ctx.engine.plans.store.load(value['plan_id'])
        ctx.engine.plans.store.delete(value['plan_id'])
        value['plan_id'] = stored.fingerprint
        ctx.engine.plans.store.save(StoredPlan(value['plan_id'], stored.fingerprint, ctx.command,
                                              stored.arguments, stored.stored_at))
    if not ctx.confirm and any(s['action'] == 'reopen' for s in value['steps']):
        alias = 'p_' + sha256(('relaunch:' + value['plan_id']).encode()).hexdigest()
        ctx.engine.plans.store.save(StoredPlan(alias, ctx.engine.plans.store.load(value['plan_id']).fingerprint,
            'relaunch', {'action_command': ctx.command, 'action_plan_id': value['plan_id']}, ctx.engine.clock.now()))
        for note in value['notes']:
            if any(b['id'] == 'close_sync_reopen' or b['id'] == 'confirm' and note['id'] == 'relaunch.order' for b in note['buttons']):
                note.update(output.note(note['id'], {**note['values'], 'relaunch_plan_id': alias}))
        # An add/attach preview remains available as an explicitly separate choice.
        ordinary = prepare(request)
        possible = kind == 'sync' and any(s.action == 'attach' for s in ordinary.steps)
        later = kind == 'link' and ctx.engine.linker.confirmation_available(ordinary)
        if possible or later:
            data = {**request, '_relaunch': False}
            ident = ctx.remember(ordinary.plan_id, data)
            choice = 'attach' if possible else 'sync_relaunch_later'
            for note in value['notes']:
                if any(b['id'] == 'close_sync_reopen' or b['id'] == 'confirm' and note['id'] == 'relaunch.order' for b in note['buttons']):
                    # Each alternative keeps its own request, fingerprint and command gate.
                    allowed = [*note['values'].get('button_ids', ()), choice]
                    note.update(output.note(note['id'], {**note['values'], 'button_ids': allowed,
                                                        choice + '_plan_id': ident,
                                                        choice + '_command': ctx.command}))
    return value


def self_window(operation, tool):
    return operation.snapshots[tool]['facts']['write_window'] == 'app_closed'
