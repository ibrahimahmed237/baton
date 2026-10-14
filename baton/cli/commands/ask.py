"""Preview a second opinion, then review before a separately confirmed add."""
from . import command
from .brief import dispatch_background
from ...services.background_brief import configure_retention
from ...services.background_opinion import generate_opinion, immediate_opinion
from .. import output
from ..tools import label
from ...domain.errors import NotAvailable
from ...services.background import Background, Opinions


def arguments(parser):
    parser.add_argument('--chat')
    parser.add_argument('--from', dest='source')
    parser.add_argument('--tool')
    parser.add_argument('--turn', type=int)
    parser.add_argument('--question')
    parser.add_argument('--add-to-chat', action='store_true')
    parser.add_argument('--answer')
    parser.add_argument('--status')
    parser.add_argument('--cancel')
    parser.add_argument('--background', action='store_true')


def service(engine):
    return Opinions(engine.store, engine.adapters, engine.clock, label)


def add_preview(ctx, ident):
    request = service(ctx.engine).add_preview(ident)
    token = ctx.remember(request['fingerprint'], {'stage': 'add', 'request': request})
    answer = request['answer']
    return output.plan(token, request['snapshot']['link_id'],
                       [output.step(answer['source'], request['action'], ())], stage='add', answer_id=ident,
                       answer=answer['answer'], decision_needed=not request['available'],
                       notes=[output.note(request['note_id'] if request['available'] else 'ask.add_unavailable')],
                       confirmation=output.note(request['note_id'] if request['available'] else 'plan.unavailable'))


def confirm(ctx):
    opinions = service(ctx.engine)
    def check(value):
        opinions.validate(value['request'])
        return value['request']['fingerprint']
    stored = ctx.confirmed(check)
    if stored['stage'] == 'add':
        result = opinions.add(stored['request'])
        return output.plan(ctx.confirm, stored['request']['snapshot']['link_id'],
            [output.step(stored['request']['answer']['source'], stored['request']['action'], ())],
            applied=result['applied'], answer_id=result['answer_id'], chat_id=result['chat_id'], queued=result.get('queued', False),
            notes=[output.note('ask.queued' if result.get('queued') else 'ask.added')])
    background = Background(ctx.engine.store, ctx.engine.clock)
    ident = background.create('ask', stored['request'])
    dispatch_background(ctx.engine, lambda engine: generate_opinion(engine, ident, label))
    return output.background_status(background.status(ident))


@command('ask', output.note('cli.ask_summary')['text'], arguments=arguments, plan=True)
def ask(ctx, args):
    configure_retention(ctx.engine)
    background = Background(ctx.engine.store, ctx.engine.clock)
    if getattr(args, 'cancel', None):
        return output.background_status(background.stop(args.cancel))
    if getattr(args, 'status', None):
        return output.background_status(background.status(args.status))
    if ctx.confirm:
        return confirm(ctx)
    if getattr(args, 'answer', None) and getattr(args, 'add_to_chat', False):
        return add_preview(ctx, args.answer)
    chat = getattr(args, 'chat', None) or getattr(args, 'source', None)
    if not chat or ':' not in chat or not getattr(args, 'question', None):
        raise NotAvailable()
    source, chat_id = chat.split(':', 1)
    request = service(ctx.engine).preview(source, chat_id, args.question,
                getattr(args, 'tool', None), getattr(args, 'turn', None))
    if getattr(args, 'source', None) and not ctx.dry_run and not getattr(args, 'background', False):
        value = immediate_opinion(ctx.engine, request, label)
        ident = value['request_id']
        return {**output.background_status(value).get('result', {}), 'notes': [output.note('background.' + value['state'])],
                'request_id': ident, 'state': value['state']}
    token = ctx.remember(request['fingerprint'], {'stage': 'generate', 'request': request})
    values = {'tool': request['writer'], 'tokens': request['tokens']}
    return output.plan(token, request['snapshot']['link_id'], (), stage='generate',
                       writer=request['writer'], estimated_tokens=request['tokens'], read_only=True,
                       notes=[output.note('ask.writer_reason', values), output.note('ask.preview', values)],
                       confirmation=output.note('ask.preview', values))


def add_arguments(parser):
    parser.add_argument('--answer')


@command('ask add', output.note('cli.ask_add_summary')['text'], arguments=add_arguments, plan=True)
def ask_add(ctx, args):
    configure_retention(ctx.engine)
    if ctx.confirm:
        return confirm(ctx)
    if not args.answer:
        raise NotAvailable()
    return add_preview(ctx, args.answer)
