# CP3 carry-over engine — Task A

Built on 2026-10-14, directly in the shared repository. No state-changing Git command, worktree, real chat/tool data, live script, real app or real CLI was used. The starting untracked `docs/plan/reports/E9-E10.md` and the other builders' changes were preserved.

## What was built

- **H4:** confirmation loads and compares the command before claiming its plan. A wrong command leaves the original confirmation available. The claimed record is still checked, single-use and fingerprinted.
- **H5:** CLI usage refusals now return rendered catalogue notes, with the existing `message` field carrying the same rendered text. Parser diagnostics become the catalogue's plain usage note; command-specific flag errors have their own notes. Internal errors already used `error.unexpected` and continue to hide private exception details. Argparse descriptions/help text stay in argparse, as Task A permits.
- **H6:** preview uses a non-spawning `ready()` probe on the native runners. It checks command presence only; sign-in/availability checks stay at generation time. Inert runners report unready. Legacy injected runners may expose an already-cached `finding`; without one their availability is resolved at generation. Preview never calls `available()` or `ask()`.
- **H13:** `BriefService` remains the public facade. Generation/creation/data now live in `brief_generation.py`, `brief_creation.py` and `brief_types.py`. Existing consent, privacy, cache, artifact, transaction and rollback behavior is retained. The facade keeps the UUID injection point and the original logging category, preserving deterministic fixtures and existing callers.
- **Q14:** Claude validates required message envelope keys/types (`uuid`, nullable/string `parentUuid`, `sessionId`, `type`, `timestamp`, nonempty `version`, boolean `isSidechain`, `message.role/content`) and the content blocks its reader/writer consume. Missing/malformed shape disables writes, including hidden sidebar targets. Known shapes remain writable on an untested release. Appending stamps the last message record's version from that chat; creation uses the observed format version. Codex keeps its column/type gate and additionally checks native envelopes, session metadata, message/function payloads and relevant event fields, including full target parsing before mutation. Known native environment messages without IDs remain accepted because the reader already handles those. CLI release lists provide disclosure evidence, never the permission to write.
- **New-release disclosure:** `FormatCheck.new_version` and `SideCondition.format_new_version` carry informational release evidence. Status includes the condition flag only when true. Setup adds the `format.new_version` catalogue note when a supported reported version is outside the checked list. The note says the version was not checked yet and Baton reads/writes it because the chat format is the same. These informational flags do not alter existing dataclass snapshot dictionaries or plan fingerprints.
- **Claude release:** after the owned idle process is released, both session and sidebar size/mtime must remain equal across two observations. Clock and sleep are injected, observations are 0.1 seconds apart, and settling is bounded to three seconds. Continued change or missing files refuses with `ChatChanged`. The existing ownership, busy-state and registry-release checks remain.
- **Rollback intents:** native adapter constructors accept `rollback_root`; directly constructed defaults are `<adapter root>/.baton/rollback/<tool>`. Wiring passes `<Baton store root>/rollback/<tool>` at construction, including to Codex's descendant recovery scanner. Intents remain private, fsynced and recoverable for prepared/uncommitted writes. Verified post receipts embed the complete intent manifest, so durable undo/restore no longer needs the intent file. Wiring removes intents only after the ledger has committed those exact receipts, on command completion and on startup; failed cleanup leaves the note for retry. Take-back removes its intent. Native `writer.verified(receipt)` is the explicit completion hook for non-CLI callers and must only be called after persisting the post receipt. Created Codex descendants can be recovered from durable committed receipts after their intent is cleared.
- **Exact rename restoration:** the existing native snapshots already retained Claude's original sidebar bytes and Codex's separate title/name columns. That precision is now retained in durable post receipts after cleanup, and `restore()` accepts rename receipts under a fresh reversible receipt. Tests cover backticks, different Codex title/name values, JSON serialization, restored writes and take-back. Codex still refuses native cut restoration.

The proposed journal.py scope extension was unnecessary: the completion hook is wired through the already-authorized wiring.py instead. journal.py was not changed.

## Files added

- `baton/services/brief_creation.py`
- `baton/services/brief_generation.py`
- `baton/services/brief_types.py`
- `tests/adapters/test_carryover_engine.py`
- `tests/unit/test_carryover_engine.py`
- `docs/plan/reports/CP3-carryover-engine-2026-10-14.md`

## Files changed

- `baton/cli/plans.py`
- `baton/cli/main.py`
- `baton/cli/output.py`
- `baton/cli/wiring.py`
- `baton/services/brief.py`
- `baton/adapters/claude/app.py`
- `baton/adapters/claude/runner.py`
- `baton/adapters/claude/state.py`
- `baton/adapters/claude/tool.py`
- `baton/adapters/claude/writer.py`
- `baton/adapters/codex/facts.py`
- `baton/adapters/codex/records.py`
- `baton/adapters/codex/runner.py`
- `baton/adapters/codex/scope.py`
- `baton/adapters/codex/state.py`
- `baton/adapters/codex/tool.py`
- `baton/adapters/codex/writer.py`
- `baton/domain/conditions.py`
- `baton/ports/tool.py`
- `baton/notes/catalogue.py`
- `tests/adapters/suite.py`
- `tests/adapters/test_claude.py`
- `tests/adapters/test_codex.py`
- `tests/unit/test_cli.py`

## Each shared-file edit

- `baton/notes/catalogue.py`: additive five-note update: `cli.usage`, `cli.unknown_command`, `cli.no_plan_flags`, `cli.conflicting_flags`, `format.new_version`. Existing definitions/ordering are unchanged.
- `baton/ports/tool.py`: additive `FormatCheck.new_version` constructor flag and initialization; existing serialized fields are unchanged.
- `baton/domain/conditions.py`: additive informational condition flag and initialization; existing serialized fields are unchanged. Concurrent adapters can also pass this flag.
- `baton/cli/wiring.py`: additive optional store-root argument/options at adapter construction, plus verified-intent cleanup under the command lock after durable receipt storage and at startup/close. No existing service routing or tool-specific branch was added.
- `tests/adapters/suite.py`: the facts assertion now accepts a known shape disclosed as a new version, rather than requiring every writable version to occur in the exact checked list. Existing write/read/capability checks remain.

## Validation

- Focused engine command: `python3 -m unittest tests.adapters.test_carryover_engine tests.unit.test_carryover_engine tests.unit.test_cli tests.unit.test_brief tests.unit.test_brief_lifecycle tests.adapters.test_claude tests.adapters.test_codex`: **329 tests pass**.
- `app/scripts/check.sh`: **passes**, including **26 contract fixture-gate tests**, the app build, **134 UI tests** and **21 engine-client tests** (155 app tests).
- Eight removal mutations were caught by regression tests: H4 command preservation, H5 catalogue usage notes, H6 no availability call at preview, Q14 same-shape release acceptance, native Claude version stamping, settle wait, post-commit intent cleanup, exact Codex title/name restoration. Each owned file was restored after the temporary mutation; no Git restore was used.
- `git diff --check`: passes.
- `python3 -m unittest discover -s tests -t .`: **988 tests run; six failure records**, all from the two wiring-sandbox methods described below (five root-injection subtest failures and one unavailable-adapter assertion). No Task A test failed. The outstanding failures belong to the unowned `tests/unit/test_wiring_sandbox.py`: its expectations still list only Claude/Codex and expect OpenCode/Cursor to be unavailable. The concurrent B3/B4 implementations make those assertions stale; Task A did not change that file.

## Generated app fixtures

**None require regeneration for Task A.** The fixture gate proves every existing tracked byte and two independent generation runs still match. Optional new-version fields/notes only appear on native observations of untested releases, outside the existing fixture recipes. Dataclass snapshot dictionaries, the facade UUID injection point, logging category and cached readiness handling preserve existing fixture fingerprints and fallback copy. `app/Fixtures` was not touched.

## Decisions where the plan was silent

- Release settling uses a 0.1-second interval and a three-second deadline for the settling phase; registry release retains its previous separate timeout.
- Shape checks allow additive keys and known non-message bookkeeping records. They validate the message/block types read or written, rather than pinning a release number. Claude image/document and thinking blocks remain readable shapes; Codex's non-message response types remain tolerated by its existing reader.
- New-release flags are informational and excluded from the existing snapshot dictionaries, avoiding unrelated confirmation/fixture changes.
- Intent deletion follows durable ledger completion, not merely the return from native publication. Deleting earlier would break recovery in the crash window before the ledger saves the post receipt. Direct adapter/service callers must persist the post receipt before calling `verified`; ordinary wired commands do this automatically.
- No migration of historical real-home rollback files was attempted; real tool data is outside this task's permission.

## Proposed contract additions (not applied to the frozen file)

- Optional `Side.condition.format_new_version: bool`, true for a known record shape from an untested release.
- Optional setup-tool `format_new_version: bool` and additive `new_version` finding with catalogue note `format.new_version`; existing `ready`/format support remain true when shape is supported.
- Usage errors may additionally contain `note: Note`; their existing `message` is the same rendered catalogue text.
- Internal adapter lifecycle: optional `ChatWriter.verified(receipt)` clears a crash intent only after its complete post receipt is durably committed; `restore` can restore an exact rename under a new receipt. This is an architecture/port clarification, not an app command rename.

## Open questions / not done

- The orchestrator must update/review the stale wiring-sandbox tests in their own scope and run the aggregate suite after B3/B4 settle.
- Native live proof of creation/cut/release remains the authorized CP3 live checkpoint's work. This task used temporary fixtures and fake controls only.
- No frozen specification, feature document, checkpoint/status/map/handoff page, generated fixture, app file, sibling adapter, commit, push or PR was changed by Task A.

## Review round 1

A-fix, 2026-10-14. Existing uncommitted builder work was read and preserved; no Git state-changing command, worktree, sibling adapter edit, or real chat/app access was used. All added native tests build temporary data and use fixture controls. This section supersedes the earlier permissive Codex subtype and legacy-intent decisions.

### Finding → change → test

1. **BLOCKER: Claude chained system/attachment envelopes were unchecked.** Every reader-chained type now requires `uuid`, `parentUuid`, `type`, `sessionId`, and `timestamp`, with their expected types; user/assistant records retain their stricter message checks. Unknown ancestors referenced by either `parentUuid` or compaction's `logicalParentUuid` refuse writing. Regression `test_every_chained_claude_record_requires_a_known_envelope` checks odd system/attachment leaves, each missing key, unknown ancestors, and a complete known system leaf. The shared Claude attachment test helper now supplies the required native envelope.
2. **Historical rollback receipts could not resolve.** Both writers accept exactly `<adapter root>/.baton-rollback/<token>.json` when reading a saved receipt for take-back/recovery or verified cleanup. Publication continues exclusively at the new rollback root. Legacy files and directories must remain inside the adapter root without symlinks; existing manifest ownership and stale-write checks remain. Regression `test_legacy_receipts_recover_both_prepared_and_completed_writes` covers both adapters and both receipt stages; `test_legacy_create_intents_recover_on_restart_and_clear_pending_journal` proves fresh-adapter create recovery, retry of an earlier failed journal entry, intent deletion, no pending entries, and no second recovery; `test_legacy_receipts_refuse_symlink_files_and_directories` covers both adapters' refusal paths.
3. **Machine factories silently defaulted to home-folder rollback.** Both `on_this_machine` factories now refuse missing or `None` `rollback_root` before selecting real controls. Direct constructors remain inert with explicitly injected roots and retain the test-root default; they never discover the real home. `test_real_machine_factories_require_explicit_rollback_root` checks both factories without invoking any selected process controls. Existing owned factory-selection tests now supply temporary rollback roots.
4. **Codex unknown subtypes inherited writing permission.** Removed both permissive subtype fallthroughs. Boundary subtypes `task_started`, `task_complete`, `turn_aborted`, and `item_completed` have specific checks; completed items explicitly accept the observed `UserMessage` and `AgentMessage`. Response messages and function calls/results retain specific validation, and the reader's known custom/tool-search calls/results have explicit payload checks. Non-boundary allow-lists are documented: events `token_count`, `user_message`, `agent_message`, `agent_reasoning`; response items `reasoning`. Unknown subtypes refuse writes while tolerant reads may skip them. `test_codex_unknown_subtypes_disable_writing_but_known_bookkeeping_does_not` and `test_codex_reader_tool_shapes_are_explicitly_accepted` cover this. Existing top-level `world_state`/`token_usage_record` evidence from the live report remains intact.
5. **Claude selected the first lexically sorted version.** Release components are compared as integers and the newest version is reported and stamped on both created and appended records. The new-version flag describes that reported release. `test_claude_format_version_and_created_records_use_numeric_newest` mixes `2.1.0`, `2.9.9`, and `2.10.1`, then checks state, append and create.
6. **The shared facts suite skipped checking new-version flags.** It now asserts `new_version == (version not in checked_versions)`. `test_shared_suite_rejects_an_incorrect_new_version_flag` injects a contradictory flag into the actual Claude suite and proves the assertion rejects it.
7. **H5 text classification.** Decision recorded: argparse help and command summaries are developer text; the app never requests/displays them, so they stay as written. App command/usage/refusal/crash stdout passes through JSON serializers and catalogue notes, with raw parser/crash prose excluded. Existing `UsageNotes` regressions and the CLI suite verify these boundaries; no help/summary copy was moved or changed in this round.
8. **Wrong-command confirmation said the chat changed.** `WrongPlanAction`, local to CLI planning, returns catalogue note `plan.wrong_action`: “This plan belongs to another action. Review a plan for this action before confirming.” The shown plan remains available to its owning action. `test_wrong_command_confirmation_has_its_own_catalogue_refusal` checks rendered stdout payload and preservation; the existing PlanBook command-preservation test now expects this refusal type.
9. **Symlinked explicit store roots made native writes refuse.** Wiring canonicalizes the store root before storage/adapters are built and canonicalizes a directly supplied `load_adapters` store root. Both native constructors resolve an injected rollback root once. Runtime intent checks still refuse later path substitution. `test_symlinked_store_root_and_rollback_root_support_writes` performs a real fixture rename through a symlinked temporary store and checks both constructors; the owned CLI root test now expects explicit alias resolution. Ledger/lock symlink and hardlink refusal tests remain.

### Exact files changed in this round

- `baton/adapters/claude/state.py`
- `baton/adapters/claude/tool.py`
- `baton/adapters/claude/writer.py`
- `baton/adapters/codex/records.py`
- `baton/adapters/codex/tool.py`
- `baton/adapters/codex/writer.py`
- `baton/cli/plans.py`
- `baton/cli/wiring.py`
- `baton/notes/catalogue.py`
- `tests/adapters/suite.py`
- `tests/adapters/test_claude.py`
- `tests/adapters/test_codex.py`
- `tests/adapters/test_carryover_engine.py`
- `tests/unit/test_cli.py`
- `tests/unit/test_carryover_engine.py`
- `docs/plan/reports/CP3-carryover-engine-2026-10-14.md`

No files were added this round. `main.py` and `output.py` were inspected and tested but not changed.

**Shared edits:** catalogue received only the additive `plan.wrong_action` note; wiring received only the two root-canonicalization statements. No shared file was reordered or reformatted; ports/domain were untouched.

### Validation and regression evidence

- Focused CLI/native/carry-over run: **280 tests pass** (`tests.adapters.test_carryover_engine`, `tests.unit.test_carryover_engine`, `tests.adapters.test_claude`, `tests.adapters.test_codex`, `tests.unit.test_cli`).
- The new regressions were first run before fixes and reproduced the returned failures. Nine separate removal mutations were subsequently caught: chain validation, numeric newest release, legacy Claude receipt, legacy Codex create recovery, machine rollback requirement, Codex subtype fallthrough, shared-suite flag assertion, wrong-action note, and store canonicalization. Each temporary owned-file mutation was restored immediately without Git.
- `git diff --check`: passes.
- `app/scripts/check.sh`: fixture gate **26 tests pass**, app builds, engine-client **21 tests pass**; UI run **137 tests, one failing issue** in unowned `ThemePreferenceTests.testProcessCannotReachStoredAppearance` (`sharedAccessPermitted` returned true). No app file was edited to fix it.

### Decisions, proposed additions, and remaining work

- Timestamp keys require strings, including empty timestamps used by synthetic fixture turns; native unknown field values still refuse where they affect the interpreted shape. Numeric release comparison accepts suffixes by extracting numeric components; release spelling breaks equal-component ties deterministically.
- Historical intents are resolved on demand from saved receipts rather than scanned, migrated, or rewritten. No legacy directory is created for new publication.
- Machine construction must provide rollback storage. Direct-root test construction stays inert and avoids home discovery. Existing unowned native-coordination/live-factory tests and live helper callers need explicit rollback roots in their owner's scope.
- Proposed additive contract/architecture clarification (not applied): wrong-action confirmations may return `wrong_plan_action` with `plan.wrong_action`, leaving the original plan claimable; explicitly supplied storage aliases are resolved once, while storage files and runtime substituted paths remain protected; machine adapter factories require an explicit Baton rollback root.
- **Generated app fixtures: none change or need regeneration.** The 26-test fixture gate passes; these native format/receipt observations and CLI PlanBook refusal are outside the fixture recipes. `app/Fixtures` was untouched.
- **Not done:** updates to unowned failing tests/helpers; app theme-gate repair; native live proof. No frozen specs or planning status/map/handoff/checkpoint pages changed.

**Final aggregate engine run:** `python3 -m unittest discover -s tests -t .` ran **1,036 tests**, with **six failure records and three errors**, all outside the assigned test files. Two errors in `tests/adapters/test_codex_coordination.py` still call `on_this_machine` without the now-required rollback root; one in `tests/unit/test_cp2_live.py` reaches the old `tools/live/cp2_live.py` factory with the same missing argument. Six failure records in `tests/unit/test_wiring_sandbox.py` expect every inert runner's note to be `setup.runner`, whereas a concurrent adapter returns `setup.runner_reinstall`. These callers/assertions were reported and left untouched as instructed. Test counts increased while other builders added tests; the final run above is the aggregate count, and the focused 280-test run is this round's owned acceptance evidence. No owned test failed.

## Review round 2

Findings 4 and 5 fixed; finding 2 covered for all adapters:

- `baton/adapters/claude/writer.py:83`, `:225`, `:251`: absent intent no longer falls back to embedded receipt data for restore or completed-write take-back. Refuses as `ChatChanged("receipt consumed")`, carrying existing catalogue note `write.chat_changed` instead of an internal bare ValueError. Prepared receipts with no publication remain a harmless recovery no-op.
- `baton/adapters/codex/writer.py:216`, `:469`: same absent-intent refusal for restore/completed-write take-back. Embedded manifests remain in durable receipts and are still available for failure reversal within the publishing call and verified created-identity bookkeeping, but cannot authorize a later native rollback alone.
- Both adapters' regression: `NativeCarryover.test_verified_or_missing_intents_refuse_take_back_and_restore_with_catalogue_note` (`tests/adapters/test_carryover_engine.py:380`). Covers both verified cleanup and externally missing intent, both operations, JSON-round-tripped receipts, catalogue note and unchanged native content. Earlier tests expecting successful restore/take-back after cleanup were corrected; exact rename restore remains covered with a live intent. `CodexSafety.test_a_consumed_receipt_cannot_be_used_twice` (`tests/adapters/test_codex.py:789`) now also checks the catalogue-backed refusal.
- `baton/adapters/codex/writer.py:218`: restore compares manifest token/chat id/kind against the receipt before preparing or publishing. Mismatch refuses with `ValueError("receipt mismatch")`; native row/log and intent set remain unchanged. Test: `NativeCarryover.test_codex_restore_refuses_each_manifest_identity_mismatch_without_mutation` (`tests/adapters/test_carryover_engine.py:399`), one subcase per identity field.
- Finding 2 coverage: `NativeCarryover.test_real_machine_factories_require_explicit_rollback_root` (`tests/adapters/test_carryover_engine.py:254`) now checks all four missing/None/provided root cases. `TheDefaultHome.test_the_default_home_selects_the_real_implementations_without_calling_them` (`tests/unit/test_wiring_sandbox.py:116`) verifies all four production roots. `baton/cli/wiring.py:217` was already correct and was not edited.

Files changed this round: `baton/adapters/claude/writer.py`, `baton/adapters/codex/writer.py`, `tests/adapters/test_carryover_engine.py`, `tests/adapters/test_codex.py`, `tests/unit/test_wiring_sandbox.py`, and this report. No files added; no shared implementation edit.

This section supersedes the earlier report's claim that an embedded receipt alone can restore a verified write after intent cleanup. Decision where the plan was silent: use existing `ChatChanged`/`write.chat_changed` to make consumed receipts an expected refusal with catalogue wording. Proposed contract additions: none. Open questions/not done: existing live obligations remain; redesigning durable undo after receipt cleanup is outside this six-finding task.

Validation: full engine suite **1,041 tests pass** (`python3 -m unittest discover -s tests -t .`); **`app/scripts/check.sh` passes**: fixture gate **26 tests**, Swift build, and **160 Swift tests** (**139 UI + 21 kit/engine**). Engine log: `/tmp/baton-review2-engine.log`; app log: `/tmp/baton-review2-app.log`. The focused engine run passed 73 tests. Independent in-memory removals of every engine fix made its named regression fail (`/tmp/baton-review2-mutants.py`); repository sources were not reverted for these checks.

Generated app fixtures: **none change**. These fixes affect native adapters or presentation of existing notes, not fixture payloads; no fixture was regenerated. No shared engine file was edited; production wiring was inspected and covered by tests without changing it. No Git state-changing command, real chat access, real app/CLI operation, live script execution, or frozen spec/planning-page edit occurred.
