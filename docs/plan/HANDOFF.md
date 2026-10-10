# Hand-off message

Paste this into the Codex chat (`codex://threads/01a1115f-070d-7982-b130-91876028685f`) when work moves there. Kept current by whoever is orchestrating; the date below says how fresh it is.

**Last updated:** 2026-10-10, B2 fixture safety accepted

---

You are taking over as orchestrator of Baton from Claude. Read, in this order: `AGENTS.md`, `docs/plan/STATUS.md` (Now and Next), `docs/plan/MAP.md`, `docs/plan/ORCHESTRATOR.md`.

What changed since you last worked here:
- Everything you left as patches (R10 to UI13) is committed and pushed. The patch workflow is over: if you can write to git, commit one package at a time on `chore/project-setup`, message says why, no attribution, do not push unless I say "push".
- My three decisions: the reached line reads "*agent* has reached here" (spec, catalogue and fixtures already changed); the engine `theme` setting is the one source, wired in D12; live run of the Claude and Codex adapters has my go, each app close is still asked.
- App build and test: `app/scripts/check.sh`.
- Before touching anything run `git status --short`. Uncommitted files belong to a package that was being built when Claude stopped: read its report in `docs/plan/reports/`, run the tests, have a separate agent review it, then finish or fix it. Do not discard it.
- STATUS.md "Now" lists which packages were in flight and which files each owns.

Then continue with STATUS.md "Next". Update STATUS.md, MAP.md and this file after every package.

Current hand-off state: G2 `dab931c`, G3 `7f6e39f`, C1 `e15e076`, E9 `650a8d1`, D6 `604e6d8` are committed separately. Approved repair-plan/interface record `825137e` is committed. Ibrahim authorized self-commits; normal approved Git operations work. Never bypass sandbox-only read restrictions or push.

Prior E9/D6 usage stop is historical. E10/D7 are independently accepted and committed: root702 engine /143 app/build; initial privacy/lifecycle/atomic brief coverage and hand-off display gates fixed, with actual-effect and adversarial tests. E10 `ec88983` and D7 `c8720bf` committed; stopped at this boundary because five-hour usage95%. Preserve unfinished B2 Codex files/tests and old reports. C2 not started; CP2/live not passed. Package reports and CP2-2026-10-09.md contain pasted checks/review findings.

Ibrahim approved CP2-REPAIR-PLAN.md product/boundary decisions: estimated costs before generation, separate generation/review/create, truthful summary coverage, action-specific controls and Automatic/Offline. Unsupported CP3 choices preserve the request and cannot confirm. Next batch: B2 safety, then C2 generation and scoped live gates, at most two active agents. Preserve unfinished files and update STATUS/MAP/HANDOFF after every package.

Direct Engine callers hold engine.command_lock() before first service access through planning/applying; C4 must include bounded lock acquisition in its deadline. Prior live go is only for explicitly scoped throwaway chats; every app closure requires a fresh go. No real app/chat was accessed or push made this batch.

2026-10-10 resume: B2 safety started, existing native files preserved. Worker owns Codex adapter/native tests/fixtures; root owns plan records. C2 follows B2 acceptance. No live access or push; no usage reset credit used.

B2 fixture implementation/safety accepted: root730 engine/143 app/build,149 native fixtures,77 CP2 scenarios. Full-row CAS, continuous fixture coordination, explicit scope/private recovery, aliases/index/trust refusals and publicSQL guard reviewed. Commit pending; C2 follows. Production native writes/automatic closure stay unavailable until verified native coordination/trust/schema; no live acceptance. Current evidence CP2-2026-10-10.md.
