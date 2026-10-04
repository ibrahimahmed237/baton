# Feature: sync status

Part of [the Baton design](../DESIGN.md). Status: requirements agreed, not built. What the user can *do* to a link (pause, remove, copy, undo, rename) is in [link-actions.md](link-actions.md).

## Problem

A linked chat can look different from what its agent knows. Baton delivers a turn in one of two ways: as a normal message when the receiving chat is closed, or attached to the user's next message when it is open. A chat linked with "history attached" never shows its earlier history at all. And some turns may not have arrived yet.

So, looking at Claude or Codex alone, the user cannot tell whether that side is up to date, which message it has reached, whether the agent knows more than the chat shows, or what to do to see the rest. Without an answer the user either stops trusting the sync or sends a message into a chat that is behind.

## Goals

1. For any linked chat, the user can tell from Baton alone, without opening either app, **which message each side has reached**.
2. The user can read **the conversation itself** in Baton, with each message marked by where it stands on each side.
3. The user can tell apart what each side's chat **shows** and what its agent **has** without showing.
4. When something has not arrived, the user is told **why** and **what to do**, including which app to relaunch.
5. The user always knows **which two chats** are linked, by the name each one has in its own app.
6. Baton never reports a side as up to date when it is not.

## Non-goals

- **Turning attached turns into normal messages.** That would mean inserting into the middle of a chat, which Baton does not do. The way to a chat that shows everything is a new full copy ([link-actions.md](link-actions.md), A4).
- **Relaunching an app without the user asking.** A relaunch stops a reply in progress; the user decides.
- **Editing or deleting individual messages.** Baton shows the conversation; it does not let the user change it.
- **Live mirroring of an open chat's screen.** Neither app reloads an open chat; Baton is where the truth is shown.

## Words used

A **turn** is one of the user's messages and the reply to it. For each turn, each side is in exactly one state:

| State | Meaning |
|---|---|
| **Written here** | The turn was created in this app. |
| **Shown** | Baton added it to this app's chat. It appears there as a normal message. |
| **Added, shown after a relaunch** | Baton added it to this app's chat while the app was running (a chat created for Claude, or "Add them now", R5). The agent has it. It appears as a normal message the next time the app starts, and its state then becomes Shown. |
| **Attached** | Baton gave it to this app's agent together with one of the user's messages. The agent has it. It is not shown as a message, and never will be in this chat. |
| **Waiting** | It has not reached this side yet. |
| **Skipped** | The user chose to keep the other side's version in a conflict. It stays only where it was written. |
| **Kept back** | The user marked the turn to stay on the side it was written ([working-across.md](working-across.md), W12). It is not waiting and will not be sent. |

Per side, two things follow from these:

- **What the agent has**: every turn that is written here, shown, added or attached. Its last one is the message this side is synced up to.
- **What the chat shows**: the turns that are written here or shown.

"In sync" means both agents have every turn. A side can be in sync and still show fewer turns than its agent has.

In the app these are said in full, never as bare labels: "Claude's agent has all 16 turns. The chat shows 12 of them; 4 were attached and are not shown."

## User stories

1. As someone about to switch tools, I want to see whether the other chat already has my latest turns, so that I know what will happen when I type there.
2. As someone looking at a chat that seems to be missing messages, I want to know whether the agent has them anyway, so that I don't repeat myself.
3. As someone who wants the missing messages on screen, I want to be told exactly what to do and in which app, so that I don't guess.
4. As someone who linked a chat with the history attached, I want to see what the agent on that side has, since the chat itself doesn't show it.
5. As someone who wants to check what was said, I want to read the messages in Baton, not a row of boxes.
6. As someone with several chats, I want to see each chat's name as it is in Claude and in Codex, so that I know exactly which two I am on.
7. As someone glancing at the menu bar, I want one line per chat that tells me if anything needs me.
8. As someone who distrusts a sync tool, I want every "in sync" to be true.

## Requirements

All of these are in the first version unless marked later.

### Where each side stands

**R1. Position of each side.** For each linked chat, Baton shows for Claude and for Codex: how many turns the conversation has, how many this side's agent has, how many its chat shows, and how many are waiting.
- Given a conversation of 16 turns where Claude's agent has all 16 and its chat shows 14, then Claude's summary says so in a full sentence.

**R2. The message each side has reached.** For each side Baton shows the last turn its agent has: the message text, which app it was written in, and the time.
- Given Codex is waiting for two turns, then Codex's "synced up to" is the turn before them.

**R3. "If you send here now."** Each side's status says what will happen on the next message there: nothing extra, or "2 turns from Codex are attached first", with an estimate of their size in tokens.

**R4. Why something is waiting.** For every side with waiting turns Baton states the reason: the chat is open on that side; a decision is needed (both sides have new turns); that side's hooks are not installed or not trusted; the link is paused; that side is missing.

**R5. How to see them as normal messages.** Whenever turns are waiting because a chat is open, Baton names the step that makes them arrive as normal messages instead of attached, per app:
- Claude: relaunch Claude before sending a message in that chat. A Claude chat stays open until the app quits.
- Claude, without a relaunch: "Add them now". While the chat is not replying, Baton closes that one chat's background process and adds the turns; Claude loads the chat again on the next message. The agent then has them as real turns, and the chat shows them the next time Claude starts. Until then their state reads "added, shown after a relaunch", which is different from attached: attached turns are never shown. A setting decides when this happens: only when the user presses "Add them now" (default), or automatically whenever the chat is not replying. Baton never does it to a chat that is replying. The automatic choice applies to links made by copying the full history; a link made with the history attached keeps attaching, since its chat does not show earlier turns either way.
- Codex: relaunch Codex. Leaving the chat is not enough: chats left idle for hours were still held. If Codex does let go by itself, Baton adds the turns straight away and they show when the chat is opened, with no relaunch.
- Cursor: Baton closes Cursor, adds the turns and opens it again; it never writes while Cursor runs.
- OpenCode: nothing to do. Baton adds real turns at any time; if the chat is on screen, open it again to see them.
- Baton also says that this is optional: without it, the turns are attached and the agent still has them.

**R6. The relaunch offer.** For a link made by copying the full history, Baton offers the relaunch every time turns are waiting for an open chat: in the chat's status, in its menu-bar line, and with the button that does it ([link-actions.md](link-actions.md), A6). The offer names the app and the number of turns, and clears when the turns are shown or attached.
- A link made with the history attached does not get the offer by default, since that way of linking was chosen to avoid relaunches. Its status still shows what is waiting. The user can turn the offer on or off per link.
- Given a full-copy twin was just created for Claude, then the chat is marked "Relaunch Claude to see this chat" until Claude has been relaunched.

**R7. Chats linked with the history attached.** Their status makes the hidden part explicit.
- Before the first message in the new chat: the history is listed as waiting, with "will be attached to your first message".
- After it: the history is listed as attached, and the side's summary says the agent has it and the chat does not show it.

Each side's status also shows how full its agent's context is and what the other agent did since the user was last there. Those are specified in [working-across.md](working-across.md), W5 to W8.

**R8. Setup state per side.** Each side's status shows whether Baton's hooks are installed and trusted there. Without them that side cannot receive attached turns or report a finished reply, and the status says which step fixes it.

### The conversation

**R9. Messages, not boxes.** Baton shows the conversation as messages: for each turn, what the user wrote and what the agent answered, in order, with the app it was written in and the time.
- A long message is shortened to a few lines and can be opened in full.
- What the agent did in between is summed up in one line ("ran 3 commands, changed 2 files"), and can be opened.
- Each turn carries its state on Claude and on Codex, in words.
- Text that the apps or Baton added around a message (reminders, hook text) is not shown.

**R10. Where each side stands, inside the conversation.** The conversation marks the point each side has reached: a line reading "Claude's agent has everything above this line", and the same for Codex when it differs. Turns below a side's line are waiting for it.

**R11. Turn-by-turn strip.** Above the conversation, one strip per side with a block per turn, coloured by state, so the two sides can be compared at a glance. Choosing a block jumps to that turn.

**R12. Filter.** All, waiting, attached.

**R13. Long conversations.** Runs of turns that are in the chat on both sides are folded ("11 earlier turns, in both chats") and open on request. The view starts at the first turn that differs between the sides, or at the end when nothing differs.

### Which chats, and their names

**R14. Both names.** A link shows the name its chat has in Claude and the name its chat has in Codex, each next to its app, plus the folder they work in.
- The names are read from the apps each time Baton refreshes. When a chat is renamed in either app, Baton shows the new name within a few seconds.
- When the two names differ, both are shown everywhere the link appears, never just one.
- In lists, the link is called by the name of the side that was linked from, with the other name underneath when it differs.

**R15. Menu-bar line.** Each linked chat has one line that says the most important thing: in sync; one side ahead and by how many; turns waiting and where; relaunch needed and which app; a decision needed; paused.

### Truthfulness

**R16. Only confirmed states.** Baton marks a turn shown or attached only after checking it.
- Shown: the turn is in the chat's file *and* part of the conversation the agent has. A turn that was written but then bypassed by a later message counts as not delivered, goes back to waiting, and is delivered again.
- Attached: the hook reported that it handed the turn over for that message.
- When Baton cannot confirm, the state reads "not confirmed", never "shown".

**R17. Freshness.** The status reflects a change within a few seconds: after a reply finishes, after a message is sent, after Baton writes, after a chat is renamed, and after an app starts or quits. It also says when it last checked.

**R18. Wording.** Every line follows the message rules in the design (section 7a): what happened, why, what to do, and whether anything was changed.

### Later

**R19. Notifications.** A system notification when turns have been waiting for long. Off by default; the status and the menu-bar badge are the main signal.

**R20. Search.** Find a word across the conversation of a linked chat.

## Acceptance scenarios

Each is a test: set up the two chats and Baton's record, then check the status Baton reports.

| # | Given | When | Then |
|---|---|---|---|
| S1 | Full copy; the Claude chat is open; two new turns are written in Codex | nothing else happens | Claude: 2 waiting, reason "chat is open", relaunch offered and named. Codex: in order. |
| S2 | S1 | the user sends a message in the Claude chat | The 2 turns are attached on Claude. Claude's agent has all, its chat shows 2 fewer. The relaunch offer clears. |
| S3 | S1 | the user relaunches Claude first | The 2 turns are shown on Claude. Its agent has all and its chat shows all. |
| S4 | Full copy; Codex has let go of the chat; a new turn is written in Claude | Baton syncs | The turn is shown on Codex, no relaunch needed. |
| S4b | Full copy; Codex still holds the chat although the user left it; a new turn is written in Claude | Baton syncs | Codex: 1 waiting, reason "Codex still has this chat open", relaunch offered. |
| S5 | Linked with history attached, 12 earlier turns; no message sent yet in the new chat | — | New side: 12 waiting, "will be attached to your first message". No relaunch offer. |
| S6 | S5 | the user sends the first message | New side: agent has 12, chat shows none of those 12; each listed as attached. |
| S7 | Both sides have turns the other never received | — | Both sides list waiting turns, reason "a decision is needed"; the menu-bar line says so. |
| S8 | Codex has not trusted Baton's hooks; a turn is waiting for an open Codex chat | — | Codex: waiting, reason names the hooks and the step to trust them. |
| S9 | A turn was added to a Claude chat and then bypassed by a later message | Baton reads the chat again | The turn is back to waiting on Claude and is delivered again; it is never listed as shown. |
| S10 | A full-copy twin was created for Claude; Claude has not been relaunched | — | The chat is marked "Relaunch Claude to see this chat". |
| S11 | A linked chat is renamed in Codex | Baton refreshes | The link shows the new Codex name next to the unchanged Claude name. |
| S12 | A turn with a long reply and several tool calls | the conversation is shown | The reply is shortened with a way to open it, and the tool calls are one summary line. |

## What the engine has to record

For every linked chat, for every turn, for each side: its state, when it got there, and how (created here, added to the file, attached to which message). The two things per side and every line above are computed from that record plus a fresh read of both chats, including each chat's current name. This is the ledger the engine builds next.

## How we will know it works

- All scenarios pass as automated tests, built from made-up chats.
- Walk-through on the real apps: for each of the questions in the problem statement, the answer can be read from Baton without opening Claude or Codex.
- No case found, in tests or in use, where Baton says a side has a turn that its agent does not have.

## Open questions

| Question | Who | Blocking? |
|---|---|---|
| What makes Codex let go of a chat without a relaunch? It happened to two chats once; chats idle for up to 581 minutes were otherwise still held. Baton does not depend on the answer, since it checks whether a chat is held before every write. | Engineering | No |
