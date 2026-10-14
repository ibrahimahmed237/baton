"""Change the counterpart while retaining the selected side."""
from . import command
from .link import chat_argument
from .link_action import link_action
from .. import output


def arguments(parser):
    parser.add_argument('--link', type=int)
    parser.add_argument('--to')
    parser.add_argument('--status')
    parser.add_argument('--cancel')
    parser.add_argument('--keep')
    parser.add_argument('--mode', default='full_copy')


@command('relink', output.note('cli.relink_summary')['text'], arguments=arguments, plan=True)
def relink(ctx, args):
    service = ctx.engine.linker
    request = {k: getattr(args, k, None) for k in ('link', 'to', 'keep', 'mode')}
    def prepare(r):
        target, ident = chat_argument(r['to'])
        return service.plan_relink(r['link'], target, ident, r['mode'] or 'full_copy', r['keep'])
    return link_action(ctx, args, request, prepare)
