"""Immediate record-only send action."""
from . import command
from .. import output
from ...services.continue_open import RecordActions


def arguments(parser):
    parser.add_argument('--turn', type=int, required=True)


@command('send', output.note('cli.send_summary')['text'], arguments=arguments)
def send(ctx, args):
    value, notes = RecordActions(ctx.engine.store, ctx.engine.clock).turn('send', args.turn)
    return {'turn': output.turn(value), 'notes': output.note_list(notes)}
