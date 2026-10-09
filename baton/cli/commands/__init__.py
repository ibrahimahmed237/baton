"""How a command is added: one file in this folder with one `@command(...)` function.

    from . import command

    @command("pause", "Pause a link", arguments=lambda p: p.add_argument("--link", type=int, required=True))
    def pause(ctx, args):
        ...
        return {"link_id": args.link, "paused": True}

A command parses nothing itself, holds no rules and prints nothing: it calls one
service on `ctx.engine` and returns the dict of the contract (or a string, for
`catch-up`, whose output is what the calling tool expects). Expected refusals are
raised as BatonError and turned into the error object by `main`.
A command that writes to a chat or changes a link passes `plan=True`, which adds
`--dry-run` and `--confirm <plan_id>` to it; see `Context.remember` and
`Context.confirmed`.
"""
from __future__ import annotations

import argparse
import importlib
import pkgutil
from dataclasses import dataclass
from typing import Any, Callable, Iterator, Mapping

from ..wiring import Engine

Run = Callable[["Context", argparse.Namespace], "dict[str, Any] | str"]
Arguments = Callable[[argparse.ArgumentParser], None]


@dataclass(frozen=True)
class Context:
    """What a command gets: the engine and the global flags."""
    engine: Engine
    command: str
    json: bool = True
    dry_run: bool = False
    confirm: str | None = None

    def remember(self, fingerprint: str, arguments: Mapping[str, Any]) -> str:
        """Keep a plan about to be shown, with the arguments that produced it, for ten minutes.

        `fingerprint` is the service's plan id. Returns the confirmation id: show
        that as the plan's `plan_id`, not the service's.
        """
        return self.engine.plans.remember(fingerprint, self.command, arguments)

    def confirmed(self, plan_again: Callable[[Mapping[str, Any]], str]) -> Mapping[str, Any]:
        """Check `--confirm` and return the stored arguments to plan and apply again.

        `plan_again(arguments)` plans the stored request from the chats as they are
        now and returns the service's plan id. ChatChanged is raised unless that is
        the fingerprint stored with the confirmation id, the plan is older than ten
        minutes, it is unknown or another process confirmed it first. The plan is
        used up by this call.
        """
        if not self.confirm:
            raise ValueError("no --confirm given")
        return self.engine.plans.confirm(self.confirm, self.command, plan_again).arguments


@dataclass(frozen=True)
class Command:
    """A command's name, its arguments and the function that runs it."""
    name: str                      # "links", or "settings get" for a sub-command
    summary: str
    run: Run
    arguments: Arguments = lambda parser: None
    plan: bool = False             # writes to a chat or changes a link: takes --dry-run and --confirm


class CommandRegistry:
    """The commands by name."""
    def __init__(self) -> None:
        self._commands: dict[str, Command] = {}

    def add(self, command: Command) -> Command:
        """Register a command; two commands may not share a name."""
        if command.name in self._commands:
            raise ValueError("command registered twice: " + command.name)
        self._commands[command.name] = command
        return command

    def command(self, name: str, summary: str, *, arguments: Arguments = lambda parser: None,
                plan: bool = False) -> Callable[[Run], Run]:
        """Decorator form of `add`."""
        def register(run: Run) -> Run:
            self.add(Command(name, summary, run, arguments, plan))
            return run
        return register

    def get(self, name: str) -> Command | None:
        """Return the command with this name, if any."""
        return self._commands.get(name)

    def __iter__(self) -> Iterator[Command]:
        return iter(self._commands.values())


REGISTRY = CommandRegistry()
command = REGISTRY.command


def discover(registry: CommandRegistry = REGISTRY) -> CommandRegistry:
    """Import every module of this folder so its commands register themselves."""
    for module in pkgutil.iter_modules(__path__):
        importlib.import_module("%s.%s" % (__name__, module.name))
    return registry
