"""Suggest unlinked conversations using shared public-content matching."""
from .. import output
from . import command

@command('suggestions', output.note('cli.suggestions_summary')['text'])
def suggestions(ctx, args):
    """Call the recovery-free projection and serialize the contract result."""
    return {'suggestions': [{'a': output.chat_from_ref(*item['a']), 'b': output.chat_from_ref(*item['b']),
                             'matched_turns': item['matched_turns']} for item in ctx.engine.reads.suggestions()]}
