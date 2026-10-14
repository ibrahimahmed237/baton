# Track C — command line, hooks, relaunch, background runs

Thin layers over the services. No rules live here: a command parses, calls one service, prints the JSON of [CONTRACT.md](CONTRACT.md).

---

## C1. Command skeleton and wiring

**Goal.** `baton` runs, builds the adapters once, prints contract JSON.
**From.** CONTRACT.md rules.
**Depends on.** E1, B0.
**Files.** `baton/cli/{__init__,main,wiring,storage,output,tools,plans}.py`, `baton/cli/commands/{__init__,links}.py`, `pyproject.toml` (entry point `baton`). Additive shared changes: `baton/services/status.py` headline selection, catalogue `error.unexpected`. Tests: `tests/unit/test_cli.py`, `tests/contract/{__init__,test_shapes}.py`.
**Steps.** 1. `wiring.build(root=None) -> Engine` creates the store (`~/Library/Application Support/Baton/baton.sqlite`), the four adapters, the services. `BATON_HOME` overrides the location for tests. 2. `output.py` turns results and errors into the shared objects. 3. Global flags `--json`, `--dry-run`, `--confirm`. 4. Plan ids: a plan is stored for ten minutes with a hash of the chats' state; `--confirm` re-checks it.
**Tests.** `tests/contract/test_shapes.py`: each shared object has exactly the documented fields.
**Done when.** `baton links --json` prints `{"links": []}` on an empty home.

**Resume review, 2026-10-09.** CLI dispatch and ledger initialization use one OS-held per-root command lock. Recovery can interpret pending writes as abandoned only while holding that lock. Direct Engine callers must lock before first service access and retain it through planning/applying. Read summaries use ChatRefresh, never construct recovery/writer services. Validate owned storage paths without following symlinks; root is 0700, database/lock files 0600. C4 must bound lock acquisition within its two-second hook deadline rather than inherit an unbounded wait.

## C2. Read commands

**Goal.** `setup`, `chats`, `suggestions`, `links`, `status`, `history`, `merge --show`, `settings get`.
**From.** CONTRACT.md; sync-status R1 to R16.
**Depends on.** C1, E2, E9, the catalogue through CP2. E12 (CP3) completes/audits the remaining catalogue; it cannot be a prerequisite for CP2 read commands.
**Files.** `baton/cli/commands/{setup,chats,suggestions,links,status,history,merge,settings}.py`, `cli/{wiring,output,tools}.py`, recovery-free `services/{read_views,settings_read,setup_read}.py`; read projection extraction in `services/{linker,merger,refresh}.py`; additive `services/status.py` headline selection for existing relaunch/reopen requirements; narrow shared recovery-free Undo/Restore planning seam in `services/undo.py` for truthful history eligibility (no apply/recovery change); additive `ports/store.py`, `ledger/{schema,sqlite_store,read_metadata}.py`; Ibrahim-approved history/preset labels in `notes/catalogue.py`; `tests/contract/test_read_commands.py`, compatibility assertions in `tests/contract/test_shapes.py` and `tests/unit/test_cli.py`, private metadata tests in `tests/unit/test_read_metadata.py`; additive history-bookkeeping documentation in CONTRACT.md. C2b owns `tests/contract/{fixture_manifest,generate_fixtures,test_fixtures}.py`, generated `app/Fixtures/`, and narrow fixture-test compatibility in `app/Tests/Baton{UI,Kit}Tests/` (ComponentTests private test-root routing, LinkDialog, decoding/transport, Popover, Window, SyncStatus, Receipt, HandOff, PlanReview expectations), plus FixtureEngine documentation and additive per-tool read-fixture routing; EmptyStateTests follows that route. Preserve behavioural assertions; no production UI policy changes to accommodate bad fixtures.

**Orchestrator execution decision, 2026-10-10 (checked by a separate reviewer agent).** C2 has two independently checked green boundaries: C2a read commands/projections, then C2b deterministic manifest/generation. C2 is complete only after both; C2a does not satisfy generated-fixture acceptance or promote CP3 actions. Each boundary has a report and one commit. This limits interruption risk across the large277-file fixture replacement without changing the contract or checkpoint requirements.
**Tests.** C2a: `tests/contract/test_read_commands.py`. C2b: `tests/contract/test_fixtures.py` verifies catalogue/state semantics, service effects, deterministic generation into temporary folders and agreement with every tracked fixture. Explicit regeneration via `python3 -m tests.contract.generate_fixtures` writes `app/Fixtures/*.json`; ordinary tests never modify tracked files.
**Done when.** Fixtures exist for every screen state and are generated, not hand-written.

**Accepted2026-10-11:** C2a914d9d3 + C2b325 deterministic manifest routes;787 engine/146 app/build,26 own state/effect checks and255 renders. Independent review approved; C2b committed `2bbdbe3`. [Report](reports/C2b-2026-10-11.md). Native live and production action execution remain separate.

## C3. Action commands

**Goal.** `link`, `copy`, `relink`, `unlink`, `pause`, `resume`, `sync`, `continue`, `merge`, `undo`, `restore`, `keep`, `send`, `pin`, `unpin`, `brief`, `rename`, `open`, `settings set`.
**From.** CONTRACT.md; all five specs.
**Depends on.** C1, E5 to E13.
**Files.** `baton/cli/commands/<one per command>.py`.
**Steps.** Each: build the plan, attach notes, on `--dry-run` or first call return it; on `--confirm` apply it.
**Tests.** `tests/contract/test_action_commands.py`: for each command, dry run returns a plan with at least one note; confirm applies; a stale plan id is refused.
**Done when.** Every scenario in `tests/scenarios/` can also be driven through the commands.

## C4. Hooks

**Goal.** The two entry points every tool calls, and their installation.
**From.** DESIGN 3, 4 "Catch-up at send"; more-tools per-tool sections.
**Depends on.** C1, E5, B1 to B4.
**Files.** `baton/hooks/prompt.py`, `baton/hooks/turn_end.py`, `baton/hooks/opencode_plugin.js`, `baton/cli/commands/{catch_up,notify}.py`.
**Steps.**
1. `catch-up --tool T --chat ID`: find the link; if turns are waiting for this side and the plan says `attach`, print what that tool expects (`hooks.attach_reply`) with the digest first, the turns in a `<baton-catch-up>` block, each with its time; record them as attached. Otherwise print the tool's "nothing" reply. Must answer in under two seconds and never fail the user's prompt: on any error, print "nothing" and log.
2. `notify --tool T --chat ID`: refresh the link, plan a sync, apply the steps that need no user decision, queue the rest, return offers (limit reached, decision needed).
3. Install and uninstall per tool through `HookSupport`; never write a tool's trust or approval.
4. The OpenCode plugin calls the same two commands.
**Tests.** `tests/unit/test_hooks.py`: each tool's exact output shape for attach, nothing and turn end; slow or failing engine still yields a valid "nothing".
**Done when.** Live on throwaway chats in all four tools: a turn written on one side is attached on the other at send, and synced at turn end.

## C5. Relaunch

**Goal.** Close, write, reopen, from one command.
**From.** link-actions A6; more-tools notes (Claude, Cursor); T5, T6.
**Depends on.** E13, B1, B4.
**Files.** `baton/cli/commands/relaunch.py`; detaching helper in `baton/services/relaunch.py`.
**Steps.** 1. Runs detached from the app that started it, as `spike/m0_relaunch.py` does. 2. Waits for idle when asked. 3. Asks the app to quit, waits up to a minute, writes, reopens, lands on the chat or folder. 4. Writes its progress where `baton status` can report it.
**Tests.** With the fake `AppControl`: order of calls, refusal when replying, give-up when the app does not quit.
**Done when.** Live for Claude and Cursor on throwaway chats.

## C6. Background runs: agent brief and second opinion

**Goal.** `brief --writer`, `ask`, `ask add`.
**From.** DESIGN 6; working-across W9 to W11; V9, V10.
**Depends on.** E10, B1, B2 (B3, B4 report "not available" until repaired).
**Files.** `baton/cli/commands/{brief,ask}.py`.
**Steps.** 1. Never runs against a linked chat's own session. 2. Read-only always. 3. Token estimate shown before running. 4. `ask add` makes the answer a turn marked as a second opinion and delivers it by the usual plan.
**Tests.** V9, V10 through the commands with a fake runner.
**Done when.** Live with Claude and Codex.

## C7. Limit offer and file watching

**Goal.** Offer the switch at a limit; notice changes when a hook did not fire.
**From.** working-across W1 to W4; DESIGN 3 (watcher as fallback); V1 to V3.
**Depends on.** C4, E9.
**Files.** `baton/cli/commands/watch.py`, additions to `notify`.
**Steps.** 1. At turn end, read the limit state; return an offer note once per limit. 2. `baton watch --once` re-reads linked chats whose files changed since the last look, for the app to call on a timer.
**Tests.** V1 to V3.
**Done when.** V1 to V3 pass through the commands.

## Reviewer carry-over from CP1

- F2 (C2): emit additive `tool_label` in Chat, Side, Step and setup tool objects, and render coding-app note values with display labels from CONTRACT.md. D4b supplies hand-made labelled fixtures first.
- F6 (C2): select catalogue `write.chat_open_release` instead of `write.chat_open` only for an open, idle, release-capable full-copy side with the on-button setting. Never offer release for a replying/held-only side or initial attached-history delivery. Preserve the generic note for those cases.
- R9 (C3): add `baton link --link L --replace T --mode full_copy` and `baton relink --link L --to T[:ID] --keep T2`; existing signatures remain. D5 exposes these choices.
