"""List native chat references, optionally in one exact folder."""
from .. import output
from . import command

def arguments(parser):
    """Register this read command’s documented arguments."""
    parser.add_argument('--tool', required=True)
    parser.add_argument('--folder')

@command('chats', 'List chats', arguments=arguments)
def chats(ctx, args):
    """Call the recovery-free projection and serialize the contract result."""
    return {'chats': [output.read_chat(item) for item in ctx.engine.reads.chats(args.tool, args.folder)]}
