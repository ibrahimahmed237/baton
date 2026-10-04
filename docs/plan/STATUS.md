# Status

The one place that says where the build stands. Kept current by the orchestrator ([ORCHESTRATOR.md](ORCHESTRATOR.md)); every entry is a fact that was checked, not a plan.

**Branch:** `chore/project-setup` · **Last checkpoint passed:** CP0, 2026-10-05 · **Working towards:** CP1

## Now

Nothing in progress.

## Next

Towards CP1 ([CHECKPOINTS.md](CHECKPOINTS.md)):

| Track | Packages, in order | Folders |
|---|---|---|
| Engine ([track-e-core.md](track-e-core.md)) | E2 delivery by facts → E3 journal and safety → E4 turn mapping → E5 applier → E6 linking and copying | `baton/`, `tests/` |
| App ([track-d-app.md](track-d-app.md)) | D1 theme and components → D2 menu-bar popover → D3 window and lists → D4 sync status | `app/` |

The two tracks do not share files and can run at the same time.

## Done

| Package | Date | Commit | Tests after |
|---|---|---|---|
| E0 restructure into layers | 2026-10-05 | `d4d9153` | 70 engine |
| E1 ports and capabilities | 2026-10-05 | `cb11c88` | — |
| B0 fake tool and adapter suite | 2026-10-05 | `fcd3f41` | 129 engine |
| D0 app skeleton | 2026-10-05 | `bc2e180` | 15 app |

## Ready to commit

*(Entries appear here when a package is finished but could not be committed from the agent's environment: paths and message.)*

## Questions

*(Anything that stopped a package. Each with the package, the question, and what was done meanwhile.)*

## Log

- 2026-10-05 — CP0 passed. Contract frozen. See [CHECKPOINTS.md](CHECKPOINTS.md).
- 2026-10-05 — Orchestrator hand-off written.
