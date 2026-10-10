"""The tools Baton can talk to: ids, display labels and where each adapter lives.

This is the one list to extend when a tool gets an adapter. The command line may
know tool ids; services and ports may not.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolEntry:
    """One tool: its stable id, display label and adapter class."""
    id: str
    label: str
    module: str     # dotted path of the module holding the adapter
    adapter: str    # name of the adapter class in that module
    home: str = ""  # sub-folder of the tools home given to the adapter as its root


TOOLS: tuple[ToolEntry, ...] = (
    ToolEntry("claude", "Claude", "baton.adapters.claude.tool", "ClaudeAdapter"),
    ToolEntry("codex", "Codex", "baton.adapters.codex.tool", "CodexAdapter"),
    ToolEntry("opencode", "OpenCode", "baton.adapters.opencode.tool", "OpenCodeAdapter"),
    ToolEntry("cursor", "Cursor", "baton.adapters.cursor.tool", "CursorAdapter"),
)

LABELS: dict[str, str] = {entry.id: entry.label for entry in TOOLS}


def label(tool: str) -> str:
    """Return the display label of a tool id, or the id itself when it is not known."""
    return LABELS.get(tool, tool)


def installed(tool: str) -> bool:
    """Probe executable presence without running it or treating sign-in as installation."""
    from shutil import which
    from pathlib import Path
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
