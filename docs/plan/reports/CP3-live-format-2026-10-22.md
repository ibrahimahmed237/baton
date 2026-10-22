# Task FV — CP3 format checks and Codex trust

Implemented 2026-10-22. No state-changing Git command, worktree, real tool-data access, tool CLI/app launch, spike script, or live-check script was used. All chat/config fixtures were made in temporary directories, with fake or inert controls. Engine changes use only the Python standard library.

## Format checks

- Claude and Cursor tool status samples the five newest readable chats, ordered by native activity/update timestamps. Hidden chats remain eligible for that sample. Missing session files/composer data are skipped without consuming a sample slot. Unknown readable shapes in the sample still report an unknown format; older shapes outside it do not affect status.
- Claude and Cursor writers strictly validate the particular target, independently of the tool-wide sample. An unknown target refuses its write even when newer chats are known. Conversely, an unrelated unknown recent chat does not prevent writing a known target. Existing publication-time checks remain in place.
- Claude creates records using the newest readable chat's checked version. Adding uses the target's checked version and existing target prompt template. Creation checks its version source rather than all status samples.
- Cursor creation validates the scoped originals whose headers and role templates it copies. Writes to a previously created chat also validate the originals used for its role templates. Authorization is checked before target format reads.
- Codex status now explicitly orders and limits scoped rollouts to five readable recent chats, skipping missing files. Its condition reports that sample. Its existing full-target parser remains mandatory before writes, with schema validation independent of unrelated sampled chats. Target metadata that the locator cannot recognize refuses with `UnknownFormat` before mutation.
- Codex creation validates the schema and selected template chats, including their entire rollout, instead of depending on unrelated status samples. An incomplete or damaged template refuses creation, even though tolerant status/read operations can still inspect that chat. No tolerant read licenses a write.

## Codex trust

`CodexHooks.trusted()` reads the adapter home's `config.toml` using `tomllib`, and checks both measured table keys for the currently selected/recorded absolute hooks-file path:

```toml
[hooks.state."/absolute/project/.codex/hooks.json:user_prompt_submit:0:0"]
trusted_hash = "fixture-hash"

[hooks.state."/absolute/project/.codex/hooks.json:stop:0:0"]
trusted_hash = "fixture-hash"
```

Both values must be non-empty strings. Missing/malformed configuration, one missing event, empty/non-string hashes, and trust for another hooks-file path do not establish trust. The existing installed-entry and entry-point checks still apply. Trust reads do not modify configuration.

The reader does **not recompute or verify the hashes**: Codex's hash algorithm has not been verified. This implements the measured table-presence/non-empty-hash evidence requested for FV. The older Task L report's statement that the production trust reader deliberately always returns false is superseded by this task.

## Verification

Only the four touched test modules were run:

```sh
python3 -B -m unittest tests.adapters.test_claude tests.adapters.test_cursor tests.adapters.test_cursor_storage tests.adapters.test_codex
```

Final result: **233 tests run; 232 passed; one failure**:

- `tests.adapters.test_cursor.CursorSuite.test_round_trip` expects the created chat's relative folder `"folder"`; the concurrent Cursor locator change returns `""` because it accepts an absolute folder. This also fails when loading the original HEAD Cursor state and writer into memory while retaining the concurrent locator. FV did not edit the locator or change that test's expectation. The listing builder/orchestrator must reconcile that separate folder behavior.

Seven selected format/trust regressions were also run with original HEAD state/writer classes loaded into memory and the trust reader restored to `False`: all seven failed (five assertion failures, two `UnknownFormat` errors). No checkout or file rollback was used. These cover recent sampling/missing entries, scoped target writes, selected creation templates, measured trust, and recorded hook-path trust. The final focused run above exercises these tests with the implementation present.

Additional coverage retains unknown-target refusal without mutation, archived/hidden shapes, known shapes with new versions, missing bubbles, incomplete Codex templates, wrong hook paths, malformed TOML, and single-event trust. The TOML fixture is local to `test_codex.py`; the older guessed shared fixture helper was not edited.

`git diff --check` for the task files passed. No whole-suite run, app build, or app fixture change was made.

## Ownership and shared changes

The initial working tree already contained changes from other builders, including `codex/hooks.py` and `test_codex.py`. Those edits were preserved. FV changes only the `trusted()` reader in `codex/hooks.py`; the pre-existing `_installed()` change belongs to the other builder. Existing Codex tests in the shared test module were retained except for the format/trust expectations explicitly superseded here.

No catalogue, port, or domain file was changed by FV. No locator was edited. No frozen planning/design file was edited. No contract addition is needed: existing format and hook-readiness fields retain their types and meanings.

## Exact task file list

- `baton/adapters/claude/state.py`
- `baton/adapters/claude/writer.py`
- `baton/adapters/cursor/state.py`
- `baton/adapters/cursor/writer.py`
- `baton/adapters/codex/state.py`
- `baton/adapters/codex/writer.py`
- `baton/adapters/codex/hooks.py`
- `tests/adapters/test_claude.py`
- `tests/adapters/test_cursor.py`
- `tests/adapters/test_cursor_storage.py`
- `tests/adapters/test_codex.py`
- `docs/plan/reports/CP3-live-format-2026-10-22.md`
