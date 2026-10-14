"""Preview and confirm removing a link without changing its chats."""
from .. import output
from ...domain.errors import BatonError, ChatChanged, NotAvailable
from . import command


def confirmed_action(ctx, request, prepare, serialize, apply):
    """Confirm the stored request through C1's command and fingerprint guard."""
    if ctx.confirm:
        held = []
        def again(stored):
            try:
                planned = prepare(stored)
            except (BatonError, KeyError):
                raise ChatChanged() from None
            held.append(planned)
            return planned.plan_id
        ctx.confirmed(again)
        planned = held[0]
        value = serialize(planned)
        result = apply(planned)
        value['applied'] = result.applied
        value['confirmation'] = None
        return output.action_receipt(value, result)
    planned = prepare(request)
    value = serialize(planned)
    value['plan_id'] = ctx.remember(planned.plan_id, request)
    return value


def arguments(parser):
    parser.add_argument('--link', type=int)


@command('unlink', output.note('cli.unlink_summary')['text'], arguments=arguments, plan=True)
def unlink(ctx, args):
    if args.link is None and not ctx.confirm:
        raise NotAvailable()
    service = ctx.engine.linker
    return confirmed_action(ctx, {'link_id': args.link},
                            lambda r: service.plan_unlink(r['link_id']),
                            output.unlink_action_plan, service.apply)
