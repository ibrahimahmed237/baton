# Track D — the Mac app

SwiftUI, macOS menu-bar app plus a window. It shows what the engine returns and sends the user's choices back. It holds no rules: no sync logic, no per-tool behaviour, no sentences of its own. Built against [CONTRACT.md](CONTRACT.md) and the fixture files, so it does not wait for the engine.

Mockup: https://claude.ai/artifact/XCLxrptfHM5QAqWMoRdLjh. Each package names its board.

## Structure

```
app/Sources/Baton/             thin executable and scenes
app/Sources/BatonKit/          Engine/ and Models/
app/Sources/BatonUI/           Theme/, Components/, Screens/ (views and view models)
app/Tests/BatonKitTests/       existing engine/model tests
app/Tests/BatonUITests/        fixture view-model tests and ImageRenderer snapshots
app/Fixtures/                 hand-made through CP1; C2 generates later
app/Snapshots/                light/graphite PNGs for human review, git-ignored
```

Rules for this track:
- A view model takes an `EngineClient` and nothing else. Previews and tests use `FixtureEngine`.
- A view shows `Note.text`; it never builds a sentence. Buttons come from `Note.buttons`.
- Colour comes from `Theme` by meaning (state, tool, tone), never a literal in a view.
- Every destructive or unusual action goes through `ConfirmBar`, which stays disabled until its notes are on screen (more-tools G4a).
- Each screen has an ImageRenderer test in light and graphite for every fixture state below: assert a non-empty image and write its PNG to app/Snapshots/. View-model tests provide behavioural assertions. No third-party dependencies.
- D1 adds the BatonUI target and app/.gitignore entry for Snapshots/. D2–D4 add hand-made fixtures until C2.

---

## D0. Project, models, engine client

**Status.** Done 2026-10-05, commit `bc2e180`.

**Goal.** An app that launches, decodes every contract object, and can run either engine.
**From.** CONTRACT.md.
**Depends on.** CONTRACT.md frozen (CP0).
**Files.** `App/`, `Engine/`, `Models/`.
**As built.** A Swift package (`app/Package.swift`) with a library `BatonKit` and an executable `Baton`, so it builds and tests from the command line with `swift build` and `swift test`. An Xcode project is added in D13 for signing.
**Steps.** 1. Swift package, menu-bar extra plus window, no dock icon by default. 2. Codable models for Note, Chat, Side, Turn, Step, Plan and each command's result. 3. `EngineClient` with one async function per command. 4. `ProcessEngine` runs `baton … --json`, maps `error` objects to a Swift error carrying the note. 5. `FixtureEngine` loads `Fixtures/<command>.<state>.json`.
**Tests.** Decoding every fixture file.
**Done when.** The app starts and lists the fixture links.

## D1. Theme and components

**Goal.** The look, once.
**From.** DESIGN 7 (glass, light and Graphite, colour by meaning, tool identity colours).
**Board.** all.
**Files.** `app/Package.swift`, `app/.gitignore`, `app/Sources/BatonUI/Theme/`, `app/Sources/BatonUI/Components/`, `app/Tests/BatonUITests/`.
**Components.** NoteView, StateChip, ToolDot, TurnRow, MessageBubble, PlanSteps, ConfirmBar, MeterBar.
**Steps.** 1. Palette tokens for light and graphite; the glass material with the see-through setting. 2. `StateColour`: added green, attached and waiting amber, merged violet, link changes and main action blue, undo and conflict red. 3. `ToolColour`: Claude coral, Codex teal, OpenCode yellow, Cursor sky. 4. Components listed above, each with previews in both themes. 5. `NoteView` by tone; `PlanSteps` numbers steps and colours close red, write green, reopen blue.
**Tests.** Snapshot per component and theme.
**Done when.** Every component previews in both themes with no literal colour.

## D2. Menu-bar popover

**Files.** `app/Sources/BatonUI/Screens/Popover/`, `app/Sources/Baton/`, `app/Sources/BatonKit/Models/Results.swift` (optional engine notes, additive), `app/Sources/BatonUI/Components/Components.swift` (optional exclusion of duplicated plan notes), `app/Fixtures/`, `app/Tests/BatonUITests/`.

**Board.** Menu bar and window. **From.** DESIGN 7; sync-status R15, R16; G9.
**Shows.** One line per link: both tools' dots, name, headline note, state colour. Continue button for the selected link. "Link a recent chat" with the suggestion count. Icon badge when a link needs a decision.
**Fixture states.** no links; in sync; one side ahead; waiting; relaunch needed; decision needed; paused; setup incomplete.
**Done when.** All eight states snapshot correctly; Continue calls `continue` and shows its plan.

## D3. Window shell and chat lists

**Files.** `app/Sources/BatonUI/Screens/Window/`, `app/Sources/Baton/`, `app/Sources/BatonKit/Models/Shared.swift` (optional engine needs_attention, additive), `app/Fixtures/`, `app/Tests/BatonUITests/`.

**Board.** Menu bar and window. **From.** DESIGN 7; G2, G9.
**Shows.** Sidebar: Linked, Needs attention, Suggestions, All chats per tool (only installed tools), Activity. Detail area hosts the screens below.
**Fixture states.** each list empty and filled; a tool not installed.
**Done when.** Navigation works on fixtures; an uninstalled tool is not offered.

## D4. Sync status

**Files.** `app/Sources/BatonUI/Screens/SyncStatus/`, `app/Sources/BatonUI/Screens/Window/` (detail integration), `app/Sources/BatonUI/Screens/Popover/PopoverPreviews.swift` (supplementary fixture previews left uncommitted from D2), `app/Sources/BatonUI/Components/Components.swift` (engine-provided state labels), `app/Sources/BatonKit/Engine/EngineClient.swift` (pause/resume immediate-command flags), `app/Sources/BatonKit/Engine/FixtureEngine.swift` (additive per-link fixture routing), `app/Fixtures/`, `app/Tests/BatonUITests/`, `app/Tests/BatonKitTests/` (pause/resume transport regression).

**Board.** Sync status. **From.** sync-status R1 to R20; S1 to S12; W5 to W8; A1, A7.
**Shows.** Both names with tool dots and folder; a card per side (agent has, chat shows, attached, waiting and why, synced up to, "if you send here now", context meter, since-you-left line, setup line, notes with their buttons); the turn-by-turn strip; the conversation as messages with each turn's state per side; filter; pause, history, remove, copy, open chat.
**Fixture states.** S1 to S12, one fixture each; plus paused, side missing, hooks not ready, format unknown.
**Done when.** Each S fixture renders the sentence its spec row expects.

## D4b. Visual fidelity pass

**Goal.** D1 to D4 look like the mockup boards, not just contain the same information.
**From.** DESIGN 7 (glass, Graphite, colour by meaning); the mockup boards "Menu bar and window" and "Sync status"; reviewer findings F2 to F6 in STATUS.md.
**Depends on.** D4.
**Files.** `app/Sources/BatonUI/` (theme, components, the three screens), `app/Sources/Baton/BatonApp.swift` (native menu-bar scene integration), `app/Sources/BatonKit/Models/` (tool labels), `app/Fixtures/`, `app/Tests/BatonUITests/`; F2/F6 support also adds to `docs/plan/CONTRACT.md`, `baton/notes/catalogue.py`, and `tests/unit/test_notes.py` (no other engine behavior changes).
**Steps.** 1. Glass panels with the see-through setting; window with sidebar and detail as on the board. 2. Sync status: both names and tool dots in the header, the two app cards side by side, each with its sentences, meter with its sentence, since-you-left only where it applies, offer buttons in one row. 3. Turn strip and conversation under the cards, messages as bubbles with the app chip and state per side. 4. Tool display names from `tool_label`; times formatted by the system. 5. Popover as on the board: pair dots, name, headline, state colour.
**Tests.** View-model tests for F2, F3, F5, F6. PNGs for every state, light and Graphite.
**Done when.** Ibrahim has looked at the running app next to the mockup and says the three screens match. The PNGs are for the orchestrator's own check before asking him.

## D5. Link and copy dialogs

**Files.** `app/Sources/BatonUI/Screens/Link/`, `app/Sources/BatonUI/Screens/Window/` (dialog integration), `app/Sources/BatonKit/Engine/` (additive dialog transport and fixture routing), `app/Sources/BatonKit/Models/` (additive presentation fields), `app/Fixtures/`, `app/Tests/BatonUITests/`, `app/Tests/BatonKitTests/`; `baton/notes/catalogue.py` and `tests/unit/test_notes.py` for the specified dialog labels; additive `docs/plan/CONTRACT.md` for R9 and engine-supplied presentation. Orchestrator coordinates shared catalogue/contract edits.

**Board.** Link a chat. **From.** DESIGN 4 "Linking"; A0, A3, A4; G2, G4a, G5, G6; X1, X2.
**Shows.** Tool picker (installed tools; one not set up is shown with what is missing); the three ways with their tags; the "What will happen" block from the plan's notes; Create, Copy without linking, Cancel. Already-linked chat: the change-link note.
**Fixture states.** one per target tool; already linked; a way greyed out with its reason; large chat suggesting a brief.
**Done when.** Switching the tool swaps the notes with no text in the view.

## UI1. Window, navigation and scroll interaction audit

**Goal.** Repair the interaction defects Ibrahim reported on 2026-10-06, preserving the accepted glass appearance.
**From.** Ibrahim's UI review request; D3/D4/D5 existing screens. No feature spec is changed.
**Depends on.** D4b and D5 working-tree implementations.
**Files.** BatonApp.swift; WindowView/WindowViewModel; SyncStatusView/SyncStatusViewModel; LinkDialogView; PopoverView; Components/WindowPresentation.swift; WindowInteractionTests, PopoverTests, LinkDialogTests; plan status, this track and UI1 report.
**Steps.** Allow native resize/full screen and flexible content; make padded row areas clickable; retain selection on repeated navigation; bound long dialog/popover content and use native overlay scrolling; repair repeated turn jumps; independently challenge and validate.
**Tests.** Native fixture window controls, actual blank-row mouse events, repeat navigation/jump requests, full-size renders in both themes, native SwiftUI overlay attachment/overflow, scroll to end of long dialog. Mutation of click shapes must fail the click test.
**Done when.** These regression checks and the full engine/app checks pass, and the independent review has no blockers. Human confirmation of the actual full-screen transition and live visual appearance remains explicitly pending when desktop capture is unavailable. Broader polish stays tracked in the UI1 report and D13.

## UI2. Glass title bar

**Goal.** Blend native window chrome into the approved light/graphite app palette.
**From.** Ibrahim's title-bar request, 2026-10-06.
**Files.** BatonApp.swift; Components/WindowPresentation.swift; WindowView.swift; WindowInteractionTests.swift; plan status/track/report.
**Tests.** Native title-bar flags/colors/controls in both themes, theme-change attachment, hosted content at minimum size, existing click/resize tests and full app suite.
**Done when.** Native title bar uses the existing palette without losing controls or clipping body content, independent review and checks pass. Native CUA confirmed light chrome and actual full-screen entry; graphite is checked by native configuration tests.

## D6. What-will-happen and confirmation

**Board.** What will happen, per tool; Relaunch warning. **From.** more-tools notes table, G4a, G4b; A6; T5, T6.
**Shows.** `PlanSteps` and notes for any plan; the offers close-sync-reopen, sync now and relaunch later, attach instead; the replying warning naming chats, with "when idle".
**Fixture states.** each row of the notes table that has buttons.
**Done when.** No plan can be confirmed before its notes are shown.

## D7. Hand-off and limit offer

**Board.** Hand-off. **From.** DESIGN 6; W1 to W6; V1 to V6.
**Shows.** Limit banner with or without a reset time; both sides' fullness; full sync or brief; who writes the brief and why; preview.
**Fixture states.** linked and not linked; with and without reset time; with and without context size; brief fallback.
**Done when.** V1 to V6 fixtures render.

## D8. Merge

**Board.** Both chats have new turns. **From.** merge.md M1 to M12; U1 to U9.
**Shows.** Last shared turn; unsynced turns as messages with app and time; reorder by buttons and drag, refused moves explained; presets; live result per app; overlap and same-file warnings; keep one side, split; "always by time".
**Fixture states.** U1, U2, U4, U6, U7.
**Done when.** Reordering calls `merge --show` with the new order and redraws the outcome.

## D9. History and undo

**Board.** History; Undo in Claude; Undo in Codex. **From.** A8 to A10; T7 to T11; notes table (four undo rows).
**Shows.** Entries newest first, each with kind tag, colour bar and legend; undo and restore buttons. Undo dialog: turns grouped as "Baton added" and "written afterwards", those that exist only there called out, the turn it ends at, and the per-tool note (cut, or shorter chat).
**Fixture states.** history with every kind; undo for a cut-capable tool and a shorter-chat tool; undo while replying.
**Done when.** T7 to T11 fixtures render and the confirm button names the action and count.

## D10. Second opinion

**Board.** Second opinion. **From.** W9 to W11; V9, V10.
**Shows.** The turn, the question, token estimate, read-only note, the answer, add / copy / ask again / discard, and the cannot-run note.
**Fixture states.** before running; answer; cannot run (limit, command missing, signed out).
**Carry-over from CP0.** The contract gained `answer_id` on `ask` after the models were written; add it to the `ask` result type and its sample here. Also replace the `facts` dictionary in the setup models by a typed `Capabilities` now that its JSON is fixed.

## D11. Setup and settings

**Board.** Setup and settings. **From.** DESIGN 6, 7; G7; X5; CONTRACT settings table.
**Shows.** A card per tool with findings and their fix buttons; settings from the contract table; theme and see-through.
**Fixture states.** all ready; Codex not trusted; OpenCode command damaged; Cursor runner signed out; a tool not installed; unknown format version.

## D12. Wire to the real engine

**Goal.** Replace fixtures by `ProcessEngine` everywhere; refresh on a timer through `baton watch --once` and on window focus.
**Depends on.** CP3 (C1 to C5).
**Tests.** UI test on a temporary `BATON_HOME` with fake-adapter data.
**Done when.** Every screen works against the engine with the fake adapters.

## D13. Polish

Empty states, loading and error states for every screen, keyboard navigation, VoiceOver labels on chips and dots (state and tool names spoken), reduced-transparency setting honoured, notifications for offers.
**Done when.** Each screen has its empty, loading and error snapshot in both themes.

## UI3 — native full-screen routing

**Goal:** Correct Ibrahim’s reported normal window zoom and transition chrome churn.

**Files:** app/Sources/BatonUI/Components/WindowPresentation.swift; app/Tests/BatonUITests/WindowInteractionTests.swift; plan status/report records.

**Tests:** Both window paths receive fullScreenPrimary without conflicting auxiliary/none flags; repeated chrome updates do not mutate window geometry/styles; native fixture enter/exit full screen and sidebar click after transition.

**Done when:** Green control enters native full screen on the ordinary window, transitions preserve interaction, full regression/build gates pass and independent review completes.

UI3 continuation (Ibrahim, 2026-10-06): main window opens on Finder launch and reopen, with close/minimize/full-screen controls; menu icon remains. Scope also includes app/Sources/Baton/BatonApp.swift and a shared main-window controller in WindowPresentation.swift. A single window/model is reused, rather than separate review and ordinary windows. Tests cover native style/control presence and close/reopen identity.

UI3 accepted 2026-10-06: 377 engine/74 app/build pass with installed SDK flags; separate code review no blocker; ordinary fixture launch plus native full-screen/Escape/sidebar verified; Ibrahim confirms visible controls. Ctrl-Command-F wiring remains in keyboard polish, not claimed fixed.

## UI4 — orient the conversation timeline

**Goal.** Make it immediately clear which turn a message belongs to, which app produced it, what each app has received, where the reached boundary sits, and which folder a linked chat belongs to.

**From.** Ibrahim's 2026-10-06 report that the Attention conversation's messages and “has everything above this line” notes are difficult to interpret; sync-status R9, R10, R11 and R13.

**Files.** `app/Sources/BatonUI/Screens/SyncStatus/SyncStatusView.swift`; `app/Sources/BatonUI/Screens/Window/WindowView.swift`; `docs/plan/STATUS.md`; this track; `docs/plan/reports/UI4-2026-10-06.md`; `docs/plan/reports/patches/UI4.patch`.

**Steps.** Label each conversation card with its turn sequence, source app and time; group the per-app state with each app identity; place each existing reached note inside its reached turn card, directly below its messages, with an inset connector rail instead of a full-width divider. If filtering or folding hides that reached turn, show its note above the visible subset; suppress it when no turns remain visible. Show chat folders as compact path chips with middle truncation and the full path available on hover and to accessibility tools. Keep engine wording, ordering, filtering, folding, jump behavior, and the existing palette.

**Checks.** Challenge the diff against S1–S12 and R9–R13; run the repository's app build and tests; inspect the actual fixture rendering before closing visual acceptance. Do not infer the display copy from tool names or create user-facing sentences in the view.

**Done when.** Each visible card is self-identifying, both sides' state is adjacent to its tool identity, reached notes appear only when there are visible turns and their “above this line” wording matches their position, and folder paths read as intentional location labels. No message or state ordering changes.

## UI5 — signed identity and useful empty screens

**Goal.** Use Ibrahim's chosen burgundy/black handoff logo, including I.A in its compact form, to replace blank window/detail/list/conversation areas with relevant explanations.

**From.** Ibrahim's 2026-10-06 logo and empty-screen requests; he selected burgundy/black and asked for I.A in the compact logo.

**Depends on.** UI4, D3 and D4.

**Files.** `app/Brand/`; `app/Package.swift`; `app/Sources/Baton/BatonApp.swift`; BatonUI `Resources/Brand/`, `Components/BrandMark.swift`, `Components/EmptyStateView.swift`, WindowView/WindowViewModel, SyncStatusView/SyncStatusViewModel, PopoverView/PopoverViewModel; existing fixtures' notes; focused BatonUITests; `baton/notes/catalogue.py`; plan status, this track, UI5 report and package patch.

**Steps.** Generate the chosen signed icon without changing the handoff mark. Bundle the reviewed identity in BatonUI. Use catalogue-provided title/body notes for no item selected, no linked chats, no attention items, no suggestions/chats/activity, no conversation turns, and filters without matches. Use the appropriate existing navigation action where it is useful; never invent a data action. Show no empty-success claim while a model is loading or failed. Keep changes additive and preserve existing palette, sync rules and launch/window behavior.

**Tests.** Check empty-state selection against real fixture model data, loading/error versus empty success, and filtered conversation versus genuinely empty history. Render new components/states in both themes; run engine suite and app build/tests. Inspect the signed compact artwork and current fixture window.

**Done when.** Empty places explain their state and next step, with catalogue sentences only. Burgundy/black and I.A are present in the compact logo and app review; brand remains readable on graphite using its light backing. Build/tests and independent review pass. Menu-bar adoption of tiny signed artwork is not required by this package.

UI4/UI5 completion 2026-10-06: independent review findings fixed. Shared tree passes 377 engine tests, Swift build and 79 app tests with installed SDK26.5/TestingMacros flags. Signed compact asset and light/graphite renders inspected; current native fixture shows signed empty state and Show all turns restores messages. UI5 preserves the intentionally legacy fixture without presentation notes.

## UI6 — transparent logo and dark glass

**Goal.** Carry the signed burgundy/black mark into the menu bar and remove the baked-in white tile from current app logo placements.

**From.** Ibrahim's 2026-10-06 request for the changed menu icon, no white margins around B/I.A, and gray glass around the logo in dark mode.

**Files.** app/Brand asset and README; BatonUI/Resources/Brand asset; Components/BrandMark.swift and WindowPresentation.swift; Screens/Popover/PopoverView.swift; Theme/Theme.swift if needed; Sources/Baton/BatonApp.swift; focused BatonUITests; plan status/track/UI6 report/patch.

**Steps.** Extract transparent signed mark with imagegen, preserve handoff shape and I.A. Use the cutout directly in light mode and a restrained gray glass backing for graphite. Replace the menu's chain glyph with the same identity while retaining the decision badge. Keep icon colors readable on both surfaces; refresh only the already-authorized fixture bundle.

**Checks.** Confirm PNG alpha excludes the old white tile; inspect rendered brand and menu states in both themes, badge/no badge and reduced transparency. Run the repository engine/app gates and independent review.

**Done when.** Menu uses the signed mark, no baked-in white square remains in runtime logo placements, graphite uses gray glass and reduced-transparency fallback, and tests/build/review are green. I.A is retained but its tiny menu rendering is not claimed as comfortably readable.

UI6 completion 2026-10-06:377 engine /81 app tests and installed-SDK Swift build pass. Separate reviewer confirms accessibility injection/opaque pixels and stable initial root identity fixes. Native graphite fixture and light/graphite/menu/badge/reduced-transparency renders inspected. Direct menu-item capture was unavailable; signature remains tiny at menu size. Ready after UI5.
