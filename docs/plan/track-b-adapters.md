# Track B — adapters, one per tool

Each adapter is a package under `baton/adapters/<tool>/` implementing the interfaces in [ARCHITECTURE.md](ARCHITECTURE.md). The only place a tool's file format, database or process is known. Facts come from [../SPIKE-M0.md](../SPIKE-M0.md) and [../features/more-tools.md](../features/more-tools.md); the scripts in `spike/` show how each was measured and are the reference for the exact record shapes.

Every adapter passes the same suite, `tests/adapters/suite.py`:

| Suite check | Proves |
|---|---|
| `test_reads_turns` | prompts, replies and tool calls come back as turns; only real prompts start a turn |
| `test_skips_inserted_text` | text the tool or Baton inserted is not read as a prompt |
| `test_round_trip` | turns written by the writer are read back equal |
| `test_second_read_adds_nothing` | ids are stable |
| `test_create_then_add` | a created chat takes further turns |
| `test_condition` | exists, open, replying, app running are reported as built in the fixture |
| `test_refuses_outside_write_window` | the writer raises the right error when the facts say it must |
| `test_take_back` | a write can be undone exactly |
| `test_cut_or_refuse` | cut works, or raises `NotAvailable`, as the facts say |
| `test_unknown_version_blocks_writes` | reading still works |
| `test_facts_match_behaviour` | every fact is exercised |

All adapter tests run on files and databases built in a temporary folder that the adapter is pointed at (`root` argument). No adapter test touches the user's real chats. Live checks are separate (`tests/live/`, off by default).

---

## B0. Fake adapter

**Goal.** An in-memory tool whose facts can be set, so the core can be built and every scenario tested without a real tool.
**Depends on.** E1.
**Files.** `baton/adapters/fake/`, `tests/adapters/suite.py`.
**Steps.** 1. Chats as lists of turns in memory. 2. Settable `Capabilities` and conditions (open, replying, app running, version). 3. A fake runner that returns canned text or fails. 4. A fake `AppControl` that records calls. 5. Four ready-made fact sets: `claude_like`, `codex_like`, `opencode_like`, `cursor_like`.
**Tests.** The suite runs on the fake with each fact set.
**Done when.** The suite passes four times on the fake.

## B1. Claude

**Facts.** write window `CLOSED_OR_RELEASED`; new chat `AFTER_RELAUNCH`; added turn `AFTER_RELAUNCH`; can cut; cannot place; can release one idle chat; opens at chat; limit with reset time; context size per model; hooks need nothing.

| Part | File | Details |
|---|---|---|
| Locator | `locator.py` | Chats from the desktop sidebar entries (`claude-code-sessions/<org>/<account>/local_*.json`): stable id is the entry's `sessionId`, current file from `cliSessionId`. `resolve` follows a chat that continued under a new session id. Name from the entry's `title`. Script-started sessions hidden by setting. |
| Reader | `reader.py` (exists) | Live chain from the newest record by `parentUuid`, across compaction markers. Prompts are records whose origin is human or peer. Hook attachments are separate records and skipped. `usage`: sum of input, cache and output tokens of the latest reply; limit from the marked error reply with `quotaLimits`. `files_changed` from edit and write tool calls. |
| State | `state.py` | Open: a live process in `~/.claude/sessions/` for the chat. Replying: that entry's status is busy. App running: process check. Version: the record fields the reader relies on are present. |
| Writer | `writer.py` | `add`: append records chained to the newest record, shaped as in `spike/m0_append.py`; refused while a process holds the chat. `create`: session file plus sidebar entry, as `spike/m0_create.py`. `cut`: truncate to the end of a turn after saving the removed part, as `spike/m0_cut.py`. `rename`: the entry's title, only while the app is closed. `place`: not available. |
| Hooks | `hooks.py` | Prompt and turn-end entries in the project's or user's settings; output is `hookSpecificOutput.additionalContext` plus optional `systemMessage`. |
| Runner | `runner.py` | `claude -p --no-session-persistence` with `--allowedTools Read,Grep,Glob`; needs the one-time login; reports "not logged in". |
| App | `app.py` | `close`: ask the app to quit; `open`: `claude://claude.ai/epitaxy/<id>`; `release`: end one idle chat's process and wait for its registry entry to go. |

**Done when.** The suite passes on built fixtures; live: on a throwaway chat, add while closed is shown after a relaunch and known; release-then-add is known on the next message.

## B2. Codex

**Facts.** write window `NOT_HELD`; new chat `AT_ONCE`; added turn `AT_ONCE`; cannot cut; cannot place; no release; opens at chat; limit with reset time; context size known; hooks need a one-time trust.

| Part | File | Details |
|---|---|---|
| Locator | `locator.py` | Chats from the `threads` table of `state_5.sqlite`: id, title or name, rollout path, folder. |
| Reader | `reader.py` (exists) | `response_item` records; injected messages skipped by prefix; id from the payload or the ordinal. `usage` from the last `token_count` event (`last_token_usage`, `model_context_window`, `rate_limits`). |
| State | `state.py` | Held: the thread's writer lock is taken. Replying: a task has started without a completion after it. Version: the `threads` columns and record types match the known set. |
| Writer | `writer.py` | `add`: append records with the next ordinals and update the thread row, as `spike/m0_append.py`; refused while held. `create`: rollout file, verify it parses, insert the thread row, as `spike/m0_create.py`; any failure rolls the earlier steps back. `cut`: raises `NotAvailable`, except taking back its own last write while Codex's index has not read past it. `rename`: `title` and `name`. |
| Hooks | `hooks.py` | `hooks.json` entries; turn-end prints exactly `{}`; `check` reports whether the entries are trusted and never writes the trust itself. |
| Runner | `runner.py` | The CLI bundled in the ChatGPT app: `exec --ephemeral -s read-only`. |
| App | `app.py` | `open`: `codex://threads/<id>`. |

**Done when.** The suite passes; live: add to a chat not held shows at once; a held chat is refused.

## B3. OpenCode

**Facts.** write window `ANY_TIME`; new chat `AT_ONCE`; added turn `ON_REOPEN_CHAT`; can cut; can place; no release; does not open at a chat; limit without reset time; context size not recorded; hooks need one restart.

| Part | File | Details |
|---|---|---|
| Locator | `locator.py` | `session` rows of `opencode.db` with no parent (sub-agent runs are skipped); folder from `directory`; project row by the folder's first commit. |
| Reader | `reader.py` | `message` rows in time order; `part` rows per message. A user message starts a turn; text parts marked `synthetic` are skipped; reasoning parts dropped; tool parts become tool calls. `usage` from the last reply's `tokens`; limit from a reply's `error` with a rate-limit status. `files_changed` from the user message's `summary.diffs`. |
| State | `state.py` | Exists; app running by process; replying from the newest reply having no `finish`. Version: the tables and columns the adapter uses are present. |
| Writer | `writer.py` | IDs as OpenCode builds them (prefix, 48 bits of time and counter, 14 random characters; chats count down). Times taken from the turn, strictly increasing within a chat. `create`, `add`, `place` (rows with times before the target message), `cut` (delete rows after saving them), `rename`, all in one transaction each, as `spike/m0b_opencode.py`. |
| Hooks | `hooks.py`, `baton/hooks/opencode_plugin.js` | A plugin in the config's plugins folder: `chat.message` adds a part marked synthetic; `event` reports busy and idle with the chat's id by calling `baton notify`. Loaded when OpenCode starts. |
| Runner | `runner.py` | The `opencode` command; `available` detects a command that the system refuses to run and returns the finding "reinstall". |
| App | `app.py` | `open`: `opencode://open-project?directory=…`; reports `opened: folder`. |

**Done when.** The suite passes; live: create and add while running, shown on reopening the chat and known on the next message; cut the same.

## B4. Cursor

**Facts.** write window `APP_CLOSED`; new chat `AFTER_RELAUNCH`; added turn `AFTER_RELAUNCH`; cannot cut (the agent keeps cut turns); can place; no release; does not open at a chat; limit without reset time; context size known; hooks need nothing; checked version: chat record `_v` 18.

| Part | File | Details |
|---|---|---|
| Locator | `locator.py` | `composerHeaders` rows of the app's `state.vscdb`: id, name, folder, times. Not `cursor-agent`'s chats. |
| Reader | `reader.py` | Prefer the transcript file (`~/.cursor/projects/<folder>/agent-transcripts/<id>/<id>.jsonl`): strip the timestamp and query wrapper from prompts; `turn_ended` lines end a turn and carry a failure reason. Times and ids from the chat record's ordered message list. Chats without a transcript are read from the message records. `usage` from the chat record (`contextTokensUsed`, limit, percent). |
| State | `state.py` | App running by process. Replying: the hooks' start and end of a turn, kept by `baton notify`. Version: the chat record's `_v`. |
| Writer | `writer.py` | Only while the app is not running, else `AppMustBeClosed`. Writes display records only: one record per message and the ordered list, as `spike/m0b_cursor_create.py`; the agent's encoded state is never written. `create`: empty agent state, which Cursor builds from the display. `add`: at the end. `place`: before a given message, for turns already attached. `cut`: `NotAvailable`. `rename`: the list row and the chat record. An unknown `_v` blocks all of these. |
| Hooks | `hooks.py` | `hooks.json` with `beforeSubmitPrompt` (returns `additional_context`) and `stop`. Chat-start context is not used; it does not reach the agent. |
| Runner | `runner.py` | `cursor-agent -p`; `available` reports "sign in" when it is signed out. |
| App | `app.py` | `close`, `open` on the folder; reports `opened: folder`. |

**Done when.** The suite passes; live: create and add while closed are shown and known after opening; place shows at the position; an unknown version turns writing off.

---

## Fixtures

`tests/fixtures/<tool>/build.py` builds a small chat in that tool's real shape inside a temp folder: three turns, one with a tool call, one inserted-text record that must be skipped. The shapes are copied from the spike scripts, with made-up content only. The fixture builder is the single place a test knows a tool's format.
