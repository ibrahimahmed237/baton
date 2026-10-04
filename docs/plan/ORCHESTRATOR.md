# Orchestrator: how the build is run

One Codex chat is the **orchestrator**. It runs the work packages, checks them, records what happened, and hands the result to the **reviewer** (Claude, or Ibrahim) for approval. Anyone can pick the work up from [STATUS.md](STATUS.md) at any time: it is the single place that says where things stand.

## Roles

| Who | Does |
|---|---|
| Orchestrator (Codex chat "Baton orchestrator") | Picks the next packages from STATUS.md, implements them or gives them to worker agents, checks each one, keeps STATUS.md current, prepares commits, writes the hand-back report. |
| Worker agents (optional) | Implement one package each, in the folders that package lists. Never commit. Report what they did and what was unclear. |
| Reviewer (Claude or Ibrahim) | Reads the hand-back report, re-runs the checks, approves and pushes, or sends specific findings back. Updates the wider docs. |

## The loop, per package

1. **Read** the package in its track file, the requirement it cites, and ARCHITECTURE.md. If the package is unclear or conflicts with a spec, stop and write the question in STATUS.md under "Questions"; do not guess on anything that changes behaviour.
2. **Announce** in STATUS.md: package, started, folders it will touch.
3. **Build** it, with its tests, touching only the files the package lists. Two packages may run at the same time only if their folders do not overlap (engine `baton/` + `tests/` versus app `app/`).
4. **Check**, every time, and paste the real output into the report:
   - Engine: `python3 -m unittest discover -s tests -t .` — all pass; state the count.
   - Layer rule: `grep -rnE "^(from|import) .*(adapters|ledger)" baton/domain baton/ports baton/services` prints nothing.
   - No tool name in the core: `grep -rniE "claude|codex|opencode|cursor" baton/ports baton/services tests/adapters/suite.py` prints nothing new.
   - No sentence for the user outside `baton/notes/`.
   - App: `cd app && swift build && swift test` — all pass; state the count.
   - The package's own "Done when" line is true. Say how you know.
   - `git status --short` shows only files inside the package's folders.
5. **Challenge it** before calling it done: read the diff as a reviewer would. Look for behaviour the spec does not ask for, missing edge cases from the spec's scenarios, names that are not in the user's words, duplicated logic, tests that would pass even if the code were wrong. Fix what you find and say what you fixed.
6. **Prepare the commit**, do not push: one commit per package, only that package's files, message in the style of `git log` (a short subject, a body that says why). If the environment does not let you write to `.git`, list the exact paths and the message under "Ready to commit" in STATUS.md instead.
7. **Record** in STATUS.md: done, test counts, commit or ready-to-commit entry, anything left open.

## Hand-back report

After a batch (normally: up to the next checkpoint), write `docs/plan/reports/<checkpoint>-<date>.md` with:

- Packages done, each with: what was built in two or three plain sentences, files added and changed, test count before and after, the commit hash or ready-to-commit entry.
- Output of every check in step 4, pasted, not summarised.
- What was challenged and changed in step 5.
- Decisions taken that the plan did not settle, each with the reason.
- Gaps or contradictions found in the plan, specs or contract.
- What was **not** done or not verified, plainly.
- The checkpoint's own checks from CHECKPOINTS.md, each marked pass or fail with evidence.

The reviewer answers with **approved** or a numbered list of findings. Findings are fixed and the report is amended; nothing is argued away.

## Hard limits

- Never push, never open a pull request, never commit to `main`, never rewrite history.
- Never read or write real chats of Claude, Codex, OpenCode or Cursor, and never run the scripts in `spike/`. Adapter work uses fixtures built in temporary folders. Live checks belong to the reviewer and Ibrahim.
- Never change `docs/DESIGN.md`, `docs/features/*`, or the frozen parts of `docs/plan/CONTRACT.md`. Propose changes in the report.
- Never install software, change system settings, or approve permissions on Ibrahim's behalf.
- No `Co-Authored-By` or other attribution in commits.
- If a check fails and you cannot fix it within the package's scope, stop, record it, hand back.

## If the session is interrupted

STATUS.md is the memory. On start, read it, run the engine and app tests to confirm the recorded state is true, then continue from "Next". If the tests do not match what STATUS.md says, fix STATUS.md first and say so.
