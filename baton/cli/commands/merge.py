"""Read choices and confirm an exact merge decision."""
from .. import output
from ..plans import StoredPlan
from ...domain.errors import ChatChanged, BatonError, OrderNotAllowed, NotAvailable
from ...services.merger import Merger
from . import command


def arguments(parser):
    parser.add_argument('--link', type=int)
    parser.add_argument('--show', action='store_true')
    choice = parser.add_mutually_exclusive_group()
    choice.add_argument('--preset')
    choice.add_argument('--order')
    choice.add_argument('--keep')
    choice.add_argument('--split', action='store_true')
    parser.add_argument('--first')


def action_plan(ctx, request, prepare, serialize, apply):
    """Keep the service's exact plan ID and consume it through the command guard."""
    if ctx.confirm:
        held = []
        def again(stored):
            try:
                planned = prepare(stored)
            except BatonError:
                raise ChatChanged() from None
            held.append(planned)
            return planned.plan_id
        ctx.confirmed(again)
        planned = held[0]
        value = serialize(planned)
        result = apply(planned)
        value.update(applied=result.applied, event_id=result.event_id)
        if result.error:
            value['error'] = {'kind': output.snake_case(result.error), 'note': output.note('error.unexpected')}
        return value
    planned = prepare(request)
    ctx.engine.plans.purge()
    ctx.engine.plans.store.save(StoredPlan(planned.plan_id, planned.plan_id, ctx.command,
                                         request, ctx.engine.clock.now()))
    return serialize(planned)


@command('merge', 'Show merge choices', arguments=arguments, plan=True)
def merge(ctx, args):
    if args.link is None and not ctx.confirm:
        raise NotAvailable()
    preset = getattr(args, 'preset', None) or ''
    if preset == 'one_side_first':
        first = getattr(args, 'first', None)
        if not first:
            raise OrderNotAllowed()
        preset = first + '_first'
    order = getattr(args, 'order', None)
    if order is not None:
        try:
            order = [int(i) for i in order.split(',')]
        except ValueError:
            raise OrderNotAllowed() from None
    if getattr(args, 'show', False):
        fresh = ctx.engine.reads.merge_show(args.link)
        value = Merger.present(fresh, ctx.engine.adapters, order=order, preset=preset)
        status = ctx.engine.reads.status(args.link)
        for side, outcome in value['outcome'].items():
            if outcome == 'keeps_chat':
                value['notes'] += status['side_notes'][side]
        return output.read_merge(value)
    request = {'link_id': args.link, 'preset': preset, 'order': order,
               'keep': getattr(args, 'keep', None) or '', 'split': bool(getattr(args, 'split', False))}
    service = ctx.engine.merger
    result = action_plan(ctx, request, lambda r: service.plan(**r),
                         lambda p: output.merge_plan(p, service), service.apply)
    if result['applied']:
        result['notes'] = [output.note('merge.open', {'tool': s['tool'], 'tool_id': s['tool'],
                           'chat_id': ctx.engine.store.get_link(result['link_id']).chat(s['tool'])})
                           for s in result['steps'] if s['action'] == 'create']
        if result.get('split'):
            result['notes'].append(output.note('merge.completed_split'))
        elif result.get('keep'):
            kept = result['keep']
            other, = ctx.engine.store.get_link(result['link_id']).others(kept)
            result['notes'].append(output.note('merge.completed_keep', {'tool': kept, 'other_tool': other}))
        else:
            result['notes'].append(output.note('merge.completed'))
            link = ctx.engine.store.get_link(result['link_id'])
            for side in link.sides:
                if not any(s['tool'] == side and s['action'] == 'create' for s in result['steps']):
                    result['notes'].append(output.note('merge.completed_side', {'tool': side}))
        if not result.get('split'):
            link = ctx.engine.store.get_link(result['link_id'])
            status = ctx.engine.reads.status(link.id)
            for side in link.sides:
                result['notes'] += [output.note(ident, values) for ident, values in status['side_notes'][side]]
        result['confirmation'] = None
    return result
