"""Prompt hook registration; native rules live behind the hook boundary."""
from . import command
from ...hooks.runtime import arguments, invoke
from ...notes.catalogue import get


@command('catch-up', get('cli.catch_up').template, arguments=arguments)
def catch_up(ctx, args):
    return invoke(args, prompt=True, engine_factory=lambda: ctx.engine, locked=True)
