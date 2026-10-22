"""Read setup checks without installing, signing in or launching anything."""
from .. import output
from . import command

@command('setup', output.note('cli.setup_summary')['text'])
def setup(ctx, args):
    """Call the recovery-free projection and serialize the contract result."""
    from ...services.setup_check import SetupCheck
    from ...services.setup_install import SetupInstall
    from ...adapters.setup_files import SetupFiles
    engine = ctx.engine
    hooks = SetupInstall({tool: adapter.hooks for tool, adapter in engine.adapters.items()},
                         SetupFiles(engine.root), '', app_running={})
    check = SetupCheck(engine.adapters, installation_probe=engine.installation_probe,
                       hook_probe=hooks.check)
    return output.read_setup(check.complete(engine.setup_read.tools()))
