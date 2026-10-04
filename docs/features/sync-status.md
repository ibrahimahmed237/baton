# Feature: sync status

Part of [the Baton design](../DESIGN.md). Status: requirements, not built.

## Problem

A linked chat can look different from what its agent knows. Baton delivers a turn in one of two ways: as a normal message when the receiving chat is closed, or attached to the user's next message when it is open. A chat linked with "history attached" never shows its earlier history at all. And some turns may not have arrived yet.

So, looking at Claude or Codex alone, the user cannot tell whether that side is up to date, which message it has reached, whether the agent knows more than the chat shows, or what to do to see the rest. Without an answer the user either stops trusting the sync or sends a message into a chat that is behind.

## Goals

1. For any linked chat, the user can tell from Baton alone, without opening either app, **which message each side has reached**.
2. The user can tell apart what each side **shows** as messages and what its agent **knows** without showing.
3. When something has not arrived, the user is told **why** and **what to do**, including which app to relaunch.
4. Baton never reports a side as up to date when it is not.

## Non-goals

- **Turning attached turns into normal messages.** That would mean inserting into the middle of a chat, which Baton does not do. The way to a chat that shows everything is a new full copy (R12).
- **Relaunching an app without the user asking.** A relaunch stops a reply in progress; the user decides.
- **A full transcript reader.** The status view shows each turn's first line, time and state, not whole conversations.
- **Live mirroring of an open chat's screen.** Neither app reloads an open chat; the status view is where the truth is shown.

## Words used

A **turn** is one of the user's messages and the reply to it. For each turn, each side is in exactly one state:

| State | Meaning |
|---|---|
| **Written here** | The turn was created in this app. |
| **Shown** | Baton added it to this app's chat. It appears there as a normal message. |
| **Attached** | Baton gave it to this app's agent together with one of the user's messages. The agent knows it. It is not shown as a message, and never will be in this chat. |
| **Waiting** | It has not reached this side yet. |
| **Skipped** | The user chose to keep the other side's version in a conflict. It stays only where it was written. |

Per side, two positions follow from these:

- **Knows up to**: the last turn the agent has, by any of the first three states.
- **Shows up to**: the last turn visible in the chat, written here or shown.

"In sync" means both sides know every turn. A side can be in sync and still show less than it knows.

## User stories

1. As someone about to switch tools, I want to see whether the other chat already has my latest turns, so that I know what will happen when I type there.
2. As someone looking at a chat that seems to be missing messages, I want to know whether the agent has them anyway, so that I don't repeat myself.
3. As someone who wants the missing messages on screen, I want to be told exactly what to do and in which app, so that I don't guess.
4. As someone who linked a chat with the history attached, I want to see what the agent on that side knows, since the chat itself doesn't show it.
5. As someone glancing at the menu bar, I want one line per chat that tells me if anything needs me.
6. As someone who distrusts a sync tool, I want every "in sync" to be true.

## Requirements

### Must have (P0)

**R1. Position of each side.** For each linked chat, Baton shows for Claude and for Codex: how many turns the conversation has, how many this side's agent knows, how many its chat shows, and how many are waiting.
- Given a conversation of 16 turns where Claude knows all 16 and shows 14, then Claude's line reads as "knows 16 of 16, shows 14", in words the user would use.

**R2. The message each side has reached.** For each side Baton shows the last turn it knows and the last turn it shows: first line, which app it was written in, and time.
- Given Codex is waiting for two turns, then Codex's "knows up to" is the turn before them, with its first line and time.

**R3. Turn list.** A list of every turn in order, each with its first line, where and when it was written, and its state on Claude and on Codex.
- Long runs of turns that are the same on both sides are folded into one row ("11 earlier turns, on both sides").
- A turn's state on a side is always one of the five above.

**R4. Why something is waiting, and what happens next.** For every side with waiting turns Baton states the reason and the consequence.
- Reasons: the chat is open on that side; a decision is needed (both sides have new turns); that side's hooks are not installed or not trusted; that side is missing.
- Given the chat is open, then Baton says the turns will be attached to the next message sent there.

**R5. How to see them as normal messages.** Whenever turns are waiting because a chat is open, Baton names the step that makes them arrive as normal messages instead of attached, per app:
- Claude: relaunch Claude before sending a message in that chat.
- Codex: leave that chat (open another one) before sending a message in it.
- Baton also says that this is optional: without it, the turns are attached and the agent still knows them.

**R6. Which app needs a relaunch.** If a relaunch would change what a chat shows, Baton names the app, in the chat's status and in its menu-bar line.
- Given a full-copy twin was just created for Claude, then the chat is marked "Relaunch Claude to see this chat" until Claude has been relaunched.
- Given waiting turns for an open Claude chat, then the chat is marked "Relaunch Claude to show 2 turns" and the mark clears when they are shown or attached.

**R7. Chats linked with the history attached.** Their status makes the hidden part explicit.
- Before the first message in the new chat: the history is listed as waiting, with "will be attached to your first message".
- After it: the history is listed as attached, and the side's line says the agent knows it and the chat does not show it.

**R8. Menu-bar line.** Each linked chat has one line that says the most important thing: in sync; one side ahead and by how many; turns waiting and where; relaunch needed and which app; a decision needed.

**R9. Only confirmed states.** Baton marks a turn shown or attached only after checking it.
- Shown: the turn is in the chat's file *and* part of the conversation the agent has. A turn that was written but then bypassed by a later message counts as not delivered, goes back to waiting, and is delivered again.
- Attached: the hook reported that it handed the turn over for that message.
- When Baton cannot confirm, the state reads "not confirmed", never "shown".

**R10. Freshness.** The status reflects a change within a few seconds: after a reply finishes, after a message is sent, after Baton writes, and after an app starts or quits.

**R11. Wording.** Every line follows the message rules in the design (section 7a): what happened, why, what to do, and whether anything was changed.

### Should have (P1)

**R12. Full copy on demand.** From a chat whose side shows less than it knows, the user can create a new twin that shows everything ("Create a full copy"). The link moves to the new chat; the old one is left as it is. Same rule as a brief or a merge: a changed view starts a new chat.

**R13. Relaunch from Baton.** A "Relaunch Claude" button that does it in the safe order: quit Claude, add the waiting turns to the now-closed chats, reopen Claude. If Claude is in the middle of a reply, Baton warns first and names the chat.

**R14. Open the chat.** From a side's line, a button opens that app at that chat.

### Later (P2)

**R15. History of deliveries.** Per turn: when it was delivered, how, and to which message it was attached.

**R16. Notifications.** A system notification when turns have been waiting for long. Off by default; the status and the menu-bar badge are the main signal.

## Acceptance scenarios

Each is a test: set up the two chats and Baton's record, then check the status Baton reports.

| # | Given | When | Then |
|---|---|---|---|
| S1 | Full copy; the Claude chat is open; two new turns are written in Codex | nothing else happens | Claude: 2 waiting, reason "chat is open", marked "Relaunch Claude to show 2 turns". Codex: in order. |
| S2 | S1 | the user sends a message in the Claude chat | The 2 turns are attached on Claude. Claude knows all, shows 2 fewer. The relaunch mark clears. |
| S3 | S1 | the user relaunches Claude first | The 2 turns are shown on Claude. Claude knows all and shows all. |
| S4 | Full copy; the Codex chat is not on screen; a new turn is written in Claude | Baton syncs | The turn is shown on Codex, no relaunch needed. |
| S5 | Linked with history attached, 12 earlier turns; no message sent yet in the new chat | — | New side: 12 waiting, "will be attached to your first message". |
| S6 | S5 | the user sends the first message | New side: knows 12, shows 0 of those 12; each listed as attached. |
| S7 | Both sides have turns the other never received | — | Both sides list waiting turns, reason "a decision is needed"; menu-bar line says so. |
| S8 | Codex has not trusted Baton's hooks; a turn is waiting for an open Codex chat | — | Codex: waiting, reason names the hooks and the step to trust them. |
| S9 | A turn was added to a Claude chat and then bypassed by a later message | Baton reads the chat again | The turn is back to waiting on Claude and is delivered again; it is never listed as shown. |
| S10 | A full-copy twin was created for Claude; Claude has not been relaunched | — | The chat is marked "Relaunch Claude to see this chat". |

## What the engine has to record

For every linked chat, for every turn, for each side: its state, when it got there, and how (created here, added to the file, attached to which message). The two positions per side and every line above are computed from that record plus a fresh read of both chats. This is the ledger the engine builds next.

## How we will know it works

- All ten scenarios pass as automated tests, built from made-up chats.
- Walk-through on the real apps: for each of the four questions in the problem statement, the answer can be read from Baton without opening Claude or Codex.
- No case found, in tests or in use, where Baton says a side has a turn that its agent does not have.

## Open questions

| Question | Who | Blocking? |
|---|---|---|
| Should Baton relaunch Claude itself when asked (R13), or only tell the user to? | You | No, R13 is P1 |
| How quickly does Codex let go of a chat after the user leaves it? The wording of R5 for Codex depends on it. | Engineering, by measuring | No |
| Are "knows" and "shows" the right two words for the user, or should the app say it differently? | You | No, wording only |
