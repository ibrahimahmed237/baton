"""Read validated stored settings and their contract defaults."""
from .. import output
from . import command

@command('settings get', output.note('cli.settings_summary')['text'])
def get(ctx, args):
    """Call the recovery-free projection and serialize the contract result."""
    return output.read_settings(ctx.engine.settings_read.get(), ctx.engine.settings_read.defaults)
