# Status

The current hand-off page. Historical decisions, reviews and logs are in [reports/](reports/) and git history. Whole road: [MAP.md](MAP.md).

**Branch:** `chore/project-setup` · **Last checkpoint passed:** CP1, 2026-10-05 · **Working towards:** CP2 (not passed) · **Last checked:** 2026-10-09

## Now

Codex has taken over from Claude. Existing package files are preserved. Two independent reviewer agents were used; root owns fixes and the record. G2 committed as `dab931c`, G3 as `7f6e39f`. C1 accepted; its isolated commit is being prepared. Ibrahim explicitly authorized self-commits on 2026-10-09. Normal approved Git writes work; sandbox-only Git writes remain restricted. No push.

Resume baseline: **640 engine tests, 1 fixture failure**; current measurement is green. **App check now passes: 115 tests and build**, after fixing writable module caches and nested manifest sandbox execution. Engine now passes all 650 tests after the C1 safety regressions; D7 fixture receipts corrected. Reports' earlier green counts are historical only.

| Package | Current state | Owned files |
|---|---|---|
| G2/G3 | G2 `dab931c`, G3 `7f6e39f` committed | `app/scripts/check.sh`, `app/README.md`, `app/Package.swift`, `app/Tests/BatonUITests/BrandTests.swift` |
| E9/E10 | Separate review found privacy, digest, threshold and completeness blockers; not accepted | `baton/services/{usage,digest,limit_offer,noteformat,brief,transcripts}.py`, corresponding unit/scenario tests, E9/E10 catalogue blocks |
| B2 | Native Codex fixture implementation preserved; root/separate review still owed; live not verified | `baton/adapters/codex/`, `tests/fixtures/codex/`, `tests/adapters/test_codex.py` |
| C1 | Accepted after safety repairs, 119 focused tests and separate re-review; ready to commit | `baton/cli/`, `pyproject.toml`, `tests/contract/`, `tests/unit/test_cli.py`, `error.unexpected` catalogue note |
| D6/D7 | Separate review found wrong action routing and fixture/presentation blockers; not accepted | `app/Sources/BatonUI/Screens/{PlanReview,HandOff}/`, focused tests and `*.d6_*`/`*.d7_*` fixtures |

Full findings: [CP2-resume-2026-10-09.md](reports/CP2-resume-2026-10-09.md). No new package is called done from a builder report alone.

## Next

1. Finish the independently reviewed C1 commit using the approved Git path. G2 is committed. Preserve all other in-flight files; never stage all or reapply old patches.
2. Complete the two-agent CP2 repair plan and settle its product/contract decisions with Ibrahim before dependent implementation. Updated baseline: 650 engine / 115 app, build green. Update STATUS, MAP and HANDOFF after each package.
3. Fix and accept E9, E10, B2, D6, D7 in dependency order, resolving the recorded review blockers first. E10 needs real journaled brief creation, not only a plan object.
4. C2 read commands and generated fixtures; then the specifically approved Claude/Codex throwaway live run. Each app close still needs Ibrahim's go at that moment. Record CP2 checks; continue to CP3 only when they pass.

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
| C1 | 2026-10-09 | awaiting commit below | 650 engine / 115 app green |

## Ready to commit

### C1 — Keep commands and recovery safe across processes

Code paths (exact): `baton/cli/__init__.py`, `baton/cli/main.py`, `baton/cli/wiring.py`, `baton/cli/storage.py`, `baton/cli/output.py`, `baton/cli/tools.py`, `baton/cli/plans.py`, `baton/cli/commands/__init__.py`, `baton/cli/commands/links.py`, `baton/services/status.py`, `pyproject.toml`, `tests/contract/__init__.py`, `tests/contract/test_shapes.py`, `tests/unit/test_cli.py`.

Shared-file hunk: `baton/notes/catalogue.py` **only `error.unexpected`**; all other new notes belong to unfinished E9/E10 and must stay unstaged.

Record paths: `docs/plan/STATUS.md`, `docs/plan/MAP.md`, `docs/plan/HANDOFF.md`, `docs/plan/ARCHITECTURE.md`, `docs/plan/track-c-cli-hooks.md`, `docs/plan/reports/C1.md`, `docs/plan/reports/CP2-resume-2026-10-09.md`, `docs/plan/reports/STATUS-before-CP2-resume-2026-10-09.md`, `docs/plan/reports/G2-G3-D6-D7.md` (superseded acceptance header; original builder evidence retained).

Body: Serialize commands before recovery and keep read summaries away from writers so listing cannot undo an active write. Protect chat-bearing storage and consume each confirmation once while preserving the shared JSON contract.

Remaining commit: C1 (G2/G3 committed). **Do not stage all:** E9/E10, B2 and D6/D7 remain unfinished, including the corrected D7 fixtures. No new patches are needed.

R10 through UI13 were committed and pushed by Claude on 2026-10-09; see Done.

## Decisions and reviewer findings

- **Ibrahim Q4 (2026-10-09):** orchestrator may commit the reviewed packages itself and must keep docs current. Approved Git staging worked; G2 commit verified in Git. Never push.

- **Ibrahim Q1:** reached copy reads “agent has reached here”; spec, catalogue and committed fixtures were changed in `773c831`.
- **Ibrahim Q2:** engine `theme` is the source of truth when D12 wires it; current app preference is a stand-in.
- **Ibrahim Q3:** Claude/Codex live run on two named throwaway chats has go; every app closure is still asked, and no working chat may be touched.
- **Reviewer G1:** at three accepted-uncommitted packages, stop for commits. G2/G3 and C1 are accepted after root checks and independent review. G1 is being cleared by actual commits; no waiver inferred. G4 was withdrawn because UI1–UI13 are already in the track. G5 closed by archiving the long page and retaining current state/ten logs. G6 live adapter acceptance remains owed.

## Questions and unresolved work

- E9/E10 review: source-writer brief privacy, immutable per-content transcripts, real brief creation/link movement, durable offer memory, digest on a fully received side, command classification, changed known IDs and exact >80% threshold. See the report; none is waived.
- D6/D7 review: 17 unknown catalogue IDs and 17 differing note occurrences in 27 fixtures; request-aware button and side routing; preserving creation through relaunch/attach choices; deferred-sync contract; ordinary/brief confirmation; actual catalogue IDs and wording; writer selection; preview for selected mode; fixed destination on a limit offer. See the report; none is waived.
- C1 is complete as a skeleton; C2/C3 commands and installed entry-point verification remain. Direct Engine callers must hold command_lock before first service access through apply. C4 must bound lock acquisition within its two-second deadline.
- B2 report explicitly lists guessed native schema/index/hook-trust assumptions. Those are not live evidence. B1's fixture acceptance also still needs its live check.
- Ctrl-Command-F integration remains D13 work; native green-button full screen was checked earlier. C2/D12 must replace preview settings and hand-made fixtures with authoritative engine responses.

## Log

- 2026-10-09 — G3 committed `7f6e39f`, only BrandTests and its report. C1 staging isolates its catalogue note from unfinished E9/E10; CP2 plan adds stale UI, brief cost/baseline and Codex rollback concerns.

- 2026-10-09 — Ibrahim authorized self-commits. Normal approved Git path succeeded: G2 `dab931c`, only its four reviewed files. G3/C1 next; two independent GPT-6.1 agents refining the CP2 repair plan. Fresh checks: 650 engine / 115 app, build green.

- 2026-10-09 — C1 accepted after root repairs, regressions and separate re-review. CLI command exclusion, private owned storage, no recovery on read, loader isolation and service-owned headline fixed. 119 focused / 650 full engine, 115 app and build pass. Three ready packages: stop under G1 for commits. CP2 not passed; no live chats or Git writes.

- 2026-10-09 — G3 accepted with independent review. Brand test checks explicit sRGB in both themes/badge states; root inspected both plain PNGs. Product logo unchanged. 115 app / 650 engine green; ready entry recorded.

- 2026-10-09 — G2 accepted with independent review. Bare check script builds and passes 115 app tests; explicit SDKROOT BrandTests check passes 4. Ready entry recorded; no Git writes.

- 2026-10-09 — Codex resumed the CP2 hand-off. Preserved all unfinished files; git read-only. Measured 640 engine tests with a D7 fixture failure; check script probe failed on unwritable module cache. Two independent reviewer agents found E9/E10 and D6/D7 blockers; G3 has no review blocker. C1 review and G2 repair started. Long prior status archived without discarding records.

- 2026-10-06 — UI12 complete at a green boundary: 379 engine / 96 app tests and Swift build pass with installed SDK flags. Ibrahim asked for a smaller application icon and the real signed logo in grayscale glass in the menu bar. The Dock tile now has transparent outer room; the menu renders the cached, cropped logo at 3× with the neutral decision badge. Independent review found a repeated 1254×1254 crop and a self-referential test; both were fixed, re-reviewed and retested. The previous fixture process was closed through its own Quit confirmation, the new temporary bundle signed/verified and relaunched, and Computer Use confirmed the current window. PNGs show both themes and badge states; the actual system menu-bar pixels were not captured. UI12 patch/report and ready entry recorded; no Git write, push or real chat access.

- 2026-10-06 — UI7 complete:377 engine/83 app/build pass with installedSDKflags. Kept exact existing B/I.A artwork after Ibrahim clarified surroundings only; no alternate-color asset adopted. Content is bare, Dock tile white, selector visible at sidebar bottom. Native Light/Dark switches inspected; user later selected System/Activity, so no further automation or relaunch. Review warning fixed with mounted offscreen native theme/retained-state assertions after layout settles; final full suite passes. UI7 ready after UI6; no Git or real-chat writes.

- 2026-10-06 — UI6 completed:377 engine /81 app/build pass. Imagegen transparent extraction replaces white runtime tile; brand/menu/theme/reduced-transparency PNGs inspected. Root native fixture confirms graphite signed gray-glass logo after exact-binary refresh. Separate reviewer warning closed by explicit native accessibility injection, opaque pixel assertions and Dock notification refresh; initial hosted view identity corrected. UI6 patch follows UI5; no Git/real-chat writes. SystemUIServer direct menu capture timed out, so no native item photograph claimed.

- 2026-10-06 — UI5 complete, UI4 shared gate closed: 377 engine / 79 app tests and Swift build pass with installed SDK flags. Signed burgundy/black I.A icon bundled and inspected on both themes and native fixture. Fixed independent review’s absent-sidebar guidance in popover, preserved intentionally note-less legacy fixture after a real failing compatibility test, and joined hidden-turn fallback to the first visible card. Separate reviewers confirm fixes. Ordered UI5 patch includes text and binary assets; no Git or real-chat writes.

- 2026-10-06 — UI3 completed at green boundary. Ibrahim answered “Yes, the window and controls are visible” for the running updated fixture. Native launch/fullscreen/Escape/sidebar gates passed; root377/74/build and independent review pass. Ready entry/ordered patch follow E8; no commit or push because Git remains read-only.

- 2026-10-06 — UI3 launch continuation checked by root and separate reviewer, no code blocker. Root377/74/build pass local SDK flags. Updated temporary fixture resources under Contents/Resources, LSUIElement=false, binary replaced; approved normal LaunchServices launch exited0. CUA confirms a main window directly, native full-screen button plus close/minimize, entry/exit via Escape, one-click sidebar after transition. Traffic-light screenshot area has a purple sharing overlay; Ibrahim’s visual confirmation pending. No real chat/tool app or Git write.
