# Baton — design

Hand a conversation from Claude Code to Codex and back. Each linked chat exists once on each side; new turns are appended to the same pair, never copied into a new session. A summary is never inserted into an existing chat: a brief always starts a new chat.

Status: design agreed 2026-10-04, nothing built yet. Own codebase, not a fork. `Chamotrans/codex-claude-session-sync` (MIT) is studied as a reference for the session formats and for what already works; any code taken from it keeps its license notice. Mockup: https://claude.ai/artifact/XCLxrptfHM5QAqWMoRdLjh

## 1. Decisions

| Area | Decision |
|---|---|
| Usage | Hand-off, one tool at a time |
| History sent across | Two hand-off modes: full sync into the same linked chat, or a brief that starts a new chat on the other side |
| Scope | Only chats the user links |
| Audience | Built for one Mac first, polish for release later |
| Codebase | Written fresh in its own repo; the upstream tool is a reference, not a base |
| Trigger | Automatic at turn end (hooks, file watching as fallback) plus a Continue button |
| Open chat that is behind | Catch up, then send: the missing turns are attached to the user's message with their times. No closing, no reopening. A setting chooses whether a notice is shown when that happens |
| Conflicts | Merged in time order. A side that would need turns in the middle gets a merged copy as a new chat. Asked once with a preview, then remembered; changeable in Settings |
| Turns that ran at the same time | Ordered by start time; a warning when both changed the same file |
| App shape | Menu-bar app plus a full window |
| Stack | SwiftUI shell, Python engine |
| Linking | From the menu-bar list |
| Chats Codex already imported (70) | Shown as suggestions; linking aligns turns by content first |
| Extra feature | Size and cost preview before a hand-off |
| Agent | Not in the sync path. Both brief writers ship in the first version: agent-written and offline, offline as fallback |
| Visual style | Light glass, system materials; light and dark themes; dark is mid-gray, not near-black |
| Name | Baton |

Surfaces in scope: Claude desktop app (Code tab) and Codex Desktop. No CLI or VS Code sessions exist on the target machine. SDK script sessions (`sdk-py`) are hidden by default.

## 2. What testing the upstream tool showed

Tested against a throwaway copy of real data (104 Claude sessions, 75 Codex threads), Claude Code 2.1.179, Codex 0.159.2.

Learn from (it works, so Baton's own code follows the same approach):
- How the two formats map onto each other. Its converters produced valid output on both sides: tool calls paired, parent chain intact, Codex files use the same record types as Codex's own Claude imports.
- Append-only writes, the "open or just written" guard, refusing to write on conflict.

Do differently:
- **Turn-count cursor.** Both sides count turns differently (Codex counts compaction summaries and injected messages). On pairs Codex had imported itself, 1–5 Claude turns per pair had no match in Codex after sync.
- **Merge on conflict.** "Merge both" re-reads Codex after writing to it and pushes Claude's own new turns back into Claude.
- **Human-turn filter.** Slash-command echoes, local command output and system reminders are counted and pushed as user prompts.
- **Safety.** No backup, no dry run, no undo. File is written before the Codex database row.
- **UI.** Hard-coded Cantonese, window only.

## 3. Architecture

```
Claude desktop ── Stop hook ──┐                    ┌── stop hook ── Codex Desktop
~/.claude/projects/*.jsonl    │                    │   ~/.codex/sessions/**/rollout-*.jsonl
                              ▼                    ▼   ~/.codex/state_5.sqlite
                        ┌─────────────────────────────┐
                        │ baton engine (Python, CLI)  │
                        │  adapters: claude, codex    │
                        │  ledger (SQLite)            │
                        │  planner → applier          │
                        └──────────────▲──────────────┘
                                       │ JSON over stdout
                        ┌──────────────┴──────────────┐
                        │ Baton.app (SwiftUI)         │
                        │  menu-bar popover + window  │
                        │  file watcher (fallback)    │
                        └─────────────────────────────┘
```

- **Adapters** read a session into a common list of turns and write turns in the native format. They are written fresh, with the upstream converters as the reference for the formats.
- **Ledger** is Baton's own SQLite file in `~/Library/Application Support/Baton/`. It holds links, per-message mappings and a journal of every write.
- **Planner** is a pure function: both sides' turns plus the ledger in, a plan out (what would be appended where, or "conflict", or "history changed"). Every UI action shows the plan first; dry run is the planner without the applier.
- **Applier** executes a plan with the safety steps in section 5.
- **Turn-end hooks** call `baton notify --side claude|codex --session <id>`. The engine syncs that one link if the target side is closed, otherwise queues it.
- **Prompt hooks** call `baton catch-up --side claude|codex --session <id>` when the user presses send. If the other side has turns this chat has not received, the hook returns them as text to attach to the message.
- **App** never touches session files. It calls the engine and renders its JSON.

## 4. Sync model

**Identity, not counts.** Claude records carry `uuid`; Codex `response_item` records carry `id`. The ledger stores, for every synced message: source side, source ID, content hash, and the ID Baton wrote on the other side.

- New turns on a side = turns after the last ledger-known message on that side, in file order.
- A message Baton wrote itself is in the ledger, so it is never pushed back. This removes the echo bug by construction.
- Content hash (role plus normalized text) is the fallback when an ID is missing or a side was rewritten.

**Turn** = one real user prompt plus everything up to the next one. Not a real prompt: system reminders, slash-command echoes, local command output, compaction summaries, hook-injected text, Codex environment/instruction blocks.

**States per link:** in sync, Claude ahead, Codex ahead, conflict, history changed, side missing, target open (queued).

**Two ways a turn reaches the other side**

1. *Closed chat: append.* The real turns are appended to the saved chat. They show as normal turns when the chat is opened.
2. *Open chat: catch up at send.* An open chat holds its history in memory and does not re-read the file, so appending to it is unsafe. Instead, when the user presses send in a linked chat that is behind, the prompt hook attaches the missing turns to that message, each with its real time and origin. The agent answers knowing them.

Example: "add login" in Claude, synced. "add logout" in Codex. Back in the still-open Claude chat the user types "add tests". Claude receives "add tests" plus "at 14:05 in Codex: user asked for logout; Codex did X".

Rules for catch-up:
- The ledger records those turns as delivered to that chat, so they are never appended there again.
- The attached block is wrapped in a Baton marker. When that message is later pushed to the other side, the marker and its contents are stripped: the other side already has those turns.
- Order is truthful: the agent is told afterwards, with times, about turns it did not see. Nothing is rewritten to look as if it had seen them.
- If the catch-up text would be very large, the hook attaches a brief of the missing turns plus the path of the full transcript.
- If the hook cannot run, the message is sent as usual and the link may become a conflict.

How it is delivered: both tools run a hook when the user submits a prompt, pass it the session ID and the prompt, and add the text the hook returns to the model's context (`hookSpecificOutput.additionalContext`). Confirmed in use in the Claude desktop app; confirmed for Codex in its hooks documentation, not yet run live.

Notice shown or hidden (a setting, default shown): the attached turns always reach the agent. When the setting is on, the hook also returns a short user-facing notice (`systemMessage`), for example "Baton attached 1 turn from Codex: add logout". When off, nothing extra is shown. Both tools document this field; how each desktop app displays it is a spike question.

Codex runs a new hook only after the user reviews and trusts it once (`/hooks` in Codex). Baton never writes that trust entry itself.

**Conflict** (both sides have turns the other never received, by append or by catch-up). With catch-up in place this needs a missing or failed hook, or both chats closed with separate work. Nothing is written until the merge is confirmed.

Default merge: time order, never a rewrite.
- All new turns from both sides are sorted by start time.
- A side whose own new turns are all earlier than the other side's keeps its chat: the other side's turns are appended and the result is in time order.
- A side that would need turns placed in the middle gets a merged copy as a new chat on that side, in time order, and the link moves to it. The old chat is left untouched and marked as an earlier copy. Same rule as a brief: a changed context starts a new chat.
- Turns that ran at the same time in both tools are ordered by start time and marked as overlapping. If two overlapping turns changed the same file, the file is flagged for the user to check. Baton does not merge file contents.

Asking: the first conflict shows a preview (merged order, which side gets a new chat, flagged files) and waits. "Always do this" makes later ones automatic. The choice can be changed at any time in Settings.

Other choices offered in the preview:
- Add at the end, labelled: no new chat; the two sides end in different order.
- Keep Claude / Keep Codex: push one way; the other side's extra turns stay there, marked skipped.
- Split: unlink; the two chats continue separately.

**History changed** (a known message disappeared, e.g. rewind or edit): flag and ask; never auto-repair.

**Linking**
- New link from one side: create the counterpart under the same session ID, record every message in the ledger.
- Linking an existing pair (the 70 suggestions): align both turn lists by content hash, show what matches and what would be pushed, then record. No blind cursor.

**Compaction**
- Compaction never deletes saved history. It adds a marker and a summary record; the app then sends the model only what follows the marker. Baton reads the file, so it still sees every turn.
- The summary record is not a user prompt and is never pushed.
- Codex compacts in place: both user-facing compacted threads in the sandbox keep full history in the same rollout file.
- Claude does both. Of 48 compacted session files in the sandbox, 16 keep the earlier messages in the same file and 26 start at the compaction marker, with the earlier history in a different session file. A chat can therefore continue under a new session ID.
- A link is to a chat, not to one session ID. Baton follows the chain: the marker's parent pointer and the desktop sidebar registry say which file continues which. Which app action creates the new file is a spike question.

## 5. Safety rules

1. Never write to the file of a session that is open: Claude session registry (live pid), Codex writer locks, and a recent-write window. An open chat is reached through catch-up at send, not through its file.
2. Journal first: record target path and its size before writing. Undo = truncate back to that size and remove the database row Baton added.
3. Order for a new Codex thread: write file, verify it parses, insert database row, commit ledger. Any failure rolls back the earlier steps.
4. Dry run for every action; the app shows the plan before the first write to any chat.
5. Only linked chats are ever written. Unlinked sessions are read-only.
6. Format check at startup: if the Codex `threads` schema or the record shapes differ from the known set, Baton goes read-only and says which format changed.
7. Everything is local. No network calls.

## 6. History sent across

Two hand-off modes, chosen per hand-off. The size and cost preview recommends one.

**Full sync (default).** New turns are appended to the linked chat on the other side, exactly. Claude → Codex flattens tool calls to labelled text (Codex cannot replay Claude's tools); Codex → Claude writes real tool-call blocks. Reasoning never crosses. Each tool keeps managing its own context with its own compaction.

**Brief in a new chat.** A summary changes the context, so it never goes into an existing chat. Baton creates a new chat on the destination that opens with:
- the brief,
- the most recent turns verbatim,
- the path of the full transcript, saved as a Markdown file the receiving agent can read.

The link then points at the new chat. The earlier counterpart, if there was one, is left untouched and marked as an earlier copy. From there, new turns sync in full between the source chat and the new chat.

Brief is the recommended mode when the history is over the size threshold, and available any time the user wants a fresh start on the other side.

**Who writes the brief (both in the first version)**
1. Agent brief: decisions made, state of the work, files touched, open items. Run headless by the tool being moved to, because the tool being left may be at its limit. If that tool has no headless runner, the other tool writes it.
2. Offline brief: mechanical list of user requests plus recent exchanges. Free and instant. Used when the user picks it or when the agent run fails.

Briefs are cached per chat and updated from the new turns only.

Headless runners on the target machine: both exist. `claude` is installed, and the ChatGPT app bundles the Codex CLI at `/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex` (0.159.2, the same version as the desktop engine, with `exec --ephemeral`). Baton finds and calls that bundled binary. No second copy is installed: a separately installed CLI at a different version would share `~/.codex` with the desktop app.

**Size and cost preview:** turns to send, estimated tokens of history, and the recommended mode, shown before a hand-off.

## 7. App

**Menu-bar popover**
- Linked chats with a status dot and one-line state ("in sync", "Claude ahead by 2", "conflict").
- Continue in Codex / Continue in Claude for the selected chat: sync, then open the other app.
- Recent unlinked chats with a Link button.
- Badge on the menu-bar icon when something needs a decision.

**Window**
- Sidebar: Linked, Needs attention, Suggestions, All Claude, All Codex, Activity.
- Detail: both sides' turns in one timeline, each marked with where it was written and whether it has crossed.
- Size and cost preview panel.
- Conflict sheet: preview of the time-ordered merge (order, which side gets a new chat, flagged files), the other choices, and "always do this".
- Activity log with Undo on the last write per chat. Catch-ups are listed too: which turns were attached to which message.
- Settings: hooks installed or not, catch-up notice (shown or hidden), conflict behaviour (ask, or the remembered choice, changeable any time), summary threshold, hidden session types, title tag.

Synced chats get a short title tag on the other side (`[Claude]`, `[Codex]`), configurable.

**Visual style**
- Light glass: system materials behind the popover, the sidebar and the window, with the content pane more opaque than the sidebar so text stays readable. One setting controls how translucent it is.
- Themes: Light, Dark, or follow the system.
- Dark is mid-gray (window around `#3E4148`, sidebar slightly lighter), with white hairlines at about 10% instead of black fills. No near-black surfaces.
- One accent (blue) for the primary action and "ahead" states; green for in sync, red for needs a decision. Claude and Codex each get a fixed tag color.
- Text contrast stays at 4.5:1 or better on glass in both themes.

Build note: the target machine has Command Line Tools only, no Xcode. The app is built as a Swift package and bundled by script, or Xcode is installed first.

## 8. Milestones

| | Goal | Done when |
|---|---|---|
| M0 | Spike on the real apps with one throwaway chat | The questions in section 9 are answered |
| M1 | Engine core | Ledger, planner, turn filter, session-chain following, safety rules, offline brief, test suite built from the sandbox fixtures; upstream bugs covered by failing-then-passing tests |
| M2 | CLI, hooks, agent brief | `link`, `plan`, `sync`, `continue`, `brief`, `undo`, `notify`, `catch-up`; turn-end and prompt hooks installed in both tools; agent brief with offline fallback |
| M3 | Baton.app | Menu-bar popover, window, conflict sheet with time-ordered merge preview, mode switch, glass light and dark-gray themes |
| M4 | Release polish | Signing, docs; report the merge bug to the upstream author |

M1 to M3 are the first version.

## 9. Open questions for the spike (M0)

1. Does the Claude desktop app open and continue a chat whose file Baton appended to? Does it need a restart, or only reopening the chat?
2. Same for Codex Desktop with an appended rollout and a Baton-created thread.
3. How long does a session count as open after the user leaves it (Claude process lifetime, Codex lock lifetime)?
4. Do the Stop hooks fire in the desktop apps, and do they receive the session ID?
5. Can either app be opened at a specific chat (`claude://` exists; Codex unknown)?
6. Do the fields native Claude records carry and upstream omits (`promptSource`, `turnOrigin`, `turnPosition`, `requestId`, `effort`) matter on resume?
7. Does adding a row to Codex's database from outside survive a Codex update or restart?
8. When does the Claude desktop app continue a chat under a new session ID (auto-compaction, reopening, something else), and does the sidebar registry always point at the newest file?
9. Does a chat Baton creates from a brief open as a normal new chat in each app?
10. Can `claude -p` and the bundled `codex exec --ephemeral` each write a brief from a transcript file without touching the user's open sessions or leaving a chat behind?
11. Live check of Codex catch-up, after the user trusts Baton's hook once: does the attached text reach the agent in Codex Desktop as the documentation says?
12. How does each desktop app display the attached text and the optional notice, with the notice setting on and off?
