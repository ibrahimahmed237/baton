# TASK SC — CP3 live scope repair, 2026-11-09

Status: command scoping and L6 implemented; one hook integration call awaits permission to edit outside the assigned files. No commit, push, app changes, or real-chat access.

## Implementation

`Engine.scope_for` in `baton/cli/wiring.py` computes separate identity sets for each tool from command arguments and active ledger links. The command registry calls it before service construction. Confirmations restore the original stored selection rather than authorizing replacement flags on the confirmation command. Relink targets, source/destination identities, tool/chat pairs, stored second-opinion requests, brief requests/artifacts and relaunch aliases resolve through this helper. Link-only commands obtain both sides from recorded links. A new command replaces the previous command's named identities. Sidebar discovery never expands authorization.

Codex, OpenCode and Cursor expose `scope_chats` to bind those identities. Existing durable creation-intent validation stays in place, and verified created descendants remain usable. Binding Codex updates the locator's scope as well as the adapter's. Binding OpenCode rebuilds its writer's scope-dependent receipt key. Cursor now guards content reads, usage and target format checks as well as writes; global format checks sample authorized identities only. Listing continues to return sidebar metadata across scopes.

Claude was inspected: it has no explicit chat allowlist or `require_chat` gate. Its root, path, process and write guards remain unchanged. This package applies the shared mechanism to all three adapters that already scope chats; it does not introduce an additional Claude access policy.

L6: `output.error` supplies nonempty tool/action/reason values for every `tool.cannot` refusal, preserving supplied values. Scope guards use the additive catalogue note `scope.chats_only`: “Baton can only use the chats you chose or linked.” Generic refusals use catalogue fallback labels/reasons; private exception strings are never rendered.

Default engine construction seeds linked chat scopes before verified-intent cleanup. Engines explicitly passed adapters keep their scope until command dispatch, which also preserves the selected scope in detached workers that reuse those adapters.

## Checks

Exact final command:

```sh
python3 -B -m unittest tests.unit.test_scope_wiring tests.unit.test_cli tests.contract.test_action_commands tests.adapters.test_codex
```

Output (progress dots omitted):

```text
Baton opens Codex at "Imaginary orchard".
OpenCode cannot be opened at a chat. Baton opens the folder; pick "Imaginary orchard" in the list.
Ran 249 tests in 4.755s

OK
```

`git diff --check` produced no output. Only the four named modules ran; neither the whole engine suite nor the app check ran.

The initial three-module baseline after implementation ran 240 tests and exposed one registry test that assumed the registered callable was never wrapped. That test now checks the wrapped callable's original identity and duplicate-registration behavior. The final count adds eight wiring fixture tests and one Codex descendant test.

Evidence:

- Claude ↔ Codex and OpenCode ↔ Cursor link previews use temporary native-shaped files and default empty scopes.
- A preview can be confirmed in a separately built engine without repeating chat arguments.
- Listing does not grant read, usage or prepare/write access to unnamed, unlinked scoped chats.
- A later command drops prior named IDs, and IDs never transfer between tools.
- Existing linked OpenCode/Cursor chats work for status and sync without chat arguments.
- A native Cursor prompt-hook payload catches up a linked chat after fresh engine construction and records the attached delivery. Its hooks and running process are fixtures.
- Codex reloads durable created descendants only through its matching private creation intent.
- Generic and scoped NotAvailable refusals have nonempty values and useful catalogue text.

## Remaining integration and ownership question

Native hook commands are dispatched before the ordinary command registry. `baton/hooks/runtime.py:invoke` parses and validates native stdin, creates the engine, acquires its lock and then observes/delivers. Consequently, command argument scoping alone cannot authorize an **unlinked** identity present only in native stdin. Linked-chat catch-up already works through the ledger scope and is tested.

The required remaining change is the following single call, inside the existing lock and before `observe`:

```python
engine.scope_for({'tool': args.tool, 'chat': call.chat})
```

This grants exactly the validated payload chat plus linked chats through the same wiring helper; payload mismatch and missing-chat rejection still happen first. An asynchronous question asks Ibrahim to authorize this edit because `baton/hooks/runtime.py` is outside TASK SC's explicit ownership list. No edit to that file has been made. Add fixture assertions for unlinked payload authorization and conflicting payload rejection once authorized; then rerun the same four modules.

## Files

Changed: `baton/cli/wiring.py`, `baton/cli/commands/__init__.py`, `baton/cli/output.py`, `baton/notes/catalogue.py`, `baton/adapters/codex/scope.py`, `baton/adapters/codex/tool.py`, `baton/adapters/opencode/tool.py`, `baton/adapters/cursor/tool.py`, `tests/unit/test_cli.py`, `tests/adapters/test_codex.py`.

Added: `tests/unit/test_scope_wiring.py` and this report.

The pre-existing untracked `docs/plan/reports/E9-E10.md` is untouched. Branch remains `chore/project-setup`. Wider planning documents were not edited because TASK SC assigns only this report.

## Review limits

This is fixture evidence, not a new real-Mac live check. Scope receipt fingerprints, path ownership checks, native exclusion, process-state restrictions and confirmation freshness were not relaxed. CONTRACT.md and existing catalogue definitions are unchanged. TASK SC is not fully complete until the payload-only hook integration above lands.

## Review round 1

SC-fix completed on 2026-11-09. The orchestrator's approved hook-runtime scope call is present and preserved; the earlier integration-pending statements above describe the original handoff, not the current tree.

The requested baseline reproduced 443 tests with 13 errors and two failures, all in Cursor. Create preparation tried to snapshot the generated destination through the newly guarded transcript locator before granting that destination scope. Direct fixture adapters also lost their existing unrestricted observation behavior: the fake desktop constructs a fresh adapter to simulate visible chats, and native format diagnostics sample recent composers, including hidden ones.

Cursor now distinguishes direct fixture observation from bound command observation. Direct construction retains the earlier content-reading and recent-format diagnostics; writes still require explicitly allowed or Baton-created IDs. Calling `scope_chats` enables the content allowlist, and `on_this_machine` binds it immediately, even before dispatch. Default production wiring already binds command scope before content observation. Scoped format checks inspect only authorized IDs, and sidebar listing remains metadata-only and does not grant access.

Create preparation grants its generated ID before snapshotting and saves the existing durable creation receipt. If snapshotting or saving the intent fails, that generated authorization is removed. Successful descendants remain readable and writable after restart under their matching receipt scope and remain authorized when command selection changes.

Regression coverage added for command-scoped prepare/create/restart, descendant retention when dropping the source selection, failed preparation authorization cleanup, scoped format sampling and refusal at each content entry point, and immediate guarding of machine adapters. Existing failing create, rollback, format and fake-desktop tests now pass unchanged.

Exact validation command:

```sh
python3 -B -m unittest tests.adapters.test_cursor tests.adapters.test_cursor_storage tests.adapters.test_cursor_review tests.adapters.test_live_listing tests.unit.test_hooks tests.contract.test_hooks tests.unit.test_scope_wiring tests.unit.test_cli tests.adapters.test_codex tests.adapters.test_opencode tests.contract.test_action_commands tests.unit.test_setup_install
```

Result: **447 tests passed in 13.257s**. An intermediate focused run of `tests.adapters.test_cursor`, `tests.adapters.test_cursor_storage`, `tests.adapters.test_cursor_review`, and `tests.unit.test_scope_wiring` passed 68 tests before adding the four regression cases. `git diff --check` passed. No full-suite or app checks ran; no app code or fixtures changed. No real chats, tool data, apps or tool CLIs were accessed or controlled by this fix.

Exact files edited by SC-fix:

- `baton/adapters/cursor/tool.py`
- `baton/adapters/cursor/writer.py`
- `tests/adapters/test_cursor.py`
- `docs/plan/reports/CP3-live-scope-2026-11-09.md`

All pre-existing uncommitted changes were retained. No edits to shared catalogue, ports or domain files; no other adapter or wiring edits were needed. No contract additions proposed. No git state changes, worktrees, commits, pushes or pull requests.
