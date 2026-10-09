"""User-facing wording from the feature specifications.

Templates substitute tool names and counts instead of branching on a tool.
E12 completes and audits the catalogue; earlier packages add their specified wording.
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
    Note('screen.settings', "info", 'Settings'),
    Note('screen.open_window', "info", 'Open Baton'),
    Note('screen.quit', "info", 'Quit Baton…'),
    Note('quit.title', "info", 'Quit Baton?'),
    Note('quit.confirm', "info", 'Baton will close. Your saved settings will be kept.'),
    Note('screen.received_here', "info", 'History received through this turn'),
    Note('screen.received_both', "info", 'Both agents have the conversation through this turn.'),
    Note('screen.received_one', "info", '{tool} has the conversation through this turn.'),
    Note('screen.received_hidden', "info", 'Received history outside this view'),
    Note('screen.received_hidden_tool', "info", '{tool} has history through turn {seq}.'),
    Note('settings.preview', "info", 'These choices are saved for this preview. Live chat syncing is not connected yet.'),
    Note('settings.appearance', "info", 'Appearance'),
    Note('settings.sync', "info", 'Sync and delivery'),
    Note('settings.chats', "info", 'Chats and context'),
    Note('settings.default', "info", 'Default: {value}'),
    Note('settings.reset', "info", 'Restore defaults'),
    Note('settings.saved', "info", 'Saved'),
    Note('settings.error', "info", 'The change could not be saved. Your previous choice is still in use.'),
    Note('settings.invalid', "info", 'Enter a positive whole number of tokens.'),
    Note('settings.on', "info", 'On'),
    Note('settings.off', "info", 'Off'),
    Note('settings.on_button', "info", 'Ask me to add them'),
    Note('settings.automatic', "info", 'Add automatically when idle'),
    Note('settings.ask', "info", 'Ask each time'),
    Note('settings.by_time', "info", 'Merge by time'),
    Note('settings.notice_on_attach', "info", 'Show a notice when history is attached'),
    Note('settings.offer_relaunch', "info", 'Offer to relaunch for visible messages'),
    Note('settings.add_to_idle_claude', "info", 'Delivery to an idle {tool} chat'),
    Note('settings.offer_switch_at_limit', "info", 'Offer to switch when a limit is reached'),
    Note('settings.merge', "info", 'When both chats have new turns'),
    Note('settings.brief_threshold_tokens', "info", 'Offer a brief above this token count'),
    Note('settings.hide_script_chats', "info", 'Hide chats created by scripts'),
    Note('settings.title_tag', "info", 'Tag chat titles with Baton'),
    Note('settings.theme', "info", 'Colour theme'),
    Note('settings.glass', "info", 'Surface opacity'),
    Note('settings.glass_help', "info", 'Lower values let more of the background show through.'),
    Note('settings.apply', "info", 'Apply'),
    Note('settings.loading', "info", 'Loading settings…'),
    Note("quit.actions", "warning", "Quit Baton?", (Button("cancel", "Keep Baton open", True), Button("quit", "Quit Baton"))),

    Note("setup.hooks", "warning", "Baton's hooks are not ready in {tool}. Install Baton's hooks and check again."),
    Note("setup.runner", "warning", "{tool} cannot run a background brief. Check its command and sign in, or use the offline brief."),
    Note("nothing_unusual", "info", "Nothing unusual."),
    Note("new_chat.at_once", "info", "The new chat appears in {tool} right away. No relaunch."),
    Note("new_chat.relaunch", "info", "Baton closes {tool}, creates the chat, and opens {tool} again at it. {tool} lists a new chat only when it starts; you do this once for this chat.", ("Close {tool}, sync, reopen", "Sync now, I relaunch later", "Cancel"), "Relaunch {tool} to see this chat"),
    Note("write.app_must_close", "warning", "Baton closes {tool}, writes, and opens {tool} again on this folder; your windows come back. Baton never writes while {tool} runs, because {tool} would write over it.", ("Close {tool}, sync, reopen", "Attach instead", "Cancel"), "{n} turns waiting until {tool} is closed"),
    Note("relaunch.replying", "warning", '{tool} is replying in "{title}". Closing now stops that reply.', ("Wait until it has finished", "Close anyway", "Cancel"), "Will sync when {tool} is idle"),
    Note("format.unknown_version", "warning", "{tool} was updated and saves chats differently (version {version}). Baton still reads its chats and attaches turns, but will not create or add messages there until Baton is updated.", (), "{tool}: reading only"),
    Note("link.attached_history", "info", "The agent gets the history with your first message. The chat will never show it as separate messages.", (), "Agent has {n} turns the chat does not show"),
    Note("write.chat_open", "info", "These {n} turns will be attached to your next message there. To get them as normal messages, relaunch {tool}.", ("Close {tool}, sync, reopen",), "{n} turns waiting, attached on next message"),
    Note("write.chat_open_release", "info", "These {n} turns will be attached to your next message there. To get them as normal messages, relaunch {tool}.", ("Close {tool}, sync, reopen", "Add them now"), "{n} turns waiting, attached on next message"),
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
    Note("link.full_copy", "info", "A new {tool} chat shows the full history. The link moves to it; your current chat stays exactly as it is."),
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
    Note("history.title_tag", "info", "[{tool}]"),
    Note("mapping.tool_call", "info", "Tool call {n}: {tool}\n{input}\n{text}"),
    Note("mapping.tool_result", "info", "Tool result for call {n}: {text}\nError: {is_error}"),
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
    Note("screen.theme", "info", "Appearance"),
    Note("screen.theme.light", "info", "Light"),
    Note("screen.theme.graphite", "info", "Dark"),
    Note("screen.theme.system", "info", "System"),
    Note("screen.chats", "info", "Chats"),
    Note("screen.links", "info", "Links"),
    Note("screen.sync_status", "info", "Sync status"),
    Note("screen.turn_by_turn", "info", "Turn by turn"),
    Note("screen.conversation", "info", "Conversation"),
    Note("screen.empty", "info", "No linked chats yet"),
    Note("screen.list_empty", "info", "No items yet"),
    Note("empty.popover.title", "info", "No linked chats yet"),
    Note("empty.popover.body", "info", "Choose Link a recent chat to find a conversation to link."),
    Note("empty.linked.title", "info", "No linked chats yet"),
    Note("empty.linked.body", "info", "Choose a chat from the sidebar to link it with another coding agent."),
    Note("empty.attention.title", "info", "Nothing needs your attention"),
    Note("empty.attention.body", "info", "Chats that need a decision or another step appear here."),
    Note("empty.suggestions.title", "info", "No suggested links yet"),
    Note("empty.suggestions.body", "info", "Choose a chat from the sidebar to make a link yourself."),
    Note("empty.chats.title", "info", "No chats found"),
    Note("empty.chats.body", "info", "Start a chat in this app, then refresh Baton."),
    Note("empty.activity.title", "info", "No activity yet"),
    Note("empty.activity.body", "info", "Syncs and changes to your links appear here."),
    Note("empty.select_link.title", "info", "Choose a linked conversation"),
    Note("empty.select_link.body", "info", "Select a pair from the sidebar to see what each agent has received and what is waiting."),
    Note("empty.select_chat.title", "info", "Choose a chat"),
    Note("empty.select_chat.body", "info", "Select a chat to link it with another agent or copy its history."),
    Note("empty.select_suggestion.title", "info", "Choose a suggested link"),
    Note("empty.select_suggestion.body", "info", "Select a pair to see the two conversations."),
    Note("empty.select_activity.title", "info", "Choose an activity"),
    Note("empty.select_activity.body", "info", "Select an entry to see its linked conversation and what changed."),
    Note("empty.conversation.title", "info", "No conversation turns yet"),
    Note("empty.conversation.body", "info", "Turns appear here after a conversation has been recorded."),
    Note("empty.filtered.title", "info", "No turns match this filter"),
    Note("empty.filtered.body", "info", "The conversation is still here. Show all turns to see it."),
    Note("screen.show_all_turns", "info", "Show all turns"),
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
    Note("status.first_message", "info", "These {n} turns will be attached to your first message."),
    Note("status.chat_held", "info", "{tool} still has this chat open. Relaunch {tool} to see {n} waiting turns as normal messages."),
    Note("status.next_none", "info", "If you send a message now, nothing extra is attached."),
    Note("status.checked", "info", "Last checked {at}"),
    Note("screen.show_tools", "info", "Show tool activity"),
    Note("screen.hide_tools", "info", "Hide tool activity"),
    Note("screen.hide_reply", "info", "Hide full reply"),
    Note("message.prompt", "info", "User"),
    Note("message.reply", "info", "Reply"),
    Note("message.tool_call", "info", "Tool call"),
    Note("message.tool_result", "info", "Tool result"),
    Note("message.tool_text", "info", "Tool activity"),
    Note("status.tool_activity", "info", "Ran {commands} commands, changed {files} files"),
    Note("status.attached", "info", "{tool}'s agent has {n} attached turns. They are not shown as messages in this chat."),
    Note("status.setup_ready", "ok", "Baton's hooks are installed and trusted in {tool}."),
    Note("status.new_chat_relaunch", "info", "Relaunch {tool} to see this chat.", ("Relaunch {tool}",), "Relaunch {tool} to see this chat"),
    Note("dialog.link", "info", "Link a chat"),
    Note("dialog.target", "info", "Tool"),
    Note("dialog.target_chat", "info", "Chat"),
    Note("dialog.new_chat", "info", "New chat"),
    Note("dialog.retained_side", "info", "Keep this side"),
    Note("dialog.ways", "info", "Ways to link"),
    Note("dialog.what_will_happen", "info", "What will happen"),
    Note("dialog.actions", "info", "Link a chat", (Button("create", "Create", True), Button("copy_without_linking", "Copy without linking"), Button("copy_and_link", "Copy and link"), Button("cancel", "Cancel"), Button("change_link", "Change the link"), Button("full_copy", "Create a full copy"))),
    Note("link.large_copy", "info", "This chat is about {tokens} tokens. A brief in a new chat is available instead."),
    Note("mode.full_copy", "info", "Copy the full history"),
    Note("mode.attached_history", "info", "Start now, history attached"),
    Note("mode.brief_new_chat", "info", "A brief starts a new chat."),
    Note("mode.brief", "info", "Brief in a new chat"),
    Note("tag.no_relaunch", "info", "No relaunch"),
    Note("tag.history_attached", "info", "History attached"),
    Note("tag.new_chat", "info", "New chat"),
    Note("undo.cut", "warning", "This removes {n} turns from the {tool} chat, listed below. {tool}'s agent stops having them right away; the chat still displays them until you relaunch {tool}. A copy is kept for 30 days.", (Button("undo", "Remove {n} turns from the {tool} chat", True), Button("cancel", "Cancel")), "Relaunch {tool} to stop seeing the removed turns"),
    Note("undo.cut_reopen", "warning", "This removes {n} turns from the {tool} chat, listed below. If the chat is on screen, open it again to see the change. A copy is kept for 30 days.", (Button("undo", "Remove {n} turns from the {tool} chat", True), Button("cancel", "Cancel")), "Open the chat again to see the change"),
    Note("undo.shorter", "warning", "{tool} can't make a chat shorter, so Baton creates a shorter chat and links it. Your current chat stays as it is.", (Button("undo", "Create the shorter {tool} chat", True), Button("cancel", "Cancel")), "Earlier chat kept"),
    Note("undo.shorter_closed", "warning", "{tool}'s agent would keep turns that are only hidden, so Baton creates a shorter {tool} chat and links it. {tool} is closed while it is created. Your current chat stays as it is.", (Button("undo", "Close {tool}, create the shorter chat, reopen", True), Button("cancel", "Cancel")), "Earlier chat kept"),
    Note("undo.replying", "warning", "{tool} is replying in this chat, so it can't be taken back right now. Baton can do it as soon as the reply has finished.", (Button("when_idle", "Undo when the reply has finished", True), Button("cancel", "Cancel"))),
    Note("undo.attached", "warning", "Undoing it means going back to before the message it was attached to."),
    Note("undo.only_here", "warning", "Those {n} exist only in {tool}."),
    Note("undo.ends_at", "info", 'Afterwards the {tool} chat ends at "{first_line}", {at}.'),
    Note("undo.earlier_copy", "info", "Earlier copy"),
    Note("undo.restore", "info", "Restore", (Button("restore", "Restore", True), Button("cancel", "Cancel"))),
    Note("undo.earlier_chat", "info", "Go back to the earlier chat", (Button("restore", "Go back to the earlier chat", True), Button("cancel", "Cancel"))),
    Note("undo.merge", "warning", "Chats that were created are removed from the link and left in place."),
    Note("merge.header", "warning", "Both chats have new turns. {first_tool} has {first_count} turns {second_tool} never received, and {second_tool} has {second_count} that {first_tool} never received. Nothing has been changed yet."),
    Note("merge.order_help", "info", "Move a turn up or down to change where it goes. Turns from the same app keep their order."),
    Note("merge.dont_reorder", "warning", "Each chat gets the other's turns at its end. No new chat. The two chats will hold the same turns in a different order."),
    Note("merge.same_file", "warning", "Both agents changed {file}, in turns {turns}. Baton does not merge files. Check that file."),
    Note("merge.large_copy", "info", "This merged copy is about {tokens} tokens. A brief in a new chat is available instead."),
    Note("merge.keeps_chat", "info", "{tool} keeps its chat. {other_tool}'s {turns} turns are added at the end."),
    Note("merge.merged_copy", "info", "{tool} gets a merged copy as a new chat. The old chat stays as it is."),
    Note("merge.keep", "warning", "Only {tool}'s turns are sent across. {other_tool}'s unsynced turns stay where they were written and are marked skipped."),
    Note("merge.split", "warning", "The link is removed and the two chats continue separately."),
)}


def get(note_id: str) -> Note:
    """Read the wording for a note id."""
    return CATALOGUE[note_id]
