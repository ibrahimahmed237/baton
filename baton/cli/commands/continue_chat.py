"""Deliver the selected link side before opening it."""
from . import command
from .. import output
from ...domain.errors import BatonError, ChatChanged
from ...services.continue_open import ContinueOpen


def arguments(parser):
    parser.add_argument('--link', type=int)
    parser.add_argument('--in', dest='destination')


@command('continue', output.note('cli.continue_summary')['text'], arguments=arguments, plan=True)
def continue_chat(ctx, args):
    service = ContinueOpen(ctx.engine.store, ctx.engine.adapters, ctx.engine.applier)
    def prepare(r):
        return service.plan(r['link'], r['destination'])
    if ctx.confirm:
        held = []
        def again(request):
            try:
                value = prepare(request)
            except (BatonError, KeyError):
                raise ChatChanged() from None
            held.append(value)
            return value.plan_id
        ctx.confirmed(again)
        planned = held[0]
        value = output.continue_action_plan(planned, ctx.engine.reads.status(planned.link_id))
        result = service.apply(planned)
        value.update(applied=result['applied'], opened=result['opened'], confirmation=None)
        value['notes'] += output.note_list(result['notes'])
        return value
    request = {'link': args.link, 'destination': getattr(args, 'destination', None)}
    planned = prepare(request)
    value = output.continue_action_plan(planned, ctx.engine.reads.status(planned.link_id))
    value['plan_id'] = ctx.remember(planned.plan_id, request)
    return value
