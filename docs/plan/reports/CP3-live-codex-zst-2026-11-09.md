# TASK ZST — compressed Codex chats

Implemented on 2026-11-09. No Git state changes, app control, real chat access, live scripts, or external dependencies.

## Result

When a thread's recorded `.jsonl` file is absent, the locator checks its `.jsonl.zst` sibling. It keeps the existing sessions-folder, filename/ID, ownership, single-link regular-file, symlink, and explicit content-scope checks. A present plain rollout takes precedence. Explicit recorded `.jsonl.zst` paths also work. `CodexLocator.compressed(chat_id)` exposes the selected storage form without decoding it.

The reader, usage scan, reply-state scan, target-format check, recent-format check, and new-chat settings template can read compressed records. Decoding uses Python's standard-library `compression.zstd`, entirely in memory. Compressed input and decoded output are each limited to 64 MiB; the decoder window is limited to 64 MiB. Oversized, invalid, or truncated streams use the existing `UnknownFormat` refusal. No decompressed file is published.

Add and rename refuse compressed targets before preparation or mutation. The final publication guard rechecks compression. Restore and take-back refuse compressed targets, including a recheck under rollback exclusion; saved rollback intents remain available. Unsupported cut/place operations remain unsupported.

On Python without `compression.zstd`, metadata listing and safe path resolution still work. Content reading and reply-state scans refuse with the new Python-version note; format checks report unknown. The locator cannot validate the compressed payload's session ID on that runtime, so it defers that content check; content reads and all compressed writes are refused. Plain reads and writes remain available. New-chat creation can inherit settings from a compressed source when zstd support is available.

## Exact files for this task

- `baton/adapters/codex/locator.py`
- `baton/adapters/codex/reader.py`
- `baton/adapters/codex/state.py`
- `baton/adapters/codex/records.py`
- `baton/adapters/codex/writer.py`
- `baton/notes/catalogue.py`
- `tests/adapters/test_codex.py`
- `tests/adapters/test_codex_zst.py` (new)
- `tests/fixtures/codex/build.py`
- `docs/plan/reports/CP3-live-codex-zst-2026-11-09.md` (this report)

Shared-file edit: only two additive catalogue entries, `write.codex_compressed` and `read.codex_compressed_python`. No domain or port edits. The write note reads: “This Codex chat is stored compressed; open it in Codex once, then Baton can add to it.” The read note explains the Python 3.14 requirement. No contract additions are needed: refusals use the existing error/note envelope, and compression exposure stays inside the adapter.

Existing work was present in the Codex scope/tool, Cursor tool/writer, OpenCode tool, CLI/hook files, catalogue, Codex/Cursor/CLI tests and untracked reports/scope-wiring tests. Those edits were preserved. In the two overlapping files, this task only adds the two catalogue entries and `CodexPlainStorageCompatibility` in `test_codex.py`.

## Verification

Runtime: Python 3.14.7. Zstd fixtures are real compressed bytes generated with `compression.zstd` in temporary folders. New tests run under the no-processes guard with injected fixture process/coordination controls.

Only these test modules were run:

```text
python3 -B -m unittest tests.adapters.test_codex tests.adapters.test_codex_zst
.......................................................................................................................................
----------------------------------------------------------------------
Ran 135 tests in 2.077s

OK
```

The existing Codex module initially had 120 tests; this task adds one plain-storage compatibility test there and 14 compressed-storage tests in the new module. Coverage includes fallback/explicit paths, ordinary-file precedence, metadata discovery outside content scope, content-scope refusal, symlinks, hardlinks, directories, out-of-sessions paths, mismatched session identity, turns/usage/state, unfinished tasks, unknown records, invalid/truncated streams, compressed-input and decoded-output bounds, add/rename/restore/take-back refusals, late publication/rollback checks, compressed settings templates, missing zstd support, and no plain-copy publication.

Regression proof used an ordinary temporary copy of `baton/` and `tests/`, replacing only the five adapter implementation modules with their `git show HEAD:<path>` contents. This was not a worktree and did not alter the working repository. The same new test module failed against the pre-change implementations:

```text
python3 -B -m unittest tests.adapters.test_codex_zst
----------------------------------------------------------------------
Ran 14 tests in 0.124s

FAILED (failures=3, errors=12)
Pre-change adapter exit: 1
```

`git diff --check` produced no output. Imports remain within the adapter's permitted domain/port layers and the Python standard library. All added user-facing wording is in the catalogue. No app code or app fixtures changed, so the app check was not run. No whole-suite run.

## Review and limits

The first focused compatibility run found that an early take-back scope check changed the existing cross-scope forged-receipt rejection from `ValueError` to `NotAvailable`. The check now runs early only for IDs already in scope, retaining the original receipt-validation and created-chat recovery order. The existing regression passes. Added late-publication and under-exclusion rollback tests verify compression cannot bypass the final guards.

The 64 MiB limits are conservative builder choices, not measurements of real chat sizes. No live check was performed. Python older than 3.14 was simulated by making zstd unavailable; no older interpreter was run. Compressed writes remain intentionally unavailable until their effect is measured. No commit was made.
