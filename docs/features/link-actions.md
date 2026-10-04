# Feature: what you can do with a link

Part of [the Baton design](../DESIGN.md). Status: requirements agreed, not built. What Baton *shows* about a link is in [sync-status.md](sync-status.md).

## Problem

Linking two chats is not the end of it. The user wants to stop for a while, stop for good, copy a chat across without tying the two together, take back a sync that went wrong, and keep track of chats whose names change. Each of these touches real chats, so each has to say exactly what it will change before it does.

## Goals

1. Every action on a link says, before it runs, **what will change and what will stay**.
2. Anything that removes messages names **each message that will be removed** and requires a confirmation.
3. Anything that needs an app relaunched **says which app and why**, and offers to do it.
4. A sync can be taken back to **any earlier point**, not only the last one.

## Non-goals

- **Deleting a chat in Claude or Codex.** Baton removes links and turns it added; it never deletes a whole chat that an app created.
- **Undoing what an agent did to your files.** Undo is about chats. File changes are a matter for git.
- **Renaming chats without being asked.** Baton follows names; it changes one only through the action in A5.

## Requirements

All of these are in the first version unless marked later.

### One chat, one link

**A0. A chat is linked to exactly one other chat.** A link is always one Claude chat and one Codex chat. A chat cannot be in two links, and there are no links of three.
- Trying to link a chat that is already linked does not create a second link. Baton says which chat it is linked to and offers to change the link.
- *Change the link*: the user picks which side to replace, Claude's or Codex's, and the chat to put there (an existing one, or a new one by either way of linking). The old link is removed first, as in A2: both of its chats stay as they are. Then the new link is made.
- A chat that was left behind by a change, a merge, a brief or a full copy is shown as an earlier copy: not linked, not synced, never deleted.

Reason: with one partner per chat the user always knows where a turn goes and what "in sync" means. With three, every turn would need a rule for who gets it and every difference would be three-way.

### Pause, resume, remove

**A1. Pause and resume.** The user can pause one link. While paused, nothing is delivered either way and no hook attaches anything for that chat; the status says "Paused" and counts what is waiting. Resuming goes through the normal rules, including the merge when both sides moved on.

**A2. Remove a link.** The user can remove a link. Both chats stay exactly as they are; Baton stops syncing them and forgets what it delivered. The confirmation says so, names both chats, and says how many waiting turns will not be delivered.
- Removing a link never removes a message from either chat.

### Copying

**A3. Copy a chat without linking.** From any chat in either app, "Copy to Codex" or "Copy to Claude" creates a new chat on the other side with every turn as a normal message, and does not link the two. Before it runs, Baton says whether a relaunch is needed to see the copy:
- to Codex: none, the copy appears right away;
- to Claude: one relaunch, because Claude lists new chats only when it starts.

The same dialog offers "Copy and link" for the user who wants them kept in sync after all.

**A4. Full copy on demand.** From a linked chat whose side shows fewer turns than its agent has, "Create a full copy" makes a new twin that shows everything. The link moves to the new chat; the old one is left as it is. Same rule as a brief or a merge: a changed view starts a new chat. The relaunch note of A3 applies.

### Names

**A5. Use one name on both sides.** When the two chats' names differ, the user can pick one and Baton renames the other to match. The action says whether the app has to be relaunched to show the new name. Baton never does this by itself: by default it only follows the names ([sync-status.md](sync-status.md), R14).

### Relaunch

**A6. Relaunch from Baton.** "Relaunch Claude" and "Relaunch Codex" do it in the safe order: quit the app, add the waiting turns to the now-closed chats, reopen the app.
- If any chat in that app is in the middle of a reply, Baton warns first, names those chats, says that relaunching stops those replies, and does nothing until the user confirms.
- The warning also offers "Relaunch when idle": Baton waits until no chat in that app is replying, then relaunches.
- If the app could not be reopened, Baton says so, and that the waiting turns were still added.

**A7. Open the chat.** From a link, a button opens Claude or Codex at that chat.

### History and undo

**A8. Sync history.** Each link has a list of everything Baton did to it, newest first: when, in which direction, which turns, and how (added as messages, attached to a message, twin created, merged).

**A9. Undo back to any point.** The user can pick any entry in the history and take the chat back to how it was just before it. This cuts a chat back; it is the one action that removes messages, so:
- Before anything happens, Baton shows **exactly what will be removed and from which chat**: the turns Baton added at and after that point, and every message written in that chat after them, each by its first line and time. It also states the message the chat will end at afterwards.
- Messages that exist only in the chat being cut (never delivered to the other side) are called out separately: "these 2 exist only in Codex".
- The confirmation button names the action and the count: "Remove 5 turns from the Codex chat". Nothing happens until it is pressed.
- A turn that was attached cannot be taken back by itself. Undoing it means cutting that chat back to before the message it was attached to; the dialog says so and lists that message too.
- A chat can only be cut back while it is closed. If it is open, Baton says so and offers the relaunch of A6, doing the cut while the app is closed.
- The other chat is not changed. The turns become "waiting" again and the link is paused, so they are not delivered straight back.

**A10. Saved copy before every cut.** Before cutting, Baton saves what it removes. For 30 days the history entry offers "Restore", which puts the turns back if nothing has been written to the chat since.

### Later

**A11. Folder check.** Warn when the two linked chats work in different folders or on different git branches, since the agent on one side would not see the other's files.

**A12. Save the conversation as a file.** Export a linked chat as Markdown.

**A13. Check a link.** Re-read both chats against Baton's record and report or repair anything that does not match.

## Wording

Following the message rules in the design (section 7a).

| Where | Message |
|---|---|
| Linking a chat that is already linked | **"*name*" is already linked to "*other name*" in Codex.** A chat can be linked to one chat at a time. Buttons: *Change the link*, *Cancel* |
| Change the link | **Link "*name*" to "*new name*" instead?** The link to "*other name*" is removed first. That chat stays exactly as it is and is no longer synced. Buttons: *Change the link*, *Keep the current link* |
| Paused | **Syncing is paused for this chat.** Nothing is sent either way until you resume. 2 turns are waiting. Button: *Resume* |
| Remove a link | **Remove the link between "*Claude name*" and "*Codex name*"?** Both chats stay exactly as they are. Baton stops syncing them. The 2 turns still waiting for Claude will not be delivered. Buttons: *Remove link*, *Keep link* |
| Copy to Codex | **Copy "*name*" to Codex?** Baton creates a new Codex chat with all 16 turns as normal messages. It appears in Codex right away. The two chats will not be kept in sync. Buttons: *Copy to Codex*, *Copy and link*, *Cancel* |
| Copy to Claude | **Copy "*name*" to Claude?** Baton creates a new Claude chat with all 16 turns as normal messages. Claude lists new chats only when it starts, so relaunch Claude once to see it. The two chats will not be kept in sync. Buttons: *Copy to Claude*, *Copy and link*, *Cancel* |
| Undo to a point | **Take the Codex chat back to 14:10?** This removes 5 turns from the Codex chat: 3 that Baton added ("Add logout", "Fix the failing test", "Add refresh tokens") and 2 that you wrote there afterwards ("Store them in Redis", "Add a rate limit"). Those 2 exist only in Codex. Afterwards the Codex chat ends at "Add a login endpoint", 13:40. The Claude chat is not changed. Baton keeps a copy of what it removes for 30 days. Buttons: *Remove 5 turns from the Codex chat*, *Cancel* |
| Undo while the chat is open | **The Codex chat is open, so it can't be cut back right now.** Relaunch Codex and Baton does it while the app is closed. Buttons: *Relaunch Codex and undo*, *Cancel* |
| After an undo | Removed 5 turns from the Codex chat. It now ends at "Add a login endpoint". The link is paused so they are not sent back. Buttons: *Restore*, *Resume sync* |
| Names differ | Claude calls this chat "*name A*". Codex calls it "*name B*". Buttons: *Use "name A" on both*, *Use "name B" on both*, *Keep both* |

## Acceptance scenarios

| # | Given | When | Then |
|---|---|---|---|
| T0 | Claude chat A is linked to Codex chat B | the user tries to link A to Codex chat C | No second link is made; Baton names B and offers "Change the link". On confirm, A is linked to C, and B is unchanged and unlinked. |
| T1 | A link with 2 turns waiting for Claude | the user pauses it, then a reply finishes in Codex | Nothing is delivered and no hook attaches anything; the status reads "Paused, 3 waiting". |
| T2 | A link | the user removes it | Both chat files are byte-for-byte unchanged; the link is gone from Baton. |
| T3 | A Claude chat with 16 turns, not linked | "Copy to Codex" | A new Codex chat holds 16 turns; no link exists; the dialog said no relaunch is needed. |
| T4 | A Codex chat, not linked | "Copy to Claude" | A new Claude chat exists; the dialog said one relaunch is needed; the chat is marked so until Claude is relaunched. |
| T5 | Claude is replying in two chats | the user presses "Relaunch Claude" | A warning names both chats; nothing is quit until the user confirms. |
| T6 | T5 | the user chooses "Relaunch when idle" | Baton relaunches only after both replies have finished. |
| T7 | Three syncs into the Codex chat, then two turns written in Codex | the user picks the second sync in the history and "Undo" | The dialog lists the turns Baton added in the second and third syncs and the two written afterwards, calls out the two as existing only in Codex, and names the message the chat will end at. |
| T8 | T7, confirmed, Codex chat closed | — | The Codex chat ends at the named message; the removed part is saved; the link is paused; the Claude chat is unchanged. |
| T9 | T8 | "Restore" with nothing written since | The Codex chat is back to what it was before the undo. |
| T10 | T7, but the Codex chat is open | the user confirms | Nothing is cut; Baton offers "Relaunch Codex and undo". |
| T11 | A turn was attached to a message in Claude | the user undoes that sync | The dialog says the Claude chat will be cut back to before that message, and lists it. |

## To verify before building

These touch app behaviour not covered by the spike. Each needs one run on a throwaway chat.

- **Cutting a chat back after the app has loaded the later part.** Claude: does the app open a chat whose file is shorter than what it last saw? Codex: its own record of the chat points past the new end of the file; does it rebuild or fail? If either app does not accept it, undo creates a copy that ends at the chosen point and moves the link to it, instead of cutting.
- **Renaming a chat from outside.** Where each app keeps the name, whether a running app picks up a change, and whether it writes its own name back over it.
