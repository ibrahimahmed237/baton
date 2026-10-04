# Feature: more tools, any two linked

Status: agreed 2026-10-04. Claude Code with Codex is the first pair and the first version. OpenCode and Cursor are looked at now and built after the first pair works (milestones M5 and M6 in [DESIGN.md](../DESIGN.md)).

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

## What is known per tool

"Yes" and "no" are measured (SPIKE-M0.md). "To verify" has not been run.

| | Claude | Codex | OpenCode | Cursor |
|---|---|---|---|---|
| Closed chat takes new turns | yes | yes | to verify | to verify; creating a chat works |
| Chat created from outside appears | after a relaunch | at once | at once, with the app running | after a relaunch (written while Cursor is closed); shown and known to the agent |
| Added turn appears | after a relaunch; the agent has it at once | at once if Codex let go of the chat, else after a relaunch | to verify | to verify |
| Attach turns to the next message | yes | yes | yes, through a plugin | yes |
| Tells when a reply finishes | yes | yes | yes, through a plugin | yes |
| Open and replying can be told | yes | yes | to verify | to verify |
| Chat can be made shorter | yes | no; a shorter chat is created | to verify | to verify |
| Background run, read-only | yes | yes | command damaged on this Mac | only through `cursor-agent`, signed out here |
| Records limits and context | yes; context size not recorded | yes | token counts yes; limits to verify | context yes, with size and percentage; limits to verify |
| Opens at a given chat | yes | yes | to verify | to verify |

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
- The app knows hook events for a submitted prompt, a finished reply, the end of a turn, session start and end, and compaction, and its code names fields for extra context and for a follow-up message. So attaching turns and noticing a finished reply look possible; both need a live run.
- Adding turns to a Cursor chat as normal messages would mean writing into the 3.8 GB database in a format that is not documented. Expect Cursor to work with "Start now, history attached" only, at least at first (G4).

A throwaway chat made in the app, in the Baton folder, shows how a chat is saved:

- The list of chats has one row per chat with its name, folder, times and how full its context is.
- The chat itself is one record that lists its messages in order, and one record per message with its text, time and token count. The record also holds an encryption key for part of its state, which is another reason not to write there.
- The transcript file appeared at once, in the folder named after the project: the prompt wrapped in a time stamp and a query marker, the reply, and a line marking the end of the turn. That end-of-turn line is a second way to notice a finished reply.
- The chat record carries the context in use, the limit and the percentage, so "how full is this side" needs no arithmetic for Cursor.

A test hook was registered for the Baton folder and run on two chats (`spike/m0b_cursor_hook.py`; removed again afterwards):

- **Text can be attached to a prompt.** With a prompt hook returning extra context, the agent repeated the codeword in four seconds without using any tool. The attached text is not written to the transcript, so it is never read back as part of a prompt.
- **Text offered at chat start did not reach the agent.** The hook ran, but the agent said it had been given nothing. This costs nothing: the prompt hook also runs on a chat's first message, so the history can be attached there.
- **Cursor says when a reply finishes, and in which chat.** The hooks after a reply and at the end of a turn pass the chat's ID, the path of its transcript, the model, a status and the token counts of the turn.
- Hooks were picked up while Cursor was running, with no restart and no approval step.

**A chat created from outside is accepted, shown, and known to the agent.** `spike/m0b_cursor_create.py` wrote only the display records of a new chat (one question and answer) while Cursor was closed, with the agent's state left empty. After Cursor was opened, the chat was listed and showed both messages, and asked for the codeword the agent gave it without using any tool. Cursor builds the agent's state from the displayed messages when there is none. The first assumption, that copied history could not be shown in Cursor, was wrong.

What this means for a link with Cursor: every way of linking works. "Copy the full history" creates the chat while Cursor is closed, so it needs one relaunch of Cursor, as Claude does. Reading, catch-up at send and automatic sync work as tested. Still to test: adding turns to an existing Cursor chat that already has an agent state, where the display and the state could disagree.

## OpenCode on this Mac (checked 2026-10-04)

- The `opencode` command is damaged: macOS stops it at launch because its signature is no longer valid. Reinstalling it fixes that; Baton's setup check has to detect it and say so.
- The OpenCode app runs a local server, but it asks for a password that the app makes up at each start. Baton does not go around that.
- So the only way in from outside is the database. A throwaway chat was created there by `spike/m0b_opencode.py` with the app running: one project row, one chat, one finished question and answer, in the shapes OpenCode itself writes. The database stayed healthy and the script's `remove` takes exactly those rows out again.
- **It worked.** The user opened the folder in OpenCode: the chat was listed, its turn was shown as normal messages, and asked for the codeword the agent answered with it. OpenCode then added the new question and answer after Baton's rows and left those rows as they were. The app was running when the chat was created, so a chat made from outside needs no relaunch here.
- **Attaching at send and the finished-reply signal both work**, through a plugin in the folder's `.opencode/plugins` (loaded when OpenCode starts). The plugin added a text part to the user's message; the agent answered from it; OpenCode stores that part marked as inserted, so a reader leaves it out. OpenCode reports a chat going busy and idle with the chat's ID.
- This is different from the other tools in a useful way: the database takes writes from outside while the app is running without breaking, where a chat file does not. Whether a turn added to a chat the app has on screen appears there, and whether the agent has it, is still to test.
- Useful details in the format: a user message records which files its turn changed; a reply records its token counts including the total; text the app inserted itself is marked as such, so it can be left out of prompts; chats that are sub-agent runs have a parent.
- OpenCode has been used little here: 34 chats, the newest from May 2026.

## Known so far (read-only look, 2026-10-04)

Both tools are installed on the target Mac. This first look wrote nothing and started no chat.

**OpenCode**
- Chats are in one database, `~/.local/share/opencode/opencode.db`: `session` (title, folder, parent session, token totals, cost), `message` (one row per message, role `user` or `assistant`) and `part` (the pieces of a message: text, reasoning, tool call with its state, step start and finish with token counts). 34 sessions here.
- A session can have a parent session; those are sub-agent runs and are not chats to link.
- The database also has newer, still empty tables (`session_message`, `session_input`, `event`), so the format is moving. The format check (G8) matters here.
- It has plugins. The installed plugin interface offers a hook when the user sends a message, one that can change the messages sent to the model, and one at compaction. These are the candidates for attaching turns and for noticing a finished reply.
- All chats share one database file that the app keeps open, so "never write into an open chat" needs its own answer here: either through OpenCode's own commands or server, or only while it is not running.

**Cursor**
- The Cursor app keeps its chats in `~/Library/Application Support/Cursor/User/globalStorage/state.vscdb`, a 3.8 GB database with 426 chats listed. The format is not documented.
- The `cursor-agent` command keeps its chats elsewhere: `~/.cursor/chats/<folder>/<chat>/store.db`, one small database per chat (`meta` with the chat's name, model and newest entry; `blobs` with the content). It can print a reply without a window and resume a chat by ID.
- The two `cursor-agent` chats on this Mac are **not** in the app's database. So on this Mac, with this version, they look like two separate stores, and nearly all conversations are in the app's. This is checked live before anything is built: start a `cursor-agent` chat and look for it in the app.
- No Cursor hooks are installed. Whether Cursor can attach text to a message or tell when a reply ends is to verify.

## To verify with a live run (spike M0b)

Per tool, on throwaway chats made in the Baton folder, the same questions as the first spike:

1. Add a turn to a closed chat: is it shown, and does the agent have it?
2. Create a chat from outside: does it appear at once or after a relaunch?
3. What marks a chat as open or replying?
4. Can text be attached to the user's next message, and how is it stored?
5. Is there a signal when a reply finishes, with the chat's ID?
6. Background run: can it be limited to reading, and does it leave a chat behind?
7. Can the app be opened at a given chat?
8. Where is the chat's name, and is a change from outside picked up?
9. Does a chat made shorter get accepted?
10. Cursor only: are `cursor-agent` chats and app chats the same chats?

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
