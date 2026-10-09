# Map: from here to a finished app

One page that shows the whole road. [STATUS.md](STATUS.md) says what is happening this hour; this page says how far the whole build is. Updated whenever a package or checkpoint changes state.

**Last updated:** 2026-10-09 · **You are here:** CP2 review/repair; G2/G3/C1 committed; E9/D6 accepted; green commit boundary, CP2 not passed

```
CP0 ✅ ── CP1 ✅ ── CP2 ◐ ── CP3 ○ ── CP4 ○ ── CP5 ○ ── works on my Mac ○
layout    core on    two real   four tools,  app on the  daily   seen by Ibrahim
fixed     fakes      adapters   commands,    real        use     on throwaway
                                hooks        engine              chats
```

✅ passed · ◐ in progress · ○ not started

G2 common app check, G3 brand assertion and C1 accepted on 2026-10-09; G2 dab931c, G3 7f6e39f and C1 e15e076 committed separately. Ibrahim authorized approved self-commits; no push.

## Packages

| Checkpoint | Engine core (E) | Adapters (B) | Command line, hooks (C) | App (D) | Live check on the real apps |
|---|---|---|---|---|---|
| **CP0** ✅ | E0 ✅ E1 ✅ | B0 fake ✅ | | D0 ✅ | |
| **CP1** ✅ | E2 ✅ E3 ✅ E4 ✅ E5 ✅ E6 ✅ | | | D1 ✅ D2 ✅ D3 ✅ D4 ✅ | |
| **CP2** ◐ | R10 ✅ E7 merge ✅ E8 undo ✅ E9 usage ✅ E10 briefs ◐ | B1 Claude ✅ (fixtures) B2 Codex ◐ | C1 skeleton ✅ C2 read commands ○ | D4b ✅ D5 ✅ UI1–UI13 ✅ D6 confirmation ✅ D7 hand-off ◐ | Claude and Codex adapters on two throwaway chats ○ (Ibrahim said go) |
| **CP3** ○ | E11 keep, pin, pause, names ○ E12 notes audit ○ E13 setup check, relaunch ○ | B3 OpenCode ○ B4 Cursor ○ | C3 action commands ○ C4 hooks ○ C5 relaunch ○ C6 background runs ○ | D8 merge ○ D9 history, undo ○ D10 second opinion ○ D11 setup, settings ○ | Catch-up at send and sync at turn end in all four tools; relaunch for Claude and Cursor ○ |
| **CP4** ○ | | | C7 limit offer, file watching ○ | D12 wire to the real engine ○ | Each screen by hand against throwaway chats ○ |
| **CP5** ○ | | | | D13 polish ○ | The CP5 checklist in [CHECKPOINTS.md](CHECKPOINTS.md) ○ |

**Count:** 55 packages. 35 done, 3 in review or repair, 17 not started. Plus four live checks, none done yet.

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
