"""The current condition of a chat."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SideCondition:
    """What is true of one side's chat right now."""
    exists: bool = True
    open: bool = False
    replying: bool = False
    hooks_ready: bool = True
    app_running: bool = False
