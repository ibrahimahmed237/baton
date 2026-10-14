"""Copy a conversation using Linker's immutable creation plan."""
from . import command
from .link import chat_argument
from .link_action import link_action
from .. import output


def arguments(parser):
    parser.add_argument('--from', dest='source')
    parser.add_argument('--to')
    parser.add_argument('--status')
    parser.add_argument('--cancel')
    parser.add_argument('--and-link', action='store_true')


@command('copy', output.note('cli.copy_summary')['text'], arguments=arguments, plan=True)
def copy(ctx, args):
    service = ctx.engine.linker
    request = {k: getattr(args, k, None) for k in ('source', 'to', 'and_link')}
    def prepare(r):
        source, ident = chat_argument(r['source'], True)
        return service.plan_copy(source, ident, r['to'], bool(r['and_link']))
    return link_action(ctx, args, request, prepare)
