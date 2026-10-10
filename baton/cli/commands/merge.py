"""Recovery-free decision screen; execution is a later command package."""
from .. import output
from . import command

def arguments(parser):
    """Register this read command’s documented arguments."""
    parser.add_argument('--link', required=True, type=int)
    parser.add_argument('--show', required=True, action='store_true')

@command('merge', 'Show merge choices', arguments=arguments)
def merge(ctx, args):
    """Call the recovery-free projection and serialize the contract result."""
    return output.read_merge(ctx.engine.reads.merge_show(args.link))
