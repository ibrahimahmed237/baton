# SI — hook installation and the installed baton command

Implemented the engine installation boundary for the CP3 live check. All work landed in the main repository. No Git state-changing command, worktree, commit, push, real coding-tool launch/control, real chat/tool-data access, spike execution or live script was used. The initial unrelated untracked `docs/plan/reports/E9-E10.md` was preserved.

## Built

- `baton setup install --tool T --json` returns a preview. `--confirm ID` applies the stored request after rechecking its fingerprint. `--dry-run` is also accepted. Uninstall has the same preview/confirmation boundary. Supplying another tool during confirmation cannot replace the stored request; confirmations for another action are refused without consuming that action's plan.
- `SetupInstall` owns the service logic through the new installation port. The command parses, dispatches and serializes; filesystem work lives in the adapter. Services contain no tool-name branches or user-facing sentences.
- Previews disclose absolute hook paths, exact hook/plugin entries, the absolute executable, the private installation-record path, and any backup path. Each file has a create/change/remove/unchanged action. Existing settings are fingerprinted byte for byte. Normal CLI plan/lock/store bookkeeping follows the existing CLI convention; previews do not write hooks, installation records or backups.
- Confirmation uses the exact rechecked snapshot rather than replanning again before writing. Both the hook file and ownership record are checked again at apply. Existing hook files are backed up byte for byte under `<BATON_HOME>/hook-backups`, with mode 0600, before replacement/removal. Content-addressed backups are never overwritten with different data. Hook publication and record publication use fsynced temporary files and atomic replacement.
- JSON installation preserves unrelated values, their original numeric/string spelling, unrelated hook entries and approval/trust fields. Changed container separators may be normalized. Duplicate keys, malformed JSON, malformed hook containers, non-UTF-8 files and unsafe file aliases refuse. Uninstall removes exact owned entries, preserves other hooks in mixed entries and their original byte spelling, and leaves absent/empty/unrelated settings alone. A changed OpenCode plugin is refused rather than overwritten or removed.
- Repeated installation leaves the hook file and identical ownership record unchanged and creates no new backup. Uninstall is likewise idempotent. It restores no earlier settings or unrelated entries.
- All four adapters generate commands using the installed absolute launcher path. The launcher records its identity in `BATON_COMMAND`; the engine persists that path at confirmation and reloads it for subsequent readiness checks and removal. Hooks invoke `catch-up`/`notify`; none of the installed hook entries invokes `python3 -m`.
- Codex's note tells the user to type `/hooks` and trust Baton's two entries; Baton neither writes nor claims native trust. OpenCode's note requests one restart. Cursor's note requests a restart as this task explicitly requires, although the recorded spike saw hooks load without one. Claude has no further step.
- `tools/install/install-baton.sh` installs only the small repository launcher at `~/.local/bin/baton`, using the available system `python3` and this repository through `PYTHONPATH`; no pip. It prints catalogue wording and refuses a different existing command, symlink path or multiply-linked destination. It was executed only by its authorized test with temporary HOME/tool/store folders, never as a real installation.
- `setup_install_recipe(tool, state, root)` in the fixture generator produces real command output for `preview` and `result` for each of the four tools. These are opt-in recipes tested against fake files and inert adapters.

## Verification

Final checks passed: `python3 -m unittest discover -s tests -t .` ran **1,345 tests**, all passing (48.606 seconds). `app/scripts/check.sh` passed its build, **185 UI tests + 21 kit tests**, and the **26-test fixture gate**. `git diff --check` passed. No unrelated failing test was encountered. The focused SI suite covers **14 tests**, including all four hook shapes; every preview path and first-use step; no hook/backup/ownership writes before confirmation; exact backups; JSON/approval preservation; malformed files; no-op install/uninstall; unrelated hooks; mixed hook entries; changed files and ownership records after replay; wrong-action confirmations; plugin conflicts; symlinks; missing launchers; persisted commands/project paths; and installed-launcher execution from a working folder outside this repository, with spaces in temporary HOME.

Installation tests use both the `no_processes` guard and a temporary-home guard on path opens, descriptor opens (including directory-relative opens) and SQLite connections. The one subprocess test runs only the installer and this repository's Baton launcher against isolated HOME, BATON_HOME and BATON_TOOLS_HOME; it verifies `baton links --json` returns an empty links list and drives setup preview/confirm through the installed launcher. Recipe tests run under `no_processes` too.

## Decisions where the plan was silent

- This task's explicit preview/`--confirm` requirement takes precedence over the frozen contract's older immediate-install sentence. The contract is unchanged; the additive/replacement documentation needed is proposed below.
- Installation requires an executable launcher before offering an install preview. The launcher supplies `BATON_COMMAND`; otherwise composition resolves `baton` on PATH, then the expected `~/.local/bin/baton` location. A stored installation retains its recorded executable even if PATH later changes. Uninstall does not require the executable still to exist.
- In production, the project-scoped OpenCode plugin and Cursor hook file use the command's current folder for a first installation. Injected roots use their isolated tool root. The recorded path is restored on later commands, so changing the working folder does not move or orphan the installed hooks. Sandboxed composition refuses a stored hook path outside its injected tool root.
- One installation location is recorded per tool. Installing in additional OpenCode/Cursor projects needs an explicit future folder-scoped ownership model; this task does not silently change project locations.
- The existing adapters specify JSON hook files and a generated JavaScript plugin. This task does not change or rewrite any TOML configuration, and never changes approval/trust configuration.
- New presentation wording is additive in the catalogue. The preview offers stable `install_hooks`/`uninstall_hooks` buttons; category and Check again labels are available for setup integration without changing existing setup responses or fixtures.

## Proposed contract additions

Document `setup install --tool T [--dry-run] [--json]` and `setup uninstall --tool T [--dry-run] [--json]` as preview routes; `setup install --confirm ID` and `setup uninstall --confirm ID` execute their stored requests. Reconcile the existing immediate-install exemption with this explicitly authorized confirmation flow, without removing any existing field/signature silently.

Document the setup-install/uninstall envelope: `plan_id`, `applied`, `tool`, `tool_label`, `executable`, `files: [{path, action, entries}]`, `notes`, and applied `backups: [absolute paths]`. `files` includes external hook files plus private installation records/backups; ordinary CLI plan/lock/store bookkeeping is unchanged. Entries are the exact generated hook/plugin configuration; unchanged files are explicitly identified. These are setup file plans, not chat/link Plans.

Document stable catalogue controls and presentation IDs: `setup.install_action`, `setup.uninstall_action`, `setup.install_review`, `setup.uninstall_review`, `setup.installed`, `setup.uninstalled`, `setup.install_refused`, `setup.command_missing`, `setup.no_hook_step`, `setup.restart_hooks`, `setup.category.hooks`, `setup.category.runner`, `setup.category.format`, `setup.check_again`, `setup.launcher_installed`, `setup.launcher_conflict`. Existing Codex/OpenCode first-use note IDs are reused.

## Generated fixtures

No existing `app/Fixtures` payload changes as a result of this work; the default manifest and existing setup response are unchanged. No fixtures were regenerated or hand-edited. The opt-in recipes can produce eight new files when the fixture owner is authorized to publish them:

- `app/Fixtures/setup-install.si_claude_preview.json`
- `app/Fixtures/setup-install.si_claude_result.json`
- `app/Fixtures/setup-install.si_codex_preview.json`
- `app/Fixtures/setup-install.si_codex_result.json`
- `app/Fixtures/setup-install.si_opencode_preview.json`
- `app/Fixtures/setup-install.si_opencode_result.json`
- `app/Fixtures/setup-install.si_cursor_preview.json`
- `app/Fixtures/setup-install.si_cursor_result.json`

Each would capture its named tool's production command preview/receipt against fake files. Their caller-owned absolute paths and ephemeral plan IDs need deterministic recipe identity/path inputs before adding them to the reproducible published manifest. No applied state is fabricated.

## Open questions and what is not done

- App routing/model/display changes remain with the app owner: the previously implemented D11 immediate install transport must display this file preview and its notes, then issue the separate confirmation. Existing `setup` responses are deliberately not given a new immediate-install button that would bypass that review. Category/check-again notes are available in the catalogue; emitting them in the existing setup read cards requires that owner's fixture regeneration.
- Publishing the new recipe fixtures, app UI acceptance and the CP3 throwaway-chat live check are not claimed. Codex trust and actual OpenCode loading remain user/native observations; writing a file is never reported as proof of those observations.
- JSON edits retain unchanged values/entries; formatting of changed object/array separators can change. Uninstall does not restore the complete original file from a backup. Unknown/edited plugin content and foreign/legacy commands are left alone rather than guessed to be owned.
- The current frozen contract and D11 immediate route wording need reconciliation with the requested review flow. No frozen contract, design/feature specification, status/map/handoff/checkpoint file, relaunch service or action command from a5e86fa was edited.

## Exact files added/changed

- `baton/adapters/claude/hooks.py`
- `baton/adapters/codex/hooks.py`
- `baton/adapters/cursor/hooks.py`
- `baton/adapters/opencode/hooks.py`
- `baton/adapters/hook_json.py` (new)
- `baton/adapters/setup_files.py` (new)
- `baton/cli/commands/setup_install.py` (new)
- `baton/cli/wiring.py`
- `baton/notes/catalogue.py`
- `baton/ports/setup_install.py` (new)
- `baton/services/setup_install.py` (new)
- `tests/contract/generate_fixtures.py`
- `tests/contract/test_setup_install_recipes.py` (new)
- `tests/unit/test_setup_install.py` (new)
- `tools/install/install-baton.sh` (new, executable)
- `docs/plan/reports/setup-install-2026-10-15.md` (this report)

Shared additive edits: `baton/cli/wiring.py` adds the lazy service, project/plugin constructor options and recorded-command/path loading; `baton/notes/catalogue.py` appends only the 16 IDs listed above; `baton/ports/setup_install.py` is a new dedicated installation boundary, with no existing port changed. The fixture generator only appends the opt-in recipe function. No existing shared file was reordered or reformatted.

## Review round 1

SI-fix closes the unsafe publication/backup, source-identity, permission and scope behavior within the assigned files. **Finding 4 remains partially open:** setup previews no longer persist a plan, but the normal CLI still constructs its database/lock before reaching this command. `baton/cli/main.py` is outside this builder's file list. Permission for the necessary setup-only dispatch/composition edit was requested and has not arrived; neither main.py nor wiring.py was changed in this round. Do not describe the complete CLI preview as read-only yet.

### Built and safety decisions

1. Configuration and ownership reads/publications now use pinned directory descriptors, a component-by-component `O_NOFOLLOW` directory walk, no-follow regular-file reads and descriptor-relative staging/link/replace/unlink. Backups are published without replacing an existing destination. Both original bytes and directory/file identity are rechecked after backups and immediately before each publication, including after ownership publication. Backup-time outside edits, missing-file races and directory/symlink swaps refuse without overwriting the outside content.

   **Native configuration-writer exclusion is not proven.** Advisory flock cannot exclude a writer that ignores it. SetupFiles therefore requires an injected continuous configuration coordinator and otherwise returns `setup.writers_unverified` before creating installation directories or changing any hook/ownership/backup file. Production composition supplies no coordinator, so real installation AND uninstallation remain disabled. Tests and opt-in recipes explicitly inject a coordinator for their exclusively owned fake files; that is not live verification. Preview facts disclose `configuration_coordination_verified` and add the refusal note when false. Existing-file and installer-directory flock provide additional cooperative exclusion, not the claimed native protocol. The verified coordinator must cover configuration/ownership writers and ancestor replacements through preparation, rechecks, publication and recovery.

2. Both replacements and rollback contents are staged before either file is published. Install publishes and fsyncs durable ownership before configuration; uninstall removes configuration before removing ownership. Interruption can leave harmless ownership of an unchanged/absent hook, but cannot leave a newly installed hook without its executable/path record. Ordinary publication failure restores already published files from the prepared contents, after checking that recovery will not overwrite an outside edit. Ownership publication failure leaves configuration exact. Configuration publication failure restores ownership. Failed record preparation publishes neither file.

3. JSON survivors retain their source paths through editing. Rendering matches their original array positions, including when an owned-only entry was removed before a mixed entry. Foreign numeric spelling (`1.00`), key order, escape spelling and unchanged entry bytes survive; no modified entry borrows a deleted entry's span.

4. Setup confirmation IDs carry the reviewed action/request, fingerprint and creation time (`p_si_` plus an encoded envelope); no preview calls PlanBook.remember or creates a plan file. Confirm decodes the request, checks the action/ten-minute lifetime, replans and compares the fingerprint before applying. The fingerprint includes exact ownership-record bytes as well as hook bytes. Wrong-action confirmation preserves the original token. Repeated effective writes are refused by changed fingerprints; unchanged confirmations can repeat harmlessly. Removing engine construction writes is still owed as described above.

5. Ownership-record changes/removal disclose and create exact private content-addressed backups, just like hook files. Even a formatting-only record rewrite is fingerprinted, labelled `change`, backed up and checked before mutation. The backup paths appear in `files` and applied `backups`.

6. Replacement stages preserve complete `stat.S_IMODE` bits, uid/gid and extended attributes; unsupported owner/group retention refuses. macOS ACL-bearing files refuse before mutation rather than silently losing their ACLs. ACL inspection and extended-attribute copy use standard-library ctypes against libc, with descriptor-based calls. Unknown ACL lookup/copy failures refuse. This managed Mac strips setuid/setgid when chmod runs; the regression injects those stat bits and verifies that complete `06750` reaches fchmod, alongside actual owner/group/ordinary-mode checks. A real temporary extended attribute is verified after replacement; ACL refusal uses an injected ACL result.

7. Added `--scope project|global` (project default) and optional `--project PATH`. Production previews default to the current project; isolated engine requests remain within their injected tool root. Measured project files are `<project>/.claude/settings.local.json`, `.codex/hooks.json`, `.opencode/plugins/baton.js`, and `.cursor/hooks.json`. Preview names the scope, project, every planned persistent path and entries. Each hook adapter's `global_location_verified` is false; global previews refuse with `setup.global_unverified` before configuration reads/writes. Global candidates are `~/.claude/settings.json`, `~/.codex/hooks.json`, `~/.config/opencode/plugins/baton.js`, and `~/.cursor/hooks.json`; none is claimed to load. The existing single recorded location per tool remains: a conflicting project request or legacy record outside the measured project shape refuses rather than migrating it silently.

### Verification

- Focused SI tests: **30 pass** (`python3 -m unittest tests.unit.test_setup_install tests.contract.test_setup_install_recipes`), up from 14. All run against temporary fake data; installer subprocesses are only the authorized fake-home launcher test.
- Full engine suite: **1,367 pass**, 42.453 seconds. The final missing-file refusal checks were then verified by the focused 30-test run. No SI test failed in the final runs.
- **17 reverse-check variants** run in a temporary copy of baton/tests: each targeted test fails when its relevant protection is removed. They cover backup/publication-time edits, directory swaps, ownership ordering/recovery, preparation before publication, source identity, persisted plans, record backup/fingerprints, special mode bits, ACL refusal, attribute retention, project defaults, global refusal, unverified coordinator refusal and missing-file preview races. No reverse-check changed this repository or another builder's files.
- `app/scripts/check.sh` passed the build, app tests and 26-test fixture gate. `git diff --check` passed.
- One intervening full run with output redirected reported nine failures and one error in **unowned** `tests/unit/test_hooks.py` and `tests/contract/test_hooks.py` (hook deadlines/empty output/SQLite timeout). Those two suites passed in isolation (30 tests); the following full run passed all 1,367. Their files were not changed. The failed run is recorded at `/tmp/baton-si-final-engine.log`; no cause is claimed.

### Shared additive edits and exact files changed this round

- `baton/adapters/hook_json.py`
- `baton/adapters/setup_files.py`
- `baton/adapters/claude/hooks.py`
- `baton/adapters/codex/hooks.py`
- `baton/adapters/opencode/hooks.py`
- `baton/adapters/cursor/hooks.py`
- `baton/services/setup_install.py`
- `baton/ports/setup_install.py`
- `baton/cli/commands/setup_install.py`
- `baton/notes/catalogue.py`
- `tests/unit/test_setup_install.py`
- `tests/contract/generate_fixtures.py`
- `docs/plan/reports/setup-install-2026-10-15.md`

Catalogue additions only: `setup.global_unverified`, `setup.scope_project`, `setup.scope_global`, `setup.writers_unverified`. The dedicated installation port adds the coordinator-verification property, exact record-source read, optional source snapshot at apply, and the two typed refusals. The fixture generator's existing opt-in SI recipe adds only a nullcontext import and explicitly injected fake coordinator. Existing shared code was not reformatted/reordered. `tests/contract/test_setup_install_recipes.py`, `tools/install/install-baton.sh`, main.py and wiring.py were not edited this round. All initial dirty/untracked work was retained. No Git state-changing command, worktree, frozen specification edit, real tool-data read, coding-tool launch/control, spike execution or live script was used.

### Fixtures and proposed contract additions

No published `app/Fixtures` file changes and none was regenerated. The eight opt-in `setup-install.si_{claude,codex,opencode,cursor}_{preview,result}.json` recipes would now include scope/project, both verification facts, the measured Claude project filename and self-contained confirmation IDs if their publication is later authorized. Exact record-backup coverage applies to change/uninstall receipts; the current fresh-install recipe does not fabricate an existing ownership record.

Propose additive documentation for the two scopes, optional project argument, measured/default paths, global/native-coordination refusal gates, preview verification facts, `p_si_` token format/lifetime/replanning, and ownership-byte fingerprints/backups. Clarify durable ownership ordering and ACL refusal. The old report's exception for CLI preview bookkeeping is superseded by the orchestrator's read-only decision; **do not approve a bookkeeping exception**. The remaining main/wiring dispatch must bypass ordinary store/lock construction for setup preview (and ideally for confirm, whose file coordinator provides exclusion). The frozen CONTRACT.md is unchanged.

### Open questions and what is not done

- **Finding 4 is not complete:** no plan file is created, but ordinary CLI construction still creates store/lock files that are not part of this setup plan. The orchestrator must authorize/own the setup-only main.py dispatch and read-only composition, then add a fresh empty-root filesystem-snapshot regression. The pending scope question names main.py and wiring.py precisely.
- **Native installation is intentionally refused** until live evidence establishes continuous exclusion of each tool's configuration writers. No real coordinator or native loading verification was guessed. The safety fixes must not be bypassed by injecting nullcontext in production.
- All global flags remain false until each tool's global loading has been proven in an authorized live check. Existing unexpected global ownership paths require an explicit reviewed migration/removal decision.
- One ownership location per tool, app routing/model integration, published fixtures and CP3 live acceptance remain outside this round. The launcher itself was not changed.

## Review round 2 — SI-fix2

### Built and decisions

The orchestrator settled both items left open in Review round 1. Production installation and uninstallation no longer require a verified native configuration coordinator. For hook configuration, the adapter declares that its app must be closed; wiring supplies its existing process `running` check. A true, unknown, or failed observation refuses the write with `setup.install_app_running`. Preview discloses that refusal, returns `can_confirm: false`, and the CLI supplies no confirmation token (`plan_id: null`). The user quits the app themselves; installation never calls app close, open, release, or signal operations.

Confirmation replans and checks app state again. The file adapter checks the same guard before installation directories, staging or backups, and immediately before each publication. The existing last-moment byte/metadata/ancestor fingerprint validation remains immediately before atomic replace/unlink. This is the orchestrator's app-closed rule, not a claim that an advisory lock excludes every native writer. Optional injected coordination and cooperative locks remain usable for fixture callers, but absence of a coordinator is no longer a production refusal. The earlier `setup.writers_unverified` note/type are retained as legacy shared definitions to respect additive-only catalogue/port edits; no production SI path emits them or requires their gate.

OpenCode's `baton.js` belongs to Baton. Its adapter declares no app-closed requirement, so it can install/remove that exact owned file even while its app runs or process observation fails. Ownership, backups, exact-content checks and last-moment fingerprints still apply.

Preview may create Baton's store and command lock inside its own folder. New catalogue note `setup.preview_bookkeeping` explicitly discloses the folder and says that every listed installation file waits for confirmation. Setup previews still create no persisted plan file; the self-contained confirmation token remains. This supersedes Review round 1's request to bypass store/lock construction and its rejection of a bookkeeping exception. No main.py change is required.

Where the plan was silent: the refusal wording covers both an observed running app and an unavailable process check. Guarding uninstall as well as install prevents removal from racing a running app. A late app start during staging refuses before publication; an app start after ownership publication is also guarded before hook publication, using the existing rollback handling. This does not establish a continuous native-writer exclusion protocol or eliminate the observation-to-replace race.

### Verification

- Focused SI unit and opt-in recipe suites: **36 pass** (previously 30).
- Full engine: `python3 -m unittest discover -s tests -t .` — **1,373 pass**, 49.104 seconds. Log: `/tmp/baton-si-fix2-engine.log`.
- `app/scripts/check.sh` — **passes**: build, **206 app tests** (185 + 21), and **26 fixture-gate tests**. Log: `/tmp/baton-si-fix2-app.log`.
- **Nine reverse-check variants** in separate temporary copies of baton/tests failed as expected: removing the running gate, restoring the coordinator requirement, dropping confirm's app guard, treating process failure as closed, dropping publication's app guard, requiring OpenCode's app closed, issuing a confirmation token for a refused preview, omitting bookkeeping disclosure, and writing an external hook file during preview. Script: `/tmp/baton-si-fix2-reverse.py`. No reverse-check modified the working repository.
- Regression coverage includes all three configuration adapters running/closed, app start between preview and confirmation, actual adapter process checks with injected `ps` failure, uninstall refusal, OpenCode's exception, app start during preparation, and a fresh CLI preview snapshot. The snapshot compares directories, file bytes, modes and file modification times outside Baton's folder; existing tool configuration and absent configuration paths remain unchanged. The fresh preview also asserts no plans folder.
- `git diff --check` passes. No unowned test failure was encountered in this round.

### Exact files changed this round

- `baton/adapters/setup_files.py`
- `baton/adapters/claude/hooks.py`
- `baton/adapters/codex/hooks.py`
- `baton/adapters/cursor/hooks.py`
- `baton/adapters/opencode/hooks.py`
- `baton/services/setup_install.py`
- `baton/ports/setup_install.py`
- `baton/cli/commands/setup_install.py`
- `baton/cli/wiring.py`
- `baton/notes/catalogue.py`
- `tests/unit/test_setup_install.py`
- `docs/plan/reports/setup-install-2026-10-15.md`

Shared edits are small and additive: `ports/setup_install.py` adds the bookkeeping root property, optional pre-publication callback argument, and `InstallAppRunning`; `cli/wiring.py` passes the adapter process checks into SetupInstall; the catalogue adds only `setup.install_app_running` and `setup.preview_bookkeeping`. No shared code was reordered or reformatted. Initial modified/untracked work, including fixture generator changes and hook_json.py, was carried forward and not reverted. No Git command changed state, no worktree was used, and no real chat/tool-data read, real app/CLI control, spike execution, or live script was performed.

### Fixtures, proposed contract additions, and remaining scope

No `app/Fixtures` file was regenerated or changed. If the opt-in recipes are later published, these exact eight outputs change:

- `setup-install.si_claude_preview.json`
- `setup-install.si_claude_result.json`
- `setup-install.si_codex_preview.json`
- `setup-install.si_codex_result.json`
- `setup-install.si_cursor_preview.json`
- `setup-install.si_cursor_result.json`
- `setup-install.si_opencode_preview.json`
- `setup-install.si_opencode_result.json`

They gain the bookkeeping note and `can_confirm`; their facts replace the prior coordinator-verification field with `requires_closed_app` and `app_running` (OpenCode's requirement is false). Token fingerprints are unaffected by app observations/bookkeeping prose. No new running-state fixture recipe was authored or published.

Propose contract documentation for the app-closed configuration rule, failure-as-running, OpenCode's owned-file exception, refused previews' null plan ID and false `can_confirm`, the two fact fields, and the explicit preview bookkeeping allowance. These supersede the earlier proposed mandatory native-coordination refusal gate. CONTRACT.md remains frozen and unchanged.

Both assigned findings are closed. No open implementation question remains for SI-fix2. Native/global loading verification, live app checks, app routing/model integration, published fixture regeneration and the existing one-location ownership policy remain outside this task. No native installation or process behavior was claimed from these fixture tests.
