"""Immediate record-only keep action."""
from . import command
from .. import output
from ...services.continue_open import RecordActions


def arguments(parser):
    parser.add_argument('--turn', type=int, required=True)


@command('keep', output.note('cli.keep_summary')['text'], arguments=arguments)
def keep(ctx, args):
    value, notes = RecordActions(ctx.engine.store, ctx.engine.clock).turn('keep', args.turn)
    return {'turn': output.turn(value), 'notes': output.note_list(notes)}
