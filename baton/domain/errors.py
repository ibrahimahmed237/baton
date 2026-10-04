"""Errors raised by Baton, with the note ids used to explain them."""
from __future__ import annotations

from .link import Link


class AlreadyLinked(Exception):
    """The chat is in a link already; that link has to be removed first."""

    note_id = "link.already_linked"

    def __init__(self, side: str, link: Link):
        super().__init__("the %s chat %s is already linked" % (side, link.chat(side)))
        self.side = side
        self.link = link


class AlreadyDelivered(Exception):
    """The turn reached another side already, so it can no longer be kept back."""

    note_id = "keep.too_late"

    def __init__(self, turn_id: int, side: str, at: str):
        super().__init__("turn %d was already delivered to %s at %s" % (turn_id, side, at))
        self.turn_id = turn_id
        self.side = side
        self.at = at


class OrderNotAllowed(Exception):
    """The order moves one app's own turns past each other, or is not the same set of turns."""

    note_id = "merge.order_not_allowed"


class ChatHeld(Exception):
    """A write was requested for a chat held by its app."""

    note_id = "write.chat_open"


class AppMustBeClosed(Exception):
    """A write requires the running app to be closed."""

    note_id = "write.app_must_close"


class ChatReplying(Exception):
    """Closing or releasing the chat would stop a reply."""

    note_id = "relaunch.replying"


class UnknownFormat(Exception):
    """The chat uses a format version that has not been checked."""

    note_id = "format.unknown_version"


class ChatChanged(Exception):
    """The chat changed between planning and writing."""

    note_id = "write.chat_changed"


class DecisionNeeded(Exception):
    """Both sides have unsynced turns and need a merge decision."""

    note_id = "merge.decision_needed"


class NotAvailable(Exception):
    """The tool lacks what the requested action needs."""

    note_id = "tool.cannot"


class SetupIncomplete(Exception):
    """A required setup step is missing."""

    note_id = "setup.<finding>"
