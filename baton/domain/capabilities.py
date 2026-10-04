"""Facts describing what a tool can do."""
from dataclasses import dataclass
from enum import Enum


class WriteWindow(Enum):
    """When a tool allows real turns to be written."""
    CLOSED_OR_RELEASED = "closed_or_released"
    NOT_HELD = "not_held"
    ANY_TIME = "any_time"
    APP_CLOSED = "app_closed"


class Visibility(Enum):
    """When written turns become visible in the app."""
    AT_ONCE = "at_once"
    AFTER_RELAUNCH = "after_relaunch"
    ON_REOPEN_CHAT = "on_reopen_chat"


class HookNeed(Enum):
    """The first-use step needed by hooks."""
    NONE = "none"
    TRUST_ONCE = "trust_once"
    RESTART_ONCE = "restart_once"


@dataclass(frozen=True)
class Capabilities:
    """All facts needed to choose actions for a tool."""
    write_window: WriteWindow
    new_chat_visible: Visibility
    added_turn_visible: Visibility
    can_cut: bool
    can_place: bool
    can_release_chat: bool
    opens_at_chat: bool
    limit_has_reset_time: bool
    context_size_known: bool
    hooks_need: HookNeed
    checked_versions: tuple[str, ...]
    replays_tool_calls: bool
