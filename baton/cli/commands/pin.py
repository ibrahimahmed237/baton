"""Immediate record-only pin action."""
from . import command
from .. import output
from ...services.continue_open import RecordActions


def arguments(parser):
    parser.add_argument('--turn', type=int, required=True)


@command('pin', output.note('cli.pin_summary')['text'], arguments=arguments)
def pin(ctx, args):
    value, notes = RecordActions(ctx.engine.store, ctx.engine.clock).turn('pin', args.turn)
    return {'turn': output.turn(value), 'notes': output.note_list(notes)}
