"""Shared record validation and metadata calculations."""
from datetime import datetime, timezone
from ..domain.model import Turn
from ..domain.link import TOOLS

_FIRST_LINE_CHARS = 200

def now() -> str:
    """Return the UTC timestamp used by record operations without an explicit time."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _tool(side: str) -> str:
    if side not in TOOLS:
        raise ValueError("unknown tool: %s" % side)
    return side


def _size(turn: Turn) -> int:
    """Characters of text in a turn, for estimating what it costs to send."""
    return len(turn.prompt.text) + sum(len(message.text) for message in turn.messages)
