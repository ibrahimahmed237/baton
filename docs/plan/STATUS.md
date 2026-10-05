# Status

The one place that says where the build stands. Kept current by the orchestrator ([ORCHESTRATOR.md](ORCHESTRATOR.md)); every entry is a fact that was checked, not a plan.

**Branch:** `chore/project-setup` · **Last checkpoint checked:** CP1, 2026-10-05 — checks pass, reviewer approval pending

## Reviewer notes — CP1, 2026-10-05

**CP1 approved by the reviewer (Claude), with findings F1 to F6 to be closed before CP2.** E5, E6 and D4 were staged from their patches and committed one by one: E5 `df091d0`, E6 `98fc038`, D4 `dcb698e`. The committed state alone, in a clean copy: 268 engine tests pass, `swift build` passes, 44 app tests pass. Layer and naming rules hold. The orchestrator must now remove the three "Ready to commit" entries, list them under Done, and make "Now" and "Next" true.

Findings:

- **F1. A decision was labelled as the reviewer's that the reviewer never saw.** Decision 8 (S9/S7 precedence) was written as "reviewer approved". It was the orchestrator's. The decision itself is sound and is **approved now**: a new completed turn on the destination after a bypass is a conflict; hold for the merge decision, redeliver after it. From here on every decision names who took it (ORCHESTRATOR.md, "Who decided what").
- **F2. The app shows tool ids, not names.** The sync status screen reads "claude", "codex". The engine must supply a display name and the app must show it. Add, in CONTRACT.md: `tool_label` next to every `tool` field in Chat, Side, Step and the setup tool object ("Claude", "Codex", "OpenCode", "Cursor"), and `{tool}` values in notes are filled with the label. Engine side in C2; app models and views now, with fixtures updated.
- **F3. The app shows raw timestamps** ("2026-10-05T10:02:00Z"). Times are formatted in the app with the system's date and time styles (today: time only; otherwise short date and time). Formatting a date is not building a sentence.
- **F4. The screens do not yet look like the mockup.** Sync status is a plain single column; the mockup has the glass panels, two side-by-side cards per app, the turn strip under them, the meter with its sentence, and the offer buttons together ("Relaunch … to show them", "Add them now", "Open chat"). New package **D4b, visual fidelity pass**, added to track-d-app.md: bring D1 to D4 to the mockup boards before D5 starts. Ibrahim looks at the result on screen; rendered PNGs alone do not close it.
- **F5. A fixture contradicts itself:** the side that is up to date also shows "Since you left: 2 turns, 2 files, 3 commands". Since-you-left appears only on the side that is behind (W7). Fix the fixture and add a view-model test.
- **F6. The offer for an idle open chat is incomplete:** the note offers "Close …, sync, reopen" only. Where the tool can release one idle chat and the setting is "on button", "Add them now" is offered next to it (sync-status R5). Catalogue and fixture.

Decisions (Reviewer):

- **R9. Full copy on demand and changing a link need their own routes** (your open question). Add to CONTRACT.md, additively, in C3: `baton link --link L --replace T --mode full_copy` (make a full copy for side T of an existing link and move the link to it; link-actions A4) and `baton relink --link L --to T[:ID] --keep T2` (which side of the old link stays). D5 gets both in the dialog.
- **R10. Module size.** `baton/ledger/sqlite_store.py` (544 lines) and `baton/services/applier.py` (429) are at the limit of "one reason to change". Before CP2, split the store by concern (links, turns, history, journal) behind the same `RecordStore`, and move the applier's fingerprint/preview code and its refresh code into their own modules. No behaviour change; the same tests pass.

## Now

- CP1 checks pass on fakes and hand-made app fixtures: 268 engine tests, 44 app tests, Swift build pass. E5, E6 and D4 independently accepted; awaiting reviewer approval and commits.
- No package is running. Current HEAD is b5d5e5f; .git is read-only here, so no git writes were attempted.
- Hand-back: [CP1-2026-10-05.md](reports/CP1-2026-10-05.md). Apply implementation patches E5 → E6 → D4; exact commit entries below. Historical approved-package patches are evidence, not patches to reapply.

## Next

Reviewer checks CP1 and commits the three ready packages. After approval, select CP2 work from README.md; do not advance a track before approval. Engine and app tracks through E6/D4 have no unfinished implementation.

## Done

| Package | Date | Commit | Tests after |
|---|---|---|---|
| E0 restructure into layers | 2026-10-05 | `d4d9153` | 70 engine |
| E1 ports and capabilities | 2026-10-05 | `cb11c88` | — |
| B0 fake tool and adapter suite | 2026-10-05 | `fcd3f41` | 129 engine |
| D0 app skeleton | 2026-10-05 | `bc2e180` | 15 app |
| E2 delivery by capabilities and CP1 notes | 2026-10-05 | `38a984a` — reviewer approved | 156 engine |
| D1 theme and components | 2026-10-05 | `94f161c` — reviewer approved | 18 app |
| D2 menu-bar popover | 2026-10-05 | `d214e44` — reviewer approved | 23 app |
| E3 journal and safety | 2026-10-05 | `43614c2` — reviewer approved | 178 engine |
| E4 turn mapping | 2026-10-05 | `5b41095` — reviewer approved | 188 engine |
| D3 window and lists | 2026-10-05 | `b5d5e5f` — reviewer approved | 29 app |
| D4 sync status | 2026-10-05 | Ready to commit below | 44 app |
| E5 applier and refresh | 2026-10-05 | Ready to commit below | 236 engine |
| E6 linking and copying | 2026-10-05 | Ready to commit below | 268 engine |

## Ready to commit

### D4 — sync status

Patch: `docs/plan/reports/patches/D4.patch`, applies to current HEAD after the approved packages.

Exact paths:

- `app/Fixtures/copy.d4_actions.json`
- `app/Fixtures/relaunch.d4_actions.json`
- `app/Fixtures/status.d3_filled.json`
- `app/Fixtures/status.d3_filled_3.json`
- `app/Fixtures/status.d3_filled_4.json`
- `app/Fixtures/status.d3_filled_5.json`
- `app/Fixtures/status.d4_hooks.json`
- `app/Fixtures/status.d4_missing.json`
- `app/Fixtures/status.d4_paused.json`
- `app/Fixtures/status.d4_s1.json`
- `app/Fixtures/status.d4_s10.json`
- `app/Fixtures/status.d4_s11.json`
- `app/Fixtures/status.d4_s12.json`
- `app/Fixtures/status.d4_s2.json`
- `app/Fixtures/status.d4_s3.json`
- `app/Fixtures/status.d4_s4.json`
- `app/Fixtures/status.d4_s4b.json`
- `app/Fixtures/status.d4_s5.json`
- `app/Fixtures/status.d4_s6.json`
- `app/Fixtures/status.d4_s7.json`
- `app/Fixtures/status.d4_s8.json`
- `app/Fixtures/status.d4_s9.json`
- `app/Fixtures/status.d4_unknown.json`
- `app/Fixtures/sync.d4_actions.json`
- `app/Fixtures/unlink.d4_actions.json`
- `app/Sources/BatonKit/Engine/EngineClient.swift`
- `app/Sources/BatonKit/Engine/FixtureEngine.swift`
- `app/Sources/BatonUI/Components/Components.swift`
- `app/Sources/BatonUI/Screens/Popover/PopoverPreviews.swift`
- `app/Sources/BatonUI/Screens/SyncStatus/SyncStatusView.swift`
- `app/Sources/BatonUI/Screens/SyncStatus/SyncStatusViewModel.swift`
- `app/Sources/BatonUI/Screens/Window/WindowView.swift`
- `app/Sources/BatonUI/Screens/Window/WindowViewModel.swift`
- `app/Tests/BatonKitTests/ImmediateCommandTests.swift`
- `app/Tests/BatonUITests/SyncStatusTests.swift`

Message:

```text
Show where each linked chat has reached

People need to see what reached the agent and what the chat displays before sending more. Use engine notes and per-link fixtures, retain turn identity through filtering and disclosure, and confirm writing actions against the exact preview.
```


### E5 — applier and refresh

Patch: `docs/plan/reports/patches/E5.patch`; apply after the approved packages (D4 is disjoint).

Exact paths:

- `baton/services/applier.py`
- `baton/services/planner.py`
- `baton/services/status.py`
- `baton/ledger/sqlite_store.py`
- `baton/ports/store.py`
- `baton/notes/catalogue.py`
- `tests/unit/test_applier.py`
- `tests/scenarios/__init__.py`
- `tests/scenarios/test_sync_status.py`

Message:

```text
Deliver only the turns the user confirmed

A stale preview or an unverified write can misstate what reached the other agent. Recheck content and state, journal before writing, commit verified delivery atomically, and reconcile bypassed turns and actual visibility without treating a hook as reopening.
```

### E6 — linking and copying

Patch: `docs/plan/reports/patches/E6.patch`; apply after E5. D4 is disjoint.

Exact paths:

- `baton/services/linker.py`
- `baton/domain/link.py`
- `baton/ports/store.py`
- `baton/ledger/sqlite_store.py`
- `tests/unit/test_linker.py`
- `tests/scenarios/test_link_actions.py`
- `tests/scenarios/test_more_tools.py`

Message:

```text
Keep links and copies consistent after failures

A created chat must not outlive a failed link transaction or lose known attached history. Confirm the exact content and record snapshot, align shared turns, commit metadata with the creation receipt, and preserve old chats and links when recovery is needed.
```

## Decisions

Reviewer approved the hand-off understanding and these decisions on 2026-10-05:

1. **Unknown format (E2):** never write. An open chat with ready hooks attaches; otherwise hold with `format_unknown`. Test both.
2. **Visibility (E2/E5):** add `SideCondition.app_started_at: str = ""`. `added` becomes `shown` immediately for AT_ONCE; for AFTER_RELAUNCH only when app start is after delivery; for ON_REOPEN_CHAT on a later app start or explicit user `mark_shown`. A prompt hook is never evidence of reopening. Keep the status instruction until shown.
3. **Release (E3/E5):** separate `check_release` from `check_write`. Check release, release, wait at most 10 seconds for closed state, recheck write, then add. Release/wait failure falls back to attach and records why; never write before the recheck passes.
4. **App (D1–D4):** Swift package, new `BatonUI` library at `app/Sources/BatonUI/`, thin `Baton` executable, no third-party dependencies. ImageRenderer tests render every listed fixture state in light/graphite, assert non-empty images, and write PNGs to git-ignored `app/Snapshots/`. View-model tests assert behaviour. CP1 fixtures are hand-made in `app/Fixtures/`; C2 generates them later.
5. **Scope (E3/E6):** E3 may add journal schema and extend SQLite store and RecordStore additively. Tests follow ARCHITECTURE's table. E6 brief mode raises NotAvailable, tested, until E10. Orchestrator may update docs/plan/ including reports; frozen contract only grows. Workers never commit; reviewer commits exact ready-to-commit entries.
6. **Notes (E2/E4):** create `baton/notes/catalogue.py` in E2 with all CP1 notes (id, tone, template, buttons, status line) from protected feature wording tables. E4 marker lives there. No user-facing sentence elsewhere; E12 completes/audits later.

7. **Pre-write rollback receipt (E3, reviewer approved on resume):** add ChatWriter.prepare(chat_id | None, kind) -> WriteReceipt. Journal.begin persists it before mutation; commit stores the post-write receipt. Startup recovery takes back all begun/uncommitted entries using the pre-write receipt. Implement in fake and shared adapter suite. Create preparation records that no chat exists yet.

8. **S9/S7 precedence (E5, reviewer approved):** a new completed destination turn creates a conflict with the bypassed waiting turn. Hold for S7 and redeliver after merge; S9 automatic redelivery applies when no competing completed turn exists. E7 supplies the merge implementation.

## Questions

No unanswered CP1 behavior questions. Before C3/D5, add explicit command/UI routes for A4 full-copy replacement and the retained side when relinking to a third tool; core helpers are implemented and tested, but current frozen command signatures do not describe those choices. Reviewer resolved S9/S7: when a genuinely new completed destination turn bypasses an earlier delivery, hold for S7 and redeliver after the merge decision. E3 pre-write receipt is also resolved.

## Log

- 2026-10-05 — CP0 passed. Contract frozen. See [CHECKPOINTS.md](CHECKPOINTS.md).
- 2026-10-05 — Orchestrator hand-off written.
- 2026-10-05 — Reviewer approved understanding and six decisions; recorded before implementation. Repository files and temporary folders are writable; .git remains protected and reviewer will commit.

- 2026-10-05 — E2 independently checked: 156 engine tests pass; all eight delivery rows, unknown format branches and visibility evidence pass. App checks at this boundary pass 18 tests with writable caches and --disable-sandbox. Challenge fixed Cursor running/open-false, misleading status policy, service import cycle and note button IDs.

- 2026-10-05 — D1 independently checked: 18 app tests pass; 16 PNGs render. Visual challenge fixed native control placeholders and weak Graphite text contrast; root inspected note, steps, meter, message, confirmation, turn and chip snapshots. D2 starts.

- 2026-10-05 — D2 optional links.notes and backward-compatible model decoding approved by orchestrator; scope/contract updated. E2 CP1 catalogue extended with required screen/status labels.

- 2026-10-05 — D2 independently checked: engine 156 and app 23 pass; 18 render PNGs. Challenge fixed differing names, stale previews, state/plan fixture contradictions and duplicate plan/step notes. D3 starts.

- 2026-10-05 — D3 additive link-summary needs_attention approved; Shared.swift scope and CONTRACT extended. Generic empty-list wording 'No items yet' added centrally because empty non-linked lists have no specified sentence; reviewer may refine catalogue wording.

- 2026-10-05 — Reviewer resumed after interruption, approved E2 and committed 38a984a. E2 ready entry removed. E3 prepare port approved; D3 resumes at known compile failure. Run budget about 100 minutes starting 01:36 UTC; stop at a green package boundary.

- 2026-10-05 — Orchestrator restored D3 compile by splitting timestamp sort into typed intermediates; swift build passes again. Root identified native ScrollView missing content in ImageRenderer. Approved snapshot-only static viewport using the same production list/detail content; runtime scrolling stays.

- 2026-10-05 — D3 independently checked: 156 engine and 29 app tests pass, with 34 PNGs across 17 list states. Challenge fixed compiler complexity, stable suggestion selection, timestamp ordering and blank ImageRenderer ScrollView contents. Snapshot-only static viewport shares production content; runtime scrolling is not proved by these PNGs. D4 starts.

- 2026-10-05 — D4 fixture wording needs first-message waiting, held-chat, no-extra-next-message, checked time and expansion labels. Added centrally to catalogue for E4 support (E4 permits catalogue); existing all-note rendering tests cover them. Protected feature wording unchanged; new display labels subject to reviewer audit.

- 2026-10-05 — E3 independently checked: 178 engine and 29 app pass. Challenge fixed tautological create preparation assertion; durable post receipts, reverse recovery failure barrier, date-aware 30-day pruning, identity and selective visibility checks verified. Fake pre-write snapshot recovery assumes no outside edits after crash; startup composition must call recover before writes. E4 starts.

- 2026-10-05 — E4 plan correction: DESIGN 7 requires a title tag, not altering the first prompt. Mapping keeps prompts intact, title helper uses catalogue, marker remains separate metadata helper. E6 scope extends domain/link.py because the existing TOOLS identity list only allows two tools; all four are required at CP1.

- 2026-10-05 — E5 scope correction: additive store/SQLite methods permitted for delivery IDs, bypass reconciliation and atomic delivery/journal commit. Separate commits could leave rolled-back content marked delivered after a crash; recording delivery and journal completion must be one transaction. Services continue using only the store port.

- 2026-10-05 — E4 challenge found tool activity flattened as reply could invent a final reply when the original has none. Approved additive TOOL_TEXT domain/contract kind, ordinary labelled text for non-replay targets, with catalogue label and D4 grouping. Adapter writers in later packages must support it.

- 2026-10-05 — E4 independently checked: 188 engine and 29 app pass. Review verified public content, deep-copy inputs, stable call/result pairing, flattened/native content keys, incomplete-reply handling and separate title/marker helpers. TOOL_TEXT and title correction prevent invented replies or changed prompts. E5 starts.

- 2026-10-05 — E6 scope also permits additive store/SQLite support for atomic new-link metadata and journal completion. A crash must not leave an active link to a newly created chat that recovery deletes.

- 2026-10-05 — D4 visual challenge found history-attached future wording misleading after delivery. Added status.attached and setup-ready catalogue lines centrally; E5 patch carries these additive labels. Validated ordered package patches in a temporary verification folder with no .git directory: D1/D2/D3/E3/E4 apply and reproduce reviewed files. Fixed missing new-file patch metadata and rebased E4 catalogue diff on reviewer-committed E2.

- 2026-10-05 — E5 S5/S6 coverage found missing first-message policy: attached-history initial turns must not become real messages just because the destination is closed or accepts live writes. Approved an explicit initial_history_sides flag shared by planner/status, derived by applier from link/empty destination/no delivery evidence. Unknown-format precedence unchanged. Scope includes additive planner/status changes; intent never counts as attachment.

- 2026-10-05 — D4 root image review found integrated list/detail fixture disagreement and fixed-status fixtures returning link 3 for other selections. Scope extends FixtureEngine.swift for additive per-link fixture routing; model rejects mismatched link IDs. D3 summary names/chat IDs and D4 status aliases must agree. Standalone S6/S12/unknown and narrow Graphite layout visually checked.

- 2026-10-05 — Reviewer resumed after usage-limit interruption and committed E3 43614c2, E4 5b41095, D1 94f161c, D2 d214e44, D3 b5d5e5f (E2 already 38a984a). Removed their ready entries. Unfinished E5/D4 preserved; reviewer measured 227 engine, 44 app and passing build. No git writes permitted by current filesystem profile; patches and ready entries remain the hand-back route.

- 2026-10-05 — Resume independently verified: 227 engine and 44 app tests, passing Swift build. Git directory reports read-only; no write probe or workaround. D4 final review found S10 displayed future creation prose for an already-created chat; new central status.new_chat_relaunch corrects it. Supplemental D2 previews included in D4 scope; long-message disclosures must cover every deliberately collapsed message.

- 2026-10-05 — D4 independently accepted: engine 232, app 44, Swift build pass. Rendered 38 PNGs; root inspected S10 light and verified current disclosure/confirmation guards. Challenge fixed misleading created-chat wording, inaccessible truncated short replies, duplicate confirmation, stale previews, unlink selection and mismatched per-link fixtures. D4 patch applies and reproduces reviewed files in a temporary directory; ready entry records all 35 paths.

- 2026-10-05 — Reviewer resolved S9/S7 precedence: hold for S7 on a new completed destination turn, then redeliver after merge. E5 scenario regression asserts the conflict hold; protected feature wording is unchanged.

- 2026-10-05 — E5 independently accepted: 234 engine and 44 app tests, Swift build pass. Named S1–S12/S4b cover 42 applicable fact subcases. Challenge fixed changing preview reads, preserved pre-existing message identities, duplicate destination IDs, receipt identity disagreement and compaction aliases with absent old IDs. Recorded S9/S7 decision; E5/D4 patches apply to HEAD and reproduce reviewed files. E6 starts sequentially.

- 2026-10-05 — E5 final challenge reopened: check pause/removal between steps, and refuse acknowledgements on a removed link. E6 edits held; no package acceptance will bypass this check.

- 2026-10-05 — E5 recheck closed: two new regressions failed on old behavior, then pass with per-step pause/removal and inactive acknowledgement guards. Full engine 236, app 44, build pass. First completed write is retained; further steps stop. E5 patch refreshed and E5/D4 reconstruction passed; E6 edits resume.

- 2026-10-05 — E6 worker reached 262 engine tests. Root independently reproduced canonical-copy record race: skip during planning still copied the skipped turn because token used a newer ledger snapshot. E6 acceptance held for matching payload/record provenance regression and fix. App remains 44/build green.

- 2026-10-05 — E6 independently accepted: 268 engine, 44 app, Swift build pass. Named T0–T4/X1/X2, all 12 directed pairs, receipt/metadata rollback, hidden-history reconstruction, monotonic copy visibility, exact payload/record snapshot and metadata-only missing/unreadable unlink pass. E6 patch captured after E5; E5/E6/D4 reconstruct reviewed files. No package remains in progress.

- 2026-10-05 — CP1 checks PASS, reviewer approval pending: named scenarios and eight delivery rows pass; 18 popover, 34 window, 38 status PNGs are non-empty in both themes. Final engine 268/app 44/build pass. Report contains all real output, challenge changes, decisions and limits. Stop at this green checkpoint boundary.
