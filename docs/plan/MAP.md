# Map: from here to a finished app

One page that shows the whole road. [STATUS.md](STATUS.md) says what is happening this hour; this page says how far the whole build is. Updated whenever a package or checkpoint changes state.

**Last updated:** 2026-10-14 · **You are here:** CP3, batch 2 of 3

```
CP0 ✅ ── CP1 ✅ ── CP2 ✅ ── CP3 ◐ ── CP4 ○ ── CP5 ○ ── works on my Mac ○
layout    core on    two real   four tools,  app on the  daily   seen by Ibrahim
fixed     fakes      adapters   commands,    real        use     on throwaway
                                hooks        engine              chats
```

✅ passed · ◐ in progress · ○ not started

Historical2026-10-09 boundary: G2 common app check, G3 brand assertion and C1 accepted on 2026-10-09; G2 dab931c, G3 7f6e39f and C1 e15e076 committed separately. Ibrahim authorized approved self-commits; no push. E9 `650a8d1` and D6 `604e6d8` now committed after independent reviews. Resume baseline: 670 engine /129 app and build; isolated committed packages: 555 engine /119 app and build. E10/D7 independently accepted:702 engine/143 app/build pass. E10 `ec88983` and D7 `c8720bf` committed; usage95% means stopped at this package boundary. B2/C2 and live acceptance remain.

## Packages

| Checkpoint | Engine core (E) | Adapters (B) | Command line, hooks (C) | App (D) | Live check on the real apps |
|---|---|---|---|---|---|
| **CP0** ✅ | E0 ✅ E1 ✅ | B0 fake ✅ | | D0 ✅ | |
| **CP1** ✅ | E2 ✅ E3 ✅ E4 ✅ E5 ✅ E6 ✅ | | | D1 ✅ D2 ✅ D3 ✅ D4 ✅ | |
| **CP2** ✅ | R10 ✅ E7 merge ✅ E8 undo ✅ E9 usage ✅ E10 briefs ✅ | B1 Claude ✅ B2 Codex ✅ | C1 skeleton ✅ C2 read commands ✅ | D4b ✅ D5 ✅ UI1–UI13 ✅ D6 confirmation ✅ D7 hand-off ✅ | Claude and Codex adapters on two throwaway chats ✅ 2026-10-14 |
| **CP3** ◐ | E11 keep, pin, pause, names ◐ E12 notes audit ○ E13 setup check, relaunch ◐ | B3 OpenCode ✅ (fixtures) B4 Cursor ✅ (fixtures) | C3 action commands ○ C4 hooks ◐ C5 relaunch ○ C6 background runs ○ | D8 merge ◐ D9 history, undo ◐ D10 second opinion ○ D11 setup, settings ○ | Catch-up at send and sync at turn end in all four tools; relaunch for Claude and Cursor ○ |
| **CP4** ○ | | | C7 limit offer, file watching ○ | D12 wire to the real engine ○ | Each screen by hand against throwaway chats ○ |
| **CP5** ○ | | | | D13 polish ○ | The CP5 checklist in [CHECKPOINTS.md](CHECKPOINTS.md) ○ |

**Count:** 55 packages. 41 done, 5 being built, 9 not started. Plus four live checks, one done (CP2).

## What "finished" means

The seven points of "The finish line" in [ORCHESTRATOR.md](ORCHESTRATOR.md): all checkpoints passed with evidence; `baton` installed as a command; the app shows real status, not fixtures; hooks installed with Ibrahim's approval; a full round on two throwaway chats (link, write on each side, see it arrive, undo, unlink; once by full copy and once by attached history); every note shown before its action; nothing written to any other chat.

## What needs Ibrahim on the way

| When | What |
|---|---|
| CP2 live run | Close and reopen Claude when asked (I may not be allowed to); look at the two throwaway chats. |
| CP3 | Approve Codex hook trust and Cursor hooks himself; close and reopen Cursor; reinstall `opencode` if its command line is wanted; sign in `cursor-agent` only if wanted. |
| CP4 | Use each screen once on throwaway chats and say what is wrong. |
| CP5 | Go through the checklist; decide whether to link a real chat. |

## To continue in another chat or tool

Read [STATUS.md](STATUS.md) (Now and Next), then this page, then the package text in the track file. Nothing else is needed.

2026-10-10 B2 safety fixture boundary:730 engine/143 app/build,149 native fixture tests and77 CP2 scenarios pass; independent review accepted. C2 generation and native live gates remain.

B2 committed `cbb3e2b`,23 reviewed files; index empty. Historical E9-E10.md preserved untracked. C2 next; no push/live.

C2a started: recovery-free reads, additive metadata/settings and approved labels. Builder and separate reviewer active; C2b277 generated fixtures remains next. Whole C2/CP2 acceptance unchanged.

C2a758 engine/147 focused/143 app/build green; Q8 history display and final acceptance remain, no C2a commit yet. C2b277 generation and native live checks still owed; overall CP2 fail/incomplete.

C2a separate code review closed; acceptance conditional only on required Q8 history display approval and final regression. Source frozen, no C2a commit; internal execution split does not change whole C2 acceptance.

Ibrahim Q8 chose bookkeeping with distinct labels; separate final review approves C2a761 engine/150 focused/143 app/build. Committed914d9d3; whole C2 remains ◐ until C2b277 generated fixtures. Native live acceptance still owed; CP2 fail/incomplete.

C2a code/test/report package committed `914d9d3` (35 files), index empty. Stopped761 engine/143 app/build green at usage100%; C2b/live remain. Post-commit reference updates are local records, not unfinished implementation.

2026-10-11 C2b started: generator/manifest from semantic recipes, private fakes and actual read/service output. Baseline761 engine/143 app/build reproduced; whole C2/CP2 still incomplete.

2026-10-11 C2b accepted after separate review:325 deterministic fixtures,787 engine/146 app/build,149 native-shaped/82 scenarios,255 renders. Whole C2 complete; CP2 remains FAIL at exact-scope live acceptance. D5 duplicate-note presentation follow-up recorded; no native run/push. Committed `2bbdbe3`.
