# Task L — CP3 live-check fixes

Implemented 2026-10-22 using temporary homes/projects, fake process observations and standard-library Python only. No state-changing Git command, live tool command, app control, real chat/tool-data access, spike script, or live-check script was used.

## Changes

- **L5:** setup completes its existing read projection with a fresh check of the install record. It checks the recorded project file and executable, exact hook entries, and entry-point availability. Unrecorded entries do not establish readiness. Missing executables, missing/changed entries and invalid records produce actionable catalogue notes; an uninstalled tool gets an explicit install note. Attached-history eligibility uses the same finding. The read-only composition does not construct the app-control installation service. OpenCode file readiness no longer depends on an unavailable observation that its plugin loaded; the separate `loaded` value still reports only observed loading.
- **Codex:** installed entries remain distinct from trusted entries. Checks call the existing trust reader and never write trust. **Existing limitation retained:** the native trust schema/digest remains unverified, so the production reader deliberately returns false. Codex therefore reports `installed: true`, `trusted: false` with `setup.trust_once`; positive trust is tested through injected evidence, not a guessed native schema. Recognizing real native trust still requires verified format evidence.
- **L1:** a new project installation/removal requires an explicit project, or an explicitly injected project default. Existing records supply their project when no project is given. The CLI never substitutes its working directory. The filesystem port canonicalizes the project and refuses the home folder itself and `/`, including aliases resolving to them. An explicitly different project cannot redirect an existing installation.
- **L2:** new records retain an optional reference to the first installation backup, including across idempotent reinstallations; a null reference records that the file did not exist. Uninstall restores the exact backup bytes when remaining settings match, removes a Baton-created empty `hooks` key, and removes a Baton-created file when no other content remains. Otherwise JSON edits preserve surviving values, spelling and whitespace. Backups are also made when adopting already-present entries without changing their file.
- **Legacy records:** the two-field record format is still accepted. A unique, content-address-verified backup for the exact target can supply the original bytes. Missing or ambiguous legacy backup evidence is not guessed: uninstall removes owned entries conservatively, but cannot promise recovery of the original formatting or whether the original `hooks` key existed. New records preserve that evidence explicitly.
- **L3:** unknown, malformed, damaged and expired generic confirmations use `plan.invalid`, asking for a new preview. Setup confirmations validate their encoded request and use the same note. A generic chat fingerprint mismatch retains `write.chat_changed`; a wrong command retains `plan.wrong_action` and does not consume the other command's plan.

## Shared additive edits

- `baton/notes/catalogue.py`: added only `plan.invalid`, `setup.project_required`, and `setup.unsafe_project`; existing catalogue entries unchanged.
- `baton/ports/setup_install.py`: added `ProjectRequired`, `UnsafeProject`, and `InstallFiles.project_path(project)`. Project filesystem inspection stays in the adapter rather than the service.
- No domain file changed.

## Verification

477 tests passed with:

```sh
python3 -B -m unittest tests.unit.test_setup_install tests.unit.test_setup_check tests.unit.test_cli tests.adapters.test_claude tests.adapters.test_codex tests.adapters.test_cursor tests.adapters.test_opencode tests.contract.test_setup_install_recipes tests.contract.test_read_commands tests.contract.test_notes_audit tests.contract.test_opinion_setup_fixtures
```

30 additional affected hook tests passed with:

```sh
python3 -B -m unittest tests.unit.test_hooks tests.contract.test_hooks
```

Six selected regression tests were also run against the original implementation in a disposable copy: all six failed (five assertion failures and one missing-error-envelope failure). They cover missing-project refusal, exact CRLF backup restoration, preservation of later edits and whitespace, setup invalid confirmations, recorded installation readiness, and generic invalid confirmations.

The regressions also cover recorded project fallback, root/home refusal, legacy backup recovery, retention of the first backup across reinstall, backup creation for adopted entries, changed/missing entries, missing executables/entry points, and read-only trust handling. `git diff --check` passed. No whole-suite run, app build, or app fixture regeneration was performed; only the setup-install test recipe now supplies its explicit temporary project.

## Contract proposals (not edited)

Document the existing setup preview/confirm workflow's explicit `--project` requirement for new project installs, recorded-project fallback, home/root refusal, and the `plan.invalid`, `setup.project_required`, and `setup.unsafe_project` refusal notes. The optional internal install-record `backup` field is not an app response field. No existing response field was removed or renamed.

## Exact task file list

- `baton/adapters/claude/hooks.py`
- `baton/adapters/codex/hooks.py`
- `baton/adapters/cursor/hooks.py`
- `baton/adapters/opencode/hooks.py`
- `baton/adapters/setup_files.py`
- `baton/adapters/hook_json.py`
- `baton/services/setup_install.py`
- `baton/services/setup_check.py`
- `baton/cli/commands/setup_install.py`
- `baton/cli/commands/setup.py`
- `baton/cli/plans.py`
- `baton/ports/setup_install.py`
- `baton/notes/catalogue.py`
- `tests/unit/test_setup_install.py`
- `tests/unit/test_cli.py`
- `tests/adapters/test_opencode.py`
- `tests/contract/generate_fixtures.py`
- `docs/plan/reports/CP3-live-fixes-2026-10-22.md`

The pre-existing untracked `docs/plan/reports/E9-E10.md` was untouched. Concurrent changes appeared later in the Claude/Codex/Cursor locators, `tests/adapters/test_codex.py`, and `tests/adapters/test_live_listing.py`; none was edited or reverted by this task.
