"""Errors raised by Baton, with the note ids used to explain them."""
from __future__ import annotations

from .link import Link


class BatonError(Exception):
    """Base error carrying the note used to explain a failure."""

    note_id = ""


class AlreadyLinked(BatonError):
    """The chat is in a link already; that link has to be removed first."""

    note_id = "link.already_linked"

    def __init__(self, side: str, link: Link):
        super().__init__("the %s chat %s is already linked" % (side, link.chat(side)))
        self.side = side
        self.link = link


class AlreadyDelivered(BatonError):
    """The turn reached another side already, so it can no longer be kept back."""

    note_id = "keep.too_late"

    def __init__(self, turn_id: int, side: str, at: str):
        super().__init__("turn %d was already delivered to %s at %s" % (turn_id, side, at))
        self.turn_id = turn_id
        self.side = side
        self.at = at


class OrderNotAllowed(BatonError):
    """The order moves one app's own turns past each other, or is not the same set of turns."""

    note_id = "merge.order_not_allowed"


class ChatHeld(BatonError):
    """A write was requested for a chat held by its app."""

    note_id = "write.chat_open"


class AppMustBeClosed(BatonError):
    """A write requires the running app to be closed."""

    note_id = "write.app_must_close"


class ChatReplying(BatonError):
    """Closing or releasing the chat would stop a reply."""

    note_id = "relaunch.replying"


class UnknownFormat(BatonError):
    """The chat uses a format version that has not been checked."""

    note_id = "format.unknown_version"


class ChatChanged(BatonError):
    """The chat changed between planning and writing."""

    note_id = "write.chat_changed"


class DecisionNeeded(BatonError):
    """Both sides have unsynced turns and need a merge decision."""

    note_id = "merge.decision_needed"


class NotAvailable(BatonError):
    """The tool lacks what the requested action needs."""

    note_id = "tool.cannot"


class SetupIncomplete(BatonError):
    """A required setup step is missing."""

    note_id = "setup.<finding>"
