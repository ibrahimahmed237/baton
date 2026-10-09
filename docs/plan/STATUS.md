# Status

The current hand-off page. Historical decisions, reviews and logs are in [reports/](reports/) and git history. Whole road: [MAP.md](MAP.md).

**Branch:** `chore/project-setup` · **Last checkpoint passed:** CP1, 2026-10-05 · **Working towards:** CP2 (not passed) · **Last checked:** 2026-10-09

## Now

**E10 and D7 are independently approved and preparing separate commits.** Root measured **702 engine /143 app tests and build pass**. Engine privacy/cache/atomic creation and undo fixes were challenged; app cost/artifact/offer/stale gates were reviewed. Five-hour usage reached95%, so stop after these commits at a green package boundary; do not start B2/C2 this batch. No push or real-chat access.

Resume baseline (before E10/D7 edits): **670 engine tests, 129 app tests and build pass**. Previous isolated committed package verification: **555 engine**, **119 app and build**, excluding unfinished E10/B2/D7. Full evidence and each CP2 gate: [CP2-2026-10-09.md](reports/CP2-2026-10-09.md). **CP2 has not passed.**

| Package | State and preserved ownership |
|---|---|
| E9 | Committed `650a8d1`; [report](reports/E9-2026-10-09.md). Legacy baselines stay unverified; ordinary refresh readable, digest unavailable until a fresh explicit link establishes verified scope. |
| D6 | Committed `604e6d8`; [report](reports/D6-2026-10-09.md). Fixture-screen routing/display acceptance; C2 service-backed evidence and CP3 execution still owed. |
| E10 | Accepted after independent re-review and root checks; commit preparing. Report: [E10](reports/E10-2026-10-09.md). |
| B2 | Unfinished `adapters/codex/` native implementation and native fixtures/tests/report; only E9 standalone reader classifier committed. Safety repairs and live acceptance owed. |
| D7 | Accepted for CP2 fixture-screen scope after independent re-review; 143 app/build pass. Commit follows E10 catalogue. C2 generation still owed. |
| C2 | Not started: read projections/commands, authoritative generation and manifest. |

G2 `dab931c`, G3 `7f6e39f`, C1 `e15e076` and approved plan/interface record `825137e` were committed earlier in this batch. Normal approved Git writes work; sandbox-only `.git` remains read-only. Preserve every unfinished file.

## Next

1. Finish recording the separate accepted E10 and D7 commits, then stop at this green boundary because five-hour usage is95%.
2. Next batch: repair/review **B2 native safety**, then **C2 safe reads and deterministic generated fixtures**, under [CP2-REPAIR-PLAN.md](CP2-REPAIR-PLAN.md). Preserve all unfinished native files; at most two agents.
3. C2 must prove service effects and identify future-only providers; D6/D7 transport counters are routing evidence only.
4. After blockers close, list exact Claude/Codex throwaway live scope and ask for each app closure. CP2 cannot pass without its live evidence.

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

## Ready to commit

E10 and D7 accepted; normal approved Git commits are being prepared separately. Exact paths and messages are in their package reports. B2 remains unfinished; C2 not started.

## Decisions and reviewer findings

- **Ibrahim Q5 (2026-10-09):** approved estimated-cost-before-agent-generation, separate generated-brief review/create, truthful summary receipts, action-specific confirmation/Cancel and Automatic/Offline. Approved unavailable CP3 alternatives preserving the original request, and the planned CP2 fixture/service versus CP3 execution boundary. See CP2-REPAIR-PLAN.md; additive CONTRACT/copy recorded before workers start.

- **Ibrahim Q4 (2026-10-09):** orchestrator may commit the reviewed packages itself and must keep docs current. Approved Git staging worked; G2 commit verified in Git. Never push.

- **Ibrahim Q1:** reached copy reads “agent has reached here”; spec, catalogue and committed fixtures were changed in `773c831`.
- **Ibrahim Q2:** engine `theme` is the source of truth when D12 wires it; current app preference is a stand-in.
- **Ibrahim Q3:** Claude/Codex live run on two named throwaway chats has go; every app closure is still asked, and no working chat may be touched.
- **Reviewer G1:** at three accepted-uncommitted packages, stop for commits. G2/G3 and C1 are accepted after root checks and independent review. G1 cleared by G2/G3/C1 commits; no waiver needed. G4 was withdrawn because UI1–UI13 are already in the track. G5 closed by archiving the long page and retaining current state/ten logs. G6 live adapter acceptance remains owed.

## Questions and unresolved work

- E9 and E10 accepted after independent review. B2 safety/live and C2 safe read serialization/generated fixtures remain; no issue is waived.
- D6/D7 accepted for fixture screens; C2 service-backed/generated acceptance and D12 production integration remain. No native execution is inferred from screen transport tests.
- C1 is complete as a skeleton; C2/C3 commands and installed entry-point verification remain. Direct Engine callers must hold command_lock before first service access through apply. C4 must bound lock acquisition within its two-second deadline.
- B2 report explicitly lists guessed native schema/index/hook-trust assumptions. Those are not live evidence. B1's fixture acceptance also still needs its live check.
- Ctrl-Command-F integration remains D13 work; native green-button full screen was checked earlier. C2/D12 must replace preview settings and hand-made fixtures with authoritative engine responses.

## Log

- 2026-10-09 — E10/D7 independently accepted. Root702 engine/143 app/build; privacy, durable replay and summary-boundary undo mutants detected. Five-hour usage95%: commit both and stop before B2/C2. No live access/push.

- 2026-10-09 — Resumed E10/D7 repairs with preserved dirty scope and at most two agents. Fresh baseline confirmed: 670 engine /129 app, build pass.

- 2026-10-09 — D6 committed604e6d8 after five routing/provenance findings were fixed and independently re-reviewed. Root full670/129/build; isolated555 engine/119 app/build. Usage window100%: stop at this package boundary. CP2 report marks remaining gates fail; no live access/push.

- 2026-10-09 — E9 committed650a8d1 after durable subprocess/evidence checks, mixed-timestamp root fix and independent acceptance. Focused73/full670/isolated555 engine; final app129/build. Three regression mutations detected. No E10/D7 repair started.

- 2026-10-09 — Ibrahim approved both repair-plan questions. Two GPT-6.1 agents reviewed the written plan; lifecycle, fallback costs, coverage, canonical-evidence ordering, read projections and live allowlist refinements incorporated. E9/D6 starting with shared additive contract/catalogue settled.

- 2026-10-09 — C1 committed `e15e076`, with only its catalogue hunk and exact reviewed files. Staging whitespace check exposed an extra EOF blank line but commit was not gated; follow-up removes that whitespace without behavior change. All other package files preserved; reviewed repair plan is next.

- 2026-10-09 — G3 committed `7f6e39f`, only BrandTests and its report. C1 staging isolates its catalogue note from unfinished E9/E10; CP2 plan adds stale UI, brief cost/baseline and Codex rollback concerns.

- 2026-10-09 — Ibrahim authorized self-commits. Normal approved Git path succeeded: G2 `dab931c`, only its four reviewed files. G3/C1 next; two independent GPT-6.1 agents refining the CP2 repair plan. Fresh checks: 650 engine / 115 app, build green.

- 2026-10-09 — C1 accepted after root repairs, regressions and separate re-review. CLI command exclusion, private owned storage, no recovery on read, loader isolation and service-owned headline fixed. 119 focused / 650 full engine, 115 app and build pass. Three ready packages: stop under G1 for commits. CP2 not passed; no live chats or Git writes.

- 2026-10-09 — G3 accepted with independent review. Brand test checks explicit sRGB in both themes/badge states; root inspected both plain PNGs. Product logo unchanged. 115 app / 650 engine green; ready entry recorded.

- 2026-10-09 — G2 accepted with independent review. Bare check script builds and passes 115 app tests; explicit SDKROOT BrandTests check passes 4. Ready entry recorded; no Git writes.

- 2026-10-09 — Codex resumed the CP2 hand-off. Preserved all unfinished files; git read-only. Measured 640 engine tests with a D7 fixture failure; check script probe failed on unwritable module cache. Two independent reviewer agents found E9/E10 and D6/D7 blockers; G3 has no review blocker. C1 review and G2 repair started. Long prior status archived without discarding records.
