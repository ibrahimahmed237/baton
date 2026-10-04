# Feature: when both chats have new turns

Part of [the Baton design](../DESIGN.md). Status: requirements agreed, not built. Related: [sync-status.md](sync-status.md), [link-actions.md](link-actions.md).

## Problem

Normally one side is ahead and the other catches up. Sometimes both are ahead: the user worked in Claude and in Codex before either received the other's turns. That happens when a hook was missing or failed, when a link was paused, or when both chats were closed and used separately.

Now there are turns on each side the other has never seen. Baton cannot quietly pick an order: the order decides what each agent believes happened last, and Baton never rewrites a chat. The user has to see what is unsynced on each side and decide.

## Goals

1. The user sees **the unsynced messages of both sides together**, as messages.
2. The user decides **the order** they are merged in, starting from a sensible proposal.
3. Before confirming, the user sees **what each app will end up with**: same chat or a new one, and whether a relaunch is needed.
4. Nothing is written until the user confirms.

## Non-goals

- **Merging file contents.** If both agents changed the same file, Baton says so. Resolving it is a job for git and the user.
- **Reordering turns that are already on both sides.** Only the unsynced turns can be arranged.
- **Changing the order of one app's own turns.** A reply often depends on the turn before it in the same chat.

## Requirements

All in the first version.

**M1. Stop and flag.** When both sides have turns the other never received, Baton writes nothing. The link reads "Needs a decision" in the menu bar and in its status, with how many turns each side has.

**M2. Show both sides' unsynced turns.** The decision screen lists every unsynced turn as a message: what the user wrote, the start of the reply, the app it was written in and the time. Above them it shows the last turn both sides share.

**M3. Proposed order.** The turns are first shown in the order they started. This is the default.

**M4. The user can change the order.** Any unsynced turn can be moved up or down past turns from the other app.
- Turns from the same app keep their order relative to each other; Baton does not allow swapping two of Claude's turns or two of Codex's.
- Three shortcuts set the whole order at once: *By time*, *Claude's first*, *Codex's first*.

**M5. Result for each app, updated as the order changes.** For the order on screen, Baton says for Claude and for Codex which of these will happen:
- *Keeps its chat.* This side's own unsynced turns all come first, so the other side's turns are simply added at the end. If the chat is open they are attached to the next message instead, as usual.
- *Gets a merged copy as a new chat.* The order puts the other side's turns between or before this side's own. Baton does not rewrite a chat, so it creates a new one in the chosen order and moves the link to it. The old chat is left as it is and marked as an earlier copy.
- Whether a relaunch is needed to see it: a new Claude chat needs one relaunch of Claude; a new Codex chat appears right away.

With unsynced turns on both sides, at most one side can keep its chat. The screen says which shortcut lets a given side keep its chat.

**M6. "Don't reorder."** A fourth choice merges without creating any new chat: each side gets the other side's turns added after its own. The two chats then hold the same turns in a different order, and Baton says so before the user confirms.

**M7. Turns that ran at the same time.** Two turns whose times overlap are marked as such. They are ordered by start time unless the user moves them.

**M8. Same file changed on both sides.** If unsynced turns on both sides changed the same file, Baton names the file and the turns, and says that it does not merge files.

**M9. Other ways out.** *Keep Claude's* or *Keep Codex's*: only that side's turns are sent across; the other side's unsynced turns stay where they were written and are marked skipped. *Split*: the link is removed and the two chats continue separately. Each says what it does before the user confirms.

**M10. Confirm, and remember if asked.** The confirm button names the action ("Merge in this order"). An option "Always merge by time without asking" makes later merges automatic; it can be changed at any time in Settings. Even then Baton stops and asks when M8 applies.

**M11. After the merge.** The status shows where every turn now is. Where a new chat was created, the link points at it and the screen offers to open it. The merge is one entry in the sync history and can be undone like any other ([link-actions.md](link-actions.md), A9).

**M12. Large merges.** If a merged copy would be very large, Baton offers a brief in the new chat instead of the full history, as for any hand-off.

## Wording

| Where | Message |
|---|---|
| Header | **Both chats have new turns.** Claude has 2 turns Codex never received, and Codex has 2 that Claude never received. Nothing has been changed yet. |
| Order help | Move a turn up or down to change where it goes. Turns from the same app keep their order. |
| Result, keeps its chat | **Claude keeps its chat.** Codex's 2 turns are added at the end. The chat is open, so they are attached to your next message there; relaunch Claude first to get them as normal messages. |
| Result, new chat in Claude | **Claude gets a merged copy as a new chat.** In this order a Codex turn goes between two of Claude's, and Baton does not rewrite a chat. Relaunch Claude once to see the new chat. The old chat stays as it is. |
| Result, new chat in Codex | **Codex gets a merged copy as a new chat.** In this order a Claude turn goes before one of Codex's. It appears in Codex right away. The old chat stays as it is. |
| Don't reorder | Each chat gets the other's turns at its end. No new chat. The two chats will hold the same turns in a different order. |
| Same file | Both agents changed `src/auth/middleware.ts`, in turns 14 and 15. Baton does not merge files. Check that file. |
| Buttons | *Merge in this order*, *Keep Claude's*, *Keep Codex's*, *Split into two chats*, *Cancel* |

## Acceptance scenarios

| # | Given | When | Then |
|---|---|---|---|
| U1 | Claude has unsynced turns C1, C2 and Codex has X1, by time C1, X1, C2 | the screen opens | Order shown is C1, X1, C2; both sides read "gets a merged copy as a new chat"; nothing is written. |
| U2 | U1 | the user picks "Claude's first" | Order is C1, C2, X1; Claude reads "keeps its chat"; Codex reads "gets a merged copy as a new chat". |
| U3 | U1 | the user tries to move C2 above C1 | The move is not allowed and the help text says why. |
| U4 | U1 | the user moves X1 to the top | Order is X1, C1, C2; Codex keeps its chat; Claude gets a merged copy. |
| U5 | U2, confirmed, Claude chat open | — | X1 is waiting for Claude and will be attached to the next message; a new Codex chat holds the shared turns then C1, C2, X1; the link points at it; the old Codex chat is unchanged. |
| U6 | U1 | "Don't reorder", confirmed | Claude's chat ends C1, C2, X1 and Codex's ends X1, C1, C2 (added or attached as usual); no new chat exists. |
| U7 | C2 and X1 changed the same file | the screen opens | The file and both turns are named; with "always merge by time" on, Baton still stops and asks. |
| U8 | U1 | "Keep Claude's", confirmed | C1, C2 reach Codex; X1 stays only in Codex and is marked skipped. |
| U9 | Any merge was confirmed | the user undoes it from the history | Chats that were only added to are cut back; chats that were created are removed from the link and left in place. |
