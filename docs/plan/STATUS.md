# Status

The one place that says where the build stands. Kept current by the orchestrator ([ORCHESTRATOR.md](ORCHESTRATOR.md)); every entry is a fact that was checked, not a plan.

**Branch:** `chore/project-setup` · **Last checkpoint checked:** CP1, 2026-10-05 — approved by reviewer; findings F1–F6 and R10 precede CP2

## Reviewer notes — CP1, 2026-10-05

**CP1 approved by the reviewer (Claude), with findings F1 to F6 to be closed before CP2.** E5, E6 and D4 were staged from their patches and committed one by one: E5 `df091d0`, E6 `98fc038`, D4 `dcb698e`. The committed state alone, in a clean copy: 268 engine tests pass, `swift build` passes, 44 app tests pass. Layer and naming rules hold. The orchestrator must now remove the three "Ready to commit" entries, list them under Done, and make "Now" and "Next" true.

Findings:

- **F1. A decision was labelled as the reviewer's that the reviewer never saw.** Decision 8 (S9/S7 precedence) was written as "reviewer approved". It was the orchestrator's. The decision itself is sound and is **approved now**: a new completed turn on the destination after a bypass is a conflict; hold for the merge decision, redeliver after it. From here on every decision names who took it (ORCHESTRATOR.md, "Who decided what").
- **F2. The app shows tool ids, not names.** The sync status screen reads "claude", "codex". The engine must supply a display name and the app must show it. Add, in CONTRACT.md: `tool_label` next to every `tool` field in Chat, Side, Step and the setup tool object ("Claude", "Codex", "OpenCode", "Cursor"), and `{tool}` values in notes are filled with the label. Engine side in C2; app models and views now, with fixtures updated.
- **F3. The app shows raw timestamps** ("2026-10-05T10:02:00Z"). Times are formatted in the app with the system's date and time styles (today: time only; otherwise short date and time). Formatting a date is not building a sentence.
- **F4. The screens do not yet look like the mockup.** Sync status is a plain single column; the mockup has the glass panels, two side-by-side cards per app, the turn strip under them, the meter with its sentence, and the offer buttons together ("Relaunch … to show them", "Add them now", "Open chat"). New package **D4b, visual fidelity pass**, added to track-d-app.md: bring D1 to D4 to the mockup boards before D5 starts. Ibrahim looks at the result on screen; rendered PNGs alone do not close it.
- **F5. A fixture contradicts itself:** the side that is up to date also shows "Since you left: 2 turns, 2 files, 3 commands". Since-you-left appears only on the side that is behind (W7). Fix the fixture and add a view-model test.
- **F6. The offer for an idle open chat is incomplete:** the note offers "Close …, sync, reopen" only. Where the tool can release one idle chat and the setting is "on button", "Add them now" is offered next to it (sync-status R5). Catalogue and fixture.

Decisions (Reviewer):

- **R9. Full copy on demand and changing a link need their own routes** (your open question). Add to CONTRACT.md, additively, in C3: `baton link --link L --replace T --mode full_copy` (make a full copy for side T of an existing link and move the link to it; link-actions A4) and `baton relink --link L --to T[:ID] --keep T2` (which side of the old link stays). D5 gets both in the dialog.
- **R10. Module size.** `baton/ledger/sqlite_store.py` (544 lines) and `baton/services/applier.py` (429) are at the limit of "one reason to change". Before CP2, split the store by concern (links, turns, history, journal) behind the same `RecordStore`, and move the applier's fingerprint/preview code and its refresh code into their own modules. No behaviour change; the same tests pass.

## Now

- UI6 complete: menu renderer now uses the signed burgundy/black B and I.A; runtime marks have transparent margins in light mode and close-fitting gray glass in graphite. Window/popover/Dock follow system appearance, including native Reduce Transparency injection and Dock update notifications. Independent review findings fixed. Root377 engine / 81 app / Swift build pass; refreshed native fixture visibly shows graphite signed mark. Menu theme/badge renders inspected; direct system-menu capture timed out, so its actual on-screen item was not separately photographed. Ready-to-commit patch follows UI5; Git remains read-only.

- UI5 complete: Ibrahim's chosen burgundy/black compact logo includes I.A; branded empty/selection/filter states use catalogue wording and preserve loading/failure distinctions. Independent review's popover navigation-copy warning is fixed. Current shared tree: 377 engine / 79 app tests and Swift build pass with the installed SDK flags. Running fixture inspected; Show all turns restores messages. Ready-to-commit patch follows UI4, including binary assets; Git remains read-only.
- UI4 complete: reached notes sit beneath their own turn's messages. The hidden-turn fallback now joins the first visible card through an uninterrupted connector, and empty filters suppress it. Separate reviewer confirms its gap warning is resolved; the connector correction and shared verification are included in UI5. UI4 source patch remains the ordered predecessor to UI5.
- UI3 complete, independently reviewed and native fixture checked: ordinary launch opens the main window, standard controls work, native fullscreen entry/Escape exit and sidebar response pass. Ibrahim confirms the window and red/yellow/green controls are visible. Root 377 engine / 74 app / Swift build pass with installed SDK26.5 and TestingMacros command flags. Ready-to-commit patch follows E8; no real chats or Git writes.

- UI2 title-bar glass complete and independently reviewed. 71 app tests/build pass; isolated pre-E8 engine boundary remains 334 tests. Fixture relaunched successfully; CUA now captures it, native light title bar and full-screen entry verified. E8 is complete and independently reviewed in its fixture scope, with approved capability-based undo and additive recovery/store scope.

- UI1 interaction audit complete and independently reviewed: resize/full-screen controls, blank row click targets, repeated navigation/turn jumps, native overlay scrolling and long dialog/popover overflow are repaired. Final checks: 334 engine / 68 app tests and Swift build pass. Native fixture mouse/scroll tests pass; desktop capture failed, so the actual macOS full-screen transition and live appearance need human confirmation. See reports/UI1-2026-10-06.md.

- CP1 is approved; Ibrahim accepted retaining the existing glass style and instructed commit/continue. R10 and D4b are complete, separately reviewed and ready to commit.
- E7 merge and D5 link/copy dialogs are complete within their recorded scopes, after independent review and fixes. B1 native adapter implementation is independently reviewed and fixture-verified; its live acceptance remains pending and is not a completed checkpoint claim.
- Current working tree: 377 engine tests, 81 app tests and Swift build pass with installed SDK26.5/TestingMacros command flags, checked by root after independent UI6 review. Plain default Swift6.4/SDK27 commands have the separately recorded macro-loading environment failure. Git remains read-only; no commit or push. A sandbox escalation was used only for the previously authorized fixture-only app launch, never for Git or a real coding app. Ordered package patches reconstruct the reviewed files. This batch stops at a green implementation boundary.

## Next

UI5 signed branding/empty states and UI4 conversation orientation are complete at a green boundary. Review/commit the ordered patches through UI6, then continue E9/E10 and D6/D7, with B2/C1/C2 still pending. UI6 replaces the menu glyph with the signed mark. I.A is retained but tiny at 22 points; no claim of easy signature reading at menu size.

UI3 is complete after native checks and Ibrahim’s confirmation of visible controls. Its patch applies after E8; continue E9/D6. Ctrl-Command-F did not trigger exit; Escape did. Keyboard command wiring remains tracked for later polish. The earlier UI2 full-screen observation covered only the manual review window; ordinary routing was not verified. New Swift6.4/macOS27 default build/test macro resolution fails independently of this fix; the explicit installed SDK26.5/TestingMacros command flags pass.

The full app suite now passes with the installed SDK flags; UI4 is closed on the shared UI5 tree. Continue E9/E10 and D6/D7 in parallel as previously listed.

UI1/UI2 are ready to commit after CP2-record, in order. Rebuilt fixture chrome and actual full-screen entry were checked with CUA; Ibrahim may review its light glass appearance. Prioritize loading/error feedback and keyboard navigation before final app acceptance; details are in the UI1 report.

Continue E9/E10 (including M12), and D6/D7 in parallel; E8/U9 is now fixture-verified. B2 and C1/C2 remain; C2 must generate labels/notes/fixtures and dispatch remembered automatic merges after refresh. B1 needs a separately authorized live run after listing the exact throwaway writes and release/close/reopen actions. No real-app run is authorized by commit/continue.

## Done

| Package | Date | Commit | Tests after |
|---|---|---|---|
| E0 restructure into layers | 2026-10-05 | `d4d9153` | 70 engine |
| E1 ports and capabilities | 2026-10-05 | `cb11c88` | — |
| B0 fake tool and adapter suite | 2026-10-05 | `fcd3f41` | 129 engine |
| D0 app skeleton | 2026-10-05 | `bc2e180` | 15 app |
| E2 delivery by capabilities and CP1 notes | 2026-10-05 | `38a984a` — reviewer approved | 156 engine |
| D1 theme and components | 2026-10-05 | `94f161c` — reviewer approved | 18 app |
| D2 menu-bar popover | 2026-10-05 | `d214e44` — reviewer approved | 23 app |
| E3 journal and safety | 2026-10-05 | `43614c2` — reviewer approved | 178 engine |
| E4 turn mapping | 2026-10-05 | `5b41095` — reviewer approved | 188 engine |
| D3 window and lists | 2026-10-05 | `b5d5e5f` — reviewer approved | 29 app |
| D4 sync status | 2026-10-05 | `dcb698e` — reviewer approved | 44 app |
| E5 applier and refresh | 2026-10-05 | `df091d0` — reviewer approved | 236 engine |
| E6 linking and copying | 2026-10-05 | `98fc038` — reviewer approved | 268 engine |
| D4b glass layout and fixture launch | 2026-10-05 | Ready to commit — separate reviewer checked; Ibrahim accepted existing appearance | 270 engine / 49 app |
| R10 storage and delivery extraction | 2026-10-05 | Ready to commit — separate reviewer agent checked | 270 engine / 47 app |
| E7 merge implementation | 2026-10-05 | Ready to commit — separate reviewer checked; U9/E8 and M12/E9–E10 integrations pending | 295 engine / 49 app on its ordered patch boundary |
| D5 link/copy dialogs | 2026-10-05 | Ready to commit — separate reviewer checked | 295 engine / 60 app on its ordered patch boundary |
| UI6 transparent logo and dark glass | 2026-10-06 | Ready to commit — separate review fixes confirmed; native graphite preview inspected | 377 engine / 81 app |
| UI5 signed identity and empty states | 2026-10-06 | Ready to commit — independent review warning fixed; native fixture and both themes inspected | 377 engine / 79 app |
| UI4 conversation orientation | 2026-10-06 | Ready to commit — separate review; final connector correction included in UI5 | Shared UI5 tree: 377 engine / 79 app |
| UI3 normal launch and native window controls | 2026-10-06 | Ready to commit — independent review, native checks, Ibrahim confirms visible controls | 377 engine / 74 app with installed SDK flags |
| E8 undo and restore | 2026-10-06 | Ready to commit — independent review blockers fixed; fixtures only | 377 engine / 71 app |
| UI2 glass title bar | 2026-10-06 | Ready to commit — separate reviewer checked; native title bar/full-screen observed | 334 engine at isolated boundary / 71 app |
| UI1 window/navigation/scroll fixes | 2026-10-06 | Ready to commit — independent reviewer found no remaining blockers; desktop verification limits recorded | 334 engine / 68 app |

## Ready to commit

Historical CP1 patches have been committed; do not reapply them.

### R10 — storage and delivery responsibilities

Patch: `docs/plan/reports/patches/R10.patch`, applies to HEAD `4546808`.

Exact paths:

- `baton/ledger/sqlite_store.py`
- `baton/ledger/schema.py`
- `baton/ledger/history.py`
- `baton/ledger/journal.py`
- `baton/ledger/links.py`
- `baton/ledger/records.py`
- `baton/ledger/turns.py`
- `baton/services/applier.py`
- `baton/services/delivery_plan.py`
- `baton/services/observations.py`
- `baton/services/preview.py`
- `baton/services/refresh.py`
- `tests/unit/test_ports.py`
- `tests/unit/test_store_atomicity.py`
- `docs/plan/ARCHITECTURE.md`
- `docs/plan/track-e-core.md`

Message:

```text
Keep storage and delivery changes separate

Links, turns, history and recovery need distinct ownership without losing atomic completion. Share one SQLite connection behind the existing store interface and separate preview and refresh logic while preserving confirmation payloads and recovery behavior.
```

### D4b — glass layout and fixture launch

Patch: `docs/plan/reports/patches/D4b.patch`, applies after R10 on HEAD `4546808`. Independently reviewed; Ibrahim accepted the retained appearance and instructed commit/continue. Ordinary menu/window routing is not newly verified by that acceptance.

Exact paths:

- `app/Fixtures/ask-add.sample.json`
- `app/Fixtures/brief.sample.json`
- `app/Fixtures/chat.sample.json`
- `app/Fixtures/chats.d3_filled.json`
- `app/Fixtures/chats.d3_tool_missing.json`
- `app/Fixtures/chats.sample.json`
- `app/Fixtures/continue.d2_decision_needed.json`
- `app/Fixtures/continue.d2_paused.json`
- `app/Fixtures/continue.d2_relaunch_needed.json`
- `app/Fixtures/continue.d2_setup_incomplete.json`
- `app/Fixtures/continue.d2_waiting.json`
- `app/Fixtures/continue.sample.json`
- `app/Fixtures/copy.d4_actions.json`
- `app/Fixtures/copy.sample.json`
- `app/Fixtures/link-summary.sample.json`
- `app/Fixtures/link.sample.json`
- `app/Fixtures/links.d2_decision_needed.json`
- `app/Fixtures/links.d2_in_sync.json`
- `app/Fixtures/links.d2_no_links.json`
- `app/Fixtures/links.d2_one_side_ahead.json`
- `app/Fixtures/links.d2_paused.json`
- `app/Fixtures/links.d2_relaunch_needed.json`
- `app/Fixtures/links.d2_setup_incomplete.json`
- `app/Fixtures/links.d2_waiting.json`
- `app/Fixtures/links.d3_empty.json`
- `app/Fixtures/links.d3_filled.json`
- `app/Fixtures/links.d3_tool_missing.json`
- `app/Fixtures/links.sample.json`
- `app/Fixtures/merge.sample.json`
- `app/Fixtures/plan.sample.json`
- `app/Fixtures/plan.unlinked.json`
- `app/Fixtures/relaunch.d4_actions.json`
- `app/Fixtures/relaunch.sample.json`
- `app/Fixtures/relink.sample.json`
- `app/Fixtures/rename.sample.json`
- `app/Fixtures/restore.sample.json`
- `app/Fixtures/setup-install.sample.json`
- `app/Fixtures/setup-tool.sample.json`
- `app/Fixtures/setup.d3_empty.json`
- `app/Fixtures/setup.d3_filled.json`
- `app/Fixtures/setup.d3_tool_missing.json`
- `app/Fixtures/setup.sample.json`
- `app/Fixtures/side.empty.json`
- `app/Fixtures/side.sample.json`
- `app/Fixtures/status.d3_filled.json`
- `app/Fixtures/status.d3_filled_3.json`
- `app/Fixtures/status.d3_filled_4.json`
- `app/Fixtures/status.d3_filled_5.json`
- `app/Fixtures/status.d4_hooks.json`
- `app/Fixtures/status.d4_missing.json`
- `app/Fixtures/status.d4_paused.json`
- `app/Fixtures/status.d4_s1.json`
- `app/Fixtures/status.d4_s10.json`
- `app/Fixtures/status.d4_s11.json`
- `app/Fixtures/status.d4_s12.json`
- `app/Fixtures/status.d4_s2.json`
- `app/Fixtures/status.d4_s3.json`
- `app/Fixtures/status.d4_s4.json`
- `app/Fixtures/status.d4_s4b.json`
- `app/Fixtures/status.d4_s5.json`
- `app/Fixtures/status.d4_s6.json`
- `app/Fixtures/status.d4_s7.json`
- `app/Fixtures/status.d4_s8.json`
- `app/Fixtures/status.d4_s9.json`
- `app/Fixtures/status.d4_unknown.json`
- `app/Fixtures/status.sample.json`
- `app/Fixtures/step.sample.json`
- `app/Fixtures/suggestion.sample.json`
- `app/Fixtures/suggestions.d2_decision_needed.json`
- `app/Fixtures/suggestions.d2_in_sync.json`
- `app/Fixtures/suggestions.d2_one_side_ahead.json`
- `app/Fixtures/suggestions.d2_paused.json`
- `app/Fixtures/suggestions.d2_relaunch_needed.json`
- `app/Fixtures/suggestions.d2_setup_incomplete.json`
- `app/Fixtures/suggestions.d2_waiting.json`
- `app/Fixtures/suggestions.d3_filled.json`
- `app/Fixtures/suggestions.d3_tool_missing.json`
- `app/Fixtures/suggestions.sample.json`
- `app/Fixtures/sync.d4_actions.json`
- `app/Fixtures/sync.sample.json`
- `app/Fixtures/undo.empty.json`
- `app/Fixtures/undo.sample.json`
- `app/Fixtures/unlink.d4_actions.json`
- `app/Fixtures/unlink.sample.json`
- `app/Sources/BatonKit/Models/Shared.swift`
- `app/Sources/BatonUI/Components/ComponentPreviews.swift`
- `app/Sources/BatonUI/Components/Components.swift`
- `app/Sources/BatonUI/Components/DisplayTime.swift`
- `app/Sources/BatonUI/Screens/Popover/PopoverView.swift`
- `app/Sources/BatonUI/Screens/Popover/PopoverViewModel.swift`
- `app/Sources/BatonUI/Screens/SyncStatus/SyncStatusView.swift`
- `app/Sources/BatonUI/Screens/SyncStatus/SyncStatusViewModel.swift`
- `app/Sources/BatonUI/Screens/Window/WindowView.swift`
- `app/Sources/BatonUI/Screens/Window/WindowViewModel.swift`
- `app/Sources/BatonUI/Theme/Theme.swift`
- `app/Tests/BatonUITests/ComponentTests.swift`
- `app/Tests/BatonUITests/SyncStatusTests.swift`
- `app/Tests/BatonUITests/WindowTests.swift`
- `baton/notes/catalogue.py`
- `tests/unit/test_notes.py`
- `docs/plan/CONTRACT.md`
- `docs/plan/track-c-cli-hooks.md`
- `docs/plan/track-d-app.md`
- `app/Sources/Baton/BatonApp.swift`

Message:

```text
Make Baton match the glass mockup

Show supplied app names, local times and waiting-side offers together with both chats and their conversation. Keep fixture launch and menu rendering reviewable, while retaining the existing glass appearance Ibrahim chose.
```

### E7 — independently accepted implementation

Patch: `docs/plan/reports/patches/E7.patch`, applies after D4b.

Exact paths:

- `baton/services/merger.py`
- `baton/services/planner.py`
- `baton/services/status.py`
- `baton/services/preview.py`
- `baton/services/applier.py`
- `baton/ports/store.py`
- `baton/ledger/links.py`
- `baton/adapters/fake/tool.py`
- `tests/scenarios/test_merge.py`
- `baton/notes/catalogue.py`
- `docs/plan/track-e-core.md`
- `docs/plan/ARCHITECTURE.md`

Message:

```text
Merge without rewriting either chat

Preserve each app's own turn order and commit the chosen merge as one recoverable operation. Record exact pending attachments and visibility evidence so a merge stays truthful until delivery or a new conflict.
```

### D5 — independently accepted implementation

Patch: `docs/plan/reports/patches/D5.patch`, applies after E7.

Exact paths:

- `app/Sources/BatonKit/Engine/EngineClient.swift`
- `app/Sources/BatonKit/Engine/FixtureEngine.swift`
- `app/Sources/BatonKit/Models/Shared.swift`
- `app/Sources/BatonKit/Models/Results.swift`
- `app/Sources/BatonKit/Models/LinkDialog.swift`
- `app/Sources/BatonUI/Screens/Window/WindowView.swift`
- `app/Sources/BatonUI/Screens/Window/WindowViewModel.swift`
- `app/Sources/BatonUI/Screens/Link/LinkDialogView.swift`
- `app/Sources/BatonUI/Screens/Link/LinkDialogViewModel.swift`
- `app/Tests/BatonUITests/LinkDialogTests.swift`
- `app/Fixtures/chat.d5_already.json`
- `app/Fixtures/chat.d5_claude.json`
- `app/Fixtures/chat.d5_codex.json`
- `app/Fixtures/chat.d5_cursor.json`
- `app/Fixtures/chat.d5_large.json`
- `app/Fixtures/chat.d5_opencode.json`
- `app/Fixtures/chat.d5_unavailable.json`
- `app/Fixtures/chats.d5_already.json`
- `app/Fixtures/chats.d5_claude.json`
- `app/Fixtures/chats.d5_codex.json`
- `app/Fixtures/chats.d5_cursor.json`
- `app/Fixtures/chats.d5_large.json`
- `app/Fixtures/chats.d5_opencode.json`
- `app/Fixtures/chats.d5_unavailable.json`
- `app/Fixtures/copy.d5_already_opencode.json`
- `app/Fixtures/copy.d5_claude_claude.json`
- `app/Fixtures/copy.d5_codex_codex.json`
- `app/Fixtures/copy.d5_cursor_cursor.json`
- `app/Fixtures/copy.d5_large_codex.json`
- `app/Fixtures/copy.d5_opencode_claude.json`
- `app/Fixtures/copy.d5_opencode_codex.json`
- `app/Fixtures/copy.d5_opencode_cursor.json`
- `app/Fixtures/copy.d5_opencode_opencode.json`
- `app/Fixtures/copy.d5_unavailable_opencode.json`
- `app/Fixtures/link.d5_already.json`
- `app/Fixtures/link.d5_already_opencode.json`
- `app/Fixtures/link.d5_already_opencode_attached_history.json`
- `app/Fixtures/link.d5_already_opencode_brief.json`
- `app/Fixtures/link.d5_already_replace_opencode.json`
- `app/Fixtures/link.d5_claude.json`
- `app/Fixtures/link.d5_claude_claude.json`
- `app/Fixtures/link.d5_claude_claude_attached_history.json`
- `app/Fixtures/link.d5_claude_claude_brief.json`
- `app/Fixtures/link.d5_claude_replace_claude.json`
- `app/Fixtures/link.d5_codex.json`
- `app/Fixtures/link.d5_codex_codex.json`
- `app/Fixtures/link.d5_codex_codex_attached_history.json`
- `app/Fixtures/link.d5_codex_codex_brief.json`
- `app/Fixtures/link.d5_codex_replace_codex.json`
- `app/Fixtures/link.d5_cursor.json`
- `app/Fixtures/link.d5_cursor_cursor.json`
- `app/Fixtures/link.d5_cursor_cursor_attached_history.json`
- `app/Fixtures/link.d5_cursor_cursor_brief.json`
- `app/Fixtures/link.d5_cursor_replace_cursor.json`
- `app/Fixtures/link.d5_large.json`
- `app/Fixtures/link.d5_large_codex.json`
- `app/Fixtures/link.d5_large_codex_attached_history.json`
- `app/Fixtures/link.d5_large_codex_brief.json`
- `app/Fixtures/link.d5_large_replace_codex.json`
- `app/Fixtures/link.d5_opencode.json`
- `app/Fixtures/link.d5_opencode_claude.json`
- `app/Fixtures/link.d5_opencode_claude_attached_history.json`
- `app/Fixtures/link.d5_opencode_claude_brief.json`
- `app/Fixtures/link.d5_opencode_codex.json`
- `app/Fixtures/link.d5_opencode_codex_attached_history.json`
- `app/Fixtures/link.d5_opencode_codex_brief.json`
- `app/Fixtures/link.d5_opencode_cursor.json`
- `app/Fixtures/link.d5_opencode_cursor_attached_history.json`
- `app/Fixtures/link.d5_opencode_cursor_brief.json`
- `app/Fixtures/link.d5_opencode_opencode.json`
- `app/Fixtures/link.d5_opencode_opencode_attached_history.json`
- `app/Fixtures/link.d5_opencode_opencode_brief.json`
- `app/Fixtures/link.d5_opencode_replace_claude.json`
- `app/Fixtures/link.d5_opencode_replace_codex.json`
- `app/Fixtures/link.d5_opencode_replace_cursor.json`
- `app/Fixtures/link.d5_opencode_replace_opencode.json`
- `app/Fixtures/link.d5_unavailable.json`
- `app/Fixtures/link.d5_unavailable_opencode.json`
- `app/Fixtures/link.d5_unavailable_opencode_attached_history.json`
- `app/Fixtures/link.d5_unavailable_opencode_brief.json`
- `app/Fixtures/link.d5_unavailable_replace_opencode.json`
- `app/Fixtures/links.d5_already.json`
- `app/Fixtures/links.d5_claude.json`
- `app/Fixtures/links.d5_codex.json`
- `app/Fixtures/links.d5_cursor.json`
- `app/Fixtures/links.d5_large.json`
- `app/Fixtures/links.d5_opencode.json`
- `app/Fixtures/links.d5_unavailable.json`
- `app/Fixtures/relink.d5_already_opencode.json`
- `app/Fixtures/relink.d5_already_opencode_attached_history.json`
- `app/Fixtures/relink.d5_already_opencode_brief.json`
- `app/Fixtures/relink.d5_claude_claude.json`
- `app/Fixtures/relink.d5_claude_claude_attached_history.json`
- `app/Fixtures/relink.d5_claude_claude_brief.json`
- `app/Fixtures/relink.d5_codex_codex.json`
- `app/Fixtures/relink.d5_codex_codex_attached_history.json`
- `app/Fixtures/relink.d5_codex_codex_brief.json`
- `app/Fixtures/relink.d5_cursor_cursor.json`
- `app/Fixtures/relink.d5_cursor_cursor_attached_history.json`
- `app/Fixtures/relink.d5_cursor_cursor_brief.json`
- `app/Fixtures/relink.d5_large_codex.json`
- `app/Fixtures/relink.d5_large_codex_attached_history.json`
- `app/Fixtures/relink.d5_large_codex_brief.json`
- `app/Fixtures/relink.d5_opencode_claude.json`
- `app/Fixtures/relink.d5_opencode_claude_attached_history.json`
- `app/Fixtures/relink.d5_opencode_claude_brief.json`
- `app/Fixtures/relink.d5_opencode_codex.json`
- `app/Fixtures/relink.d5_opencode_codex_attached_history.json`
- `app/Fixtures/relink.d5_opencode_codex_brief.json`
- `app/Fixtures/relink.d5_opencode_cursor.json`
- `app/Fixtures/relink.d5_opencode_cursor_attached_history.json`
- `app/Fixtures/relink.d5_opencode_cursor_brief.json`
- `app/Fixtures/relink.d5_opencode_opencode.json`
- `app/Fixtures/relink.d5_opencode_opencode_attached_history.json`
- `app/Fixtures/relink.d5_opencode_opencode_brief.json`
- `app/Fixtures/relink.d5_unavailable_opencode.json`
- `app/Fixtures/relink.d5_unavailable_opencode_attached_history.json`
- `app/Fixtures/relink.d5_unavailable_opencode_brief.json`
- `app/Fixtures/setup.d5_already.json`
- `app/Fixtures/setup.d5_claude.json`
- `app/Fixtures/setup.d5_codex.json`
- `app/Fixtures/setup.d5_cursor.json`
- `app/Fixtures/setup.d5_large.json`
- `app/Fixtures/setup.d5_opencode.json`
- `app/Fixtures/setup.d5_unavailable.json`
- `app/Fixtures/link.d5_already_replace_codex.json`
- `baton/notes/catalogue.py`
- `docs/plan/CONTRACT.md`
- `docs/plan/track-d-app.md`
- `docs/plan/track-c-cli-hooks.md`

Message:

```text
Explain link and copy choices before creating chats

Show engine-provided tool eligibility and the exact destination plan before confirmation. Preserve existing command calls while adding explicit retained-side, selected-mode and full-copy replacement routes.
```

### B1 — native fixture implementation; live acceptance pending

Patch: `docs/plan/reports/patches/B1.patch`, applies after D5.

This is a commit-ready implementation boundary, not a claim that B1’s real-app Done-when condition or CP2 has passed. No live run was performed.

Exact paths:

- `baton/adapters/claude/facts.py`
- `baton/adapters/claude/runner.py`
- `baton/adapters/claude/hooks.py`
- `baton/adapters/claude/__init__.py`
- `baton/adapters/claude/locator.py`
- `baton/adapters/claude/reader.py`
- `baton/adapters/claude/app.py`
- `baton/adapters/claude/writer.py`
- `baton/adapters/claude/tool.py`
- `baton/adapters/claude/state.py`
- `tests/adapters/test_claude.py`
- `tests/fixtures/claude/__init__.py`
- `tests/fixtures/claude/build.py`
- `tests/adapters/suite.py`
- `tests/adapters/test_fake.py`
- `baton/services/mapping.py`
- `tests/unit/test_mapping.py`
- `baton/notes/catalogue.py`
- `docs/plan/track-b-adapters.md`
- `docs/plan/ARCHITECTURE.md`

Message:

```text
Guard native chat writes with durable rollback receipts

Implement the measured native sidebar and chat shapes behind the shared ports. Keep unknown formats, active holders and outside edits protected, while allowing interrupted publication to recover from persisted receipts; live acceptance remains separately gated.
```

### Coordination records — after the five package commits

Keep the following handoff records in a separate documentation commit; they record the accepted boundaries, remaining gates and reusable patches. `CP2-record.patch` applies after B1 and carries these records; it is a generated transport artifact and does not include itself.

Exact paths:

- `docs/plan/STATUS.md`
- `docs/plan/CHECKPOINTS.md`
- `docs/plan/reports/CP1-2026-10-05.md`
- `docs/plan/reports/CP1-findings-2026-10-05.md`
- `docs/plan/reports/CP2-2026-10-05.md`
- `docs/plan/reports/patches/R10.patch`
- `docs/plan/reports/patches/D4b.patch`
- `docs/plan/reports/patches/E7.patch`
- `docs/plan/reports/patches/D5.patch`
- `docs/plan/reports/patches/B1.patch`

Message:

```text
Keep the next Baton handoff reproducible

Record accepted package boundaries, exact commit paths and check output so work can resume without guessing. Preserve pending live checks and incomplete CP2 requirements alongside the ordered patches.
```

### UI1 — window and interaction fixes

Patch: `docs/plan/reports/patches/UI1.patch`, applies after R10 → D4b → E7 → D5 → B1 → CP2-record. Git is protected; no commit or push was attempted.

Exact paths:
- `app/Sources/Baton/BatonApp.swift`
- `app/Sources/BatonUI/Screens/Window/WindowView.swift`
- `app/Sources/BatonUI/Screens/Window/WindowViewModel.swift`
- `app/Sources/BatonUI/Screens/SyncStatus/SyncStatusView.swift`
- `app/Sources/BatonUI/Screens/Link/LinkDialogView.swift`
- `app/Sources/BatonUI/Screens/Popover/PopoverView.swift`
- `app/Sources/BatonUI/Components/WindowPresentation.swift`
- `app/Tests/BatonUITests/WindowInteractionTests.swift`
- `app/Tests/BatonUITests/PopoverTests.swift`
- `app/Tests/BatonUITests/LinkDialogTests.swift`
- `app/Sources/BatonUI/Screens/SyncStatus/SyncStatusViewModel.swift`
- `docs/plan/STATUS.md`
- `docs/plan/track-d-app.md`
- `docs/plan/reports/UI1-2026-10-06.md`

Commit message:

```text
fix(app): make window navigation and scrolling respond reliably

The fixture window and fixed content size prevented expansion. Padded rows missed clicks, repeated navigation erased selection, and long content could hide actions. Restore native window controls, full-row hits and accessible overlay scrolling without replacing the glass style.
```

### UI2 — glass title bar

Patch: `docs/plan/reports/patches/UI2.patch`, applies after UI1. Exact paths:

- `app/Sources/Baton/BatonApp.swift`
- `app/Sources/BatonUI/Components/WindowPresentation.swift`
- `app/Sources/BatonUI/Screens/Window/WindowView.swift`
- `app/Tests/BatonUITests/WindowInteractionTests.swift`
- `docs/plan/STATUS.md`
- `docs/plan/track-d-app.md`
- `docs/plan/reports/UI2-2026-10-06.md`

Commit message:

```text
fix(app): blend the title bar into the glass window

The separate system title bar broke the approved glass palette. Extend the backdrop behind transparent native chrome while preserving window controls and content safe areas.
```

### E8 — recoverable undo and restore

Patch: `docs/plan/reports/patches/E8.patch`, applies after UI2. Exact paths:

- `baton/ledger/sqlite_store.py`
- `baton/ledger/undo.py`
- `baton/notes/catalogue.py`
- `baton/ports/store.py`
- `baton/ports/tool.py`
- `baton/services/preview.py`
- `baton/services/observations.py`
- `baton/services/applier.py`
- `baton/services/refresh.py`
- `baton/services/linker.py`
- `baton/services/undo.py`
- `baton/services/status.py`
- `baton/services/merger.py`
- `baton/adapters/claude/writer.py`
- `baton/adapters/fake/tool.py`
- `tests/adapters/suite.py`
- `tests/adapters/test_claude.py`
- `tests/scenarios/test_undo.py`
- `docs/plan/STATUS.md`
- `docs/plan/ARCHITECTURE.md`
- `docs/plan/track-e-core.md`
- `docs/plan/CHECKPOINTS.md`
- `docs/plan/reports/E8-2026-10-06.md`
- `docs/plan/reports/CP2-2026-10-05.md`

Commit message:

```text
feat(core): keep undo recoverable across chat changes

Users need to return to a history point without losing messages or trusting stale previews. Journal cuts and exact restorations, create shorter copies where cutting is unsafe, and atomically pause and move the link after verification.
```

### UI3 — normal launch and native window controls

Patch: `docs/plan/reports/patches/UI3.patch`, applies after E8. Separate reviewer found no code blocker; native checks and Ibrahim’s visible-control confirmation passed. Ready to commit. Exact paths:

- `app/Sources/Baton/BatonApp.swift`
- `app/Sources/BatonUI/Components/WindowPresentation.swift`
- `app/Tests/BatonUITests/WindowInteractionTests.swift`
- `docs/plan/STATUS.md`
- `docs/plan/track-d-app.md`
- `docs/plan/reports/UI3-2026-10-06.md`

Commit message:

```text
fix(app): open the main window with native controls

Normal launch only exposed the menu icon, while separate window paths had different full-screen behavior. Reuse one retained window on launch and reopen, keep native controls, and avoid redundant chrome changes during updates.
```

### UI4 — conversation orientation

Patch: `docs/plan/reports/patches/UI4.patch`, applies after UI3. The final connector correction and shared test-gate report updates are in the succeeding UI5 patch.

Exact paths:

- `app/Sources/BatonUI/Screens/SyncStatus/SyncStatusView.swift`
- `app/Sources/BatonUI/Screens/Window/WindowView.swift`
- `docs/plan/STATUS.md`
- `docs/plan/track-d-app.md`
- `docs/plan/reports/UI4-2026-10-06.md`

Message:

```text
Make conversation ownership and sync boundaries clear

Identify each turn and keep received-history notes next to the messages they describe so people can understand what each agent has. Present linked folders as readable locations and preserve filtering and turn order.
```

### UI5 — signed identity and useful empty screens

Patch: `docs/plan/reports/patches/UI5.patch`, applies after UI4 on the recorded ordered patch chain. Includes PNG assets. Independent reviewer found no remaining warnings after fixes; root377/79/build pass.

Exact paths:

- `app/Package.swift`
- `app/Sources/Baton/BatonApp.swift`
- `app/Sources/BatonUI/Components/BrandMark.swift`
- `app/Sources/BatonUI/Components/EmptyStateView.swift`
- `app/Sources/BatonUI/Screens/Window/WindowView.swift`
- `app/Sources/BatonUI/Screens/Window/WindowViewModel.swift`
- `app/Sources/BatonUI/Screens/SyncStatus/SyncStatusView.swift`
- `app/Sources/BatonUI/Screens/SyncStatus/SyncStatusViewModel.swift`
- `app/Sources/BatonUI/Screens/Popover/PopoverView.swift`
- `app/Sources/BatonUI/Screens/Popover/PopoverViewModel.swift`
- `app/Tests/BatonUITests/EmptyStateTests.swift`
- `baton/notes/catalogue.py`
- `docs/plan/STATUS.md`
- `docs/plan/track-d-app.md`
- `docs/plan/reports/UI5-2026-10-06.md`
- `app/Brand/README.md`
- `app/Fixtures/links.d2_decision_needed.json`
- `app/Fixtures/links.d2_in_sync.json`
- `app/Fixtures/links.d2_no_links.json`
- `app/Fixtures/links.d2_one_side_ahead.json`
- `app/Fixtures/links.d2_paused.json`
- `app/Fixtures/links.d2_relaunch_needed.json`
- `app/Fixtures/links.d2_setup_incomplete.json`
- `app/Fixtures/links.d2_waiting.json`
- `app/Fixtures/links.d3_empty.json`
- `app/Fixtures/links.d3_filled.json`
- `app/Fixtures/links.d3_tool_missing.json`
- `app/Fixtures/links.d5_already.json`
- `app/Fixtures/links.d5_claude.json`
- `app/Fixtures/links.d5_codex.json`
- `app/Fixtures/links.d5_cursor.json`
- `app/Fixtures/links.d5_large.json`
- `app/Fixtures/links.d5_opencode.json`
- `app/Fixtures/links.d5_unavailable.json`
- `app/Fixtures/links.empty.json`
- `app/Fixtures/status.d3_filled.json`
- `app/Fixtures/status.d3_filled_3.json`
- `app/Fixtures/status.d3_filled_4.json`
- `app/Fixtures/status.d3_filled_5.json`
- `app/Fixtures/status.d4_hooks.json`
- `app/Fixtures/status.d4_missing.json`
- `app/Fixtures/status.d4_paused.json`
- `app/Fixtures/status.d4_s1.json`
- `app/Fixtures/status.d4_s10.json`
- `app/Fixtures/status.d4_s11.json`
- `app/Fixtures/status.d4_s12.json`
- `app/Fixtures/status.d4_s2.json`
- `app/Fixtures/status.d4_s3.json`
- `app/Fixtures/status.d4_s4.json`
- `app/Fixtures/status.d4_s4b.json`
- `app/Fixtures/status.d4_s5.json`
- `app/Fixtures/status.d4_s6.json`
- `app/Fixtures/status.d4_s7.json`
- `app/Fixtures/status.d4_s8.json`
- `app/Fixtures/status.d4_s9.json`
- `app/Fixtures/status.d4_unknown.json`
- `app/Fixtures/status.sample.json`
- `docs/plan/reports/UI4-2026-10-06.md`
- `app/Brand/baton-icon-burgundy-black-signed.png`
- `app/Brand/baton-logo-burgundy-black-v4.png`
- `app/Brand/baton-logo-burgundy-v3.png`
- `app/Brand/baton-logo-concept-v1.png`
- `app/Brand/baton-logo-palettes-v2.png`
- `app/Brand/baton-logo-review-v1.png`
- `app/Sources/BatonUI/Resources/Brand/baton-icon.png`

Message:

```text
Give Baton a signed identity and explain empty views

Use the chosen burgundy and black handoff mark with I.A in the compact icon. Explain empty lists, selection and filters with catalogue wording, while keeping loading and failed reads distinct from successful empty results.
```

### UI6 — transparent logo and dark glass

Patch: `docs/plan/reports/patches/UI6.patch`, applies after UI5, including two new PNG assets. Separate reviewer found no remaining actionable findings after fixes; root377/81/build pass.

Exact paths:

- `app/Brand/README.md`
- `app/Sources/BatonUI/Components/BrandMark.swift`
- `app/Sources/BatonUI/Components/WindowPresentation.swift`
- `app/Sources/BatonUI/Screens/Popover/PopoverView.swift`
- `app/Sources/Baton/BatonApp.swift`
- `app/Tests/BatonUITests/ComponentTests.swift`
- `app/Tests/BatonUITests/BrandTests.swift`
- `docs/plan/STATUS.md`
- `docs/plan/track-d-app.md`
- `docs/plan/reports/UI6-2026-10-06.md`
- `app/Brand/baton-mark-transparent.png`
- `app/Sources/BatonUI/Resources/Brand/baton-mark.png`

Message:

```text
Carry the signed mark across both app appearances

Replace the menu glyph and white tile with the transparent Baton identity. Keep black and I.A readable on gray glass in dark mode, preserve the decision badge, and respect system appearance and reduced transparency.
```

## Decisions

27. **Ibrahim (2026-10-06):** normal app launch should open the window directly, and the upper-left native close/minimize/full-screen controls must be available. UI3 expands to executable routing and one shared native controller; normal activation supplies the Dock/reopen path while retaining the menu icon. Protected feature/design docs were not edited.

Decisions 1–7: Reviewer, 2026-10-05. Decision 8 has its own provenance below.

1. **Unknown format (E2):** never write. An open chat with ready hooks attaches; otherwise hold with `format_unknown`. Test both.
2. **Visibility (E2/E5):** add `SideCondition.app_started_at: str = ""`. `added` becomes `shown` immediately for AT_ONCE; for AFTER_RELAUNCH only when app start is after delivery; for ON_REOPEN_CHAT on a later app start or explicit user `mark_shown`. A prompt hook is never evidence of reopening. Keep the status instruction until shown.
3. **Release (E3/E5):** separate `check_release` from `check_write`. Check release, release, wait at most 10 seconds for closed state, recheck write, then add. Release/wait failure falls back to attach and records why; never write before the recheck passes.
4. **App (D1–D4):** Swift package, new `BatonUI` library at `app/Sources/BatonUI/`, thin `Baton` executable, no third-party dependencies. ImageRenderer tests render every listed fixture state in light/graphite, assert non-empty images, and write PNGs to git-ignored `app/Snapshots/`. View-model tests assert behaviour. CP1 fixtures are hand-made in `app/Fixtures/`; C2 generates them later.
5. **Scope (E3/E6):** E3 may add journal schema and extend SQLite store and RecordStore additively. Tests follow ARCHITECTURE's table. E6 brief mode raises NotAvailable, tested, until E10. Orchestrator may update docs/plan/ including reports; frozen contract only grows. Workers never commit; reviewer commits exact ready-to-commit entries.
6. **Notes (E2/E4):** create `baton/notes/catalogue.py` in E2 with all CP1 notes (id, tone, template, buttons, status line) from protected feature wording tables. E4 marker lives there. No user-facing sentence elsewhere; E12 completes/audits later.

7. **Pre-write rollback receipt (E3, reviewer approved on resume):** add ChatWriter.prepare(chat_id | None, kind) -> WriteReceipt. Journal.begin persists it before mutation; commit stores the post-write receipt. Startup recovery takes back all begun/uncommitted entries using the pre-write receipt. Implement in fake and shared adapter suite. Create preparation records that no chat exists yet.

8. **S9/S7 precedence (E5; Orchestrator, approved by reviewer afterwards):** a new completed destination turn creates a conflict with the bypassed waiting turn. Hold for S7 and redeliver after merge; S9 automatic redelivery applies when no competing completed turn exists. E7 supplies the merge implementation.

9. **R9 (Reviewer):** C3 adds full-copy replacement of one existing linked side and explicit retained-side relinking routes; D5 exposes both. Additive command details are recorded in the reviewer notes above.
10. **R10 (Reviewer):** separate SQLite links, turns, history and journal concerns behind the existing RecordStore; extract applier preview/fingerprints and refresh. Preserve behavior and atomic transactions before CP2.
11. **D4b test scope (Orchestrator; separate reviewer agent checked, Ibrahim accepted afterwards):** include `app/Tests/BatonUITests/` in D4b's file list, because its existing acceptance conditions explicitly require view-model and snapshot tests.

12. **Fixture review diagnostics (Ibrahim, 2026-10-05):** approved launching the exact `/private/tmp/BatonFixture.app` bundle outside the shell sandbox, then approved a temporary Baton label to locate the menu entry. Orchestrator added `--review-window` to open the existing fixture window; `--review-label` adds the approved diagnostic label only when requested. Neither authorizes real-tool access or settings/permission changes, nor proves the ordinary menu-bar path. The separate reviewer checked these launch changes.

13. **Style exploration (Ibrahim, 2026-10-05):** rejected the present appearance and chose exploration of a different direction. Orchestrator prepares two fixture-only studies, a quiet native inspector and a focused Graphite workspace (these directions are the orchestrator’s proposals, not approved designs). Subsequent decision 14 closes this exploration without adopting a new reference.

14. **Retain existing style (Ibrahim, 2026-10-05):** after seeing both alternative studies, chose to leave the current style. No A/B proposal is applied; the existing glass design and mockup remain the visual reference. This settles the style choice, without claiming unverified runtime behavior.

15. **D4b acceptance (Ibrahim, 2026-10-05):** after choosing to retain the existing style, instructed “commit and let's continue”. Orchestrator records the appearance gate accepted and proceeds with CP2. This does not authorize real-app runs or imply additional runtime verification.

16. **E7 scope/dependency correction (Orchestrator, not yet reviewed):** atomic merge completion extends the store additively and exact approved decisions must survive attachment until a new conflicting turn appears. E7 proves U1–U8 plus recoverable history; E8 runs U9. M12 offer integrates E9/E10. This makes implementation dependencies explicit without relaxing the CP2 scenarios.
17. **D5 presentation (Orchestrator, not yet reviewed):** setup supplies optional notes and per-tool mode eligibility; Chat may supply its current link id. The UI shows engine choices, never infers tool rules. Catalogue is extended with the existing feature wording and specified dialog labels; C2 will generate it. R9 signatures are recorded additively before their app transport is used.

18. **Relink mode (Ibrahim, 2026-10-05):** approved optional --mode full_copy|attached_history|brief with full_copy default on R9 retained-side relink. D5 sends it; C3 implements it. Existing signatures are preserved.

19. **Rollback suite (Ibrahim, 2026-10-05):** approved reverse-order rollback and refusal when later outside writes changed a chat. Shared adapter suite no longer requires removing an earlier append beneath a later one; the fake retains its extra out-of-order capability test. Real adapter tests must verify stale receipts refuse without mutation.

20. **Native adapter boundaries (Orchestrator; separate reviewer checked):** native rollback publication uses fsynced intent plus atomic file replacement, preserving existing log bytes. Hidden targets participate in format checks; missing project directories do not prevent rollback. Exact process/session ownership is required before release. C4 must provide native stdin-to-stable-ID hook entrypoints; until then default hooks report not ready.
21. **Review fixes (Orchestrator; separate reviewers checked):** merge history carries per-write visibility evidence; paused split changes metadata only; a broken creation reservation records actual recovery evidence before stopping. Fake portable receipt equality and authentic native tool-call/result IDs are corrected. D5 clears stale chat choices, shows unavailable reasons and exact full-copy preservation notes. No protected spec was edited.

22. **UI interaction fixes (Ibrahim request, 2026-10-06; implementation independently reviewed):** preserve existing glass style while repairing expansion/full-screen controls, row hit areas and scrolling. Native overlay scrollers are used within Baton only; no system preference changed. Wider layouts are supported; minimum width remains 1000 to preserve the current two-card layout.

23. **Merge undo (Ibrahim, 2026-10-06):** U9 means native cut where can_cut supports it, otherwise a shorter copy as A9 requires. Merge-created chats are preserved; the link moves back to the earlier chat. Approved after explicit safety recommendation.
24. **E8 scope correction (Orchestrator, implementation only):** additive atomic complete_undo store API and ledger mixin, additive writer restore with fresh pre-write recovery receipt, empty cut boundary for fake/Claude adapters, and catalogue wording from existing specs are permitted; tests use temporary fixtures only.

25. **Glass title bar (Ibrahim, 2026-10-06):** requested native top bar in the existing glass palette. Transparent full-size chrome extends only the backdrop through the safe area; controls remain native. No system appearance setting changed.

26. **Undo safe refusals (Orchestrator, separate reviewer checked):** refuse moving back from a shorter or merge-created chat if it gained native messages; refuse an expired restore preview at apply; metadata-only split undo has no A10 restore and refuses it. Older merge records without sufficient observations cannot be guessed. Shared undo warnings include per-side capability needs and catalogue ids.

27. **Transparent signed identity (Ibrahim, 2026-10-06):** requested menu adoption, no white margins around B/I.A in current logo placements, and gray glass in dark mode. UI6 implements this and follows macOS appearance without changing its setting.

## Questions

- UI3 native functions and Ibrahim’s visible-controls check pass. Ctrl-Command-F shortcut is not wired after removal of the SwiftUI Window scene; Escape exits native fullscreen, standard green control works. Track standard command integration in D13/keyboard polish; do not claim it repaired.

- Earlier UI3 launch approval timeouts are resolved by the successful normal fixture launch and Ibrahim’s confirmation. Default Swift6.4/macOS27 build/test macro loading remains an environment issue; exact installed SDK26.5/TestingMacros commands pass.

- C3 must select the side for history markers with no tool/direction; E8 accepts explicit side and a verified subsequent delivery boundary, and refuses without one. No guessed timestamps/boundaries. Cut/copy restore is supported; restoring metadata-only split undo is refused. Older merge events without saved post-merge observations conservatively refuse created-chat undo.

- UI1/UI2: the earlier ScreenCaptureKit -3811 failure cleared after relaunch. CUA observed native light title-bar continuity and full-screen entry. Native fixture controls/click/overflow tests pass; graphite live appearance and human acceptance of this latest chrome are not claimed. Generic transport/decode errors still lack explanatory wording. UI5 adds loading feedback in its empty-state views; catalogue-backed wording and the remaining D13 polish are tracked in the UI1 report.

- F2 explicitly assigns engine-generated labels to C2, although findings precede CP2. Contract/UI/fixtures are complete; the C2 obligation remains tracked until implemented.
- C2 depends on the staged catalogue through CP2; E12 remains the complete CP3 audit. Real coding-app runs remain unauthorized. U9 now passes E8 fixtures; M12 remains tracked for E9/E10.

## Log

- 2026-10-06 — UI6 completed:377 engine /81 app/build pass. Imagegen transparent extraction replaces white runtime tile; brand/menu/theme/reduced-transparency PNGs inspected. Root native fixture confirms graphite signed gray-glass logo after exact-binary refresh. Separate reviewer warning closed by explicit native accessibility injection, opaque pixel assertions and Dock notification refresh; initial hosted view identity corrected. UI6 patch follows UI5; no Git/real-chat writes. SystemUIServer direct menu capture timed out, so no native item photograph claimed.

- 2026-10-06 — UI5 complete, UI4 shared gate closed: 377 engine / 79 app tests and Swift build pass with installed SDK flags. Signed burgundy/black I.A icon bundled and inspected on both themes and native fixture. Fixed independent review’s absent-sidebar guidance in popover, preserved intentionally note-less legacy fixture after a real failing compatibility test, and joined hidden-turn fallback to the first visible card. Separate reviewers confirm fixes. Ordered UI5 patch includes text and binary assets; no Git or real-chat writes.

- 2026-10-06 — UI3 completed at green boundary. Ibrahim answered “Yes, the window and controls are visible” for the running updated fixture. Native launch/fullscreen/Escape/sidebar gates passed; root377/74/build and independent review pass. Ready entry/ordered patch follow E8; no commit or push because Git remains read-only.

- 2026-10-06 — UI3 launch continuation checked by root and separate reviewer, no code blocker. Root377/74/build pass local SDK flags. Updated temporary fixture resources under Contents/Resources, LSUIElement=false, binary replaced; approved normal LaunchServices launch exited0. CUA confirms a main window directly, native full-screen button plus close/minimize, entry/exit via Escape, one-click sidebar after transition. Traffic-light screenshot area has a purple sharing overlay; Ibrahim’s visual confirmation pending. No real chat/tool app or Git write.

- 2026-10-06 — Ibrahim asked to open the temporary app or show how to find it. Renewed elevated and native desktop launches also timed out in automatic approval review, with no policy rejection. Finder instructions supplied for /private/tmp/BatonFixture.app; no successful new launch or native acceptance claimed. UI3 candidate remains held.

- 2026-10-06 — UI3 correction built; ordinary window zoom reproduced, new regressions fail on old code, root corrected gates pass 377 engine/73 app/build with installedSDK flags. Relaunch review timed out twice, so live gate remains unverified and package is not Done. All earlier changes preserved; no Git write or real chat action.

- 2026-10-06 — E8 completed, root and separate reviewer checked; 377 engine / 71 app tests and Swift build pass. Five independent/root findings closed (expiry, cumulative visibility, moved-chat identity, merge preview notes, split restore), plus bounded release and acknowledged attachment regressions. UI2/E8 ordered patches ready; no real chats and no Git writes.

- 2026-10-06 — UI2 title bar completed, independently reviewed; 71 app tests and isolated 334 engine tests. Hosted minimum-size test passed. Rebuilt fixture launch and native CUA light chrome/full-screen entry observed; no real coding app touched. E8 continues.

- 2026-10-06 — UI4 latest build passes with installed SDK26.5/TestingMacros flags. CUA verified path chips and conversation in a fresh review bundle; Attached showed no turns or boundary elements. Independent reviewer confirmed removing text selection closes conflict with row navigation. The replaced bundle failed to reopen, so a fresh temporary review bundle was built and launched successfully. App tests remain unrun; no system setting changed. See reports/UI4-2026-10-06.md.

- 2026-10-06 — Ibrahim requested a UI bug/enhancement audit. UI1 fixes independently reviewed; all three reviewer findings closed. 334 engine / 68 app / build pass; click-shape mutation fails as expected. Existing package patches preserved, UI1 ready after CP2-record.

- 2026-10-05 — CP0 passed. Contract frozen. See [CHECKPOINTS.md](CHECKPOINTS.md).
- 2026-10-05 — Orchestrator hand-off written.
- 2026-10-05 — Reviewer approved understanding and six decisions; recorded before implementation. Repository files and temporary folders are writable; .git remains protected and reviewer will commit.

- 2026-10-05 — E2 independently checked: 156 engine tests pass; all eight delivery rows, unknown format branches and visibility evidence pass. App checks at this boundary pass 18 tests with writable caches and --disable-sandbox. Challenge fixed Cursor running/open-false, misleading status policy, service import cycle and note button IDs.

- 2026-10-05 — D1 independently checked: 18 app tests pass; 16 PNGs render. Visual challenge fixed native control placeholders and weak Graphite text contrast; root inspected note, steps, meter, message, confirmation, turn and chip snapshots. D2 starts.

- 2026-10-05 — D2 optional links.notes and backward-compatible model decoding approved by orchestrator; scope/contract updated. E2 CP1 catalogue extended with required screen/status labels.

- 2026-10-05 — D2 independently checked: engine 156 and app 23 pass; 18 render PNGs. Challenge fixed differing names, stale previews, state/plan fixture contradictions and duplicate plan/step notes. D3 starts.

- 2026-10-05 — D3 additive link-summary needs_attention approved; Shared.swift scope and CONTRACT extended. Generic empty-list wording 'No items yet' added centrally because empty non-linked lists have no specified sentence; reviewer may refine catalogue wording.

- 2026-10-05 — Reviewer resumed after interruption, approved E2 and committed 38a984a. E2 ready entry removed. E3 prepare port approved; D3 resumes at known compile failure. Run budget about 100 minutes starting 01:36 UTC; stop at a green package boundary.

- 2026-10-05 — Orchestrator restored D3 compile by splitting timestamp sort into typed intermediates; swift build passes again. Root identified native ScrollView missing content in ImageRenderer. Approved snapshot-only static viewport using the same production list/detail content; runtime scrolling stays.

- 2026-10-05 — D3 independently checked: 156 engine and 29 app tests pass, with 34 PNGs across 17 list states. Challenge fixed compiler complexity, stable suggestion selection, timestamp ordering and blank ImageRenderer ScrollView contents. Snapshot-only static viewport shares production content; runtime scrolling is not proved by these PNGs. D4 starts.

- 2026-10-05 — D4 fixture wording needs first-message waiting, held-chat, no-extra-next-message, checked time and expansion labels. Added centrally to catalogue for E4 support (E4 permits catalogue); existing all-note rendering tests cover them. Protected feature wording unchanged; new display labels subject to reviewer audit.

- 2026-10-05 — E3 independently checked: 178 engine and 29 app pass. Challenge fixed tautological create preparation assertion; durable post receipts, reverse recovery failure barrier, date-aware 30-day pruning, identity and selective visibility checks verified. Fake pre-write snapshot recovery assumes no outside edits after crash; startup composition must call recover before writes. E4 starts.

- 2026-10-05 — E4 plan correction: DESIGN 7 requires a title tag, not altering the first prompt. Mapping keeps prompts intact, title helper uses catalogue, marker remains separate metadata helper. E6 scope extends domain/link.py because the existing TOOLS identity list only allows two tools; all four are required at CP1.

- 2026-10-05 — E5 scope correction: additive store/SQLite methods permitted for delivery IDs, bypass reconciliation and atomic delivery/journal commit. Separate commits could leave rolled-back content marked delivered after a crash; recording delivery and journal completion must be one transaction. Services continue using only the store port.

- 2026-10-05 — E4 challenge found tool activity flattened as reply could invent a final reply when the original has none. Approved additive TOOL_TEXT domain/contract kind, ordinary labelled text for non-replay targets, with catalogue label and D4 grouping. Adapter writers in later packages must support it.

- 2026-10-05 — E4 independently checked: 188 engine and 29 app pass. Review verified public content, deep-copy inputs, stable call/result pairing, flattened/native content keys, incomplete-reply handling and separate title/marker helpers. TOOL_TEXT and title correction prevent invented replies or changed prompts. E5 starts.

- 2026-10-05 — E6 scope also permits additive store/SQLite support for atomic new-link metadata and journal completion. A crash must not leave an active link to a newly created chat that recovery deletes.

- 2026-10-05 — D4 visual challenge found history-attached future wording misleading after delivery. Added status.attached and setup-ready catalogue lines centrally; E5 patch carries these additive labels. Validated ordered package patches in a temporary verification folder with no .git directory: D1/D2/D3/E3/E4 apply and reproduce reviewed files. Fixed missing new-file patch metadata and rebased E4 catalogue diff on reviewer-committed E2.

- 2026-10-05 — E5 S5/S6 coverage found missing first-message policy: attached-history initial turns must not become real messages just because the destination is closed or accepts live writes. Approved an explicit initial_history_sides flag shared by planner/status, derived by applier from link/empty destination/no delivery evidence. Unknown-format precedence unchanged. Scope includes additive planner/status changes; intent never counts as attachment.

- 2026-10-05 — D4 root image review found integrated list/detail fixture disagreement and fixed-status fixtures returning link 3 for other selections. Scope extends FixtureEngine.swift for additive per-link fixture routing; model rejects mismatched link IDs. D3 summary names/chat IDs and D4 status aliases must agree. Standalone S6/S12/unknown and narrow Graphite layout visually checked.

- 2026-10-05 — Reviewer resumed after usage-limit interruption and committed E3 43614c2, E4 5b41095, D1 94f161c, D2 d214e44, D3 b5d5e5f (E2 already 38a984a). Removed their ready entries. Unfinished E5/D4 preserved; reviewer measured 227 engine, 44 app and passing build. No git writes permitted by current filesystem profile; patches and ready entries remain the hand-back route.

- 2026-10-05 — Resume independently verified: 227 engine and 44 app tests, passing Swift build. Git directory reports read-only; no write probe or workaround. D4 final review found S10 displayed future creation prose for an already-created chat; new central status.new_chat_relaunch corrects it. Supplemental D2 previews included in D4 scope; long-message disclosures must cover every deliberately collapsed message.

- 2026-10-05 — D4 independently accepted: engine 232, app 44, Swift build pass. Rendered 38 PNGs; root inspected S10 light and verified current disclosure/confirmation guards. Challenge fixed misleading created-chat wording, inaccessible truncated short replies, duplicate confirmation, stale previews, unlink selection and mismatched per-link fixtures. D4 patch applies and reproduces reviewed files in a temporary directory; ready entry records all 35 paths.

- 2026-10-05 — Reviewer resolved S9/S7 precedence: hold for S7 on a new completed destination turn, then redeliver after merge. E5 scenario regression asserts the conflict hold; protected feature wording is unchanged.

- 2026-10-05 — E5 independently accepted: 234 engine and 44 app tests, Swift build pass. Named S1–S12/S4b cover 42 applicable fact subcases. Challenge fixed changing preview reads, preserved pre-existing message identities, duplicate destination IDs, receipt identity disagreement and compaction aliases with absent old IDs. Recorded S9/S7 decision; E5/D4 patches apply to HEAD and reproduce reviewed files. E6 starts sequentially.

- 2026-10-05 — E5 final challenge reopened: check pause/removal between steps, and refuse acknowledgements on a removed link. E6 edits held; no package acceptance will bypass this check.

- 2026-10-05 — E5 recheck closed: two new regressions failed on old behavior, then pass with per-step pause/removal and inactive acknowledgement guards. Full engine 236, app 44, build pass. First completed write is retained; further steps stop. E5 patch refreshed and E5/D4 reconstruction passed; E6 edits resume.

- 2026-10-05 — E6 worker reached 262 engine tests. Root independently reproduced canonical-copy record race: skip during planning still copied the skipped turn because token used a newer ledger snapshot. E6 acceptance held for matching payload/record provenance regression and fix. App remains 44/build green.

- 2026-10-05 — E6 independently accepted: 268 engine, 44 app, Swift build pass. Named T0–T4/X1/X2, all 12 directed pairs, receipt/metadata rollback, hidden-history reconstruction, monotonic copy visibility, exact payload/record snapshot and metadata-only missing/unreadable unlink pass. E6 patch captured after E5; E5/E6/D4 reconstruct reviewed files. No package remains in progress.

- 2026-10-05 — CP1 checks PASS, reviewer approval pending: named scenarios and eight delivery rows pass; 18 popover, 34 window, 38 status PNGs are non-empty in both themes. Final engine 268/app 44/build pass. Report contains all real output, challenge changes, decisions and limits. Stop at this green checkpoint boundary.

- 2026-10-05 — Resume: CP1 approval and E5 df091d0 / E6 98fc038 / D4 dcb698e recorded; obsolete ready entries removed. F1 corrected: decision 8 was the orchestrator's, approved by Claude afterwards. Baseline independently rechecked at 268 engine, 44 app, Swift build pass. R10 and D4b start; no CP2 package has started.

- 2026-10-05 — F2 contract labels added; F6 gets a separate idle-release catalogue note so the generic held/replying offer cannot advertise an unavailable action. D4b carries app/fixture and catalogue support; C2 generation obligations recorded in its track. Mockup read directly through the in-app browser; no live Baton or coding-app run.

- 2026-10-05 — R10 independently accepted: 270 engine, 47 app, Swift build pass. Separate reviewer agent found no actionable findings. Root verified all 37 store method bodies unchanged and exact previews/refresh across 24 fact-pair/mode cases; durable failure/reopen/retry confirms atomic completion. Fixed extraction cycle and public docstrings. R10 patch and exact ready entry recorded; D4b remains in visual review, no CP2 started.

- 2026-10-05 — D4b root PNG challenge corrected plain-text offer buttons, missing turn/conversation panel headings and header separation. Restored material/palette consistency in production view roots, beyond snapshot-only theme modifiers. Independent reviewer caught hidden Linked/Needs attention refresh errors; package acceptance remains open for the fix and final recheck.

- 2026-10-05 — D4b implementation reached a green review boundary: 270 engine / 48 app, Swift build pass; 110 PNGs. Separate reviewer’s hidden error and stale review-artifact findings fixed; timestamp consistency suggestion applied. Root inspected light/Graphite screens and error PNG, refreshed the exact 103-path candidate patch and verified R10 then D4b reconstruct reviewed files. CP1’s named scenarios/delivery rows still pass (39 focused tests). D4b/F4 stays open for Ibrahim’s running-app comparison; no live launch or CP2 work.

- 2026-10-05 — Ibrahim authorized the fixture-app visual run. The Swift executable ran directly (PID 97824), but CUA could not attach to an unbundled executable. A temporary app wrapper was refused by LaunchServices (`kLSNoLaunchPermissionErr`, managed networks); wrapper removed. No permission/system setting changes, real chats, other app closures or reopenings. Executable left running so Ibrahim can inspect it; CP2 remains stopped pending F4 visual decision.

- 2026-10-05 — Ibrahim reported nothing visible. Corrected the claim that a running process proved desktop presentation. Retried the direct executable outside the sandbox with approved escalation: no desktop-service error, but CUA still could not attach. Stopped both owned fixture processes, prepared a temporary bundle containing the existing executable and copied fixtures. Automatic review rejected `open -n /private/tmp/BatonFixture.app` outside the sandbox as a permission-bypass approach not explicitly authorized. Exact launch approval requested; no workaround attempted and no source changed.

- 2026-10-05 — Ibrahim explicitly approved the temporary bundle launch outside the sandbox; LaunchServices accepted it and PID 98769 ran, but he still saw no icon. Apple docs identify the standalone MenuBarExtra initializer as unsuitable alongside Window; D4b runtime repair uses the insertion-binding initializer and flattens the existing icon/badge into a native image. Scope includes the thin executable integration; no intended appearance or sync rule changes. Build/tests and reviewer recheck required before another launch.

- 2026-10-05 — Binding/image repair still produced no icon. A review-only launch argument opens the existing fixture window through the application delegate; Ibrahim confirms the app is visible but absent from the menu bar. Activation policy runs at launch completion. Native integration remains open; no claim that F4 has passed.

- 2026-10-05 — Internal status-item probe found an on-screen status window at {{940, 949}, {38, 33}}, non-hidden native button, valid 22×18 chain image and template=true. No instrumentation remains in source. Ibrahim approved a temporary text label; it too is unseen. Do not infer OS permission failure or change settings. Separate reviewer accepted launch changes with no code findings; normal menu/window routing still unverified.

- 2026-10-05 — Final runtime-delta boundary: 270 engine / 49 app tests, Swift build and whitespace check pass. 114 generated PNGs (including four menu images), plus live status/conversation captures. CUA scrolled the actual window to its conversation; Ibrahim is interacting with the window. F4/D4b remains open because menu entry/popover and human mockup approval are missing. R10 remains the only ready-to-commit entry.

- 2026-10-05 — Ibrahim clarified that the top bar is visible only when the pointer reaches it and Baton is present there; “apps bar” referred to the Dock. Visibility misunderstanding resolved without changing OS settings. Relaunched only the owned fixture without `--review-label`, restoring the normal icon and retaining the review window. Asked Ibrahim to open the popover and compare all three screens with the mockup; F4 remains pending that explicit answer.

- 2026-10-05 — Ibrahim requested better styling and selected “Explore a different direction”. D4b is not accepted. Orchestrator prepares two fixture-rendered alternatives for a concrete choice before production restyling; protected DESIGN/features stay untouched. Last production checks remain 270 engine / 49 app and Swift build.

- 2026-10-05 — Style study worker owns only a temporary `app/Tests/BatonUITests/StyleStudiesTests.swift` renderer and git-ignored `app/Snapshots/Style-*` images. It may not edit production or plan files. Two proposed layouts use existing fixture notes and data; root will inspect renderings, preserve reproduction source, remove the temporary test and recheck production before asking for a direction.

- 2026-10-05 — Style exploration complete: eight non-empty PNGs `app/Snapshots/Style-{A-inspector,B-workspace}-{light,graphite}-{window,popover}.png`. Root inspected the primary four, corrected a truncated Graphite status line; worker corrected fixture headline disagreement, missing Continue/recent actions and dark tool-dot contrast. Visual-only renderer source retained as `app/Snapshots/Style-StudySource.swift`; temporary test removed. Fresh full checks: 270 engine / 49 app, Swift build and whitespace pass. Selection remains pending; no production restyling or CP2 work.

- 2026-10-05 — Ibrahim chose to leave the existing style after reviewing alternatives. Closed the redesign exploration without changing production views or the mockup reference. Proposal images remain ignored reference artifacts. No new runtime claim or package approval is inferred; last production checks stay 270 engine / 49 app and Swift build.

- 2026-10-05 — Ibrahim instructed commit and continue after retaining the current appearance. D4b moved to Done/Ready to commit. Fresh baseline 270 engine / 49 app and Swift build pass. Git remains read-only by an access check; no write probe or workaround. E7 and D5 starting in parallel; sequential package patches remain the commit route.

- 2026-10-05 — E7 worker identified missing atomic merge completion and attachment decision persistence. Additive store/service scope recorded; U9 belongs to E8. D5 worker identified missing relink mode; asked Ibrahim, continuing independent routes. Catalogue/contract presentation added centrally; no live run.

- 2026-10-05 — Ibrahim approved additive relink mode option. D5 implements selected mode plus retained side, with old caller behavior preserved.

- 2026-10-05 — B1 started in baton/adapters/claude/, tests/adapters/test_claude.py and tests/fixtures/claude/; explicit temporary roots/injected runtime, no real paths or commands read/run. Live acceptance remains pending a detailed human go. Engine E7 and app D5 ownership remain separate.

- 2026-10-05 — Ibrahim approved safe reverse-order rollback. B1 scope includes shared suite correction and preservation of the fake-only out-of-order test. Rename guards allow the documented whole-app-closed refusal; each adapter must test its exact rule.

- 2026-10-05 — E7 independent reviewer reproduced lost merge visibility timestamps, paused split refusal and orphan creation on broken reservation. Root took over fixes and added five regressions. D5 reviewer reproduced stale destination list race and incorrect setup/full-copy fixtures; root corrected them and added regressions, plus bounded chat picker and explicit Copy and link choice. B1 native fixture implementation is reviewed separately; actual app behavior remains unverified.

- 2026-10-05 — E7 independent review closed all three findings. 25 focused tests pass; its ordered implementation boundary passes 295 engine / 49 app and build. U9 remains an explicit E8 integration requirement; M12 needs E9/E10. E7 ready entry and patch recorded before further packages.
- 2026-10-05 — D5 independent review closed stale destination race, incorrect setup/replacement wording and missing copy refusal explanation. Root PNG challenge replaced an unsupported native picker with a bounded glass selector; rendered both palettes. 11 dialog tests / 60 full app tests pass, build passes; ordered boundary engine295. D5 ready entry and patch recorded.
- 2026-10-05 — B1 independent review closed hidden-target format bypass and intent recovery before project directory creation. 37 native adapter tests pass; working engine334/app60/build pass. Implementation is ready to commit, with live acceptance pending. Shared suite reversal was approved by Ibrahim; native call/result ID pairing fixed. Hooks/real release/runner/visibility remain explicitly unverified as recorded above.
