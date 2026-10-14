"""Ready-made facts for the four measured tool behaviours (docs/features/more-tools.md)."""
from ...domain.capabilities import Capabilities, HookNeed, Visibility, WriteWindow

CLAUDE_LIKE = Capabilities(
    write_window=WriteWindow.CLOSED_OR_RELEASED,
    new_chat_visible=Visibility.AFTER_RELAUNCH,
    added_turn_visible=Visibility.AFTER_RELAUNCH,
    can_cut=True,
    can_place=False,
    can_release_chat=True,
    opens_at_chat=True,
    limit_has_reset_time=True,
    context_size_known=True,
    hooks_need=HookNeed.NONE,
    checked_versions=('fake-1',),
    replays_tool_calls=True,
)

CODEX_LIKE = Capabilities(
    write_window=WriteWindow.NOT_HELD,
    new_chat_visible=Visibility.AT_ONCE,
    added_turn_visible=Visibility.AT_ONCE,
    can_cut=False,
    can_place=False,
    can_release_chat=False,
    opens_at_chat=True,
    limit_has_reset_time=True,
    context_size_known=True,
    hooks_need=HookNeed.TRUST_ONCE,
    checked_versions=('fake-1',),
    replays_tool_calls=False,
)

OPENCODE_LIKE = Capabilities(
    write_window=WriteWindow.ANY_TIME,
    new_chat_visible=Visibility.AT_ONCE,
    added_turn_visible=Visibility.ON_REOPEN_CHAT,
    can_cut=True,
    can_place=True,
    can_release_chat=False,
    opens_at_chat=False,
    limit_has_reset_time=False,
    context_size_known=False,
    hooks_need=HookNeed.RESTART_ONCE,
    checked_versions=('fake-1',),
    replays_tool_calls=True,
)

CURSOR_LIKE = Capabilities(
    write_window=WriteWindow.APP_CLOSED,
    new_chat_visible=Visibility.AFTER_RELAUNCH,
    added_turn_visible=Visibility.AFTER_RELAUNCH,
    can_cut=False,
    can_place=True,
    can_release_chat=False,
    opens_at_chat=False,
    limit_has_reset_time=False,
    context_size_known=True,
    hooks_need=HookNeed.NONE,
    checked_versions=('18',),
    replays_tool_calls=False,
)
