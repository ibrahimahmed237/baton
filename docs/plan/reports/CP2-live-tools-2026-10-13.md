# CP2 live tools: Codex native lock, and the step-by-step live script

2026-10-13. Nothing was run against a real home, a real chat or an app. All tests use homes built in temporary folders, with `no_processes()` active around every script call. 858 tests pass (825 before, +2 coordination, +31 script).

## 1. Codex native coordination (finished and reviewed)

`baton/adapters/codex/coordination.py` (`NativeCoordination`), wired only in `CodexAdapter.on_this_machine`. A plain or injected adapter still has `coordination=None` and refuses writes. The explicit chat scope (`allowed_chat_ids`) is still required exactly as before; the lock adds exclusion, not permission.

What it does, per write: require the id to be in scope; check every folder on the way is not a symlink (before creating anything); create the `thread-writer-locks` folder (0700) only if missing; open `<id>.lock` with `O_NOFOLLOW`, created with `O_EXCL` at 0600 (or opened if it exists); take an exclusive non-blocking `flock`, `ChatHeld` if it cannot; check regular file, ours, one link; record file and folder identity. `lease.check()` re-verifies identity (inode, link count, owner, folder inode, folder not a symlink) and raises `ChatChanged`. On exit it removes the file only if this process created it and it is still the same inode, then closes (lock released). `global_idle` raises `NotAvailable`, so automatic app closing stays off.

Review changes I made:
- The scope check and the symlink check of every ancestor now happen before `mkdir`. Before, a symlinked `~/.codex` would have had `thread-writer-locks` created through it before the refusal.
- Docstring records the lock-file-removal race as an open question (below).

Tests (`tests/adapters/test_codex_coordination.py`, 21 tests, 2 added): lock taken while inside and file gone after; released on failure; a lock file that was already there is left in place; file replaced or removed mid-lease fails `check()` and the replacement is not deleted; replaced folder fails `check()`; lock held by a subprocess gives `ChatHeld` with the file left and nothing written (add, rename, and a holder arriving after the writer's own check); symlinked lock path and symlinked lock folder refused with the target untouched; symlinked ancestor refused before anything is created (new); chat outside the scope refused and no lock file made (new); bad ids refused; a lock file replaced mid-write keeps the intent and a second adapter takes it back byte for byte; production path selects `NativeCoordination` (types only) and keeps the scope empty by default.

## 2. The live script

`tools/live/cp2_live.py` (not in the `baton` package; uses only the standard library and the package's adapters). Tests: `tests/unit/test_cp2_live.py`.

### Rules it enforces
- Needs `--codex-chat` and/or `--claude-chat` (Claude accepts the sidebar id `local_...` or the session id; exactly one sidebar entry must match).
- Guard before every step: the chat name must be exactly `Baton test (safe to delete)` and its folder must equal this repository's folder (`--repo` overrides, for tests). `rename-back` needs exactly `Baton test renamed (safe to delete)`. `inspect` and `restore` accept either exact title (restore must work from both states). On a mismatch it prints only `title_ok` / `folder_ok` booleans, never the real title or folder.
- Codex adapter: `allowed_chat_ids` is only that id. Claude has no scope in its adapter, so the script narrows the locator to the one sidebar entry (the adapter's format check otherwise reads every chat in the sidebar).
- No `--yes-write`: every writing step is a dry run (reads metadata for the guard, prints `would_read`, `would_write`, `backup_to`, writes and creates nothing).
- Before every write: a verified copy under `<backup-dir>/<tool>-<chat>/NN-<step>/` (0700/0600): `rollout.bak` or `session.bak` (+ `sidebar.bak` for Claude), `row.json` for Codex, `meta.json` with hashes.
- Every write goes through the adapter (`prepare` then `add`/`rename`/`take_back`). The one exception is `restore`, which puts back its own backup (atomic replace of the file; one SQL `UPDATE` of the thread row in a transaction, while holding the Codex thread lock).
- Output is one JSON line per chat: counts, record type names, sizes, hashes, paths. Never chat text. Exit codes: 0 done, 2 refused or result not as expected, 1 unexpected exception (traceback to stderr, JSON line, nothing more written, the second chat is not touched).
- `--home` swaps the home and uses inert adapters (no process control); without it the real home and `on_this_machine` are used.

### Commands (run from the repository root; `<T>` = Codex thread id, `<S>` = Claude sidebar or session id)
Use one explicit `--backup-dir` for the whole run, so take-back and restore find the add. Without it, a writing step makes a new `.baton-spike/backup/<timestamp>/`; take-back and restore then pick the newest folder holding that chat.

```
B=.baton-spike/backup/cp2

python3 tools/live/cp2_live.py --codex-chat <T> --step inspect
python3 tools/live/cp2_live.py --claude-chat <S> --step inspect

python3 tools/live/cp2_live.py --codex-chat <T> --step refuse-held --backup-dir $B            # dry run
python3 tools/live/cp2_live.py --codex-chat <T> --step refuse-held --backup-dir $B --yes-write

python3 tools/live/cp2_live.py --codex-chat <T> --step add --backup-dir $B                    # dry run
python3 tools/live/cp2_live.py --codex-chat <T> --step add --backup-dir $B --yes-write
python3 tools/live/cp2_live.py --codex-chat <T> --step take-back --backup-dir $B --yes-write

python3 tools/live/cp2_live.py --codex-chat <T> --step rename --backup-dir $B --yes-write
python3 tools/live/cp2_live.py --codex-chat <T> --step rename-back --backup-dir $B --yes-write

python3 tools/live/cp2_live.py --codex-chat <T> --step restore --backup-dir $B --yes-write
```
The same with `--claude-chat <S>` for Claude, or both flags in one call (Codex first, stops at the first failure).

### What each step proves
| Step | Proves |
|---|---|
| `inspect` | Format known on the real chat; held and replying are reported; turn count; the record types a real rollout/session holds (closes CP2 step A's open row 14, Codex record types, on the throwaway chat only); the history index offset as Codex really stores it. Read only; needs no `--yes-write`. |
| `refuse-held` | With the chat open in the app, the adapter answers `ChatHeld` and both files are unchanged. Needs the chat held; if it is not held nothing is attempted. Needs `--yes-write` because it takes a backup and attempts an add. |
| `add` | On a chat not held: backup first, then one turn through `prepare`/`add`; read-back has one more turn, earlier turns equal, prompt and reply as given, old bytes are a prefix. The reviewer then opens the chat to see the turn (Codex at once, Claude after a relaunch). |
| `take-back` | The adapter undoes that add: files (and for Codex the thread row) equal the backup byte for byte. Codex only allows it while its index has not read past the write. |
| `rename` / `rename-back` | Title change and its way back through the adapter, read back by name. Claude refuses while its app runs (`AppMustBeClosed`). |
| `restore` | Puts the oldest backup of the folder back byte for byte (and the Codex row), only when the chat is not held; holds the Codex thread lock during it. Warns `codex_index_is_past_the_restored_file` if Codex's index offset is beyond the restored size. |

Guard tests (fixture homes): other and near-miss titles refused for every step and both tools with nothing written and no backup folder; rename and rename-back title rules; other folder refused; unknown/malformed ids; dry runs change nothing and create no folders; backup exists and equals the original before `add` writes; add then take-back leaves the file (and Codex row, and Claude sidebar) byte-identical; restore after add, rename and a second add; held chat blocks add, take-back, rename and restore; a lock taken after the script looked still stops restore; refuse-held; inspect prints no chat text (a secret-word chat); unexpected exception exits 1 and the second chat is untouched; another Claude chat with a broken file is not read.

## 3. Files
- New: `baton/adapters/codex/coordination.py`, `tests/adapters/test_codex_coordination.py`, `tools/live/cp2_live.py`, `tests/unit/test_cp2_live.py`, this report.
- Changed: `baton/adapters/codex/tool.py` (production wiring).
- Untouched: `docs/plan/reports/E9-E10.md`, DESIGN, features, CONTRACT, STATUS, MAP, HANDOFF. No app fixture changes (no JSON output of any command changed); nothing regenerated.

## 4. Open questions and things to watch in the live run
1. How does Codex react when it loads a chat while Baton holds the lock file for a few milliseconds: wait, fail, or ignore? Not known; step B must watch it.
2. Removing a lock file we created is only safe if Codex never opens the same path meanwhile. If it opens our file and waits, then locks it after we delete it, it holds a deleted inode and a later Baton lock would not exclude it. Measure with the question above; if it can happen, stop deleting the file.
3. `CodexState.held()` probes with a momentary shared lock on an existing lock file, which could briefly collide with Codex loading that chat. Milliseconds, probably harmless, not measured.
4. Both adapters keep rollback intents and receipts under `<home>/.baton-rollback/` (on the real run: `~/.baton-rollback/`, mode 0700). An `add` leaves its intent until `take-back`; a `rename` leaves one too. After the run, list and remove them by hand (the script does not).
5. The Claude adapter has no chat scope. The script narrows only the locator; the adapter still reads the whole session registry (`~/.claude/sessions/*.json`, ids/pid/status) and the hook settings. A real `ClaudeAdapter` scope would be better than the script's workaround.
6. Claude `.desktop-released.json` files and id-named folders (CP2 step A) are not understood by the adapter and not touched by the script.
7. `restore` of a Codex chat that Codex has already read past leaves Codex's index ahead of the file (SPIKE-M0: Codex then writes at a position below its index). Prefer `take-back` right after `add` and before opening the chat, or accept that this chat is then not usable.
8. `restore` uses the oldest snapshot in the backup folder, so run all steps with one `--backup-dir` and treat `restore` as "back to before the first step".
9. Real `format_known` for Codex also depends on all records in the rollout's last 1 MiB being known types (`KNOWN_RECORD_TYPES`); a newer Codex record type makes `inspect` report `format_known: false` and every write refuse. That is the intended safety, and `inspect` shows which types exist.
10. Replying detection: a crashed task in a closed chat counts as replying and blocks writes (existing decision owed after the live run).
