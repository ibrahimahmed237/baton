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

Current hand-off state: G2 committed `dab931c` through the normal approved Git path after Ibrahim authorized self-commits. G3 committed `7f6e39f`; C1 accepted, commit next; preserve the other unfinished package files. Sandbox-only Git writes remain restricted; request normal approval, never bypass permissions, never push. Current checks: 650 engine / 115 app, build green. Two agents are reviewing the concrete CP2 repair plan; no repair behavior has been approved from that plan yet.

Two independent reviewers found brief privacy/immutable-transcript and completeness issues (E9/E10) and wrong-action/presentation issues (D6/D7); none are waived. D7 false receipts/counts were corrected to restore common checks, but D7 is not accepted. B2 fixture tests pass but separate review/live acceptance is still owed. C2 is not started; CP2 has not passed. Full outputs/findings are in reports/CP2-resume-2026-10-09.md. After commits, resume STATUS Next using at most two agents. Do not run the live adapter check until the remaining package blockers are closed. No app was launched, no real chat read/written, no Git write or push in this resume.

Direct Engine callers must hold engine.command_lock() before first service access through planning/applying. C4 must bound lock acquisition within its two-second hook deadline. Ibrahim's prior live-run go remains, but each app closure still needs a fresh go.
