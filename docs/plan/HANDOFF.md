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

Current hand-off state: G2 `dab931c`, G3 `7f6e39f`, C1 `e15e076`, E9 `650a8d1`, D6 `604e6d8` are committed separately. Approved repair-plan/interface record `825137e` is committed. Ibrahim authorized self-commits; normal approved Git operations work. Never bypass sandbox-only read restrictions or push.

Stopped at the E9/D6 boundary because five-hour usage was100% consumed. Root measured working tree670 engine /129 app/build and isolated committed scope555 engine /119 app/build. Both packages had separate reviewers; E9 mixed timestamp anchor and five D6 routing/provenance findings are fixed. No package is in flight. E10/B2/D7 unfinished code remains; D7 includes compatibility edits for the D6 API. C2 not started; CP2/live not passed. See reports/CP2-2026-10-09.md for each check and pasted output.

Ibrahim approved CP2-REPAIR-PLAN.md product/boundary decisions: estimated costs before generation, separate generation/review/create, truthful summary coverage, action-specific controls and Automatic/Offline. Unsupported CP3 choices preserve the request and cannot confirm. Next: E10 and D7 repairs in parallel, at most two active agents; then B2 safety, C2 generation and scoped live gates. Preserve unfinished files and update STATUS/MAP/HANDOFF after every package.

Direct Engine callers hold engine.command_lock() before first service access through planning/applying; C4 must include bounded lock acquisition in its deadline. Prior live go is only for explicitly scoped throwaway chats; every app closure requires a fresh go. No real app/chat was accessed or push made this batch.
