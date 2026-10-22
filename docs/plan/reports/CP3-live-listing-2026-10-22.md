# Task K — CP3 live listing fixes, 2026-10-22

Implemented from the real-data shapes in the task. All verification used synthetic files and SQLite databases inside temporary folders; no real chat, tool data, app, CLI, spike script or live tool was accessed or controlled. No git command changed state.

## Changes

- Claude listing skips sidebar identities whose CLI session file cannot be found. Other readable entries remain listed. Direct resolution of the orphan still raises the existing KeyError used for missing chats; refusal handling was not changed.
- Cursor listing falls back from JSON/table lastUpdatedAt to JSON/table createdAt, and returns an empty time when neither exists. Zero remains a valid timestamp. Missing/invalid IDs, invalid JSON, non-object values and invalid/out-of-range times are skipped per row so other rows remain visible.
- Codex listing uses a separate read-only database connection and an explicit column projection: id, optional name, title, cwd, updated_at_ms/updated_at and archived. SQL filters archived threads and subagents using thread_source, agent_role and source when those columns exist. It never selects rollout_path, first_user_message, preview, instructions, usage or other content fields, and never opens a rollout. Threads can be listed even when no rollout path is recorded. References are ordered by update time, then ID. The existing recovery-free ReadViews projection filters by exact folder; no chats command change was necessary.

## Codex scope rule and remaining integration gap

Discovery grants no content or write authorization. Listing neither changes scope.original nor registers created descendants. Full-row queries, direct resolution, rollout access, reader/usage access and writer operations retain their existing explicit-ID scope checks. Scoped writer template selection still uses scoped_rows; discovery is not its input.

A link/write command must construct its adapter with only the explicitly selected chat IDs (and the existing verified created descendants). It must not grant scope to every ID returned by listing. Tests demonstrate that an empty-scope adapter can list metadata but cannot resolve/read/write those IDs, and a separately constructed adapter scoped to one selection reads only that chat.

**Integration gap found by source inspection:** baton/cli/wiring.py currently supplies no allowed_chat_ids, and the link command does not construct a selected-ID scope. Listing is repaired, but choosing a listed Codex chat in the current production link command will still need that separate explicit authorization wiring. This report does not claim linking on the real Mac is repaired. Wiring and link/write commands are outside Task K's named files; no scope was widened to conceal that gap. Suggestions also still attempts scoped content reads after discovery and may refuse an unscoped chat. Follow-up should scope only explicit selections/existing linked sides and preserve refusal for other content.

## Regression proof and validation

New module tests.adapters.test_live_listing has four tests covering the orphan Claude sidebar entry, Cursor nullable/malformed headers, Codex metadata discovery with SQLite column authorization and a file-open trap, exact folder filtering, unchanged scope, selected-ID reads, and the seconds/title fallback when optional Codex columns are absent.

Before implementation, running the new module produced:

```text
Ran 4 tests in 0.030s
FAILED (failures=1, errors=3)
```

The failures were Claude's orphan KeyError, Cursor's None timestamp TypeError, empty Codex discovery, and missing Codex metadata with optional columns absent.

Updated existing Codex assertions to expect discovery across scopes while retaining content/write refusals and the test that an unrelated rollout is never read or used as a create template. Updated the existing no-rollout expectation for metadata-only discovery. The first broader run exposed one more old empty-list expectation in the production-constructor test (264 tests, one failure); that assertion now also verifies both scope sets remain empty.

Final command (only affected adapter modules, no full suite):

```sh
python3 -B -m unittest tests.adapters.test_live_listing tests.adapters.test_claude tests.adapters.test_cursor tests.adapters.test_cursor_review tests.adapters.test_cursor_storage tests.adapters.test_codex tests.adapters.test_codex_coordination
```

Final output:

```text
Ran 264 tests in 11.760s
OK
```

Modules run: tests.adapters.test_live_listing, tests.adapters.test_claude, tests.adapters.test_cursor, tests.adapters.test_cursor_review, tests.adapters.test_cursor_storage, tests.adapters.test_codex, tests.adapters.test_codex_coordination.

`git diff --check`: no output, passed. Layer-import check with rg over baton/domain, baton/ports and baton/services: no matches. No user-facing sentences were added to code; no catalogue additions were needed. No app code or fixtures changed, so the app check was not run. No live verification was performed.

## Exact Task K file list

1. baton/adapters/claude/locator.py
2. baton/adapters/cursor/locator.py
3. baton/adapters/codex/locator.py
4. tests/adapters/test_codex.py
5. tests/adapters/test_codex_coordination.py
6. tests/adapters/test_live_listing.py (new)
7. docs/plan/reports/CP3-live-listing-2026-10-22.md (new)

No shared file edits: catalogue, ports and domain were untouched. codex/scope.py and the chats command were untouched. Existing unstaged hook/setup/catalogue/tests/report changes belonged to other work and were preserved; additional concurrent changes were left alone. No frozen contract or status/plan handoff files were edited. No contract addition is proposed: the Chat JSON shape and command signatures remain the same. Ready for review; no commit made.

## Cursor folder

Task CF adds folder discovery to `baton/adapters/cursor/locator.py` and appends twelve temporary-fixture tests to `tests/adapters/test_live_listing.py`. Existing unstaged work in both files was preserved. `baton/adapters/cursor/state.py` belongs to the other builder and was not edited.

When a header has no absolute folder or workspacePath, the locator reads each workspaceStorage folder's workspace.json file URI and its state.vscdb ItemTable entry `composer.composerData`. Membership in `allComposers` maps composerId to the decoded absolute folder. This exact mapping preserves literal hyphens, spaces and escaped URI characters, and wins over transcript evidence. Existing explicit absolute header paths remain supported, including workspacePath when folder is empty.

When membership is missing or conflicting, the locator uses the chat's `.cursor/projects/<key>/agent-transcripts/<id>/<id>.jsonl` location. A matching workspace URI supplies the exact path for that project key even when its composer list lacks the chat. Otherwise the fallback restores the leading slash and replaces key hyphens with slashes, following the encoding provided in the task (for example, `Users-ibrahimahmed-Desktop-projects-baton`). Conflicting transcript locations leave the folder empty; a chat without either source remains listed with an empty folder. The existing ReadViews exact equality filter needs no change.

Folder lookup scans each source once per listing, refreshes on the next call, opens workspace databases with mode=ro, and never reads transcript contents. It applies the locator's existing ownership, regular-file and symlink checks to metadata, databases and SQLite sidecars before opening them. Damaged, missing or unsupported workspace metadata is skipped independently, so another source can still supply the folder. Remote workspace URIs are not reported as local folders.

Evidence and limits: docs/SPIKE-M0.md and docs/features/more-tools.md were read, as was spike/m0b_cursor_create.py (source only, never executed). In this checkout that script contains no transcript folder-key encoding logic, so the supplied task's encoding is the evidence for the fallback. The key encoding is lossy for literal hyphens: without a matching exact workspace URI, a transcript key alone cannot distinguish a hyphen in a name from a replaced slash. No real Mac data was inspected and no live result is claimed; exact recovery of those ambiguous paths needs workspace evidence or another measured source.

Regression proof: before locator changes, the first eight new tests plus five existing tests ran with five failures, all showing empty folders instead of workspace/transcript paths. The test harness initially inherited existing tests and caused one duplicate-fixture error; that was corrected before the five-failure baseline. Four additional tests cover malformed metadata shapes, explicit workspacePath fallback, one read-only workspace scan without transcript-content reads, and refreshed evidence.

Only this test module was run for CF:

```sh
python3 -B -m unittest tests.adapters.test_live_listing
```

Final output:

```text
.................
----------------------------------------------------------------------
Ran 17 tests in 0.125s

OK
```

`git diff --check -- baton/adapters/cursor/locator.py tests/adapters/test_live_listing.py docs/plan/reports/CP3-live-listing-2026-10-22.md` passed with no output. Self-review checked exact-source precedence, ambiguous evidence, malformed shapes, read-only database access, symlink boundaries, fresh lookup and per-listing scan count. No shared catalogue, port or domain file changed, and no user-readable sentence was added to Python code. No app code or fixtures changed; no app check or full suite was run. No state-changing git command, real app/CLI control, real tool-data access, spike execution or live tool execution occurred. No contract addition is proposed.

Exact CF file list:

1. `baton/adapters/cursor/locator.py`
2. `tests/adapters/test_live_listing.py` (append only)
3. `docs/plan/reports/CP3-live-listing-2026-10-22.md` (this appended section)
