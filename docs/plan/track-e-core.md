# Track E — engine core

Everything here is free of tool-specific code and is tested with the fake adapter (B0) and an in-memory store. Read [ARCHITECTURE.md](ARCHITECTURE.md) first.

---

## E0. Restructure into layers

**Status.** Done 2026-10-05, commit `d4d9153`.

**Goal.** Move what exists into the package layout, with no change in behaviour.
**From.** ARCHITECTURE.md, package layout.
**Depends on.** Nothing.
**Files.** `baton/model.py` → `baton/domain/model.py`; dataclasses and state constants from `baton/ledger.py` → `baton/domain/link.py`; `SideCondition` → `baton/domain/conditions.py`; `baton/ledger.py` → `baton/ledger/sqlite_store.py`; `baton/status.py`, `baton/planner.py` → `baton/services/`; `baton/claude_reader.py`, `baton/codex_reader.py` → `baton/adapters/<tool>/reader.py`; tests → `tests/unit/`, builders → `tests/fixtures/builders.py`.
**Steps.** 1. Create packages with `__init__.py`. 2. Move files with `git mv`. 3. Fix imports. 4. Add `baton/domain/errors.py` with the table from ARCHITECTURE.md; move `AlreadyLinked`, `AlreadyDelivered`, `OrderNotAllowed` into it.
**Tests.** The existing 70 tests, unchanged in meaning.
**Done when.** All 70 pass from the new paths and `grep -rn "import" baton/domain baton/services` shows no import of `adapters` or `ledger`.

## E1. Ports and capabilities

**Status.** Done 2026-10-05, commit `cb11c88`.

**Goal.** The interfaces of ARCHITECTURE.md as code.
**From.** more-tools.md G3, G10.
**Depends on.** E0.
**Files.** `baton/ports/tool.py`, `baton/ports/store.py`, `baton/ports/clock.py`, `baton/domain/capabilities.py`.
**Steps.** 1. `Capabilities` dataclass with the enums `WriteWindow`, `Visibility`, `HookNeed`. 2. The Protocols. 3. `ChatRef`, `Usage`, `FormatCheck`, `WriteResult`, `WriteReceipt`, `SetupFinding` dataclasses. 4. `RecordStore` Protocol listing exactly the methods the SQLite store already has. 5. `Clock` with `SystemClock` and `FixedClock`.
**Tests.** `tests/unit/test_capabilities.py`: the four tools' fact tables (added in track B) are complete, i.e. no field left at a default.
**Done when.** `services/status.py` and `services/planner.py` type-check against the ports and no longer import the store class.

## E2. Planner and status read capabilities

**Goal.** Replace the remaining assumptions ("an open chat is attached to") by the adapter's facts.
**From.** more-tools.md "Best delivery per tool"; sync-status R4, R5; DESIGN 5 rule 1a.
**Depends on.** E1, B0.
**Files.** `baton/services/planner.py`, `baton/services/status.py`, `baton/domain/conditions.py`, `baton/notes/__init__.py`, `baton/notes/catalogue.py`; corresponding unit tests.
**Steps.**
1. Keep `app_running`; add `app_started_at: str = ""`.
2. `plan_sync` takes `facts: Mapping[tool, Capabilities]`. Decision per side, first that applies:
   - not exists → `hold(side_missing)`; paused → `hold(paused)`; conflict → `hold(decision_needed)`; unknown format → `attach` if chat open and hooks ready, otherwise `hold(format_unknown)`; no writes. Test both.
   - `ANY_TIME` → `add`, `needs: reopen_chat_to_see` if open.
   - `NOT_HELD` and not open → `add`.
   - `APP_CLOSED` and app not running → `add`; `CLOSED_OR_RELEASED` and no process → `add`.
   - `CLOSED_OR_RELEASED`, open, idle, `can_release_chat`, setting automatic, full-copy link → `add_after_release`, `needs: relaunch_to_see`.
   - otherwise open with hooks ready → `attach`; hooks not ready → `hold(hooks_not_ready)`.
3. Each step carries `needs` and the alternatives it could offer (`close_sync_reopen`, `add_now`, `relaunch`), for E12 to turn into notes.
4. Status: the "shown" count uses `added_turn_visible`; AT_ONCE is shown immediately; AFTER_RELAUNCH requires app_started_at after delivery; ON_REOPEN_CHAT requires a later app start or explicit user mark_shown. Never infer shown from a prompt-hook call. Keep the status instruction until shown.
5. Seed the CP1 note catalogue now from the feature wording tables, including E4 marker text. E12 completes and audits it later.
**Tests.** `tests/unit/test_planner_delivery.py`: one test per row of the "Best delivery per tool" table (8 rows), each built from a fake adapter given that tool's facts.
**Done when.** The eight rows pass and the planner has no tool name in it.

## E3. Journal and safety

**Goal.** Nothing is written without a journal entry, a saved copy where something is removed, and a way back.
**From.** DESIGN 5 (all rules); link-actions A10.
**Depends on.** E1.
**Files.** `baton/services/journal.py`, `baton/ledger/schema.py` (table `journal`), `baton/ledger/sqlite_store.py`, `baton/ports/store.py` (additive), `baton/domain/errors.py`, `baton/ports/tool.py` (additive prepare), `baton/adapters/fake/tool.py`, `tests/adapters/suite.py`; corresponding unit tests.
**Steps.** 1. `Journal.begin(link, tool, chat, action) -> entry` records intent and persists writer.prepare(chat | None, action) receipt before mutation; create preparation says no chat exists yet. 2. `commit(entry, receipt)`, `fail(entry, error)`. 3. `take_back(entry)` calls `writer.take_back(receipt)`. 4. Separate `Guard.check_release` (open, idle, release supported) and `Guard.check_write` (safe write state). The latter raises `ChatHeld`, `AppMustBeClosed`, `ChatReplying`, `UnknownFormat`, `ChatChanged` from the adapter's state, using the facts. 5. Saved copies kept 30 days; `prune()` removes older ones. 6. On start, any begun/uncommitted entry is taken back using its persisted pre-write receipt and reported; test durable recovery, including create.
**Tests.** `tests/unit/test_journal.py`, `test_guard.py`: one failing-then-passing test per safety rule; a crash between write and record is recovered.
**Done when.** Every rule in DESIGN 5 names its test in a comment at the top of the test.

## E4. Turn mapping between tools

**Goal.** One place that says how a turn written in tool X is represented in tool Y.
**From.** DESIGN 4 "Identity, not counts" and 6 "Full sync".
**Depends on.** E1.
**Files.** `baton/services/mapping.py`, `baton/domain/model.py` (additive non-replayable TOOL_TEXT kind), `baton/notes/catalogue.py` (marker and additive D4 presentation labels); corresponding unit tests.
**Steps.** 1. `for_target(turn, facts) -> Turn`: reasoning never crosses; tool calls become labelled text where the target cannot replay them, real blocks where it can (adapter fact `replays_tool_calls`). 2. Created-chat title tag from the note catalogue when the title_tag setting is on (DESIGN 7); preserve prompt content. Keep the separate catalogue marker helper for adapter metadata, never insert it into a real prompt. 3. `content_key(turn)` for matching chats that are already copies of each other.
**Tests.** `tests/unit/test_mapping.py`: round trip keeps prompt and final reply; tool calls flattened or kept by fact; reasoning dropped.
**Done when.** No adapter contains mapping logic; writers receive already-mapped turns.

## E5. Applier

**Goal.** Carry a plan out, step by step, and record it.
**From.** DESIGN 3 (applier), 4; sync-status S1 to S12.
**Depends on.** E2, E3, E4, B0.
**Files.** `baton/services/applier.py`, additive `baton/services/planner.py` and `baton/services/status.py` initial-history policy flag, `baton/notes/catalogue.py` (additive D4 status labels), additive `baton/ports/store.py` and `baton/ledger/sqlite_store.py` methods needed for local delivery IDs, reconciliation and atomic delivery/journal commit; corresponding unit and scenario tests.
**Steps.** 1. `apply(plan) -> Result`: for each step, `Guard.check_write`, `Journal.begin`, call the writer (`add`, `create`, `place`, `cut`) or record `attach` intent, verify by reading back, record local delivery IDs and commit the journal in one SQLite transaction. Recovery must never leave rolled-back content marked delivered. 2. `add_after_release`: check_release → app.release(chat) → wait at most 10 seconds for closed state → check_write → add; state `added`. Release or wait failure falls back to attach, records why, and never writes before a successful recheck. 3. A step that fails takes itself back and stops the plan; earlier steps stay and are reported. 4. `record_attached(link, tool, turn_ids, message_id)` for the prompt hook. 5. The shared planner/status policy accepts explicit initial_history_sides: attached-history initial turns remain waiting for first-prompt acknowledgement even on a closed destination; unknown-format precedence stays unchanged.
6. `refresh(link)`: read both chats, `store.record_turns`, mark `added` → `shown` only according to E2 visibility evidence; never a prompt hook.
**Tests.** `tests/scenarios/test_sync_status.py`: S1 to S12, one test each. `tests/unit/test_applier.py`: failure in the middle, read-back mismatch, plan id refused after the chat changed.
**Done when.** S1 to S12 pass on the fake adapter with each of the four fact sets where the scenario applies.

**Reviewer clarification (S9/S7).** If bypass also introduces a genuinely new completed destination turn, hold for S7; redeliver after merge (E7). Automatic S9 redelivery applies without that competing turn.

## E6. Linking and copying

**Goal.** Both ways of linking, copy without linking, change and remove.
**From.** DESIGN 4 "Linking"; link-actions A0 to A4; more-tools G2, G5, G6; scenarios T0 to T4, X1, X2.
**Depends on.** E5.
**Files.** `baton/services/linker.py`, `baton/domain/link.py` (extend tool identity list to all four tools), additive `baton/ports/store.py` and `baton/ledger/sqlite_store.py` for atomic link metadata and journal completion; corresponding unit and scenario tests.
**Steps.** 1. `plan_link(from, to_tool, to_chat|None, mode)`: `full_copy` creates the other chat (step `create`, with that tool's `needs`); `attached_history` links an existing new chat and leaves every turn `waiting`; `brief` raises `NotAvailable` until E10 exists (test the refusal). 2. Linking two existing chats aligns turns by `content_key` first, so shared turns are `shown` on both. 3. `plan_copy(from, to_tool, and_link)`. 4. `plan_relink`, `plan_unlink` (never touches a chat). 5. `suggestions()`: pairs of unlinked chats with matching content keys.
**Tests.** `tests/scenarios/test_link_actions.py` T0 to T4; `test_more_tools.py` X1, X2.
**Done when.** Those scenarios pass and a link can be made between any two of the four fact sets.

**Integration notes.** `plan_full_copy(link_id, side)` implements A4 while preserving link/turn identity and reconciling local IDs. Plain copies from linked sides include attached history. Canonical previews confirm their exact keep/skip/order record snapshot and refuse unrecorded native turns until refresh. Unlink uses metadata observations and remains available if a chat is missing or unreadable. Durable created-copy visibility is independent of rollback receipt retention. A third-tool relink requires an explicit retained `from_side`; C3/D5 must add contract/UI routes for that choice and A4 before wiring.

## E7. Merge

**Goal.** Apply a decision when both sides have new turns.
**From.** merge.md M1 to M12; U1 to U9.
**Depends on.** E5.
**Files.** `baton/services/merger.py`, small additions to `planner.py`.
**Steps.** 1. `show(link)`: last shared turn, unsynced turns, default order, outcome per side, overlaps, same-file list. 2. Same-file detection: files changed per turn from the readers' tool calls (adapter gives `files_changed(turn)`). 3. `plan(link, order|preset|keep|split)`: `keeps_chat` side → `add` the other's turns; `merged_copy` side → `create` a new chat in merged order and `move_link`; `dont_reorder` → `add` both ways; `keep` → `skip` then sync; `split` → `unlink`. 4. Large merged copy offers a brief (E10). 5. "Always by time" setting, except when same-file applies.
**Tests.** `tests/scenarios/test_merge.py` U1 to U9.
**Done when.** U1 to U9 pass.

## E8. Undo and restore

**Goal.** Back to any history entry, per tool.
**From.** link-actions A8 to A10; T7 to T11; more-tools notes table (four undo rows).
**Depends on.** E5.
**Files.** `baton/services/undo.py`.
**Steps.** 1. `plan(link, event)`: the turns that side will no longer have (delivered at and after the event, plus everything written there since), which exist only there, and the turn it will end at. 2. `can_cut` → step `cut` (saved copy first); otherwise step `create_shorter` and `move_link`, old chat marked "earlier copy". 3. After apply: affected turns back to `waiting`, link paused. 4. `restore(event)`: put a cut back if nothing was written since, or move the link back to the earlier chat. 5. Attached turns: undo goes back to before the message they were attached to.
**Tests.** `tests/scenarios/test_link_actions.py` T7 to T11, each run with a cut-capable and a not-cut-capable fact set.
**Done when.** T7 to T11 pass for both kinds.

## E9. Usage, limits, digest

**Goal.** How full each side is, limits, "since you left".
**From.** working-across W1 to W8; V1 to V8.
**Depends on.** E1.
**Files.** `baton/services/usage.py`, `baton/services/digest.py`.
**Steps.** 1. `Usage` from the reader: tokens, size or none, percent only when size is known. 2. Limit: reached or not, reset time or none; "available again" only with a reset time. 3. Digest: turns, files changed, commands run on the other side since this side's last prompt. 4. The digest is the first block of the attached text.
**Tests.** `tests/scenarios/test_working_across.py` V1 to V8.
**Done when.** V1 to V8 pass, including the no-reset-time and no-size cases.

## E10. Briefs

**Goal.** Offline brief, and agent brief with fallback.
**From.** DESIGN 6; working-across W4, W14, W15; V4, V13, V14.
**Depends on.** E5, E9.
**Files.** `baton/services/brief.py`.
**Steps.** 1. Offline brief: first prompt, every pinned turn in full, the last N turns, files touched, and the path of the saved full history. 2. Agent brief: prompt template, run through `BackgroundRunner.ask(read_only=True)`. 3. Writer order: the destination tool, else the other tool, else offline; a tool at its limit or with no runner is skipped, with a note. 4. Kept-back turns never included for the other tool. 5. A brief always creates a new chat.
**Tests.** V4, V13, V14; `tests/unit/test_brief.py` for the fallback order.
**Done when.** Those pass with a fake runner that can be made to fail.

## E11. Keep, pin, pause, names

**Goal.** The small per-turn and per-link actions as services.
**From.** link-actions A1, A5; working-across W12 to W15; sync-status R14; V11, V12.
**Depends on.** E5.
**Files.** `baton/services/marks.py`, `baton/services/names.py`.
**Steps.** 1. keep / send after all / pin / unpin over the store. 2. `names(link)`: both names, read at every refresh. 3. `plan_rename(link, name, tools)`: per tool, `needs` from facts (OpenCode at once, Codex after relaunch, Claude and Cursor while closed).
**Tests.** V11, V12; `tests/unit/test_names.py`.
**Done when.** Those pass.

## E12. Notes

**Goal.** Every sentence the user sees, in one catalogue, chosen from a plan.
**From.** DESIGN 7a; more-tools "Notes the user always sees", G4a; the wording tables of all five specs.
**Depends on.** E2 (step `needs`), E6 to E11.
**Files.** `baton/notes/catalogue.py`, `baton/services/notes.py`.
**Steps.** 1. One entry per row of the notes table and of each spec's wording table: `id`, `tone`, template, buttons, status line. 2. `notes_for(plan, facts) -> [Note]`: always at least one note ("nothing unusual" when so). 3. `status_notes(link)`: the lines that stay until they no longer apply. 4. A test walks every catalogue id and fails if a template has an unfilled value or a tool name hard-coded outside a `{tool}` value.
**Tests.** `tests/unit/test_notes.py`: each row of the notes table produces its text for each tool it names; `tests/scenarios/*` assert note ids, not strings.
**Done when.** Every row of the notes table has an id and a test, and no service or adapter contains a user-facing sentence.

## E13. Setup check and relaunch as services

**Goal.** What is missing per tool with its fix; the safe relaunch order.
**From.** DESIGN 6, 7; link-actions A6; more-tools G7; T5, T6, X5.
**Depends on.** E3, E12.
**Files.** `baton/services/setup_check.py`, `baton/services/relaunch.py`.
**Steps.** 1. Setup: per tool, installed, format version known, hooks installed and approved, runner available and signed in; each finding has a note with its fix. 2. Relaunch plan: chats replying (named), steps close → write → reopen, `when_idle` variant that waits. 3. Never forces an app to quit; if it does not quit within a minute, nothing is written and the user is told.
**Tests.** T5, T6, X5; `tests/unit/test_relaunch.py` with a fake `AppControl`.
**Done when.** Those pass.

## R10. Separate storage and delivery responsibilities before CP2

**Goal.** Preserve the reviewed CP1 behavior while giving storage and delivery concerns separate modules.
**From.** Reviewer decision R10 in STATUS.md; ARCHITECTURE single responsibility and atomic completion rules.
**Depends on.** E5 and E6 reviewed at CP1.
**Files.** `baton/ledger/`, `baton/services/applier.py`, new preview/fingerprint and refresh modules under `baton/services/`, `tests/unit/` (preservation checks).
**Steps.** Separate links, turns, history and journal implementations behind the existing Ledger/RecordStore interface and one shared SQLite connection. Extract confirmation previews and chat refresh from Applier while retaining its existing entry points and ordering.
**Tests.** All existing engine tests; durable rollback and commit boundaries across the extracted concerns; unchanged public signatures and confirmation payloads.
**Done when.** Separate reviewer challenge and all orchestration checks pass, with no behavioral or dependency change.
