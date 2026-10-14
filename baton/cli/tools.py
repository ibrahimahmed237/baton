"""The tools Baton can talk to: ids, display labels and where each adapter lives.

This is the one list to extend when a tool gets an adapter. The command line may
know tool ids; services and ports may not.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ToolEntry:
    """One tool: its stable id, display label and adapter class."""
    id: str
    label: str
    module: str     # dotted path of the module holding the adapter
    adapter: str    # name of the adapter class in that module
    home: str = ""  # sub-folder of the tools home given to the adapter as its root
    marker: str = ""  # folder inside that root whose presence means the tool is installed there


TOOLS: tuple[ToolEntry, ...] = (
    ToolEntry("claude", "Claude", "baton.adapters.claude.tool", "ClaudeAdapter", marker=".claude"),
    ToolEntry("codex", "Codex", "baton.adapters.codex.tool", "CodexAdapter", marker=".codex"),
    ToolEntry("opencode", "OpenCode", "baton.adapters.opencode.tool", "OpenCodeAdapter", marker=".local/share/opencode"),
    ToolEntry("cursor", "Cursor", "baton.adapters.cursor.tool", "CursorAdapter", marker=".cursor"),
)

LABELS: dict[str, str] = {entry.id: entry.label for entry in TOOLS}


def label(tool: str) -> str:
    """Return the display label of a tool id, or the id itself when it is not known."""
    return LABELS.get(tool, tool)


def installed(tool: str) -> bool:
    """Probe executable presence without running it or treating sign-in as installation."""
    from shutil import which
    bundles = {
        'claude': ('Claude Code.app',), 'codex': ('Codex.app',),
        'cursor': ('Cursor.app',), 'opencode': ('OpenCode.app',)}
    if tool not in LABELS:
        return False
    if which(tool) is not None:
        return True
    if tool == 'codex':
        from ..adapters.codex.runner import BUNDLED_CLI
        if Path(BUNDLED_CLI).is_file():
            return True
    folders = (Path('/Applications'), Path.home() / 'Applications')
    return any((folder / bundle / 'Contents' / 'Info.plist').is_file()
               for folder in folders for bundle in bundles[tool])


def installed_in(entry: ToolEntry, root: Path) -> bool:
    """Whether the tool's own folder exists inside `root`: what "installed" means for an injected root.

    It looks only below `root`; it never asks the machine (no PATH, no /Applications).
    """
    return bool(entry.marker) and (Path(root) / entry.marker).is_dir()


def hook_entrypoints_available():
    """Only claim entry points after their modules and registered commands exist."""
    from importlib.util import find_spec
    from importlib import import_module
    if not getattr(import_module('baton.cli.main'), 'HOOK_DISPATCH_AVAILABLE', False):
        return False
    return registered_hook_commands() and all(find_spec(name) is not None for name in (
        'baton.hooks.prompt', 'baton.hooks.turn_end',
        'baton.cli.commands.catch_up', 'baton.cli.commands.notify'))


def registered_hook_commands():
    """Readiness reflects registrations, not merely importable files."""
    from .commands import discover
    registry = discover()
    return all(registry.get(name) is not None for name in ('catch-up', 'notify'))
