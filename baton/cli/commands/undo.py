"""Preview and confirm taking a chat back to an event."""
from .. import output
from ...domain.errors import NotAvailable
from . import command
from .relaunch_action import action_with_relaunch


def arguments(parser):
    parser.add_argument('--link', type=int)
    parser.add_argument('--to', '--event', dest='event', type=int)


@command('undo', output.note('cli.undo_summary')['text'], arguments=arguments, plan=True)
def undo(ctx, args):
    service = ctx.engine.undo
    def prepare(request):
        link = request['link_id']
        if link is None:
            owners = [l.id for l in ctx.engine.store.links()
                      if any(e.id == request['event_id'] for e in ctx.engine.store.history(l.id))]
            if len(owners) != 1:
                raise NotAvailable()
            link = owners[0]
        return service.plan(link, request['event_id'])
    return action_with_relaunch(ctx, {'link_id': args.link, 'event_id': args.event}, prepare,
                       output.undo_plan, service.apply, 'undo')
