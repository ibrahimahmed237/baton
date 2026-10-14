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
    Note('screen.received_here', "info", 'Position in this conversation'),
    Note('screen.received_both', "info", 'Both agents reached this turn.'),
    Note('screen.received_one', "info", "{tool} reached this turn."),
    Note('screen.received_hidden', "info", 'Position outside this view'),
    Note('screen.received_hidden_tool', "info", "{tool} reached turn {seq} in this conversation."),
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

    Note("setup.adapter_unavailable", "warning", "Baton cannot use {tool} yet."),
    Note("setup.hooks", "warning", "Baton's hooks are not ready in {tool}. Install Baton's hooks and check again."),
    Note("hooks.command_failed", "warning", "Baton could not run the hook command. Nothing was attached."),
    Note("setup.runner_reinstall", "warning", "{tool}’s command-line tool is damaged or missing. Reinstall it, or use the offline brief."),
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
    Note("screen.conversation_guide", "info", "An agent may have a turn even when its chat does not show it."),
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
    Note("status.reached", "info", "{tool}'s agent has reached here"),
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
    Note("plan.confirm_undo", "warning", "Undo this merge", (Button("undo", "Undo this merge", True), Button("cancel", "Cancel"))),
    Note("plan.confirm_merge", "danger", "Merge in this order", (Button("confirm", "Merge in this order", True), Button("cancel", "Cancel"))),
    Note("plan.confirm_keep", "warning", "Keep {tool}'s turns", (Button("confirm", "Keep {tool}'s", True), Button("cancel", "Cancel"))),
    Note("plan.confirm_split", "warning", "Split into two chats", (Button("confirm", "Split into two chats", True), Button("cancel", "Cancel"))),
    Note("merge.keep_choice", "info", "Keep {tool}'s", (Button("keep", "Keep {tool}'s"),)),
    Note("merge.split_choice", "info", "Split into two chats", (Button("split", "Split into two chats"),)),
    Note("merge.brief_choice", "info", "Brief in a new chat", (Button("brief", "Brief in a new chat"),)),
    Note("merge.always", "info", "Always merge by time without asking", (Button("always", "Always merge by time without asking"),)),
    Note("merge.open", "info", "Open {tool}", (Button("open", "Open {tool}"),)),
    Note("merge.copy_relaunch", "info", "Relaunch {tool} once to see the new chat."),
    Note("merge.copy_visible", "info", "The new chat appears in {tool} right away."),
    Note("merge.overlap", "warning", "These turns ran at the same time."),
    Note("undo.group_added", "info", "Baton added in {tool}"),
    Note("undo.group_written", "info", "Written afterwards in {tool}"),
    Note("history.empty", "info", "No history yet. Syncs and changes to this link appear here."),
    Note("history.undo_action", "info", "Undo", (Button("undo", "Undo"),)),
    Note("history.restore_action", "info", "Restore", (Button("restore", "Restore"),)),
    Note("merge.header", "warning", "Both chats have new turns. {first_tool} has {first_count} turns {second_tool} never received, and {second_tool} has {second_count} that {first_tool} never received. Nothing has been changed yet."),
    Note("merge.order_help", "info", "Move a turn up or down to change where it goes. Turns from the same app keep their order."),
    Note("merge.dont_reorder", "warning", "Each chat gets the other's turns at its end. No new chat. The two chats will hold the same turns in a different order."),
    Note("merge.same_file", "warning", "Both agents changed {file}, in turns {turns}. Baton does not merge files. Check that file."),
    Note("merge.large_copy", "info", "This merged copy is about {tokens} tokens. A brief in a new chat is available instead."),
    Note("merge.keeps_chat", "info", "{tool} keeps its chat. {other_tool}'s {turns} turns are added at the end."),
    Note("merge.merged_copy", "info", "{tool} gets a merged copy as a new chat. The old chat stays as it is."),
    Note("merge.keep", "warning", "Only {tool}'s turns are sent across. {other_tool}'s unsynced turns stay where they were written and are marked skipped."),
    Note("merge.split", "warning", "The link is removed and the two chats continue separately."),
    Note("error.unexpected", "danger", "Something unexpected went wrong in Baton. Check your chats before you try again. Baton's log has the details."),
    # Ibrahim-approved completed history and merge choice labels, 2026-10-10.
    Note("history.linked", "info", "Linked chats"),
    Note("history.added", "info", "Added {n} turns in {tool}"),
    Note("history.attached", "info", "Attached {n} turns in {tool}"),
    Note("history.created", "info", "Created a chat in {tool}"),
    Note("history.merged", "info", "Merged chats"),
    Note("history.undone", "info", "Undid this change"),
    Note("history.restored", "info", "Restored this change"),
    Note("history.paused", "info", "Paused sync"),
    Note("history.resumed", "info", "Resumed sync"),
    Note("history.removed", "info", "Removed link"),
    Note("history.moved", "info", "Changed linked chat"),
    Note("history.brief", "info", "Created a brief in {tool}"),
    # Ibrahim Q8: retain bookkeeping in visible history with distinct labels.
    Note("history.aligned", "info", "Recognized {n} existing turns in {tool}"),
    Note("history.aligned_one", "info", "Recognized an existing turn in {tool}"),
    Note("history.attach_pending", "info", "Queued {n} turns for your next message in {tool}"),
    Note("history.attach_pending_one", "info", "Queued a turn for your next message in {tool}"),
    Note("history.not_confirmed", "warning", "Could no longer confirm {n} turns in the {tool} chat"),
    Note("history.not_confirmed_one", "warning", "Could no longer confirm a turn in the {tool} chat"),
    Note("history.undo_shown", "info", "You confirmed removed turns are no longer shown in {tool}"),
    Note("history.recorded", "info", "Recorded a history entry"),
    Note("merge.preset_time", "info", "By time"),
    Note("merge.preset_first", "info", "{tool} first"),
    Note("merge.preset_keep", "info", "Keep each chat’s order"),
    # Ibrahim-approved CP2 review controls; explanatory notes keep their original wording.
    Note("plan.confirm_sync", "info", "Sync the waiting turns.", (Button("confirm", "Sync", True), Button("cancel", "Cancel"))),
    Note("plan.confirm_continue", "info", "Sync and continue this chat in {tool}.", (Button("confirm", "Continue in {tool}", True), Button("cancel", "Cancel"))),
    Note("plan.confirm_copy", "info", "Create the copy described above.", (Button("confirm", "Copy chat", True), Button("cancel", "Cancel"))),
    Note("plan.confirm_link", "info", "Create the linked chat described above.", (Button("confirm", "Create linked chat", True), Button("cancel", "Cancel"))),
    Note("plan.confirm_unlink", "info", "Remove the link described above.", (Button("confirm", "Remove link", True), Button("cancel", "Cancel"))),
    Note("plan.confirm_relaunch", "info", "Relaunch {tool} as described above.", (Button("confirm", "Relaunch {tool}", True), Button("cancel", "Cancel"))),
    Note("plan.confirm_brief_generation", "info", "Generate a read-only brief using the writers and estimated costs above. Review the result before creating a chat.", (Button("confirm", "Generate brief", True), Button("cancel", "Cancel"))),
    Note("plan.confirm_brief_creation", "info", "Create a new chat with this brief. The earlier chat is kept.", (Button("confirm", "Create chat", True), Button("cancel", "Cancel"))),
    Note("plan.unavailable", "info", "This action is not available yet. Your current choice is kept.", (Button("cancel", "Cancel"),)),
    Note("plan.choose_counterpart", "info", "Choose the other chat before continuing.", (Button("choose_chat", "Choose chat", True), Button("cancel", "Cancel"))),
    Note("brief.summary_receipt", "info", "Summarized through this turn. The original messages are in the saved history."),
    Note("brief.cost", "info", "{tool} can write this read-only brief using about {tokens} tokens."),
    Note("brief.total_cost", "info", "If fallback is needed, the listed requests total about {tokens} tokens. Each writer is tried at most once."),
    Note("brief.pinned_size", "info", "Pinned turns add about {tokens} tokens in full."),
    Note("handoff.title", "info", "Continue the conversation"),
    Note("handoff.sides", "info", "Both chats"),
    Note("handoff.mode", "info", "What to send"),
    Note("handoff.full", "info", "Full history"),
    Note("handoff.full_help", "info", "Send the original turns that are waiting."),
    Note("handoff.brief", "info", "Brief in a new chat"),
    Note("handoff.brief_help", "info", "Start a fresh chat with a summary, important turns and saved history."),
    Note("handoff.writer", "info", "Who writes the brief"),
    Note("handoff.writer_choices", "info", "Choose how to write the brief.", (Button("automatic", "Automatic", True), Button("offline", "Offline"))),
    Note("handoff.preview", "info", "Review before continuing"),
    Note("handoff.actions", "info", "Review your choice.", (Button("review", "Review", True), Button("cancel", "Cancel"))),
    # E9, working-across W1 to W8. Times and counts arrive already formatted.
    Note("limit.reached", "warning", "{tool} has reached its usage limit."),
    Note("limit.available_at", "info", "{tool} is available again at {time}.", (), "{tool} is available again at {time}"),
    Note("limit.available", "ok", "{tool} is available again.", (), "{tool} is available again"),
    Note("limit.offer_linked", "warning", "{tool} has reached its usage limit. It resets at {time}. Continue this chat in {other_tool}? {other_tool} already has every turn.", (Button("continue", "Continue in {other_tool}", True), Button("not_now", "Not now"))),
    Note("limit.offer_linked_behind", "warning", "{tool} has reached its usage limit. It resets at {time}. Continue this chat in {other_tool}?", (Button("continue", "Continue in {other_tool}", True), Button("not_now", "Not now"))),
    Note("limit.offer_linked_no_reset", "warning", "{tool} has reached its usage limit. Continue this chat in {other_tool}? {other_tool} already has every turn.", (Button("continue", "Continue in {other_tool}", True), Button("not_now", "Not now"))),
    Note("limit.offer_linked_no_reset_behind", "warning", "{tool} has reached its usage limit. Continue this chat in {other_tool}?", (Button("continue", "Continue in {other_tool}", True), Button("not_now", "Not now"))),
    Note("limit.offer_unlinked", "warning", "{tool} has reached its usage limit. It resets at {time}. This chat is not linked to a {other_tool} chat yet.", (Button("link_and_continue", "Link it and continue in {other_tool}", True), Button("not_now", "Not now"))),
    Note("limit.offer_unlinked_no_reset", "warning", "{tool} has reached its usage limit. This chat is not linked to a {other_tool} chat yet.", (Button("link_and_continue", "Link it and continue in {other_tool}", True), Button("not_now", "Not now"))),
    Note("context.in_use", "info", "About {tokens} tokens in use, {percent}% of {size}."),
    Note("context.in_use_no_size", "info", "About {tokens} tokens in use."),
    Note("context.nearly_full", "warning", "{tool} will soon summarise this chat by itself. Continuing in {other_tool}, or handing off with a brief, avoids that."),
    Note("context.nearly_full_alone", "warning", "{tool} will soon summarise this chat by itself. Handing off with a brief avoids that."),
    Note("digest.since_you_left", "info", "Since your last message here at {at}, {tool} did {turns}, changed {files} and ran {commands}.", (Button("show_changes", "Show what changed", True),)),
    Note("digest.turns_one", "info", "{n} turn"),
    Note("digest.turns_other", "info", "{n} turns"),
    Note("digest.files_one", "info", "{n} file"),
    Note("digest.files_other", "info", "{n} files"),
    Note("digest.commands_one", "info", "{n} command"),
    Note("digest.commands_other", "info", "{n} commands"),
    Note("cli.catch_up", "info", "Catch up, then send"),
    Note("cli.notify", "info", "Sync when the reply has finished"),
    Note("catch_up.turn", "info", "{at}\n{body}"),
    Note("catch_up.notice_one", "info", 'Baton attached {n} turn from {tool} to this message: {titles}.'),
    Note("catch_up.notice", "info", 'Baton attached {n} turns from {tool} to this message: {titles}.'),
    Note("catch_up.block", "info", "<baton-catch-up>\n{body}\n</baton-catch-up>"),
    # E10, DESIGN 6 and working-across W4, W15: the brief in a new chat.
    Note("brief.prompt", "info", "Write a brief of the conversation below so that another coding agent can carry on the work. Cover the decisions made, the state of the work, the files touched and what is still open. Only read: do not change any file and do not run anything that changes something.\n\n{conversation}"),
    Note("brief.update_prompt", "info", "Update the safe brief below using only the newly appended conversation. Retain the earlier decisions, state of the work, files touched and open questions where they still apply. Only read: do not change any file and do not run anything that changes something.\n\nEarlier brief:\n{summary}\n\nNew conversation:\n{conversation}"),
    Note("brief.intro", "info", "This chat carries on work done in {tool}. Below is a brief of it."),
    Note("brief.first_request", "info", "The first request was:\n{text}"),
    Note("brief.requests_heading", "info", "Requests so far:"),
    Note("brief.request_item", "info", "{n}. {text}"),
    Note("brief.pinned_heading", "info", "Pinned turns, in full:"),
    Note("brief.recent_heading", "info", "Most recent turns:"),
    Note("brief.files_heading", "info", "Files touched:"),
    Note("brief.file_item", "info", "- {path}"),
    Note("brief.transcript_path", "info", "The full history is saved at {path}. Read it for any detail not above."),
    Note("brief.turn_header", "info", "At {at} in {tool}"),
    Note("brief.md_title", "info", "# Conversation history"),
    Note("brief.md_turn", "info", "## Turn {n}, at {at} in {tool}"),
    Note("brief.line_user", "info", "User: {text}"),
    Note("brief.line_reply", "info", "Reply: {text}"),
    Note("brief.skipped_limit", "warning", "{tool} couldn't write the brief because it has reached its usage limit."),
    Note("brief.skipped_failed", "warning", "{tool} couldn't write the brief."),
    Note("brief.skipped_no_runner", "warning", "{tool} can't run in the background, so it was not asked to write the brief."),
    Note("brief.written_by", "info", "{tool} wrote the brief."),
    Note("brief.used_offline", "info", "Baton used the offline summary instead."),
    Note("brief.large_chat", "info", "This chat is large, about {tokens} tokens. Sending all of it would fill most of {tool}'s context. Baton suggests a brief in a new chat instead.", (Button("write_brief", "Write a brief", True), Button("send_in_full", "Send in full"))),
)}


# CP3 carry-over: usage copy and known-shape versions.
CATALOGUE.update({note.id: note for note in (
    Note("cli.usage", "warning", "Baton could not understand this command. Use --help to see its arguments."),
    Note("cli.unknown_command", "warning", "Baton does not know the command {command}."),
    Note("cli.no_plan_flags", "warning", "{command} takes neither --dry-run nor --confirm."),
    Note("cli.conflicting_flags", "warning", "--dry-run and --confirm cannot be used together."),
    Note("format.new_version", "info", "This version of {tool}, {version}, was not checked yet. Baton reads and writes it because its chat format is the same."),
)})


CATALOGUE.update({"plan.wrong_action": Note("plan.wrong_action", "warning", "This plan belongs to another action. Review a plan for this action before confirming.")})


def get(note_id: str) -> Note:
    """Read the wording for a note id."""
    return CATALOGUE[note_id]


# Cursor refuses closure until hooks can supply reply evidence.
CATALOGUE.update({note.id: note for note in (
    Note("relaunch.replying_unknown", "warning", "Baton cannot tell whether a chat is replying in {tool}, so it cannot close it."),
)})


CATALOGUE.update({note.id: note for note in (
    Note('rename.at_once', 'info', '{tool} shows the new name "{name}" right away.'),
    Note('rename.relaunch', 'info', '{tool} shows the new name "{name}" after a relaunch.', (), 'Relaunch {tool} to see the new name'),
    Note('rename.closed', 'warning', '{tool} is renamed while closed. Baton offers to close {tool}, rename it to "{name}" and reopen.',
         (Button('close_rename_reopen', 'Close {tool}, rename, reopen', True), Button('cancel', 'Cancel')), 'Relaunch {tool} to see the new name'),
)})

CATALOGUE.update({note.id: note for note in (
    Note('keep.missing_turns', 'warning', '{tool} is missing {n} kept turns the conversation may refer to.'),
    Note('keep.unchanged', 'info', 'This turn stays in {tool}. No chat is changed.', (), 'Kept in {tool}'),
    Note('pin.unchanged', 'info', 'This turn is pinned. No chat is changed.', (), 'Pinned'),
    Note('pause.unchanged', 'info', 'Nothing is delivered either way while this link is paused. No chat is changed.', (), 'Paused'),
)})

CATALOGUE.update({note.id: note for note in (
    Note('setup.not_installed', 'warning', 'Not installed. Install {tool} and check again.'),
    Note('setup.format_unreadable', 'warning', 'Baton cannot check how {tool} saves chats. Check that its chats can be read and check again.'),
    Note('relaunch.replying_safe', 'warning', '{tool} is replying in "{title}". Closing now stops that reply.',
         (Button('when_idle', 'Relaunch when idle', True), Button('cancel', 'Cancel')), 'Will sync when {tool} is idle'),
    Note('relaunch.wait_reply', 'info', '{tool} is replying in "{title}". Baton waits until no chat in {tool} is replying, then relaunches.',
         (Button('cancel', 'Cancel'),), 'Will sync when {tool} is idle'),
    Note('relaunch.order', 'warning', 'Baton closes {tool}, waits until its chats are still, writes, and opens {tool} again.',
         (Button('confirm', 'Close {tool}, sync, reopen', True), Button('cancel', 'Cancel'))),
    Note('relaunch.closed_sync', 'info', '{tool} is closed. Baton syncs its waiting turns without asking.'),
    Note('relaunch.close_timeout', 'warning', '{tool} did not close within a minute. Nothing was written. Close {tool} and try again.'),
    Note('relaunch.reopen_failed', 'warning', '{tool} could not be reopened. The waiting changes were still written. Open {tool} again.'),
    Note('relaunch.reopen_failed_no_write', 'warning', '{tool} could not be reopened. Nothing was written. Open {tool} again.'),
)})

CATALOGUE.update({note.id: note for note in (
    Note('relaunch.close_failed', 'warning', '{tool} could not be closed. Nothing was written. Close {tool} and try again.'),
    Note('relaunch.partial', 'warning', 'Baton wrote the waiting changes for {n} links in {tool}, then stopped. Check the remaining links and try again.'),
    Note('relaunch.reopen_failed_partial', 'warning', '{tool} could not be reopened after some changes were written. Open {tool} again and check the remaining links.'),
    Note('relaunch.closed_open', 'info', '{tool} is closed. Baton writes its waiting changes and opens {tool}.'),
)})


CATALOGUE.update({note.id: note for note in (
    Note('relaunch.idle_timeout', 'warning', 'The request to relaunch {tool} when idle expired. Nothing was written. Review a new request to try again.'),
    Note('relaunch.write_failed', 'warning', 'Baton could not write the waiting changes in {tool}. Check the link and try again.'),
)})

CATALOGUE.update({note.id: note for note in (
    Note('undo.paused', 'warning', 'This link is paused. Resume syncing before undoing a change.'),
    Note('hook.delivery_failed', 'warning', 'Baton could not sync the waiting turns to {tool}. They remain queued. Check the link and try again.'),
    Note('merge.completed_split', 'ok', 'The link was split. Both chats keep their own turns and no longer sync with each other.'),
    Note('merge.completed_keep', 'ok', 'The {tool} chat was kept. Its turns for {other_tool} were delivered or queued; the other side’s separate turns stay only in its own chat.'),
    Note('merge.completed', 'ok', 'The merge decision was applied. Both sides will sync in the chosen order; their delivery status is shown below.'),
    Note('merge.completed_side', 'ok', '{tool} keeps its current chat. Its missing turns are delivered or queued as shown below.'),
)})
