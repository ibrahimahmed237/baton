"""Completed link events; no prospective plan text."""
from .. import output
from . import command

@command('history', output.note('cli.history_summary')['text'], arguments=lambda p: p.add_argument('--link', required=True, type=int))
def history(ctx, args):
    """Call the recovery-free projection and serialize the contract result."""
    return output.read_history(ctx.engine.reads.history(args.link))
