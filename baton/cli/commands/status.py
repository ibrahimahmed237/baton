"""Current committed delivery and observed chat state."""
from .. import output
from . import command

def arguments(parser):
    """Register this read command’s documented arguments."""
    parser.add_argument('--link', required=True, type=int)
    parser.add_argument('--messages', action='store_true')

@command('status', output.note('cli.status_summary')['text'], arguments=arguments)
def status(ctx, args):
    """Call the recovery-free projection and serialize the contract result."""
    return output.read_status(ctx.engine.reads.status(args.link, args.messages), args.messages)
