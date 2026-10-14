"""Open via the service-selected AppControl outcome."""
from . import command
from .. import output
from ...services.continue_open import ContinueOpen


def arguments(parser):
    parser.add_argument('--tool', required=True)
    parser.add_argument('--chat', required=True)


@command('open', output.note('cli.open_summary')['text'], arguments=arguments)
def open_chat(ctx, args):
    service = ContinueOpen(ctx.engine.store, ctx.engine.adapters)
    prepared = service.opening(args.tool, args.chat)
    output.display_open_note(prepared)
    return output.open_action_result(service.execute_open(prepared))
