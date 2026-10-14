"""Exact relaunch approvals and bounded, pollable idle requests."""
from dataclasses import asdict
from ...services import background_relaunch as orchestration
from ...services.background_relaunch import restore_plan
from ...services.background_brief import configure_retention

from . import command
from .brief import dispatch_background
from .. import output
from ...domain.errors import ChatChanged, NotAvailable
from ...services.background import Background


def arguments(parser):
    parser.add_argument('--tool')
    parser.add_argument('--when-idle', action='store_true')
    parser.add_argument('--then-sync', type=int)
    parser.add_argument('--status')
    parser.add_argument('--cancel')


def render_result(planned, result):
    """Serialize the service's relaunch receipt."""
    value = output.background_relaunch_plan(planned)
    value.update(applied=result.applied, opened=result.opened,
        completed_links=list(result.completed_links), waiting=False,
        notes=output.note_list(result.notes or planned.notes))
    if result.error:
        value['error'] = {'kind': output.snake_case(result.error), 'note': value['notes'][0]}
    return value


def unknown_refusal(tool, refs):
    return {'applied': False, 'decision_needed': True,
            'replying': [output.chat_from_ref(tool, ref) for ref in refs],
            'notes': [output.note('relaunch.replying_unknown', {'tool': tool, 'title': ref.name}) for ref in refs],
            'error': {'kind': 'replying_unknown', 'note': output.note('relaunch.replying_unknown',
                         {'tool': tool, 'title': refs[0].name})}}


@command('relaunch', output.note('cli.relaunch_summary')['text'], arguments=arguments, plan=True)
def relaunch(ctx, args):
    configure_retention(ctx.engine)
    background = Background(ctx.engine.store, ctx.engine.clock)
    if getattr(args, 'cancel', None):
        return background.stop(args.cancel)
    if getattr(args, 'status', None):
        return background.status(args.status)
    if ctx.confirm:
        stored = ctx.engine.plans.store.load(ctx.confirm)
        if stored is None:
            raise ChatChanged()
        # The exact original expiry and allowed idle transitions belong to E13.
        request = ctx.confirmed(lambda r: restore_plan(r['plan']).plan_id)
        planned = restore_plan(request['plan'])
        unknown, refusal, ident = orchestration.schedule(ctx.engine, planned)
        if unknown:
            return unknown_refusal(planned.tool, unknown)
        if refusal:
            return {**output.background_relaunch_plan(planned, ctx.confirm),
                    'error': {'kind': 'chat_replying', 'note': output.note_list(planned.notes)[0]}}
        dispatch_background(ctx.engine, lambda engine: orchestration.relaunch_worker(engine, ident, render_result, unknown_refusal))
        return {**background.status(ident), 'applied': False, 'expires_at': planned.expires_at}
    tool = getattr(args, 'tool', None)
    if tool is None:
        raise NotAvailable()
    planned, unknown = orchestration.preview(ctx.engine, tool,
        bool(getattr(args, 'when_idle', False)), getattr(args, 'then_sync', None))
    if unknown:
        return unknown_refusal(tool, unknown)
    ident = ctx.remember(planned.plan_id, {'plan': asdict(planned)})
    return output.background_relaunch_plan(planned, ident)
