# Status

The current hand-off page. Historical decisions, reviews and logs are in [reports/](reports/) and git history. Whole road: [MAP.md](MAP.md).

**Branch:** `chore/project-setup` · **Last checkpoint passed:** CP1, 2026-10-05 · **Working towards:** CP2 (not passed) · **Last checked:** 2026-10-10

## Now

**B2 fixture implementation/safety repairs committed `cbb3e2b`.** Root measured **730 engine tests,149 combined native fixture tests (108 Codex+41 Claude),77 CP2 scenarios,143 app tests and build pass**. All writes/reads remained temporary; no live chat/app access or push. [B2 report](reports/B2-2026-10-10.md), [current CP2 report](reports/CP2-2026-10-10.md). CP2 is **not passed**: C2 and native live evidence remain.

E9 `650a8d1`, D6 `604e6d8`, E10 `ec88983`, D7 `c8720bf`, G2 `dab931c`, G3 `7f6e39f` and C1 `e15e076` are committed. **C2a accepted, commit being prepared:** eight recovery-free read commands, private cached names/settings and full history including bookkeeping. Ibrahim Q8 chose new labels; independent final review approved with no findings. Root761 engine/150 focused/149 native/77 scenarios/143 app and build pass. [C2a report](reports/C2a-2026-10-10.md). C2b277 generated fixtures has not started; whole C2/CP2 remains incomplete. Historical untracked reports/E9-E10.md preserved. Normal approved Git writes work; never push. Session usage100%: commit this green package boundary and stop before C2b.

## Next

1. Commit accepted **C2a**, then stop at this green boundary. Next run: build/review **C2b** deterministic generated fixtures under [CP2-REPAIR-PLAN.md](CP2-REPAIR-PLAN.md); whole C2 stays incomplete until both. At most two agents.

2. C2 must prove service effects and identify future-only providers; D6/D7 transport counters are routing evidence only.
3. After blockers close, list exact Claude/Codex throwaway live scope and ask for each app closure. CP2 cannot pass without its live evidence.

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

## Ready to commit

### C2a — accepted after independent review

Exact paths:

- `baton/cli/commands/chats.py`
- `baton/cli/commands/history.py`
- `baton/cli/commands/links.py`
- `baton/cli/commands/merge.py`
- `baton/cli/commands/settings.py`
- `baton/cli/commands/setup.py`
- `baton/cli/commands/status.py`
- `baton/cli/commands/suggestions.py`
- `baton/cli/output.py`
- `baton/cli/tools.py`
- `baton/cli/wiring.py`
- `baton/ledger/read_metadata.py`
- `baton/ledger/schema.py`
- `baton/ledger/sqlite_store.py`
- `baton/notes/catalogue.py`
- `baton/ports/store.py`
- `baton/services/linker.py`
- `baton/services/merger.py`
- `baton/services/read_views.py`
- `baton/services/refresh.py`
- `baton/services/settings_read.py`
- `baton/services/setup_read.py`
- `baton/services/status.py`
- `baton/services/undo.py`
- `docs/plan/CONTRACT.md`
- `docs/plan/HANDOFF.md`
- `docs/plan/MAP.md`
- `docs/plan/STATUS.md`
- `docs/plan/reports/B2-2026-10-10.md`
- `docs/plan/reports/C2a-2026-10-10.md`
- `docs/plan/reports/CP2-2026-10-10.md`
- `docs/plan/track-c-cli-hooks.md`
- `tests/contract/test_read_commands.py`
- `tests/contract/test_shapes.py`
- `tests/unit/test_read_metadata.py`

Message:

```text
Show chat state without recovering unfinished writes

Screens need accurate chat status without undoing a write in progress.
Shared read projections preserve pending receipts, private content and
visibility evidence, while history distinguishes completed actions from
bookkeeping and retains known chat names across disappearance.
```

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


- E9/E10/B2 fixture safety accepted after independent reviews. C2 safe read serialization/generated fixtures and native live acceptance remain; no issue is waived.
- D6/D7 accepted for fixture screens; C2 service-backed/generated acceptance and D12 production integration remain. No native execution is inferred from screen transport tests.
- C1 is complete as a skeleton; C2/C3 commands and installed entry-point verification remain. Direct Engine callers must hold command_lock before first service access through apply. C4 must bound lock acquisition within its two-second deadline.
- B2 safe fixture implementation is accepted; native coordination/index/schema/marker/trust/visibility remain unverified and production mutation/automatic closure safely refuse. B1 live acceptance also remains owed.
- Ctrl-Command-F integration remains D13 work; native green-button full screen was checked earlier. C2/D12 must replace preview settings and hand-made fixtures with authoritative engine responses.

## Log

- 2026-10-10 — Ibrahim Q8 chose all bookkeeping visible with distinct labels. Root three actual-service/unknown-entry regressions and semantic mutant, separate final review: C2a accepted761 engine/150 focused/143 app/build;149 native/77 scenarios pass. Commit being prepared; C2b/live remain, no push.

- 2026-10-10 — C2a source green758 engine/147 focused/149 native/77 scenarios/143 app/build. Read-only pending-write safety, copy privacy, real history eligibility, visibility headlines and retained-name evidence reviewed/fixed. Separate final code review approved conditionally only on Q8 required display choice; C2a unaccepted/uncommitted, C2b/native live untouched. [C2a report](reports/C2a-2026-10-10.md).

- 2026-10-10 — B2 committed `cbb3e2b`:23 exact reviewed code/test/plan/report files, index empty; original E9-E10.md draft preserved untracked. No push/live access. C2 next.

- 2026-10-10 — B2 fixture safety accepted after independent final108 approval and root730/149native/77scenarios/143app/build checks. Scope/CAS/trust/format/continuous-lock mutants exercise real failure assertions. Native protocols/live still fail closed; commit pending, no push.

- 2026-10-10 — Resumed at Ibrahim’s request; B2 safety started with preserved dirty scope, C2 follows. Usage window reset naturally; no credit consumed. No live access/push.

- 2026-10-09 — D7 committed `c8720bf`, only36 reviewed app/fixture/plan files; index empty. E10/D7 complete, common702/143/build and isolated622 engine pass. Usage95% boundary: B2/C2/live remain, no push.

- 2026-10-09 — E10 committed `ec88983`, only30 reviewed engine/test/plan files; no B2/D7 files. Isolated622 engine and full702/143/build pass. D7 commit next.

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
