"""The current condition of a chat."""
from __future__ import annotations

from dataclasses import dataclass
from dataclasses import InitVar


@dataclass(frozen=True)
class SideCondition:
    """What is true of one side's chat right now."""
    exists: bool = True
    open: bool = False
    replying: bool = False
    hooks_ready: bool = True
    app_running: bool = False
    app_started_at: str = ""
    format_known: bool = True
    format_new_version: InitVar[bool] = False

    def __post_init__(self, format_new_version):
        # Informational release evidence must not change existing plan fingerprints.
        object.__setattr__(self, 'format_new_version', format_new_version)
