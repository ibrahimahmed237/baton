"""Preview and confirm the service's waiting-turn delivery plan."""
from .. import output
from ...domain.errors import NotAvailable
from . import command
from .relaunch_action import action_with_relaunch


def arguments(parser):
    parser.add_argument('--link', type=int)
    parser.add_argument('--to')


@command('sync', output.note('cli.sync_summary')['text'], arguments=arguments, plan=True)
def sync(ctx, args):
    if args.link is None and not ctx.confirm:
        raise NotAvailable()
    service = ctx.engine.applier
    def prepare(request):
        service.refresh(request['link_id'])
        planned = service.preview(request['link_id'])
        target = request['to']
        if target is not None:
            ctx.engine.adapter(target)
            if target not in planned.snapshots:
                raise NotAvailable()
            return service.prepare(planned.link_id, [s for s in planned.steps if s.side == target],
                                   {s: v['chat_id'] for s, v in planned.snapshots.items()},
                                   planned.decision_needed)
        return planned
    return action_with_relaunch(ctx, {'link_id': args.link, 'to': getattr(args, 'to', None)}, prepare,
                            lambda p: output.sync_action_plan(p, ctx.engine.reads.status(p.link_id)),
                            service.apply, 'sync')
