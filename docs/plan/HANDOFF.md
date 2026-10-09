# Hand-off message

Paste this into the Codex chat (`codex://threads/01a1115f-070d-7982-b130-91876028685f`) when work moves there. Kept current by whoever is orchestrating; the date below says how fresh it is.

**Last updated:** 2026-10-09, Codex resumed the CP2 review

---

You are taking over as orchestrator of Baton from Claude. Read, in this order: `AGENTS.md`, `docs/plan/STATUS.md` (Now and Next), `docs/plan/MAP.md`, `docs/plan/ORCHESTRATOR.md`.

What changed since you last worked here:
- Everything you left as patches (R10 to UI13) is committed and pushed. The patch workflow is over: if you can write to git, commit one package at a time on `chore/project-setup`, message says why, no attribution, do not push unless I say "push".
- My three decisions: the reached line reads "*agent* has reached here" (spec, catalogue and fixtures already changed); the engine `theme` setting is the one source, wired in D12; live run of the Claude and Codex adapters has my go, each app close is still asked.
- App build and test: `app/scripts/check.sh`.
- Before touching anything run `git status --short`. Uncommitted files belong to a package that was being built when Claude stopped: read its report in `docs/plan/reports/`, run the tests, have a separate agent review it, then finish or fix it. Do not discard it.
- STATUS.md "Now" lists which packages were in flight and which files each owns.

Then continue with STATUS.md "Next". Update STATUS.md, MAP.md and this file after every package.

Current hand-off state: G2 `dab931c`, G3 `7f6e39f` and C1 `e15e076` are committed separately. Ibrahim authorized self-commits; normal approved Git writes work. Never bypass sandbox restrictions, never push. Committed C1 state was independently exported and passed 499 engine tests; the preserved unfinished working tree passed 650 engine / 115 app with build green before repairs.

Ibrahim approved the product and CP2/CP3 decisions in [CP2-REPAIR-PLAN.md](CP2-REPAIR-PLAN.md): estimated costs before generation, separate generation/review/create confirmations, truthful summary coverage, action-specific controls and Automatic/Offline. Unsupported CP3 actions retain the request and remain unconfirmable. Root added the contract/catalogue interfaces; engine E9 and app D6 repairs are now in parallel with at most two agents. E10/D7 follow, then B2/C2, independent package reviews, generated fixtures and the live gate. Preserve every unfinished file; STATUS lists ownership.

CP2 has not passed. B1 and B2 fixture success does not establish native compatibility. No real app/chat was accessed in this resume. Existing baseline/findings are in reports/CP2-resume-2026-10-09.md; current approved repair acceptance is in CP2-REPAIR-PLAN.md. Update this page, STATUS and MAP after every package.

Direct Engine callers must hold engine.command_lock() before first service access through planning/applying. C4 must bound lock acquisition within its two-second hook deadline. Ibrahim's prior live-run go remains limited to explicitly named throwaway chats and the listed run; every app closure still needs a fresh go.

Current boundary: E9 committed `650a8d1`; D6 independently accepted; working670 engine/129 app/build. E9 isolated555 engine. Isolated D6 build/tests119 pass; commit being finalized; no new package starts because five-hour usage reached100%. E10/D7/B2 unfinished files preserved; C2/live remain. Resume exact STATUS Next after this boundary, not the earlier baseline.
