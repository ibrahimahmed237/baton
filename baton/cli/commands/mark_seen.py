"""Explicit visibility evidence for a reopened chat, through Applier."""
import argparse

from . import command
from .. import output


def turn_ids(value):
    try:
        ids = [int(part) for part in value.split(',')]
        if not ids or any(ident <= 0 for ident in ids):
            raise ValueError()
        return ids
    except ValueError as error:
        raise argparse.ArgumentTypeError('cli.usage') from error


def arguments(parser):
    parser.add_argument('--link', type=int, required=True)
    parser.add_argument('--tool', required=True)
    parser.add_argument('--turns', type=turn_ids)


@command('mark-seen', output.note('cli.mark_seen_summary')['text'], arguments=arguments)
def mark_seen(ctx, args):
    ctx.engine.adapter(args.tool)
    marked = ctx.engine.applier.mark_seen(args.link, args.tool, args.turns)
    return {'link_id': args.link, 'tool': args.tool, 'marked': marked, 'notes': []}
