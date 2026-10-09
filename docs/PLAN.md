# Baton — build plan

What gets built, in what order, and when each piece counts as done. This page is the overview. The low-level plan, with every work package, its files, tests and checkpoints, split into tracks that can be worked on at the same time, is in [plan/](plan/README.md). The design is in [DESIGN.md](DESIGN.md); section 1a there is the list of every feature. This file is the order of work.

## Where things stand (2026-10-04)

**Settled**
- Design, five feature specs, mockup with a board for every screen.
- Both spikes: how each of the four tools stores chats, takes writes, attaches text and reports a finished reply ([SPIKE-M0.md](SPIKE-M0.md), [features/more-tools.md](features/more-tools.md)).
- Dark theme: Graphite. Colour rules in DESIGN.md section 7.

**Checkpoint CP1 passed 2026-10-05; CP2 in progress (reviewed 2026-10-09).** Built and committed: delivery by each tool's facts, journal and safety, turn mapping, applier, linking and copying, merge, undo and restore, the Claude adapter on built fixtures (380 engine tests), and the app's theme, menu-bar popover, window, sync status, link and copy dialogs, brand and early settings (95 of 96 app tests). Still owed for CP2: usage and limits, briefs, the Codex adapter, the command line, two more screens, and the live run on throwaway chats. Live status and open findings: [plan/STATUS.md](plan/STATUS.md).

**Built** (`baton/` and `app/`, 129 engine tests and 15 app tests)
- `model.py`: turns and messages.
- `claude_reader.py`, `codex_reader.py`: a chat file into turns.
- `ledger.py`: links, one link per chat, a state per turn per side, history, keep back, pin, reorder.
- `status.py`: per side, what the agent has, what the chat shows, what waits and why.
- `planner.py`: per side add / add after release / attach / hold; merge orders and what each means for each chat.

**Not built**: everything below.

## Rules for every slice

- Works on made-up chats in tests before it touches a real one. Real chats only through the safety rules (DESIGN.md section 5).
- A tool's behaviour comes from its adapter's answers, never from its name in the planner or the app.
- Every action has a dry run that says what it will do, in the words of "Notes the user always sees".
- Small commits on a branch, each saying why.

## Order of work

### M1, engine core (all four tools)

| # | Slice | Done when |
|---|---|---|
| 1 | **Adapter interface.** One class per tool answering the questions of more-tools.md G3 (takes turns when, new chat appears when, can attach, can be made shorter, open/replying check, version it was checked against). Claude and Codex first, then OpenCode and Cursor; readers move behind it | The planner and status take an adapter and contain no tool names; tests run with a made-up third tool |
| 2 | **Writers.** Add turns to a closed Claude chat and a Codex chat not held; create a chat in each (Claude: file and sidebar entry; Codex: rollout and thread row). Tool calls flattened one way, real blocks the other | Round trip in tests: what a writer writes, the reader reads back as the same turns; nothing is re-read as new (ledger local IDs) |
| 3 | **Journal and safety.** Journal before every write, saved copy, take back a failed write, refuse an open or held chat, format/version check per tool | Each rule in DESIGN.md section 5 has a failing-then-passing test |
| 4 | **Applier.** Carries out a plan: add, add after release (Claude), record attach, hold; records every step in the ledger history | Sync status scenarios S1 to S12 pass end to end on made-up chats |
| 5 | **Linking.** Both ways (full copy, history attached), copy without linking, change link, remove link; content-matching for chats Codex already imported | link-actions T0 to T4 pass |
| 6 | **Merge.** Apply a chosen order: merged copy as a new chat, don't-reorder, keep one side, split; same-file warning from tool calls | merge U1 to U9 pass |
| 7 | **Undo.** Back to any history entry: cut on Claude, shorter chat on Codex; saved copy for 30 days; restore | link-actions T7 to T11 pass |
| 8 | **Following a Claude chat** across session IDs and compaction | A chat that continued under a new ID stays one linked chat in tests built from the real shapes |
| 9 | **Reading extras.** Context in use, usage limit and reset time, "since you left" digest (turns, files, commands), names | working-across V1 to V8 at engine level |
| 9a | **OpenCode adapter**: read and write its database (also while it runs), version check | Slices 2 to 9 pass for a link with OpenCode on made-up data; X1 to X4 pass |
| 9b | **Cursor adapter**: read transcripts and display records, write display records only while Cursor is closed, version check before every write | Slices 2 to 9 pass for a link with Cursor; an unknown version turns writing off and says so |
| 10 | **Offline brief**, with pinned turns in full and kept-back turns left out | V13, V14 pass |

### M2, command line, hooks, agent brief

| # | Slice | Done when |
|---|---|---|
| 11 | **`baton` command** with every action as a subcommand, JSON out, `--dry-run` everywhere | Each command's dry run prints the note the app will show |
| 12 | **Hooks.** Prompt hook (catch-up) and turn-end hook (notify) for Claude, Codex and Cursor, and the plugin for OpenCode; install, uninstall and check; each tool's exact output shapes | Live on the throwaway chats: a turn written on one side is attached on the other at send, and synced at turn end |
| 13 | **Relaunch.** Wait until idle, quit, write, reopen, land on the chat; "when idle"; releasing one idle Claude chat | Live on the throwaway chats, as `spike/m0_relaunch.py` did by hand |
| 14 | **Setup check** per tool with the fix for each finding (hooks, trust, command missing or damaged, signed out, unknown version) | Each state can be produced in a test and names its fix |
| 15 | **Agent brief and second opinion**: background runs limited to reading, fallback to the other tool, then to the offline brief | V9, V10 pass; V4 passes with one tool at its limit |
| 16 | **Limit offer** at turn end | V1 to V3 pass |

### M3, the app

| # | Slice | Done when |
|---|---|---|
| 17 | SwiftUI shell calling the engine; menu-bar popover and window; Graphite and light themes | The linked-chat list shows real status |
| 18 | Sync status screen | Matches the board; every state of sync-status.md is reachable |
| 19 | Link, copy, hand-off dialogs with the "What will happen" block | Every row of the notes table appears where it should |
| 20 | Merge screen with reordering | U1 to U6 can be done by hand |
| 21 | History, undo, restore; relaunch confirmation | T5 to T11 by hand |
| 22 | Second opinion, limit offer, setup and settings | Each setting changes what the engine does |

M1 to M3 are the first version, with all four tools.

### Last

| # | Slice | Done when |
|---|---|---|
| 23 | **Tool picker and copy any-to-any** in the dialogs; Setup card per tool | X2, X5 pass |
| 24 | Release polish (M4): signing, docs | |

Because slice 1 comes first, the OpenCode and Cursor adapters (9a, 9b) add adapters and nothing else.

## Every feature, across every tool

The features in DESIGN.md section 1a are written once and hold for any two tools. What differs per tool is only what its adapter answers:

| Feature | Claude | Codex | OpenCode | Cursor |
|---|---|---|---|---|
| Link by full copy; copy without linking; full copy on demand | new chat shows after one relaunch | at once | at once | Cursor closed while written |
| Link with history attached; catch-up at send | hook | hook, trusted once | plugin, one restart | hook |
| Automatic sync at turn end | hook | hook | plugin | hook |
| New turns as real messages | closed, or idle chat released | when not held | any time | while closed |
| Seeing them | after relaunch | at once | on reopening the chat | after relaunch |
| Merge with a merged copy | new chat, relaunch | new chat | new chat | new chat, Cursor closed |
| Undo | cut | shorter chat | cut | shorter chat |
| Brief by this tool's agent; second opinion | yes | yes | needs its command repaired | needs `cursor-agent` signed in; else the other tool |
| Context in use | tokens; percent when size known | tokens and percent | tokens | tokens and percent |
| Usage limit and reset time | yes | yes | limit yes, reset time no | limit yes, reset time no |
| Relaunch from Baton | yes | yes | not needed | yes |
| Names followed; rename | read; rename while closed | read; shows after relaunch | read; rename shows while running | read; rename while closed |
| Pause, remove link, history, keep back, pin, status | same for all | same for all | same for all | same for all |

Where a cell says something cannot be done, the dialog says so before the user confirms and offers the next best (more-tools.md, G4 and G4a).

## Open, and what happens meanwhile

| Open | Meanwhile |
|---|---|
| "Attach now, show later" in the same chat | Settled for Cursor: works, placed at the right position while Cursor is closed. Codex: one run worked but doubled the file's numbering, so Baton attaches and offers close, sync, reopen |
| Cutting an OpenCode or Cursor chat shorter | Settled: OpenCode accepts it. Cursor hides the turns but its agent keeps them, so undo on Cursor creates a shorter chat |
| Opening OpenCode or Cursor at a given chat | Settled: neither has a link to a chat. Baton opens the folder in the app and names the chat to pick |
| Usage limits in OpenCode and Cursor | Settled: both record a failed turn with the reason, without a reset time. The limit offer is shown without "available again at" |
| What makes Codex let go of a chat by itself | Check before every write |
| A future format change in any tool | Version check; writing off, reading and attaching on |

None of these blocks slice 1.
