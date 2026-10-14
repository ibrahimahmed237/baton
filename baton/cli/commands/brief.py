"""Separate consent for background generation and immutable brief creation."""
from ...services import background_worker
from ...services import background_brief as orchestration
from . import Context

from . import command
from .. import output
from ..wiring import build
from ...domain.errors import NotAvailable
from ...services.background import Background


def arguments(parser):
    parser.add_argument('--link', type=int)
    parser.add_argument('--to')
    parser.add_argument('--writer', default='auto')
    parser.add_argument('--status')
    parser.add_argument('--cancel')
    parser.add_argument('--background', action='store_true')


def dispatch_background(engine, work):
    """Supply engine construction to the service-owned worker lifecycle."""
    return background_worker.dispatch_background(engine, work, build)


def remember_brief(ctx, planned, job=None):
    """Register standalone creation through the shared brief lifecycle."""
    from .link_action import remember_brief as register
    from ...services.brief_link import BriefLink
    review = register(ctx.engine, ctx.command, BriefLink(ctx.engine).creation_review(planned))
    if job:
        ctx.engine.store.own_background_resources(job, [('cli_plan', planned.plan_id)])
    return review


def generate_brief(engine, ident, token):
    """Serialize and register the service's immutable creation review."""
    return orchestration.generate_brief(engine, ident, token,
        lambda planned: remember_brief(Context(engine, 'brief'), planned, ident))


@command('brief', output.note('cli.brief_summary')['text'], arguments=arguments, plan=True)
def brief(ctx, args):
    orchestration.configure_retention(ctx.engine)
    background = Background(ctx.engine.store, ctx.engine.clock)
    if getattr(args, 'cancel', None):
        return output.background_status(background.stop(args.cancel))
    if getattr(args, 'status', None):
        return output.background_status(background.status(args.status))
    if ctx.confirm:
        stored = ctx.confirmed(lambda r: r['service_plan'])
        token = stored['service_plan']
        stage = ctx.engine.store.brief_plan(token)['stage']
        if stage == 'generate':
            ident = background.create('brief', {'service_plan': token})
            if getattr(args, 'background', False):
                dispatch_background(ctx.engine, lambda engine: generate_brief(engine, ident, token))
                return output.background_status(background.status(ident))
            orchestration.generate_brief(ctx.engine, ident, token, lambda planned: remember_brief(ctx, planned, ident), locked=True)
            value = background.status(ident)
            rendered = output.background_status(value)
            return {**rendered.get('result', rendered), 'request_id': ident, 'state': value['state']}
        from ...services.brief_link import BriefLink
        _, result = BriefLink(ctx.engine).confirm(token, stored['review'], dispatch_background,
            lambda engine, planned: remember_brief(Context(engine, 'brief'), planned))
        return output.action_receipt({**stored.get('review', {}), 'plan_id': token,
            'applied': result.applied, 'notes': [output.note('brief.summary_receipt')] if result.applied else [],
            'confirmation': None}, result)
    link_id = getattr(args, 'link', None)
    if link_id is None:
        raise NotAvailable()
    destination = getattr(args, 'to', None)
    writer = getattr(args, 'writer', 'auto')
    planned = orchestration.plan_brief(ctx.engine, link_id, destination, writer)
    destination = planned.side
    value = remember_brief(ctx, planned)
    value['notes'].append(output.note('brief.writer_order' if writer == 'auto' else
        'brief.writer_requested' if writer != 'offline' else 'brief.writer_offline', {'tool': destination, 'writer_tool': writer}))
    return value
