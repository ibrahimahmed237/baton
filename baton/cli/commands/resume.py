"""Immediate record-only resume action."""
from . import command
from .. import output
from ...services.continue_open import RecordActions


def arguments(parser):
    parser.add_argument('--link', type=int, required=True)


@command('resume', output.note('cli.resume_summary')['text'], arguments=arguments)
def resume(ctx, args):
    value, notes = RecordActions(ctx.engine.store, ctx.engine.clock).link('resume', args.link)
    return {'link_id': value.id, 'paused': value.paused, 'notes': output.note_list(notes)}
