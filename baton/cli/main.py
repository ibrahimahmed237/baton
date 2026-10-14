"""`baton`: parse the command line, call one command, print one JSON object.

Expected refusals print their error object and exit 0. A crash prints
`{"error": {"kind": "internal", ...}}` and exits 1. A command line that cannot be
understood prints `{"error": {"kind": "usage", ...}}` and exits 2.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import Any, Callable, Sequence, TextIO

from ..domain.errors import BatonError
from . import output
from .commands import Command, CommandRegistry, Context, discover
from .wiring import Engine, build

logger = logging.getLogger(__name__)
HOOK_DISPATCH_AVAILABLE = True


class UsageError(Exception):
    """The command line could not be understood."""


class _HelpFormatter(argparse.HelpFormatter):
    def _format_usage(self, usage, actions, groups, prefix):
        return super()._format_usage(usage, actions, groups,
            output.note('cli.help_usage')['text'] if prefix is None else prefix)


class _Parser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        add_help = kwargs.pop('add_help', True)
        kwargs.setdefault('formatter_class', _HelpFormatter)
        super().__init__(*args, add_help=False, **kwargs)
        self._positionals.title = output.note('cli.help_positionals')['text']
        self._optionals.title = output.note('cli.help_options')['text']
        if add_help:
            self.add_argument('-h', '--help', action='help', help=output.note('cli.help_help')['text'])

    def error(self, message: str):  # type: ignore[override]
        raise UsageError("cli.usage")


def _flags(command: Command | None, *, base: bool) -> argparse.ArgumentParser:
    """The global flags. On a sub-command they are left out unless given, so they never overwrite the main parser's."""
    parser = _Parser(add_help=False)
    off = False if base else argparse.SUPPRESS
    none = None if base else argparse.SUPPRESS
    parser.add_argument("--json", action="store_true", default=off,
                        help=output.note('cli.help_json')['text'])
    if base or (command is not None and command.plan):
        parser.add_argument("--dry-run", action="store_true", default=off,
                            help=output.note('cli.help_dry_run')['text'])
        parser.add_argument("--confirm", metavar="PLAN_ID", default=none,
                            help=output.note('cli.help_confirm')['text'])
    return parser


def build_parser(registry: CommandRegistry) -> argparse.ArgumentParser:
    """Build the parser from the registered commands; a name with a space is a sub-command."""
    parser = _Parser(prog="baton", description=output.note('cli.description')['text'],
                     parents=[_flags(None, base=True)])
    _populate(parser, _tree(registry), 0, None)
    return parser


def _tree(registry: CommandRegistry) -> dict[str, dict[str, Any]]:
    tree: dict[str, dict[str, Any]] = {}
    for command in registry:
        children = tree
        node: dict[str, Any] = {}
        for word in command.name.split():
            node = children.setdefault(word, {"command": None, "children": {}})
            children = node["children"]
        node["command"] = command
    return tree


def _populate(parser: argparse.ArgumentParser, children: dict[str, dict[str, Any]],
              depth: int, own: Command | None) -> None:
    if not children:
        return
    sub = parser.add_subparsers(dest="word%d" % depth, metavar=output.note('cli.help_command')['text'], required=own is None)
    for word, node in children.items():
        command: Command | None = node["command"]
        child = sub.add_parser(word, help=command.summary if command else None,
                               parents=[_flags(command, base=False)])
        if command is not None:
            command.arguments(child)
        _populate(child, node["children"], depth + 1, command)


def _command_name(args: argparse.Namespace) -> str:
    words = []
    for depth in range(8):
        word = getattr(args, "word%d" % depth, None)
        if word is None:
            break
        words.append(word)
    return " ".join(words)


def _emit(out: TextIO, result: dict[str, Any] | str) -> None:
    out.write(result if isinstance(result, str) else json.dumps(result) + "\n")
    out.flush()


def main(argv: Sequence[str] | None = None, *, registry: CommandRegistry | None = None,
         engine_factory: Callable[[], Engine] = build, stdout: TextIO | None = None) -> int:
    """Run one command and return the exit status."""
    out = stdout or sys.stdout
    if registry is None:
        from ..hooks.runtime import dispatch
        hook_status = dispatch(argv, engine_factory=engine_factory, stdout=out)
        if hook_status is not None:
            return hook_status
    try:
        registry = discover() if registry is None else registry
        args = build_parser(registry).parse_args(argv)
        command = registry.get(_command_name(args))
        if command is None:
            raise UsageError("cli.unknown_command", {"command": _command_name(args)})
        if (args.dry_run or args.confirm) and not command.plan:
            raise UsageError("cli.no_plan_flags", {"command": command.name})
        if args.dry_run and args.confirm:
            raise UsageError("cli.conflicting_flags")
    except UsageError as problem:
        _emit(out, output.usage_error(problem.args[0], problem.args[1] if len(problem.args) > 1 else {}))
        return 2
    except SystemExit as leave:  # --help
        return leave.code if isinstance(leave.code, int) else 0
    except Exception as crash:  # a command module that does not import, a bad argument definition
        logger.exception("baton could not start")
        _emit(out, output.internal_error(crash))
        return 1
    return _run(command, args, engine_factory, out)


def _run(command: Command, args: argparse.Namespace, engine_factory: Callable[[], Engine], out: TextIO) -> int:
    engine = None
    try:
        engine = engine_factory()
        with engine.command_lock():
            context = Context(engine, command.name, True, args.dry_run, args.confirm)
            _emit(out, command.run(context, args))
        return 0
    except BatonError as refusal:
        _emit(out, output.error(refusal))
        return 0
    except Exception as crash:
        logger.exception("baton %s failed", command.name)
        _emit(out, output.internal_error(crash))
        return 1
    finally:
        if engine is not None:
            engine.close()


if __name__ == "__main__":
    sys.exit(main())
