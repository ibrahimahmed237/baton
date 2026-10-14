"""Link requests are planned and applied entirely by Linker."""
from . import command
from .link_action import link_action
from .. import output
from ...domain.errors import NotAvailable


def chat_argument(value, required=False):
    if not value or ':' not in value:
        if required or not value:
            raise NotAvailable()
        return value, None
    side, ident = value.split(':', 1)
    if not side or not ident:
        raise NotAvailable()
    return side, ident


def arguments(parser):
    parser.add_argument('--from', dest='source')
    parser.add_argument('--to')
    parser.add_argument('--status')
    parser.add_argument('--cancel')
    parser.add_argument('--link', type=int)
    parser.add_argument('--replace')
    parser.add_argument('--mode', default='full_copy')


@command('link', output.note('cli.link_summary')['text'], arguments=arguments, plan=True)
def link(ctx, args):
    service = ctx.engine.linker
    request = {k: getattr(args, k, None) for k in ('source', 'to', 'link', 'replace', 'mode')}
    return link_action(ctx, args, request, lambda r: prepare(service, r))


def prepare(service, request):
    if request['replace']:
        if request['link'] is None or request['mode'] != 'full_copy':
            raise NotAvailable()
        return service.plan_full_copy(request['link'], request['replace'])
    source, ident = chat_argument(request['source'], True)
    target, target_id = chat_argument(request['to'])
    return service.plan_link(source, ident, target, target_id, request['mode'] or 'full_copy')
