# Status

The current hand-off page. Historical decisions, reviews and logs are in [reports/](reports/) and git history. Whole road: [MAP.md](MAP.md).

**Branch:** `chore/project-setup` · **Last checkpoint passed:** CP1, 2026-10-05 · **Working towards:** CP2 (not passed) · **Last checked:** 2026-10-11

## Reviewer notes — 2026-10-13 (Claude, with two separate reviewer agents)

Reviewed the fifteen commits `dab931c` … `f63725c` made by the Codex orchestrator. **Measured:** 787 engine tests pass on the tree and on the committed state in a clean copy; `app/scripts/check.sh` passes, 146 app tests; naming and layer rules hold; no spec changed; CONTRACT.md 22 lines added, none removed; no attribution in any commit; 18 commits are not pushed.

**Accepted as committed:** G2, G3, E9, C2a, C2b (C2a/C2b by suite and fixture-gate only, not line by line). **Accepted with fixes owed:** C1, E10, D6, D7. **Returned:** B2 (three safety findings, all before the live run).

**Findings to close (H = this review)**

| # | Package | Finding | Fix |
|---|---|---|---|
| H1 | B2 | `codex/state.py` `replying()` is true only when the chat is also held. Hold detection is itself unverified, so an unfinished task in a chat that looks unheld can be written to or the app quit. The plan says: replying = a task started without a completion. | Unfinished task alone counts as replying until the live run proves hold detection. Invert the test that asserts the opposite. |
| H2 | B2 | `codex/writer.py` `_check`: with a lease set, the replying check is skipped. | Check the unfinished task after the lease check too. |
| H3 | B2, C1 | A test root does not fence the adapters: `build(root=tmp)` still gives the Codex adapter the real process launcher, the real bundled CLI (`login status`) and no `CODEX_HOME`; the Claude adapter the real `ps`/`open`/`osascript`. `baton setup` on an empty `BATON_HOME` reports from the real machine. | When a root is injected, process and runner must be injected or inert; real ones only in the default home. |
| H4 | C1 | `plans.py`: `--confirm` from another command destroys that command's plan before the command check. | Load, compare command, then claim. |
| H5 | C1 | Usage/crash text and argparse help are sentences outside the catalogue. | Catalogue ids; E12 audits. |
| H6 | E10 | Brief preview calls `runner.available()`, which starts a process; E10 says a preview makes no runner call. | Non-spawning readiness at preview, or state the exemption. |
| H7 | D5, D4 | The display gate exists in the plan review only. `LinkDialogViewModel.markNotesDisplayed()` is public and called just before confirm; `SyncStatusViewModel.confirmPlan()` has no gate. | Same `didDisplay(receipt)` gate in both; remove the public marker. |
| H8 | D4 | `SyncStatusViewModel` sends `relaunch` with `.confirm` and no refusal, while the plan review refuses relaunch until C5. | Route through the plan review or refuse. |
| H9 | D7 | Hand-off with no note shows a mark and a close button and no sentence; close button has no accessibility label; meter drawn when percent is unknown; brief-fallback fixture is only rendered, never asserted. | Catalogue fallback; omit meter; assert `brief.used_offline` on the fallback fixture. |
| H10 | app tests | `FixtureEngine` silently falls back to the base fixture when a state file is missing; `WindowView` reads the real stored theme in five tests; renders are only checked for "not empty". | Throw on a missing state; inject the preference; say plainly that renders are looked at by a person. |
| H11 | app | `Text("Turn \(turn.seq)")` in SyncStatusView is a sentence built in the app. | A note from the engine. |
| H12 | check | The hand-edit gate for fixtures runs only in the engine suite. | Run it from `app/scripts/check.sh` too. |
| H13 | size | `services/brief.py` 621 lines, `codex/writer.py` 544, `services/undo.py` 471. | Split brief into generate and create before CP3 adds to it. |

**Decisions the Codex chat recorded as Ibrahim's** (Q4 self-commit, Q5 brief cost/generate/create and Automatic/Offline, Q6 labels, Q7 "Baton cannot use {tool} yet.", Q8 bookkeeping visible): this reviewer did not see them being given. Ibrahim to confirm. **User-visible choices not attributed to Ibrahim:** D5 duplicate notes deferred; a dismissed limit offer is forgotten when the app restarts; E9 digest refused until a fresh link; P5 of CP2-REPAIR-PLAN.md; "Brief review details" in CONTRACT.md.

**H1 to H3 fixed 2026-10-13** (806 engine tests; each fix reverted to prove its test fails; report `reports/H1-H3-2026-10-13.md`). B2 is accepted on fixtures. Left open by the fix: a crashed, never-finished Codex task in a closed chat now refuses writes (decide after the live run); the refusal reuses the note about closing, a write-specific note goes to E12; `setup` prints a version for a tool that is not installed.

**Ibrahim, 2026-10-13:** confirmed Q4 to Q8 as his, and the four choices listed below as his. Pushed on his word.

**Decisions by Ibrahim, 2026-10-13** (on the reviewer's recommendations)
- **Q9. Duplicate notes in the link dialog:** fix soon, together with H7. The same sentence is never shown twice on one screen.
- **Q10. Dismissed limit offer:** "Not now" holds until that limit resets or a new limit is reached, across app restarts. Built in C7 with the durable offer memory.
- **Q11. "Since you left" digest when it cannot be trusted:** keep refusing it, but show a note that says why it is missing. Catalogue note in E12, shown by D4.
- **Q12. "Brief review details" in CONTRACT.md:** kept.

**Order from here:** ~~H1 to H3~~ (they guard the live run) → live run of Claude and Codex adapters on two throwaway chats → CP2 result → H4 to H13 alongside the first CP3 packages.

## Now

**C2b committed `2bbdbe3` after root challenge and separate reviewer approval on chore/project-setup.** Together with C2a `914d9d3`, C2 is complete for its approved read/service/generated-fixture boundary. Root measured **787 engine tests,146 app tests and build pass**,325 deterministic fixtures and255 non-empty renders. Own26 actual-effect/fixture checks,149 native-shaped fixture tests and82 focused CP2 scenarios pass. No live chat/app access or push. [C2b report](reports/C2b-2026-10-11.md), [current CP2 report](reports/CP2-2026-10-11.md).

**CP2 remains FAIL/incomplete solely at its required native live gate.** B1/B2 fixture implementations are accepted; Codex production mutation/automatic closure deliberately refuse until native coordination/trust/schema is verified. C3–C7/D12 production integration stays in its planned packages. D5 duplicate explanatory notes are a recorded nonblocking UI follow-up. Existing post-C2a records are included in this package; historical untracked reports/E9-E10.md stays preserved and excluded.

## Next

1. Prepare the exact Claude/Codex throwaway live scope: named test identities, descendants/templates, files read/written, backup and cleanup. Ask Ibrahim for that run after listing scope, and for every app closure. Never use working chats or bypass production safety refusal.
2. Establish native coordination/index/schema/marker/trust/visibility evidence; stop on any difference from measured specs. CP2 cannot pass and CP3 cannot start until the required live check succeeds.
3. Ask for a separate small app follow-up to remove exact duplicate D5 plan/step notes while retaining changed/opposite-side notes and fresh display approval. No product UI policy was changed in C2b.

## Done

| Package | Date | Commit | Tests after |
|---|---|---|---|
| E0 restructure into layers | 2026-10-05 | `d4d9153` | 70 engine |
| E1 ports and capabilities | 2026-10-05 | `cb11c88` | — |
| B0 fake tool and adapter suite | 2026-10-05 | `fcd3f41` | 129 engine |
| D0 app skeleton | 2026-10-05 | `bc2e180` | 15 app |
| E2 to E6, D1 to D4 | 2026-10-05 | `38a984a` … `dcb698e` | CP1: 268 engine, 44 app |
| R10 | 2026-10-09 | `b8701f5` | Keep storage and delivery changes separate |
| D4b | 2026-10-09 | `783fe02` | Make Baton match the glass mockup |
| E7 | 2026-10-09 | `c9ac1f7` | Merge without rewriting either chat |
| D5 | 2026-10-09 | `e5aa6b4` | Explain link and copy choices before creating chats |
| B1 | 2026-10-09 | `045e46b` | Guard native chat writes with durable rollback receipts |
| (records) | 2026-10-09 | `8397468` | Record the state of the plan while working towards CP2 |
| UI1 | 2026-10-09 | `67e7190` | Make window navigation and scrolling respond reliably |
| UI2 | 2026-10-09 | `47ea8cc` | Blend the title bar into the glass window |
| E8 | 2026-10-09 | `9bf51dc` | Keep undo recoverable across chat changes |
| UI3 | 2026-10-09 | `ae5980a` | Open the main window with native controls |
| UI4 | 2026-10-09 | `fe9c4cc` | Make conversation ownership and sync boundaries clear |
| UI5 | 2026-10-09 | `9d56587` | Give Baton a signed identity and explain empty views |
| UI6 | 2026-10-09 | `3e068db` | Carry the signed mark across both app appearances |
| UI7 | 2026-10-09 | `7049874` | Keep logo colors fixed and make appearance selectable |
| UI8 | 2026-10-09 | `980449a` | Show clear receipts, configuration and a confirmed Quit |
| UI9 | 2026-10-09 | `53f4365` | Make the compact menu surface easier to read |
| UI10 | 2026-10-09 | `70a8d32` | Tighten the Dock mark and soften the menu icon |
| UI11 | 2026-10-09 | `3e3e6c6` | Scale the Dock brand and sharpen the menu-bar mark |
| UI12 | 2026-10-09 | `e4a5fc8` | Make Baton recognizable at both system icon sizes |
| UI13 | 2026-10-09 | `44e106b` | Make conversation sync positions easier to read |
| G2 | 2026-10-09 | `dab931c` | 650 engine, 115 app; build green |
| G3 | 2026-10-09 | `7f6e39f` | 115 app green |
| C1 | 2026-10-09 | `e15e076` | 650 working-tree engine / 115 app green |
| E9 | 2026-10-09 | `650a8d1` | 555 isolated / 670 working-tree engine; 129 app, build green |
| D6 | 2026-10-09 | `604e6d8` | 119 isolated / 129 working-tree app; build green |
| E10 | 2026-10-09 | `ec88983` | 702 working-tree /622 isolated engine;143 app/build |
| D7 | 2026-10-09 | `c8720bf` | 143 app and build;702 working-tree engine |
| B2 fixture implementation/safety | 2026-10-10 | `cbb3e2b` | 730 engine /149 native /143 app and build; live owed |
| C2a safe read commands | 2026-10-10 | `914d9d3` | 761 engine /150 focused /143 app/build; C2b generation followed |
| C2b generated fixtures (completes C2) | 2026-10-11 | `2bbdbe3` | 787 engine /26 own /149 native /82 scenarios /146 app/build;325 fixtures,255 renders |

## Ready to commit

None. C2a `914d9d3` and C2b `2bbdbe3` committed; historical E9-E10.md excluded. Commit-reference documentation is recorded separately; no implementation remains unfinished.

## Decisions and reviewer findings

- **Orchestrator, checked by a separate reviewer agent 2026-10-10:** split C2 execution into C2a safe read commands and C2b generated fixtures, separately reviewed green commits. Whole C2 acceptance and CP2 requirements are unchanged; reduces interruption risk in277-fixture replacement.

- **Ibrahim Q6 (2026-10-10):** approved the exact completed-history labels and merge-preset labels presented in chat. C2 adds them to the catalogue; no wording lives in serializers or app code.

- **Ibrahim Q5 (2026-10-09):** approved estimated-cost-before-agent-generation, separate generated-brief review/create, truthful summary receipts, action-specific confirmation/Cancel and Automatic/Offline. Approved unavailable CP3 alternatives preserving the original request, and the planned CP2 fixture/service versus CP3 execution boundary. See CP2-REPAIR-PLAN.md; additive CONTRACT/copy recorded before workers start.

- **Ibrahim Q4 (2026-10-09):** orchestrator may commit the reviewed packages itself and must keep docs current. Approved Git staging worked; G2 commit verified in Git. Never push.

- **Ibrahim Q1:** reached copy reads “agent has reached here”; spec, catalogue and committed fixtures were changed in `773c831`.
- **Ibrahim Q2:** engine `theme` is the source of truth when D12 wires it; current app preference is a stand-in.
- **Ibrahim Q3:** Claude/Codex live run on two named throwaway chats has go; every app closure is still asked, and no working chat may be touched.
- **Reviewer G1:** at three accepted-uncommitted packages, stop for commits. G2/G3 and C1 are accepted after root checks and independent review. G1 cleared by G2/G3/C1 commits; no waiver needed. G4 was withdrawn because UI1–UI13 are already in the track. G5 closed by archiving the long page and retaining current state/ten logs. G6 live adapter acceptance remains owed.

## Questions and unresolved work

- **Ibrahim Q8 (2026-10-10):** show bookkeeping too, with new labels. Root implements distinct aligned/queued/not-confirmed/user-visibility labels and a neutral unknown-event fallback, all in the catalogue; every record and eligibility flag stays intact. This is the chosen visible-history behavior, not an omission/filter.

- **Ibrahim Q7 approved, 2026-10-10:** setup label “Baton cannot use {tool} yet.” for a tool with no implemented adapter. Catalogue id `setup.adapter_unavailable`; no fabricated install/sign-in/trust remedy.


- E9/E10/B2 fixture safety and C2 read/generated acceptance complete after independent reviews. Native live acceptance remains; no issue is waived.
- D6/D7 service-backed/generated acceptance complete; D12 production integration remains. No native execution is inferred from screen transport tests.
- C1 skeleton and C2 reads complete; C3 actions and installed entry-point verification remain. Direct Engine callers must hold command_lock before first service access through apply. C4 must bound lock acquisition within its two-second deadline.
- B2 safe fixture implementation is accepted; native coordination/index/schema/marker/trust/visibility remain unverified and production mutation/automatic closure safely refuse. B1 live acceptance also remains owed.
- Ctrl-Command-F integration remains D13 work; native green-button full screen was checked earlier. C2 now generates fixtures from authoritative engine/service responses; D12 must wire production settings/reads.

## Log

- 2026-10-11 — C2b committed `2bbdbe3`:349 exact reviewed paths, index empty and tracked tree clean before reference updates. Historical E9-E10.md excluded/preserved. Whole C2 complete;787/146/build green, CP2 native live FAIL. No push.

- 2026-10-11 — C2b independently approved:325 generated fixtures,787 engine/26 own/149 native/82 CP2 scenarios/146 app/build,255 renders. Root privacy mutant and independent fold/state-label mutants detected; all blocking findings closed. D5 duplicate notes deferred explicitly; CP2 native live still FAIL. Commit prepared, no push/live access.

- 2026-10-11 — C2b private325-route batch passes146 app/build and independent11588-note/27-status audit. Root visually checked representative light/graphite screens; scoped label and folded-state defects fixed. Explicit tracked publication next; no native run/push.

- 2026-10-11 — C2b private checks exposed catalogue drift, false trust/creation notes, missing receipt wording and single-tool fixture reuse. Root/builder fixes preserve actual service policy;324 routes planned, per-tool routing regression added. Publication held until temporary batch and app pass. No native run/push.

- 2026-10-11 — Resumed C2b generation; initial status contains only five post-commit records and preserved historical E9-E10.md. No unfinished implementation. Baseline reproduced761 engine/143 app/build; builder and independent reviewer active, no live access/push.

- 2026-10-10 — C2a committed `914d9d3`:35 exact reviewed code/test/contract/plan/report files, branch chore/project-setup, index empty; historical E9-E10.md preserved. Root761/150/143 and native149/scenarios77 pass. Q8 closed, C2b/live remain; no push. Commit tool response stalled after success; read-only Git verification established hash/index before stopping its wrapper, no retry.

- 2026-10-10 — Ibrahim Q8 chose all bookkeeping visible with distinct labels. Root three actual-service/unknown-entry regressions and semantic mutant, separate final review: C2a accepted761 engine/150 focused/143 app/build;149 native/77 scenarios pass. Commit being prepared; C2b/live remain, no push.

- 2026-10-10 — C2a source green758 engine/147 focused/149 native/77 scenarios/143 app/build. Read-only pending-write safety, copy privacy, real history eligibility, visibility headlines and retained-name evidence reviewed/fixed. Separate final code review approved conditionally only on Q8 required display choice; C2a unaccepted/uncommitted, C2b/native live untouched. [C2a report](reports/C2a-2026-10-10.md).

- 2026-10-10 — B2 committed `cbb3e2b`:23 exact reviewed code/test/plan/report files, index empty; original E9-E10.md draft preserved untracked. No push/live access. C2 next.

- 2026-10-10 — B2 fixture safety accepted after independent final108 approval and root730/149native/77scenarios/143app/build checks. Scope/CAS/trust/format/continuous-lock mutants exercise real failure assertions. Native protocols/live still fail closed; commit pending, no push.

Older entries remain in commit `2bbdbe3` and the historical reports.
