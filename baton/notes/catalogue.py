"""CP1 user-facing wording from the feature specifications.

Templates substitute tool names and counts instead of branching on a tool.
E12 will complete the catalogue for the later work packages.
"""
from dataclasses import dataclass
from string import Formatter
from typing import Mapping


@dataclass(frozen=True)
class Button:
    """A stable action id and its displayed label."""
    id: str
    label: str
    primary: bool = False


_BUTTON_IDS = {
    "Close {tool}, sync, reopen": "close_sync_reopen",
    "Sync now, I relaunch later": "sync_relaunch_later",
    "Cancel": "cancel", "Attach instead": "attach", "Wait until it has finished": "when_idle",
    "Close anyway": "close_anyway", "Relaunch {tool}": "relaunch", "Add them now": "add_now",
    "Sync when the reply has finished": "when_idle", "Change the link": "relink",
    "Keep the current link": "cancel", "Resume": "resume", "Remove link": "unlink",
    "Keep link": "cancel", "Copy to {tool}": "copy", "Copy and link": "copy_and_link",
    "{fix}": "setup_fix", "Check again": "setup_check", "Decide": "merge_show",
}


@dataclass(frozen=True)
class Note:
    """One note, its confirmation actions and persistent status instruction."""
    id: str
    tone: str
    template: str
    buttons: tuple[Button, ...] = ()
    status_line: str = ""

    def __post_init__(self) -> None:
        """Normalize catalogue shorthand to stable contract actions."""
        buttons = tuple(Button(_BUTTON_IDS[item], item, index == 0) if isinstance(item, str) else item
                        for index, item in enumerate(self.buttons))
        object.__setattr__(self, "buttons", buttons)

    def render(self, values: Mapping[str, object]) -> "Note":
        """Fill every field, raising when the caller omits a required value."""
        return Note(self.id, self.tone, self.template.format_map(values),
                    tuple(Button(button.id, button.label.format_map(values), button.primary) for button in self.buttons),
                    self.status_line.format_map(values))

    def to_dict(self, values: Mapping[str, object]) -> dict[str, object]:
        """Render the frozen contract’s Note object."""
        note = self.render(values)
        return {"id": note.id, "tone": note.tone, "values": dict(values), "text": note.template,
                "buttons": [{"id": item.id, "label": item.label, "primary": item.primary}
                            for item in note.buttons], "status_line": note.status_line or None}

    @property
    def fields(self) -> tuple[str, ...]:
        """List the values needed to render this note completely."""
        texts = (self.template, self.status_line, *(button.label for button in self.buttons))
        return tuple(sorted({name for text in texts for _, name, _, _ in Formatter().parse(text) if name}))


CATALOGUE = {note.id: note for note in (
    Note("nothing_unusual", "info", "Nothing unusual."),
    Note("new_chat.at_once", "info", "The new chat appears in {tool} right away. No relaunch."),
    Note("new_chat.relaunch", "info", "Baton closes {tool}, creates the chat, and opens {tool} again at it. {tool} lists a new chat only when it starts; you do this once for this chat.", ("Close {tool}, sync, reopen", "Sync now, I relaunch later", "Cancel"), "Relaunch {tool} to see this chat"),
    Note("write.app_must_close", "warning", "Baton closes {tool}, writes, and opens {tool} again on this folder; your windows come back. Baton never writes while {tool} runs, because {tool} would write over it.", ("Close {tool}, sync, reopen", "Attach instead", "Cancel"), "{n} turns waiting until {tool} is closed"),
    Note("relaunch.replying", "warning", '{tool} is replying in "{title}". Closing now stops that reply.', ("Wait until it has finished", "Close anyway", "Cancel"), "Will sync when {tool} is idle"),
    Note("format.unknown_version", "warning", "{tool} was updated and saves chats differently (version {version}). Baton still reads its chats and attaches turns, but will not create or add messages there until Baton is updated.", (), "{tool}: reading only"),
    Note("link.attached_history", "info", "The agent gets the history with your first message. The chat will never show it as separate messages.", (), "Agent has {n} turns the chat does not show"),
    Note("write.chat_open", "info", "These {n} turns will be attached to your next message there. To get them as normal messages, relaunch {tool}.", ("Close {tool}, sync, reopen",), "{n} turns waiting, attached on next message"),
    Note("write.any_time", "info", "Baton adds these {n} turns now. If the chat is on screen, open it again to see them.", (), "Open the chat again to see {n} new turns"),
    Note("reopen_chat_to_see", "info", "{tool} keeps showing the chat as it was until you open it again. The agent already has the change.", (), "Open the chat again to see the change"),
    Note("relaunch_to_see", "info", "The agent has these {n} turns. Relaunch {tool} to see them as normal messages.", ("Relaunch {tool}",), "Relaunch {tool} to see {n} new turns"),
    Note("write.release", "info", "Baton releases the idle chat and adds these {n} turns as real turns. Relaunch {tool} to see them.", ("Add them now", "Relaunch {tool}"), "Relaunch {tool} to see {n} new turns"),
    Note("write.when_idle", "info", "These {n} turns will be attached to your next message; Baton adds real turns once the reply ends if set to automatic.", ("Sync when the reply has finished",), "Will sync when {tool} is idle"),
    Note("write.chat_changed", "warning", "The chat changed before Baton could write. Check it again."),
    Note("link.already_linked", "warning", '"{name}" is already linked to "{other_name}" in {tool}. A chat can be linked to one chat at a time.', ("Change the link", "Cancel")),
    Note("link.change", "warning", 'Link "{name}" to "{new_name}" instead? The link to "{other_name}" is removed first. That chat stays exactly as it is and is no longer synced.', ("Change the link", "Keep the current link")),
    Note("link.paused", "info", "Syncing is paused for this chat. Nothing is sent either way until you resume. {n} turns are waiting.", ("Resume",), "Paused, {n} waiting"),
    Note("link.remove", "warning", 'Remove the link between "{name}" and "{other_name}"? Both chats stay exactly as they are. Baton stops syncing them. The {n} turns still waiting for {tool} will not be delivered.', ("Remove link", "Keep link")),
    Note("link.copy", "info", "A new chat is created in {tool} with all {n} turns. The two chats will not be kept in sync.", ("Copy to {tool}", "Copy and link", "Cancel")),
    Note("tool.cannot", "info", "{action} is not available: {reason}."),
    Note("setup.missing", "warning", "{missing}. {effect}. {fix}.", ("{fix}", "Check again"), "Setup: 1 step left"),
    Note("setup.trust_once", "info", "In {tool}, type /hooks and trust Baton's two entries.", (), "Setup: 1 step left"),
    Note("setup.restart_once", "info", "Restart {tool} once so Baton's plugin loads.", (), "Setup: 1 step left"),
    Note("merge.decision_needed", "warning", "Both sides have turns the other never received. A decision is needed.", ("Decide",), "A decision is needed"),
    Note("merge.order_not_allowed", "warning", "Turns written in one app stay in their own order; only turns from different apps can pass each other."),
    Note("keep.too_late", "warning", "This turn has already reached the other side."),
    Note("side.missing", "warning", "This chat is missing. Nothing is sent to it.", (), "Chat missing"),
    Note("history.marker", "info", "[Baton: continued from {tool}]"),
    Note("turn.written_here", "info", "Written here"),
    Note("turn.shown", "info", "Shown"),
    Note("turn.added", "info", "Added, shown after a relaunch"),
    Note("turn.attached", "info", "Attached"),
    Note("turn.waiting", "info", "Waiting"),
    Note("turn.skipped", "info", "Skipped"),
    Note("turn.kept_back", "info", "Kept back"),
    Note("status.in_sync", "ok", "In sync"),
    Note("status.ahead", "info", "{tool} is {n} turns ahead"),
    Note("status.if_send", "info", "If you send a message now, {tool} gets {n} turns, about {tokens} tokens."),
    Note("status.paused", "warning", "Paused"),
    Note("status.pinned", "info", "Pinned"),
    Note("status.kept", "info", "Kept in {tool}"),
    Note("screen.chats", "info", "Chats"),
    Note("screen.links", "info", "Links"),
    Note("screen.sync_status", "info", "Sync status"),
    Note("screen.empty", "info", "No linked chats yet"),
    Note("screen.list_empty", "info", "No items yet"),
    Note("screen.search", "info", "Search chats"),
    Note("screen.continue", "info", "Continue in {tool}"),
    Note("screen.open", "info", "Open in {tool}"),
    Note("screen.link", "info", "Link"),
    Note("screen.link_recent", "info", "Link a recent chat"),
    Note("screen.linked", "info", "Linked"),
    Note("screen.attention", "info", "Needs attention"),
    Note("screen.suggestions", "info", "Suggestions"),
    Note("screen.all_chats", "info", "All {tool} chats"),
    Note("screen.activity", "info", "Activity"),
    Note("screen.history", "info", "History"),
    Note("screen.remove", "info", "Remove link"),
    Note("screen.setup", "info", "Setup"),
    Note("status.summary", "info", "{tool}'s agent has {agent_has} of {total} turns. Its chat shows {chat_shows}; {waiting} are waiting."),
    Note("status.synced_up_to", "info", "Synced up to {first_line}"),
    Note("status.since_you_left", "info", "Since you left: {n} turns, {files} files, {commands} commands"),
    Note("status.context", "info", "Context in use: {tokens} tokens"),
    Note("status.reached", "info", "{tool}'s agent has everything above this line"),
    Note("screen.earlier_turns", "info", "{n} earlier turns, in both chats"),
    Note("screen.copy", "info", "Copy to…"),
    Note("screen.resume", "info", "Resume sync"),
    Note("screen.pause", "info", "Pause"),
    Note("screen.refresh", "info", "Refresh"),
    Note("screen.decide", "info", "Decide"),
    Note("screen.show_reply", "info", "Show full reply"),
    Note("screen.tool_calls", "info", "{n} tool calls"),
    Note("filter.all", "info", "All"),
    Note("filter.waiting", "info", "Waiting"),
    Note("filter.attached", "info", "Attached"),
    Note("filter.kept", "info", "Kept back"),
    Note("filter.pinned", "info", "Pinned"),
    Note("status.agent_has", "info", "Agent has {n} turns"),
    Note("status.chat_shows", "info", "Chat shows {n} turns"),
    Note("status.next_message", "info", "{n} turns attached on next message"),
)}


def get(note_id: str) -> Note:
    """Read the wording for a note id."""
    return CATALOGUE[note_id]
