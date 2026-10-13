# CP3 app carry-over — Task D — 2026-10-14

## Built

- H7: removed LinkDialogViewModel.markNotesDisplayed(). Link/copy and sync status now accept only didDisplay(receipt) for their exact current plan, revision and complete displayed notes. Views acknowledge mounted notes, rather than acknowledging during the confirmation click. Confirmation calls themselves refuse before display or after changes. Receipt view identity includes the actual wording, so changed notes remount even with a reused plan id/revision. Link result projection now preserves confirmation/stage fields.
- H8: sync status refuses relaunch confirmation, matching plan review's existing C5 boundary. Preview and Cancel remain available.
- H9: removed the unworded hand-off error card and its unlabeled close button. The existing engine error-note / plan.unavailable fallback remains the sentence path. If neither note exists, the view renders nothing and exposes no action. Unknown percentages show their supplied sentence without a meter. The brief-fallback fixture is asserted to disclose brief.used_offline and an offline writer.
- H10: FixtureEngine already throws when a requested state is absent on the starting tree; added a regression with a sample file present for both default-state and per-command-state selection. Optional per-link/tool fixture overrides retain their documented routing. WindowView now requires an injected ThemePreference; tests and fixture previews supply an in-memory preference. Render tests explicitly say that a person checks renders; the tests prove image production, not visual approval.
- H11: removed the app-built “Turn” sentence; the conversation heading presents only its engine sequence number. A worded heading needs engine support.
- H12: check.sh runs python3 -m unittest tests.contract.test_fixtures from the repo root before the Swift stages, and exits if it fails. A fake-python regression proves the working directory, exact command and failing exit propagation, without running Swift or real engine commands.
- Q9: link/copy and plan review share prose deduplication using note id, filled text and values. Presentation metadata differences do not repeat a sentence. Different values and side provenance survive; action provenance remains independent. Existing D5 fixtures exercise both reviews, with adversarial metadata/value/side cases.

## Validation

- Swift build and **155 app tests pass**: 134 BatonUI tests and 21 BatonKit tests (146 at the stated baseline).
- Full app/scripts/check.sh was run. First gate run: 26 fixture tests, one byte mismatch in brief.d7_brief_fallback.json. Final run while the other builders continued: 26 fixture tests, **112 failures** in test_tracked_fixtures_match_generated_bytes_exactly. The gate correctly stops before Swift. This task did not edit any fixture or engine file.
- To establish app acceptance despite that external gate failure, ran a temporary copy of check.sh with only the fixture-gate invocation omitted and app_dir fixed to this repo. It uses the same SDK probe, flags, build and test commands. Final log: /tmp/baton-task-d-swift.log. Full gate log: /tmp/baton-task-d-check.log.
- Engine suite was run during concurrent engine edits: **865 tests, 29 failures and 89 errors**. Failures/errors are outside this task's owned files, across Claude/Codex adapter tests, brief tests, fixture service proofs and temporary-data CP2 script tests. No repairs attempted. Log: /tmp/baton-task-d-engine.log. This count is an observation of an in-progress tree, not a replacement for the supplied 879-test baseline.
- git diff --check -- app passes.
- Added regressions reject incomplete/stale display receipts in all three view models; verify changed-note remount identity, refuse sync-status relaunch, preserve distinct note values/sides, omit the unknown meter by comparing rendered layout to the supplied sentence alone, render no unworded error screen, disclose fallback, refuse missing fixture states and propagate fixture-gate failure.
- No human visual approval is claimed. Existing render tests produce Light/Graphite PNGs for review.

## Decisions where the plan was silent

- Require appearance injection at WindowView's API boundary rather than relying on every caller to avoid its former .shared fallback. Production AppearanceWindowContent already supplies its preference; fixture previews now supply an in-memory one.
- Do not invent a fallback sentence or accessibility wording in Swift. A completely unworded hand-off failure has no actionable presentation until engine wording exists.
- Deduplicate prose independently from offered controls, so distinct side-bound actions keep their routing.
- Preserve optional scoped fixture selection; a missing requested state never falls back to sample. No FixtureEngine source edit was necessary.

## Needs engine / proposed contract additions / not done

1. **Needs engine:** an engine error note available when initial setup fails without an error note. Existing plan.unavailable works after successful setup; before that load, the app has no supplied wording. Propose a generated setup-failure error-envelope fixture with a nonempty catalogue note (new state; no existing fixture was hand-edited).
2. **Needs engine:** an engine-supplied close-button/accessibility label for an error presentation. None is available in the no-note path. The unlabeled icon-only button was removed; add the catalogue label and generated fixture before reintroducing it.
3. **Needs engine:** a turn-heading note keyed by turn id/sequence in status.notes, or an additive Turn label/note field. Existing status fixtures supply no heading label. The app uses number-only presentation until it exists. The engine owner should generate the relevant status fixtures when adding it.
4. No app/Fixtures file needs regeneration because of these app-only fixes. In particular, brief.d7_brief_fallback.json is consumed and asserted without edits. Its initial gate drift, and the final 112 byte mismatches, originate in the parallel engine work; the fixture owner must resolve them.
5. CONTRACT.md remains untouched. The only proposed additions are the engine notes/turn label above; confirmation remains the existing protocol. C5 relaunch execution and D12 production integration remain outside this task.
6. Final integrated engine/fixture validation remains open until the parallel builders finish. No commits, Git state-changing commands, worktrees, pushes, real chat access or real app control were performed.

## Exact files changed

- `app/Sources/BatonUI/Components/Components.swift`
- `app/Sources/BatonUI/Screens/HandOff/HandOffView.swift`
- `app/Sources/BatonUI/Screens/Link/LinkDialogView.swift`
- `app/Sources/BatonUI/Screens/Link/LinkDialogViewModel.swift`
- `app/Sources/BatonUI/Screens/PlanReview/PlanReviewViewModel.swift`
- `app/Sources/BatonUI/Screens/SyncStatus/SyncStatusView.swift`
- `app/Sources/BatonUI/Screens/SyncStatus/SyncStatusViewModel.swift`
- `app/Sources/BatonUI/Screens/Window/WindowPreviews.swift`
- `app/Sources/BatonUI/Screens/Window/WindowView.swift`
- `app/Tests/BatonKitTests/FixtureEngineTests.swift`
- `app/Tests/BatonUITests/ComponentTests.swift`
- `app/Tests/BatonUITests/EmptyStateTests.swift`
- `app/Tests/BatonUITests/HandOffTests.swift`
- `app/Tests/BatonUITests/LinkDialogTests.swift`
- `app/Tests/BatonUITests/PlanReviewTests.swift`
- `app/Tests/BatonUITests/SyncStatusTests.swift`
- `app/Tests/BatonUITests/WindowInteractionTests.swift`
- `app/Tests/BatonUITests/WindowTests.swift`
- `app/scripts/check.sh`
- `docs/plan/reports/CP3-carryover-app-2026-10-14.md`

No shared engine files were edited. Existing untracked docs/plan/reports/E9-E10.md was preserved. Other builders’ changes were left untouched.

## Review round 1

### Built

- A / H10: BatonMainWindowController requires a ThemePreference. The executable explicitly passes ThemePreference.shared; WindowInteractionTests supplies an in-memory instance, as do the other controller/window tests. Access to shared checks the test runner before initializing its private stored preference or reading UserDefaults.standard. The test helper asserts that the current test process is rejected, with regressions for SwiftPM's swiftpm-testing-helper and traditional xctest runners.
- B / Q9: displayedPlanNotes deduplicates the filled display sentence across plan notes, every step and confirmation, regardless of side or differing ids/values. The first occurrence supplies ordering and provenance. Step presentation excludes the same filled sentence already shown above it. The regression repeats a plan note in two steps and confirmation and asserts one sentence and no step copies.
- C: sameSentence now compares id, filled display text, values, tone and statusLine; buttons remain separate action metadata. When equal display text has different tones, the first occurrence retains its provenance and receives the strongest tone (danger > warning > info). Regression tests cover tone/status differences, distinct ids/values, action-only differences, escalation and preservation of an already stronger tone.
- D: the existing unworded HandOffView error remains empty and non-actionable; no Swift fallback sentence or unlabelled close affordance was introduced. Exact engine requirements are below.
- E: restored d7_setup_failed to the Light/Graphite render set. Its blank result gets a minimum test canvas so the empty view can be saved for review without introducing production UI. Restored explicit affordance assertions: no action labels, error note, target, retained chat, brief, request or pending review; beginReview cannot enable work and no generation/creation occurs.

### Validation

- Full app/scripts/check.sh **passes, exit 0**: 26 fixture-gate tests, Swift build, and **158 app tests** (137 BatonUI + 21 BatonKit; 155 before this round). Log: /tmp/baton-d-fix-check.log. Earlier runs passed the fixture gate and all behavior tests; the new runner guard test caught incomplete runner recognition, corrected using the reported swiftpm-testing-helper executable.
- git diff --check -- app/Sources app/Tests passes.
- No fixture changed or needs regeneration because of these app-only edits. The fixture gate checks all existing generated files, including brief.d7_brief_fallback.json.
- Render tests prove image production; human visual approval is not claimed.

### Decisions where the plan was silent

- Preserve the first sentence's identity, values, status line and controls as provenance, while escalating its tone in place when a later copy is stronger. Equal prose is still shown once even when ids or values differ; offered action routing remains sourced from the original plan independently of prose.
- Fail shared-preference access at the getter before lazy persistent initialization. Recognize both supported test runner forms so this applies to every test path, without relying on per-test hook installation order.
- Render the unworded setup failure on a minimal blank test canvas; the app continues to expose no unworded error affordance.

### Needs engine / proposed contract additions

- **Fallback error note id: handoff.error_unavailable.** Supply a nonempty catalogue error note in the setup/initial-load error envelope when no more specific note is available. The app cannot obtain plan.unavailable before setup succeeds. Wording needs the engine/spec owner; no wording was invented here.
- **Close label note id: handoff.close.** Supply a catalogue label and a close button with id close (including its accessibility wording) alongside the fallback error presentation. Reintroducing an error close affordance depends on these engine-owned words. Until then, the unworded path stays non-actionable.
- Propose documenting these optional error presentation notes additively in CONTRACT.md and generating a setup-failure error fixture when the engine implements them. CONTRACT.md and app/Fixtures were not edited.

### Open questions / not done

- Engine fallback/close wording and its generated fixture remain engine work. No full engine suite was run for this app-only review round; check.sh runs the required fixture gate.
- No Git state-changing command, worktree, app launch/control, real chat or tool-data access occurred. Existing edits by the other builders were preserved. No shared engine file was edited.

### Exact files changed in this review round

- app/Sources/Baton/BatonApp.swift
- app/Sources/BatonUI/Components/Components.swift
- app/Sources/BatonUI/Components/WindowPresentation.swift
- app/Sources/BatonUI/Theme/ThemePreference.swift
- app/Tests/BatonUITests/ComponentTests.swift
- app/Tests/BatonUITests/HandOffTests.swift
- app/Tests/BatonUITests/LinkDialogTests.swift
- app/Tests/BatonUITests/ThemePreferenceTests.swift
- app/Tests/BatonUITests/WindowInteractionTests.swift
- docs/plan/reports/CP3-carryover-app-2026-10-14.md

## Review round 2

Finding 3 fixed:

- `app/Sources/BatonUI/Screens/HandOff/HandOffView.swift:122`: hand-off uses `displayedPlanNotes` for both displayed writer/preview notes and step exclusion (`:137`). The combined list is partitioned between existing writer and preview positions, so step-only sentences are included once and stronger step tones remain visible. View-level regression: `HandOffTests.handOffPreviewDisplaysRepeatedStepSentenceOnceWithStrongestTone` (`app/Tests/BatonUITests/HandOffTests.swift:420`).
- `app/Sources/BatonUI/Screens/Popover/PopoverView.swift:94`: the preview displays the combined `displayedPlanNotes` list and excludes exactly that same list from the steps. View-level regression: `PopoverTests.popoverPreviewDisplaysRepeatedStepSentenceOnceWithStrongestTone` (`app/Tests/BatonUITests/PopoverTests.swift:182`). Both tests cover duplicate sentences on two steps, a stronger step sentence equal to a plan sentence, and a sentence present only on steps.
- `app/Sources/BatonUI/Components/Components.swift:139`: `sameSentence` now has a production caller inside plan de-duplication (`:150`). Exact note identity in `sameSentence` retains id, filled text, values, tone and status-line equality, independently of controls. For display de-duplication, two notes are the same sentence when their **filled display text** matches exactly, independent of those identities. Keep the first occurrence's identity/values/status/controls and elevate tone to the strongest duplicate, preserving the existing plan-level policy. Test: `ComponentTests.noteIdentityIncludesFilledTextToneAndStatusLine` (`app/Tests/BatonUITests/ComponentTests.swift:15`); existing `screenKeepsFirstSentenceAndStrongestToneAcrossBothSteps` also covers this policy.

Files changed this round: `app/Sources/BatonUI/Components/Components.swift`, `app/Sources/BatonUI/Screens/HandOff/HandOffView.swift`, `app/Sources/BatonUI/Screens/Popover/PopoverView.swift`, `app/Tests/BatonUITests/ComponentTests.swift`, `app/Tests/BatonUITests/HandOffTests.swift`, `app/Tests/BatonUITests/PopoverTests.swift`, and this report. No files added.

The initial app build obscured a `ContinueResult`/`Plan` type mismatch behind Swift's expression type-checking limit. The plan preview is a small view helper and explicitly projects the actual ContinueResult to a Plan, preserving notes, confirmation and stage. An interim identity change was caught by the existing link-dialog test; its stricter `sameSentence` semantics are preserved. Decision where the plan was silent: retain the established filled-text/strongest-tone policy across these screens. Proposed contract additions: none for this finding. Open questions/not done: earlier engine-owned fallback/close wording and live/native integration obligations remain outside this task.

Validation: full engine suite **1,041 tests pass** (`python3 -m unittest discover -s tests -t .`); **`app/scripts/check.sh` passes**: fixture gate **26 tests**, Swift build, and **160 Swift tests** (**139 UI + 21 kit/engine**). Engine log: `/tmp/baton-review2-engine.log`; app log: `/tmp/baton-review2-app.log`. The focused engine run passed 73 tests. Independent in-memory removals of every engine fix made its named regression fail (`/tmp/baton-review2-mutants.py`); repository sources were not reverted for these checks.

Generated app fixtures: **none change**. These fixes affect native adapters or presentation of existing notes, not fixture payloads; no fixture was regenerated. No shared engine file was edited; production wiring was inspected and covered by tests without changing it. No Git state-changing command, real chat access, real app/CLI operation, live script execution, or frozen spec/planning-page edit occurred.
