"""Capabilities measured by M0 for Codex (docs/SPIKE-M0.md, docs/features/more-tools.md)."""
from ...domain.capabilities import Capabilities, HookNeed, Visibility, WriteWindow

# The schema generation of Codex's state database. Codex names it in the file name.
SCHEMA_VERSION = "state_5"
CHECKED_CLI_VERSIONS = ("0.159.2", "0.160", "0.160.0")

FACTS = Capabilities(
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
    checked_versions=(SCHEMA_VERSION,),
    replays_tool_calls=False,
)
