# Feature: more tools, any two linked

Status: agreed 2026-10-04. All four tools are in the first version: Claude Code, Codex, OpenCode and Cursor. Claude with Codex is built first and the other two follow inside the same milestones ([PLAN.md](../PLAN.md)).

## Problem

The same conversation is worth continuing in more than two coding agents. Baton was specified for Claude Code and Codex by name. Adding OpenCode and Cursor must not mean a second and third copy of every rule, and must not turn a link into something harder to understand.

## Decisions

- **A link still joins exactly two chats, from two different tools.** Any two: Claude with Codex, Claude with OpenCode, Codex with Cursor, and so on. One conversation across three or four tools at once is not offered; merge and undo stay as designed.
- **A chat is in one link at a time**, whatever the tool (link-actions.md, A0).
- **A chat can be copied from any tool to any tool** without linking, and the dialog says whether the target tool has to be relaunched to show it.
- **Cursor: the chats to sync are the ones the user sees in the Cursor app.** Chats made with the `cursor-agent` command were checked and are not those chats; see "Which Cursor".
- **Adding real turns to an idle Claude chat is a setting with both choices**: only when the user presses "Add them now" (default), or automatically whenever the chat is not replying.

## Requirements

**G1. Tools are equal.** Every feature of the first version (both ways of linking, delivery, sync status, merge, undo, briefs, second opinion, limits, context) is defined for a pair of tools, not for Claude and Codex by name. Every message names the two tools of the link it is about.

**G2. Pick the other tool.** Linking or copying starts from a chat and asks which tool the other chat is in. A tool that is installed but not set up is listed with what is missing and its fix; it is not hidden.

**G3. What each tool can do is stated, not assumed.** For every tool Baton holds the answers to the same questions, and Setup shows them:

| Question | Used for |
|---|---|
| Does a closed chat take new turns as normal messages? | Delivery |
| Does a chat created from outside appear at once, or after a relaunch? | Linking by full copy, copying a chat |
| Does a turn added to a chat appear at once, or after a relaunch? | The relaunch offer |
| Can turns be attached to the user's next message in an open chat? | Catch-up at send |
| Can Baton tell when a reply finishes, and in which chat? | Automatic sync |
| Can Baton tell that a chat is open, and that it is replying? | Never writing into an open chat |
| Can a chat be made shorter? | Undo |
| Can the tool run in the background, limited to reading? | Briefs, second opinion |
| Does it record usage limits and context in use? | Limit offer, how full a side is |
| Can it be opened at a given chat? | The Continue and Open buttons |

Every dialog takes its relaunch note and its warnings from these answers for the tool it writes to. Nothing is worded for one tool and reused for another.

**G4. A tool that cannot do something degrades in the open.** Examples: no way to attach turns means turns for an open chat wait until it is closed, and the status says so; no background run means the other tool writes the brief, or the offline brief is used. The user is told which and why. Nothing is skipped silently.

**G4a. Anything unusual is said before it happens, and confirmed.** Whenever a link, a copy or a sync will not behave the usual way for the tool involved, Baton says so in the dialog, before the user confirms, and the confirm button is only enabled once the note has been shown. This covers at least: a way of linking that the tool does not support (shown greyed out with the reason, not hidden); history that the agent will know but the chat will not show, or that the chat will show but the agent will only get with the first message; a chat that will appear only after a relaunch, naming the app; a tool whose background run is missing, so another tool writes the brief. The same note stays on the link's status afterwards, so it is not a one-time message.

**G4b. A chat that does not exist yet is created by the sync.** When the other tool has no chat for this link, Baton creates it, and says for that tool whether it appears at once or after a relaunch: Claude after a relaunch, Codex at once, OpenCode at once, Cursor after a relaunch.

**G5. Copy from any tool to any tool.** "Copy to…" on a chat lists the other tools. The dialog states, for the chosen tool, whether the new chat appears at once or after a relaunch of that tool, and whether the two chats will be kept in sync (they will not, unless the user chooses "Copy and link").

**G6. One link per chat, across tools.** Linking a chat that is already linked, to a chat in any tool, names the current partner and its tool and offers "Change the link".

**G7. Setup per tool.** Setup shows one card per tool with the same lines: hooks, background runs, how chats are saved and the version Baton knows. A tool that is not installed is shown as "Not installed" and left alone.

**G8. One tool's change pauses only its links.** When a tool changes how it saves chats, links that include that tool go read-only; the others keep working.

**G9. The pair is always visible.** The menu-bar line, the sync status and the history show both tools' names for a link.

**G10. A new tool does not change Baton's record.** Sides are named by tool in the record (done in `baton/ledger.py`), so adding a tool adds a reader, a writer and its hooks, and nothing else.

## Notes the user always sees

Requirement G4a in words. Every dialog that links, copies or syncs has a "What will happen" block, built from what is known for the tool being written to. It is never left out, also when everything is ordinary; then it says so. The same lines stay on the link's status until they no longer apply.

| Situation | Note shown before confirming | Stays on the status as |
|---|---|---|
| New chat in Codex or OpenCode | The new chat appears in *tool* right away. No relaunch. | nothing |
| New chat in Claude | Baton closes Claude, creates the chat, and opens Claude again at it. Claude lists a new chat only when it starts; you do this once for this chat. Buttons: *Close Claude, sync, reopen*, *Sync now, I relaunch later*, *Cancel* | Relaunch Claude to see this chat |
| New chat or new turns in Cursor | Baton closes Cursor, writes, and opens Cursor again on this folder; your windows come back. Baton never writes while Cursor runs, because Cursor would write over it. Buttons: *Close Cursor, sync, reopen*, *Attach instead*, *Cancel* | *n* turns waiting until Cursor is closed |
| Closing an app while a chat is replying | *Tool* is replying in "*title*". Closing now stops that reply. Buttons: *Wait until it has finished*, *Close anyway*, *Cancel* | Will sync when *tool* is idle |
| Tool saved chats in a version Baton has not checked | *Tool* was updated and saves chats differently (version *n*). Baton still reads its chats and attaches turns, but will not create or add messages there until Baton is updated. | *Tool*: reading only |
| Start now, history attached | The agent gets the history with your first message. The chat will never show it as separate messages. | Agent has *n* turns the chat does not show |
| Turns for a chat that is open (Claude, Codex, Cursor) | These *n* turns will be attached to your next message there. To get them as normal messages, relaunch *tool*. | *n* turns waiting, attached on next message |
| Turns for an OpenCode chat, open or not | Baton adds these *n* turns now. If the chat is on screen, open it again to see them. | Open the chat again to see *n* new turns |
| Tool cannot run in the background | *Tool* can't write the brief here (*reason*). *Other tool* writes it instead. | none |
| A way of linking is not available | Shown greyed out with the reason and what would make it available. | none |
| Tool's command or hooks are missing | *What is missing*, what it stops Baton from doing, and the fix. Buttons: the fix, *Check again* | Setup: 1 step left |
| A tool's first use of Baton's hooks | Codex: type /hooks and trust Baton's two entries. OpenCode: restart OpenCode once so Baton's plugin loads. Claude and Cursor: nothing to do. | Setup: 1 step left |
| Undo on Codex | Codex can't make a chat shorter, so Baton creates a shorter chat and links it. Your current chat stays as it is. | Earlier chat kept |

Rules for these notes: one sentence on what happens, one on what the user has to do, the app named every time, and a count where there is one. The confirm button names the action. Nothing unusual is ever learned afterwards.

## When a tool changes its format

A future update cannot be tested ahead of time. What the existing chats show for Cursor: its chat record carries a version number, and across this Mac's 426 chats it went from 1 to 18 in eighteen months, about one change a month. The parts Baton relies on were stable through most of that: the ordered message list and the one-record-per-message layout since version 3, the agent's state since version 11. Cursor also re-saves old chats in the newest version.

So the rule (G8) for every tool that has a version in its format:
- Baton knows which versions it was checked against (Cursor: 18).
- Before every write it reads the version. A version it does not know means no creating and no adding in that tool. Reading (Cursor's transcript files do not depend on the record version) and attaching at send keep working.
- The user is told which tool changed, what still works, and that a Baton update is needed. Nothing is written on a guess.

## Two ways a turn reaches a chat, and what the user sees

Asked and settled 2026-10-04. This holds for every tool.

| | Attached to the next message (hook or plugin) | Added to the chat as a real turn |
|---|---|---|
| Works while the chat is open | always | only in OpenCode; Claude after releasing an idle chat; never in a held Codex chat or a running Cursor |
| The agent has the turn | yes, with that message | yes |
| The chat shows the turn as a message | never, also not after reopening or a relaunch | yes: OpenCode on reopening the chat, Codex at once if it was not holding the chat, Claude and Cursor after a relaunch |

So attaching is always available and never loses anything, but what was attached stays invisible in that chat for good. To see the turns as messages they have to be added as real turns, which for an open chat means closing or relaunching first (except OpenCode). The notes say which of the two will happen and offer the other.

## Best delivery per tool

The aim, in this order: the turn is shown and known now; if that cannot be, known now and shown after the smallest step; never unknown. Baton picks the first line that applies and the note says what the user has to do to get the better one.

| Tool, and state of the chat | What Baton does | Agent has it | Chat shows it | Offer in the note |
|---|---|---|---|---|
| OpenCode, any state | adds real turns | next message | when the chat is opened again | none needed |
| Codex, not holding the chat | adds real turns | yes | at once | none needed |
| Codex, holding the chat | attaches to the next message | with that message | no | *Close Codex, sync, reopen* to get them as messages |
| Claude, app closed | adds real turns | yes | yes | none needed |
| Claude, chat open and idle | releases that chat, adds real turns (by button, or automatically if set) | next message | after a relaunch | *Relaunch Claude* to see them |
| Claude, chat replying | attaches to the next message; adds real turns once the reply ends if set to automatic | with that message | no, unless added later | *Sync when the reply has finished* |
| Cursor, closed | adds real turns | yes | yes | none needed |
| Cursor, running | attaches to the next message | with that message | no | *Close Cursor, sync, reopen* to get them as messages |

Attached text is never shown, also not after a relaunch: it is not a message in the chat. To make attached turns visible later they have to be added as real turns as well, at the right position and without the agent getting them twice. Whether that can be done is open per tool:

| Tool | "Attach now, show later" in the same chat | State |
|---|---|---|
| OpenCode | not needed; real turns can always be added | settled |
| Cursor | yes: a turn placed before the message it was attached to, while Cursor was closed, was shown at that position. Cursor did not add it to the agent a second time, which is what is wanted, since the agent already has it from the attachment | settled |
| Codex | one run worked: a turn written into a held chat was shown and known after a relaunch, in the right place, but the file's numbering was doubled | to test further before relying on it |
| Claude | releasing the idle chat already gives this. For a turn attached to a message, adding it later would land after that message | use "Create a full copy" |

Where it cannot be done in the same chat, "Create a full copy" (link-actions.md, A4) gives a chat that shows everything in order.

## What is known per tool

"Yes" and "no" are measured (SPIKE-M0.md and the sections below). Anything else says what Baton does in the meantime.

| | Claude | Codex | OpenCode | Cursor |
|---|---|---|---|---|
| Closed chat takes new turns | yes | yes, also while Codex runs, as long as Codex is not holding that chat | yes, also while the app is running | yes, while Cursor is closed |
| Chat created from outside appears | after a relaunch | at once | at once, with the app running | after a relaunch (written while Cursor is closed); shown and known to the agent |
| Added turn appears | after a relaunch; the agent has it at once | at once if Codex let go of the chat, else after a relaunch | when the chat is opened again; no relaunch | after a relaunch (written while closed) |
| Attach turns to the next message | yes | yes | yes, through a plugin | yes |
| Tells when a reply finishes | yes | yes | yes, through a plugin | yes |
| Open and replying can be told | yes | yes | yes, through the plugin | running or not: yes; replying: through hooks |
| Chat can be made shorter | yes | no; a shorter chat is created | yes | yes, while closed |
| Background run, read-only | yes | yes | command damaged on this Mac | only through `cursor-agent`, signed out here |
| Records limits and context | yes; context size not recorded | yes | token counts yes; a failed reply carries the provider's error and status code, no reset time | context with size and percentage; a turn that ended on a limit says so in the transcript's end-of-turn line, no reset time |
| Opens at a given chat | yes | yes | no; Baton opens the folder and names the chat to pick | no; Baton opens the folder and names the chat to pick |

## Which Cursor: the app, not `cursor-agent` (checked 2026-10-04)

They are two separate stores, and the app's is the one in use.

| | Cursor app | `cursor-agent` command |
|---|---|---|
| Where chats are kept | `state.vscdb`, one database for everything | `~/.cursor/chats/<folder>/<chat>/store.db`, one per chat |
| Chats on this Mac | 426, from April 2025 to 30 September 2026 | 2, from August and September 2025 |
| Signed in | yes | no; it asks to sign in |
| Version | 3.21.18 | a build from August 2025 |

- The two `cursor-agent` chats are not in the app's database, by ID or by name. This was checked again with the app freshly started: still not listed.
- A new `cursor-agent` chat could not be made for a live check, because the command is signed out and Baton does not sign in for the user.
- **Decision to take: Baton links the Cursor app's chats.** `cursor-agent` is not a second place the same conversations appear; it is a different product surface with its own chats. It could later serve as Cursor's background runner (briefs, second opinion) if the user signs it in and updates it; it is not needed for syncing.

What the app offers for reading and for hooks:

- Besides the database, the app writes each newer chat as a plain transcript: `~/.cursor/projects/<folder>/agent-transcripts/<chat>/<chat>.jsonl`, one line per message with its role and content (text and tool calls). 107 of the 426 chats have one. This is the safe way to read a Cursor chat. It is the app's own export, so writing to it would not change the chat.
- The app knows hook events for a submitted prompt, a finished reply, the end of a turn, session start and end, and compaction, and its code names fields for extra context and for a follow-up message. Both were then confirmed live (below).
- The database is large and its format is not documented, but writing a chat's display records while Cursor is closed works (tested below).

A throwaway chat made in the app, in the Baton folder, shows how a chat is saved:

- The list of chats has one row per chat with its name, folder, times and how full its context is.
- The chat itself is one record that lists its messages in order, and one record per message with its text, time and token count. The record also holds an encoded agent state with an encryption key; Baton never writes that part, only the display records, and Cursor rebuilds the state from them.
- The transcript file appeared at once, in the folder named after the project: the prompt wrapped in a time stamp and a query marker, the reply, and a line marking the end of the turn. That end-of-turn line is a second way to notice a finished reply.
- The chat record carries the context in use, the limit and the percentage, so "how full is this side" needs no arithmetic for Cursor.

A test hook was registered for the Baton folder and run on two chats (`spike/m0b_cursor_hook.py`; removed again afterwards):

- **Text can be attached to a prompt.** With a prompt hook returning extra context, the agent repeated the codeword in four seconds without using any tool. The attached text is not written to the transcript, so it is never read back as part of a prompt.
- **Text offered at chat start did not reach the agent.** The hook ran, but the agent said it had been given nothing. This costs nothing: the prompt hook also runs on a chat's first message, so the history can be attached there.
- **Cursor says when a reply finishes, and in which chat.** The hooks after a reply and at the end of a turn pass the chat's ID, the path of its transcript, the model, a status and the token counts of the turn.
- Hooks were picked up while Cursor was running, with no restart and no approval step.

**A chat created from outside is accepted, shown, and known to the agent.** `spike/m0b_cursor_create.py` wrote only the display records of a new chat (one question and answer) while Cursor was closed, with the agent's state left empty. After Cursor was opened, the chat was listed and showed both messages, and asked for the codeword the agent gave it without using any tool. Cursor builds the agent's state from the displayed messages when there is none. The first assumption, that copied history could not be shown in Cursor, was wrong.

What this means for a link with Cursor: every way of linking works. "Copy the full history" creates the chat while Cursor is closed, so it needs one relaunch of Cursor, as Claude does. Reading, catch-up at send and automatic sync work as tested.

**Adding a turn to an existing Cursor chat works too.** A turn was added to the display records of a chat whose agent already had a state, with Cursor closed. After opening Cursor the turn was shown, and the agent listed both codewords, the old one and the added one, without using a tool. Cursor brings the agent's state up to date from the displayed messages.

## OpenCode on this Mac (checked 2026-10-04)

- The `opencode` command is damaged: macOS stops it at launch because its signature is no longer valid. Reinstalling it fixes that; Baton's setup check has to detect it and say so.
- The OpenCode app runs a local server, but it asks for a password that the app makes up at each start. Baton does not go around that.
- So the only way in from outside is the database. A throwaway chat was created there by `spike/m0b_opencode.py` with the app running: one project row, one chat, one finished question and answer, in the shapes OpenCode itself writes. The database stayed healthy and the script's `remove` takes exactly those rows out again.
- **It worked.** The user opened the folder in OpenCode: the chat was listed, its turn was shown as normal messages, and asked for the codeword the agent answered with it. OpenCode then added the new question and answer after Baton's rows and left those rows as they were. The app was running when the chat was created, so a chat made from outside needs no relaunch here.
- **Attaching at send and the finished-reply signal both work**, through a plugin in the folder's `.opencode/plugins` (loaded when OpenCode starts). The plugin added a text part to the user's message; the agent answered from it; OpenCode stores that part marked as inserted, so a reader leaves it out. OpenCode reports a chat going busy and idle with the chat's ID.
- This is different from the other tools in a useful way: the database takes writes from outside while the app is running without breaking, where a chat file does not. A turn added to a chat while OpenCode was running was known to the agent on the next message, and was shown once the user left the chat and opened it again; no restart. So for OpenCode an open chat is not a problem: Baton adds real turns at any time, and the only note is "open the chat again to see them".
- Useful details in the format: a user message records which files its turn changed; a reply records its token counts including the total; text the app inserted itself is marked as such, so it can be left out of prompts; chats that are sub-agent runs have a parent.
- OpenCode has been used little here: 34 chats, the newest from May 2026.

## Spike M0b: where each question stands

| # | Question | OpenCode | Cursor |
|---|---|---|---|
| 1 | Turn added to an existing chat: shown and known? | yes, while running; shown on reopening the chat | yes, written while closed |
| 2 | Chat created from outside appears | at once | after a relaunch |
| 3 | What marks a chat as open or replying | busy and idle events through the plugin; from outside the app: to build | hooks say when a turn starts and ends; whether Cursor is running is a process check |
| 4 | Attach text to the next message | yes, stored marked as inserted | yes, not stored in the transcript |
| 5 | Signal when a reply finishes, with chat ID | yes | yes |
| 6 | Background run, read-only | not available: the command is damaged here | not available: `cursor-agent` is signed out |
| 7 | Open the app at a given chat | no link to a chat exists. `opencode://open-project?directory=…` opens the folder; `opencode://new-session?directory=…&prompt=…` starts a new chat there | no link to a chat exists. The `cursor` command opens the folder |
| 8 | Name: where, and changed from outside | in the chat's row; change not tested | in the chat list row; change not tested |
| 9 | Chat made shorter | yes, while running: gone on reopening the chat, and the agent no longer has it | yes, written while closed: the removed turns are gone from the chat. That the agent forgot them is likely but was not proven, since the removed turns held nothing only the agent knew |
| 10 | `cursor-agent` same as the app? | n/a | no, separate; the app is the one to link |

What is left does not block starting: background runs need the user's repair or sign-in (6), and renaming from outside was not tried (8), so names are only read. Undo cuts the chat on OpenCode and Cursor, as on Claude.

One more thing these tests showed: an OpenCode chat that is on screen keeps showing its old content, after an add and after a cut, until the chat is opened again. The note for OpenCode says so in both cases.

## Acceptance scenarios

| # | Given | When | Then |
|---|---|---|---|
| X1 | A Claude chat linked to a Codex chat | the user links it to an OpenCode chat | No second link is made; Baton names the Codex chat and offers "Change the link". |
| X2 | A Codex chat, not linked | "Copy to…" then OpenCode | A new OpenCode chat holds every turn; no link exists; the dialog said whether OpenCode needs a relaunch, from what is known for OpenCode. |
| X3 | A tool that cannot attach turns; its chat is open; a turn is written on the other side | — | The turn waits; the reason names that tool and says the turn arrives when the chat is closed. |
| X4 | OpenCode changes how it saves chats | Baton starts | Links that include OpenCode are read-only and say why; a Claude with Codex link still syncs. |
| X5 | Cursor is not installed | the user opens Setup | Cursor is shown as "Not installed"; linking does not offer it. |
| X6 | Setting "Add turns to an idle Claude chat" is "Automatically" | a turn is written in Codex while the linked Claude chat is open and not replying | The turn is added to the Claude chat as a real turn; its state reads "added, shown after a relaunch". |
| X7 | X6 with the setting on "When I press the button" | — | The turn waits and will be attached to the next message; "Add them now" is offered. |
