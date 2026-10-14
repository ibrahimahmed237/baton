"""Save settings through the contract validation service."""
from . import command
from .. import output
from ...services.settings_write import SettingsWrite


def arguments(parser):
    parser.add_argument('key')
    parser.add_argument('value')


@command('settings set', output.note('cli.settings_set_summary')['text'], arguments=arguments)
def settings_set(ctx, args):
    settings, notes = SettingsWrite(ctx.engine.settings_read).set(args.key, args.value)
    return {'settings': settings, 'notes': output.note_list(notes)}
