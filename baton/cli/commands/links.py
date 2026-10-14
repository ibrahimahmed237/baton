"""Summaries of active links, without native write recovery."""
from .. import output
from . import command

@command('links', output.note('cli.links_summary')['text'])
def links(ctx, args):
    """Call the recovery-free projection and serialize the contract result."""
    return {'links': [output.link_summary(ctx.engine.reads.link_summary(link.id))
                      for link in ctx.engine.store.links()]}
