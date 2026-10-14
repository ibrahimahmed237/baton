"""Confirm selected native chat names through Names."""
from . import command
from .unlink import confirmed_action
from .. import output
from ...services.names import Names


def arguments(parser):
    parser.add_argument('--link', type=int)
    parser.add_argument('--name')
    parser.add_argument('--tools')


@command('rename', output.note('cli.rename_summary')['text'], arguments=arguments, plan=True)
def rename(ctx, args):
    service = Names(ctx.engine.store, ctx.engine.adapters, ctx.engine.clock)
    request = {k: getattr(args, k, None) for k in ('link', 'name', 'tools')}
    results = []
    def apply(planned):
        result = service.apply_action(planned)
        results.append(result)
        return result
    value = confirmed_action(ctx, request,
        lambda r: service.plan_action(r['link'], r['name'] or '', r['tools'].split(',') if r['tools'] else None),
        lambda p: output.rename_action_plan(p, service), apply)
    if results:
        value['notes'] = output.note_list(results[0].notes)
        value['renamed'] = list(results[0].renamed)
    return value
