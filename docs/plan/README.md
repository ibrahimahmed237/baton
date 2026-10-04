# Baton — implementation plan

The low-level plan: every piece of work, in the order it can be done, with the files it touches, the tests that prove it, and the document it comes from. [../PLAN.md](../PLAN.md) is the one-page overview; this folder is what an engineer or an agent works from.

## How to read it

| File | What it holds |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Layers, package layout, the interfaces every tool implements, error types, coding and testing rules. Read first. |
| [CONTRACT.md](CONTRACT.md) | The commands the engine offers and the JSON each returns. The app is built against this, so the two can be built at the same time. |
| [track-a-core.md](track-a-core.md) | Engine core: record, status, planner, applier, linking, merge, undo, briefs, notes. No tool-specific code. |
| [track-b-adapters.md](track-b-adapters.md) | One adapter per tool: Claude, Codex, OpenCode, Cursor. |
| [track-c-cli-hooks.md](track-c-cli-hooks.md) | The `baton` command, hooks and plugin, relaunch, setup check, background runs. |
| [track-d-app.md](track-d-app.md) | The Mac app: screens, themes, notes, wiring to the engine. |
| [CHECKPOINTS.md](CHECKPOINTS.md) | The points where everything stops and is checked together, and the full feature-to-package map. |

Each work package has the same fields: **Goal**, **From** (the requirement it implements), **Depends on**, **Files**, **Steps**, **Tests**, **Done when**. A package is small enough for one branch-sized change.

## Tracks and who can work at the same time

```
              CP0              CP1            CP2             CP3     CP4    CP5
Track A  A0 A1 │ A2 A3 A4 A5 A6 │ A7 A8 A9 A10 │ A11 A12 A13   │       │
Track B  B0    │                │ B1 B2        │ B3 B4         │       │
Track C        │                │ C1 C2        │ C3 C4 C5 C6   │ C7    │
Track D  D0    │ D1 D2 D3 D4    │ D5 D6 D7     │ D8 D9 D10 D11 │ D12   │ D13
```

- **A0, A1, B0 and D0 come first** and are done by one person: they fix the layout, the interfaces and the contract. After checkpoint CP0, four streams run in parallel.
- **Track A** needs no real tool: it works against the fake adapter of B0.
- **Track B** packages are independent of each other (one per tool) once B0 exists.
- **Track D** needs only the contract and its fixture files until CP3, when it is connected to the real engine.
- **Track C** starts once the applier (A5) and one real adapter exist.

Rules for working in parallel:
1. A package only edits the files it lists. Shared files (`ports/`, `CONTRACT.md`, the note catalogue) change only through a package that says so, and that change is announced in the package's commit message.
2. An interface is changed by adding, not by editing, until the next checkpoint.
3. Every package lands with its tests. Nothing is "tested later".
4. One branch for the whole project for now (`chore/project-setup`), small commits that say why. No pull requests until asked.

## Where the requirements live

| Document | Used for |
|---|---|
| [../DESIGN.md](../DESIGN.md) | Decisions, the complete feature list (section 1a), sync model, safety rules, message rules |
| [../features/sync-status.md](../features/sync-status.md) | R1 to R20, scenarios S1 to S12 |
| [../features/link-actions.md](../features/link-actions.md) | A0 to A13, scenarios T0 to T11 |
| [../features/merge.md](../features/merge.md) | M1 to M12, scenarios U1 to U9 |
| [../features/working-across.md](../features/working-across.md) | W1 to W15, scenarios V1 to V14 |
| [../features/more-tools.md](../features/more-tools.md) | G1 to G10, per-tool facts, best delivery per tool, the notes table, scenarios X1 to X7 |
| [../SPIKE-M0.md](../SPIKE-M0.md) | What was measured on the real apps. Adapters must match it. |
| Mockup canvas | One board per screen; the board name is given in each app package |

## Definition of done, for every package

- The listed tests exist and pass with `python3 -m unittest discover -s tests -t .` (engine) or the app's test target.
- No tool name appears outside `baton/adapters/` and the note catalogue's per-tool entries.
- Every user-facing sentence comes from the note catalogue, not from a string in the code.
- Public functions and classes have a one-line docstring saying what they are for.
- The package's "Done when" line is true and was checked, not assumed.
