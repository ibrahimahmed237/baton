# C3 merge, undo and restore — Task M, 2026-10-14

Task M built merge choice reads and executable merge/undo/restore CLI previews and confirmations, then repaired D8/D9 against that output. All implementation stayed in the main repository; no state-changing Git command, real chat/tool data, native tool process or live script was used. Existing dirty files were preserved. Other builders continued changing their owned files during validation.

### Engine behaviour

- `merge --show` supports exact `--order`, `by_time`, `<side>_first`, `one_side_first --first T`, and the separate `dont_reorder` choice. Same-origin inversions and unknown presets refuse with the catalogue order explanation. The service supplies header, order help, per-side outcome, visibility, overlap, same-file and brief notes; the command adds actual read-service delivery notes for retained chats.
- Merge previews return `MergePlan.plan_id`, never `delivery.plan_id`. PlanBook stores that exact ID/request; confirmation loads the action guard, claims once, replans, verifies freshness/expiry, and invokes `Merger.apply`. Keep either side and Split execute the existing service choices. Unsupported held/app-closure plans disclose `plan.unavailable`; confirmation does not claim native closure support.
- Undo accepts the existing `--link L --to E` and additive `--event E` (link ownership inferred when absent). Restore accepts `--event E`. Both preview/confirm through `Undo`, with real cuts, shorter copies/link moves, and restore receipts. A no-cut preview explains the shorter linked chat before confirmation. Removals carry their destination `tool`, and `removal_groups` carry engine headings and rows per side. Undo of a merge-created chat can confirm a move back while leaving the created chat untouched. A replying side is disclosed on merge-undo previews too.
- History retains every raw kind/eligibility field and supplies rendered `label`, `undo_label`, `restore_label`, and `tool_label`. Unknown kinds use the neutral catalogue fallback. Empty history supplies `history.empty`; expected errors preserve catalogue notes.

### Fixtures and app repairs

D8/D9 recipes invoke the real command handlers on injected FakeAdapters in temporary roots, including confirmations. They no longer append explanatory notes or fabricate a delivery-plan identity/confirmation. The generator produced 375 fixtures. Added U3 refusal, U5 attachment receipt, U8 Keep receipt, U9 undo of a real merge, Split, large-copy brief offer, T8/T9/T10/T10b/T10c/T11, applied receipts, refreshed history, and empty/error history recipes. Historical all-kind inputs exercise presentation only; they do not pretend every input kind was executed.

MergeViewModel checks requested orders and preset identity/order before accepting a read projection; ActionReview checks that a returned merge preview matches order/preset/Keep/Split. Don't reorder survives a second preview. Engine-labelled Keep, Split and large-merge Brief alternatives are offered; merge-created chats have engine Open buttons with exact raw destinations. Merge decision controls use red; the Brief control uses the ordinary action colour. Completed merge history remains violet; Brief history uses neutral rather than the merge colour. History shows engine labels instead of raw kinds, engine Undo/Restore accessibility labels, per-side undo headings, and engine empty/error sentences. It sorts parsed instants and then descending IDs and reloads history after confirmed undo/restore. Every confirmation uses the immutable notes-display gate.

### Validation

- Focused engine action, service presentation, merge/undo scenario and read-command suites: **93 tests pass** (7 new contract tests, 1 new unit test).
- Fixture hand-edit gate: **26 tests pass**, all 375 generated files reproduce exactly.
- `app/scripts/check.sh`: **fully passes**, build, fixture gate, **165 UI + 21 kit = 186 app tests**.
- Mutation proof: replacing the display-gate predicate with `true` caused `mergeConfirmationNeedsExactDisplayAndReturnsAppliedReceiptWithOpenOffer` to fail with two issues (exit 1). The original predicate was restored and the full app check passed afterwards.
- Full engine discovery on the concurrent tree: **1,157 run; 1 failure and 2 errors**. These are outside ownership and were not edited: `tests.adapters.test_cursor.CursorSuite.test_facts_match_behaviour` and `tests.adapters.test_cursor_storage.CursorStorage.test_default_controls_cannot_start_replace_or_signal_any_process` raise `ChatReplying` in Cursor app-control; `tests.adapters.test_opencode_review.OpenCodeReviewTests.test_plugin_failure_attaches_nothing_and_logs_once_with_ms_timeout` expects `timeout: 5000` while the other builder's hook uses `timeout: 2000`.
- PNGs are generated for the expanded scenarios in both themes. Rendering is not a claim of native integration or human visual approval.

### Decisions where the plan was silent

The explicitly requested service fingerprint is also the confirmation ID for these three routes; storage/expiry/wrong-command checks still use PlanBook. Alias signatures preserve frozen command forms. Optional presentation fields are decoded locally in the owned screens, so BatonKit and unrelated app screens were not changed. Equal parsed instants use descending numeric IDs; malformed future timestamps sort at the oldest boundary. The D8/D9 manifest keeps existing provider categories for fixture-gate compatibility, with its callable naming the actual CLI handler.

### Proposed additive contract additions (CONTRACT.md was not edited)

1. `merge --show [--order ids | --preset P]`, `--preset one_side_first --first T`, and read `selected_preset`.
2. Merge Plan optional `order`, `preset`, `keep`, `split`, `mismatch_note` and operation-specific confirmation notes. Applied merge Open notes carry raw `tool_id`/`chat_id` alongside the rendered tool label.
3. Undo alias `--event E`, optional `--link` for that alias, removal `tool`, and `removal_groups: [{tool, category: added|written, heading: Note, removes: [...]}]`.
4. History optional top-level `notes` and per-event `label`, `undo_label`, `restore_label`, `tool_label`.

### Owed / open questions / not done

- **Always by time persistence is owed**: the existing settings command only implements `settings get`. The engine label is offered but disabled; no fake saved setting is claimed. A settings-set route is outside the named files and was not added.
- **Brief navigation/execution wiring is owed to the surrounding app/C3 brief route**: D8 offers an engine-labelled alternative and exposes `onBriefRequested(link, destination, exact order)` while invalidating merge consent. It does not send an unrelated, unordered brief command. The existing `Merger.plan_brief` remains the service entry point for ordered briefs.
- **Production Open execution is owed to the C3 open route**: D8 offers and dispatches the existing EngineClient open request with exact engine destinations, but this task did not implement the separately owned CLI open route or launch a real app.
- **Idle undo scheduling is C6 work**: the replying note offers When finished visibly, but the immediate gate blocks it; no pretend queue is reported.
- D12 window/menu routing and native live acceptance remain separate. The full engine suite needs the three owner fixes above before a whole-tree green claim.

### Shared-file edits (additive only)

Only `baton/notes/catalogue.py`: added `plan.confirm_undo`, `plan.confirm_merge`, `plan.confirm_keep`, `plan.confirm_split`, `merge.keep_choice`, `merge.split_choice`, `merge.brief_choice`, `merge.always`, `merge.open`, `merge.copy_relaunch`, `merge.copy_visible`, `merge.overlap`, `undo.group_added`, `undo.group_written`, `history.empty`, `history.undo_action`, `history.restore_action`. No existing catalogue entry was renamed, removed, reordered or reformatted. No ports/domain/tools/wiring edit belongs to this task.

### Exact source/report file list

- `baton/cli/commands/merge.py`
- `baton/cli/commands/undo.py`
- `baton/cli/commands/restore.py`
- `baton/cli/output.py`
- `baton/services/merger.py`
- `baton/services/undo.py`
- `baton/notes/catalogue.py`
- `tests/contract/test_action_commands.py`
- `tests/unit/test_action_presentation.py`
- `tests/contract/generate_fixtures.py`
- `tests/contract/fixture_manifest.py`
- `app/Sources/BatonUI/Screens/Merge/ActionReviewView.swift`
- `app/Sources/BatonUI/Screens/Merge/ActionReviewViewModel.swift`
- `app/Sources/BatonUI/Screens/Merge/MergeView.swift`
- `app/Sources/BatonUI/Screens/Merge/MergeViewModel.swift`
- `app/Sources/BatonUI/Screens/History/HistoryView.swift`
- `app/Sources/BatonUI/Screens/History/HistoryViewModel.swift`
- `app/Tests/BatonUITests/MergeHistoryTests.swift`
- `docs/plan/reports/C3-merge-undo-2026-10-14.md`
- `docs/plan/reports/D8-D9-2026-10-14.md`

### Exact regenerated fixture change list and why

Existing history samples/D3 states/history-event model changed because the engine now supplies presentation/action labels and empty notes. Existing merge-show samples changed because the real command now supplies service presentation. Every D8/D9 file below was generated from its actual command recipe (including earlier builder-created files regenerated to remove fabrication); added files cover the scenarios and applied/history receipts described above. No fixture was hand-edited. Other generated files were reproduced without a Git content change.

- `app/Fixtures/history-event.sample.json`
- `app/Fixtures/history.d3_empty.json`
- `app/Fixtures/history.d3_filled.json`
- `app/Fixtures/history.d3_tool_missing.json`
- `app/Fixtures/history.sample.json`
- `app/Fixtures/merge-show.no-shared.json`
- `app/Fixtures/merge-show.sample.json`
- `app/Fixtures/history.d9_all_kinds.json`
- `app/Fixtures/history.d9_empty.json`
- `app/Fixtures/history.d9_error.json`
- `app/Fixtures/history.d9_t10.json`
- `app/Fixtures/history.d9_t10c.json`
- `app/Fixtures/history.d9_t8.json`
- `app/Fixtures/history.d9_t9.json`
- `app/Fixtures/merge-show.d8_large.json`
- `app/Fixtures/merge-show.d8_split.json`
- `app/Fixtures/merge-show.d8_u1.json`
- `app/Fixtures/merge-show.d8_u2.json`
- `app/Fixtures/merge-show.d8_u3.json`
- `app/Fixtures/merge-show.d8_u4.json`
- `app/Fixtures/merge-show.d8_u5.json`
- `app/Fixtures/merge-show.d8_u6.json`
- `app/Fixtures/merge-show.d8_u7.json`
- `app/Fixtures/merge-show.d8_u8.json`
- `app/Fixtures/merge-show.d8_u9.json`
- `app/Fixtures/merge.d8_large.json`
- `app/Fixtures/merge.d8_split.json`
- `app/Fixtures/merge.d8_split_applied.json`
- `app/Fixtures/merge.d8_u1.json`
- `app/Fixtures/merge.d8_u1_applied.json`
- `app/Fixtures/merge.d8_u2.json`
- `app/Fixtures/merge.d8_u3.json`
- `app/Fixtures/merge.d8_u4.json`
- `app/Fixtures/merge.d8_u5.json`
- `app/Fixtures/merge.d8_u5_applied.json`
- `app/Fixtures/merge.d8_u6.json`
- `app/Fixtures/merge.d8_u7.json`
- `app/Fixtures/merge.d8_u8.json`
- `app/Fixtures/merge.d8_u8_applied.json`
- `app/Fixtures/merge.d8_u9.json`
- `app/Fixtures/restore.d9_cut.json`
- `app/Fixtures/restore.d9_shorter.json`
- `app/Fixtures/restore.d9_t10c.json`
- `app/Fixtures/restore.d9_t10c_applied.json`
- `app/Fixtures/restore.d9_t9.json`
- `app/Fixtures/restore.d9_t9_applied.json`
- `app/Fixtures/undo.d9_attached.json`
- `app/Fixtures/undo.d9_cut.json`
- `app/Fixtures/undo.d9_replying.json`
- `app/Fixtures/undo.d9_shorter.json`
- `app/Fixtures/undo.d9_t10.json`
- `app/Fixtures/undo.d9_t10_applied.json`
- `app/Fixtures/undo.d9_t10b.json`
- `app/Fixtures/undo.d9_t11.json`
- `app/Fixtures/undo.d9_t8.json`
- `app/Fixtures/undo.d9_t8_applied.json`
- `app/Fixtures/undo.d9_u9.json`

## Review round 2

Findings 2, 3 and 6 fixed.

- Applier and Merger re-read pause/removal and re-run write guards after journal preparation immediately before the native write. Regressions/reversals: `tests.unit.test_applier.ApplierTests.test_pause_or_guard_change_during_preparation_prevents_native_write` (pause, reply, changed content) and `tests.scenarios.test_merge.MergeScenarios.test_pause_or_guard_change_during_preparation_prevents_native_write` (pause, unknown format). Every injection makes zero native write calls.
- Undo refuses an already-paused link before preview/preparation and re-checks before preparation and again after preparation. Additive `LinkPaused(NotAvailable)` carries `undo.paused`; execution-time refusal also returns that note. Restore retains the documented paused path. Regression/reversal: `tests.scenarios.test_undo.UndoScenarios.test_paused_undo_refuses_before_prepare_and_after_prepare` covers both native cut and shorter-copy capabilities. Existing Restore tests remain green. Two lifecycle tests now explicitly resume between successive undos.
- Every successful merge receipt includes a catalogue completion sentence: Keep explains both sides, Split explains the independent chats, and a merge includes its order, created-chat Open receipts, retained-chat location and actual per-side delivery notes. Regression/reversal: `tests.contract.test_action_commands.ActionCommandsTests.test_every_merge_outcome_has_completion_receipt` covers Keep either side, Split, Don't reorder and by-time copies.

Exact source/test changes: `baton/services/applier.py`, `baton/services/merger.py`, `baton/services/undo.py`, `baton/domain/errors.py`, `baton/cli/commands/merge.py`, `baton/notes/catalogue.py`, `tests/unit/test_applier.py`, `tests/scenarios/test_merge.py`, `tests/scenarios/test_undo.py`, `tests/unit/test_brief_lifecycle.py`, `tests/contract/test_action_commands.py`, `docs/plan/reports/C3-merge-undo-2026-10-14.md`.

Shared additive edits only: `baton/domain/errors.py` adds `LinkPaused`; `baton/notes/catalogue.py` adds `undo.paused`, `merge.completed_split`, `merge.completed_keep`, `merge.completed`, `merge.completed_side`. No shared entry renamed/removed/reordered. No frozen contract edits; no additional JSON fields needed. Decision where silent: retain structured refusal as a `NotAvailable` subtype, with a specific catalogue sentence.

Eight generated fixtures changed, regenerated through the existing real-command generator to keep the required fixture gate truthful:

- `app/Fixtures/merge.d8_split_applied.json`, `app/Fixtures/merge.d8_u1_applied.json`, `app/Fixtures/merge.d8_u5_applied.json`, `app/Fixtures/merge.d8_u8_applied.json`: completion notes and delivery explanations on applied receipts.
- `app/Fixtures/history.d9_t8.json`, `app/Fixtures/history.d9_t9.json`, `app/Fixtures/history.d9_t10.json`, `app/Fixtures/history.d9_t10c.json`: Undo eligibility now reflects paused-link refusal after Undo/Restore. Restore eligibility remains supported.

No work remains for these findings. Settings persistence remains owed to its separate C3 route; the D8 report records hiding its unsupported control.

Validation for this round: full engine discovery **1,165 tests passed** (1,157 + 8 new tests); `app/scripts/check.sh` **passed: 187 app tests (166 UI + 21 kit), build and fixture gate green**, including the 26-test fixture gate. All seven fixes were reverse-checked: the corresponding new test fails with its fix removed, then passes with it restored. The app reversal compiled and failed with two assertions in `unavailableAlwaysByTimeIsHidden`. Git whitespace check passes. No state-changing Git command, live tool data, live script or real app control was used. Existing uncommitted work was preserved.
