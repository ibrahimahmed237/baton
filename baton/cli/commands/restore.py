"""Preview and confirm restoring a saved boundary."""
from .. import output
from . import command
from .merge import action_plan


def arguments(parser):
    parser.add_argument('--event', type=int)


@command('restore', output.note('cli.restore_summary')['text'], arguments=arguments, plan=True)
def restore(ctx, args):
    service = ctx.engine.undo
    return action_plan(ctx, {'event_id': args.event}, lambda r: service.restore(r['event_id']),
                       output.undo_plan, service.apply)
