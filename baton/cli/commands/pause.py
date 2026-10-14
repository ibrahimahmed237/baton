"""Immediate record-only pause action."""
from . import command
from .. import output
from ...services.continue_open import RecordActions


def arguments(parser):
    parser.add_argument('--link', type=int, required=True)


@command('pause', output.note('cli.pause_summary')['text'], arguments=arguments)
def pause(ctx, args):
    value, notes = RecordActions(ctx.engine.store, ctx.engine.clock).link('pause', args.link)
    return {'link_id': value.id, 'paused': value.paused, 'notes': output.note_list(notes)}
