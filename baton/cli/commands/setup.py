"""Read setup checks without installing, signing in or launching anything."""
from .. import output
from . import command

@command('setup', output.note('cli.setup_summary')['text'])
def setup(ctx, args):
    """Call the recovery-free projection and serialize the contract result."""
    return output.read_setup(ctx.engine.setup_read.tools())
