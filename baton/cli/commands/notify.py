"""Turn event registration; native rules live behind the hook boundary."""
from . import command
from ...hooks.runtime import arguments, invoke
from ...notes.catalogue import get


@command('notify', get('cli.notify').template, arguments=arguments)
def notify(ctx, args):
    return invoke(args, prompt=False, engine_factory=lambda: ctx.engine, locked=True, contract=True)
