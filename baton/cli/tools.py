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
