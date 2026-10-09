# CP2 repair and acceptance plan

2026-10-09. Root orchestrator; independently checked with two GPT-6.1 agents (engine architecture and app/contract review). **Ibrahim approved the recommended product/contract changes and the CP2/CP3 boundary in two answers on 2026-10-09.** Both agents reviewed this written plan; their necessary refinements are incorporated below. This plan closes the findings in [the resume report](reports/CP2-resume-2026-10-09.md), including further defects found during planning. CP2 remains unpassed until every gate below has evidence.

## Starting point

- G2 `dab931c`, G3 `7f6e39f`, C1 `e15e076` committed separately on `chore/project-setup`; no push. Ibrahim authorized normal approved Git writes. The G1 three-uncommitted boundary is cleared.
- Working tree: 650 engine tests, 115 app tests and build pass. E9/E10, B2 and D6/D7 still unfinished; preserve their edits. C2 not started.
- Existing green tests do not prove private content stays private, background previews are free of side effects, or offered actions retain the intended chat/request.
- D6/D7 are fixture screens at CP2. D12 connects the app to the production engine. Do not call missing production window integration a CP2 defect.

## Ownership and agent use

Use at most two subagents. GPT-6.1 with high reasoning is the default for privacy, journaling, native rollback and independent review. No need to use a smaller model for those tasks. Root owns shared interface/catalogue/plan changes and checks every package.

After the approval sheet is settled, one worker owns engine code/tests, one owns app code/tests. Engine packages E9 → E10 → B2 → C2 are sequential; app D6 → D7 is sequential. They may overlap only when the agreed interfaces exist and folders do not conflict. C2 regeneration owns `app/Fixtures/`; pause the app worker's fixture edits while generating. Workers never revert others' files or commit.

At each package boundary, have the other agent review the diff and requirements with fresh context while its implementation work is idle. Root also challenges the work and runs both common checks. Fix findings before acceptance, record the exact output/decisions, commit one package, update STATUS/MAP/HANDOFF. If Git approval becomes unavailable, retain exact Ready entries and observe G1; never bypass restrictions.

## Approval sheet — approved recommendations

Ibrahim approved the brief/cost/summary/confirmation/Automatic-or-Offline recommendations and preserving unavailable CP3 paths. Internal representation details below are orchestrator choices checked by the planning reviewers; they add to the frozen contract. Existing privacy, caching, usage and safety requirements remain mandatory.

| Decision | Recommendation | Reason / scope |
|---|---|---|
| P1: agent-brief lifecycle | Initial preview shows writer and estimated read-only request cost and calls no runner. **Generate brief** explicitly starts the run. Show the resulting immutable brief, then **Create chat** confirms creation/link movement. Offline can materialize mechanically without a paid run, but still requires creation confirmation. | Browsing or dry-run must never silently run an agent. Actual brief text must be stable before native writing. Add optional Plan stage and brief estimate/artifact fields; keep all frozen fields. |
| P2: truthful brief status | Show a distinct **Summarized through this turn** receipt for covered history; only messages actually copied verbatim count as shown. Preserve pins/recent excerpts and excluded turns accurately. | One summary message cannot be a native identity for many original turns. Add separate durable summary coverage and additive status metadata; do not falsify SHOWN/agent_has counters. |
| P3: plan controls and hand-off choices | Add optional engine-supplied `Plan.confirmation: Note` with action-specific primary button and Cancel. Hand-off writer choices: **Automatic / Offline**; Automatic uses destination → eligible other tool → offline. All new headings/buttons belong to approved catalogue entries. | Ordinary confirmation is already required; its new wording/representation needs approval. Arbitrary writer dropdown is not required by DESIGN 6. Preserve burgundy/I.A artwork and existing style. |
| P4: unresolved alternative actions | Preserve original link/copy/brief request. A new-chat Attach choice leads to existing-chat/attached-history selection for an eligible link flow; it never claims success without a counterpart. For unlinked copy or unsupported close/create/reopen/deferred-sync composition, show a catalogue-based unavailable result. Never turn ordinary deferred sync into relaunch. | Frozen relaunch supports existing-link then-sync, not arbitrary pending creation. Do not invent app-side close/write/reopen or silently change copy into a link. Future engine composition belongs to E13/C3/C5. |
| P5: CP2 fixture boundary | C2 generates current D0–D7/UI read states via actual read commands, and existing action/brief preview/receipt states via real services and shared serializers on temporary fakes. Future-only relaunch/notify and Continue opening/apply contract examples are explicitly identified as contract-provider examples and non-executable at CP2. | No production C3/C4/C5/C6/C7 code is silently promoted. Do not describe future-only fake output as a real command/service. Document this boundary in tracks/checkpoint evidence before acceptance. |

P4 does not waive product behavior: the future execution remains owed at CP3 and must be listed as such. If P5 is not approved, hold CP2 until the necessary real services/commands are deliberately moved forward and implemented; do not mark the checkpoint passed using hand-authored substitutes.

## Additive representation (orchestrator, planning reviewers checked)

- Preserve every existing Plan field. Add optional `stage: "generate" | "create"` and `confirmation: Note`. Existing primary controls remain explanatory note buttons; ordinary apply comes only from the documented primary control or an explicit known action route.
- BriefDetails adds `estimated_tokens`, per-candidate estimates and `artifact_id`. Initial `brief`/dry-run returns generation stage without runner.ask. `brief --confirm GENERATE_ID` validates and consumes the stored generation request, returns a new creation-stage Plan (applied false). `brief --confirm CREATE_ID` consumes only the exact stored artifact and creates/verifies the chat. Production command dispatch remains C3/C6; CP2 proves this lifecycle through services/contract providers. Cached/offline artifacts may directly offer create stage; no unapproved agent request occurs.
- Artifact persists ID, writer, exact synthetic opening turn, separate ordered pinned/recent original turns, transcript path/digest, source and link/input fingerprint, creation time and permitted candidate attempts. A consumed token cannot rerun the operation after failure/ambiguous completion; a retry requires a fresh preview/consent. Creation does not regenerate summary content.
- Add `brief` link mode and per-side `summarized` turn state, separate from DELIVERED. Add Side.summary_coverage `{artifact_id, chat_id, through_turn_id, turn_ids}`. `total` stays canonical conversation count; summarized originals are not waiting and are excluded from ordinary agent_has/chat_shows counts. Kept/skipped exclusions remain. Only separately emitted, verified native original turns qualify for SHOWN/ADDED counts; inline verbatim excerpts in a synthetic prompt never do. Generic full-history reached receipts cannot cross a summarized gap; show the approved separate summary receipt. Synthetic opening is identified durably and excluded from native-origin reimport.
- Legacy rows without canonical evidence are explicitly unverified. Establish a current observed baseline with provenance, never claim it proves the past unchanged. Before generation/write revalidate the full current snapshot; retained verified completed content cannot be overwritten by a conflicting read. Refusal/bootstrap rules must have tests and reviewer evidence.
- Stable offer metadata goes in Note.values: offer_key, link_id, source_tool_id/source_chat_id, destination_tool_id/destination_chat_id. Display-label fields remain distinct.

## 1. E9 — usage, durable limits and exact digest

Owner: engine worker, with root coordinating additive interfaces. Paths: `baton/services/{usage,digest,limit_offer}.py`, scoped catalogue notes, additive `baton/ports/{tool,store}.py`, ledger schema/methods and canonical completed-turn payload/fingerprint evidence, fake/Claude/Codex reader additions; corresponding unit, adapter and working-across scenario tests. Announce expanded track scope before edits.

- Use the raw ratio for above 80% (`tokens * 100 > size * 80`); preserve display rounding. Unknown/invalid size produces no invented percentage.
- Persist once-per-limit claims in the record store with an atomic unique-key insert. Key includes tool, chat and limit event identity, including unlinked chats. An offer-disabled setting does not consume the event. Reopening the store/process must not redisplay a dismissed/claimed event; a new limit may offer again.
- Return stable offer routing identity in additive Note.values metadata (source/destination tool IDs and chat IDs, link ID, offer key). Display labels stay separate from IDs. UI cannot derive the destination from sorted sides or mutable selection.
- Suppress a since-you-left digest when all eligible history is received, including SHOWN, ADDED and ATTACHED. Kept/skipped turns do not reveal activity or create pending work. If any eligible turn still waits, preserve exact turn/file/command/time counts and digest-first catch-up.
- Add reader command evidence (`commands_run(turn)`); adapters classify real shell execution calls. Edits, reads, searches and tool results are not commands. Do not add tool names to services.
- Missing/changed eligible source content must not yield a deceptively partial digest; E9 owns the canonical-evidence groundwork so its acceptance does not depend on unfinished E10. E10 extends it with archived brief origins. Fresh completed observations establish evidence; legacy rows without full evidence must be marked unverified and cannot be asserted unchanged from their original recording. Compare the current preview snapshot again before generation/write, and refuse disagreement with retained evidence rather than overwriting it.

Acceptance: V1–V8 named scenarios plus independent-process offer suppression and concurrent claim, 80/80.2 boundaries, unknown-size/reset behavior, fully received/pending digest, command-vs-tool-call classification, stable destination IDs and digest-first text. No policy duplication in future C2 serializer.

## 2. E10 — privacy-safe artifacts and real brief transition

Owner: engine worker after E9. Paths: `services/{brief,transcripts,observations,linker,preview,refresh,merger,status,undo}.py`, additive domain/ports/ledger, scoped catalogue; unit/brief/link/merge/undo scenarios and fakes. Approve P1/P2/P3 before dependent implementation. Keep other engine packages idle during shared edits.

- Runner input is the intersection of destination-safe history and selected writer access. Test explicit source writer and fallback. Destination-kept sentinel must be absent from prompts, summaries, transcript, files, pins and recent excerpts. Keeping back wins over pinning.
- Publish private immutable transcript snapshots by content identity using unique temporary files and durable atomic no-clobber publication. Reusing a path requires identical content. A later source-side private brief must not change the earlier destination-safe path.
- Retain full canonical origin payload/fingerprint evidence durably when observing/linking. Detect changed completed prompts/replies even when IDs remain stable; distinguish legitimate growing replies. Do not silently treat an unverified legacy backfill as proof of earlier content. Archive origins only at explicit successful transitions; missing active origins do not justify arbitrary stale fallback.
- Preview invokes no runner. Confirm tokens bind to stored stage and exact arguments: generate and create use distinct IDs; neither client fields nor a create token can cause generation. Explicit confirmed generation validates the exact input/estimate, runs once, and persists an immutable artifact with exact opening content/time, writer, transcript digest/path and input fingerprint. One generation execution may try each pre-disclosed eligible agent at most once before offline fallback; show each candidate estimate and bounded total before consent. Creation preview gets a fresh plan ID. Creation confirmation consumes that artifact verbatim, without regenerating it or assigning new nondeterministic content.
- Reuse Linker guards, Journal.prepare/begin/verify and atomic completion patterns. Add atomic brief finalization that commits native identity, summary baseline/coverage, archived canonical sources, history, link movement and journal receipt together. Earlier counterpart remains untouched.
- Summary coverage is separate from ordinary native turn delivery. Do not reuse one native ID for all originals or declare every summarized turn SHOWN. Refresh must not import the synthetic opening as a new user turn or requeue covered originals. Future new turns sync in full in both directions; kept/excluded originals stay excluded. Existing mode fields may be extended additively; the approved representation below fixes their meaning before migrations.
- Persist per-chat/destination/writer/eligibility cache. Unchanged input uses cached content; appended eligible turns update from the previous safe summary plus delta only. Changed privacy marks, order, old content or chat identity invalidate the reusable prefix. Pins and recent excerpts are composed from current safe originals. Preview must not materialize changed content through a background call.

Acceptance: V4, V13/V14, actual M12 brief merge and relevant U9 undo; actual native created content/link movement/old-chat preservation; stale ID/removed content refusal; explicit/fallback privacy; immutable path; preview zero runner calls, generation one call on first success or bounded candidate calls on fallback, create zero; incremental cache; no duplicate originals after refresh; future sync both directions. Inject failure after prepare/create/verify/store finalization, restart a fresh engine, and prove consistent rollback/link/receipts. A failure after atomic finalization preserves the committed chat/link/receipt and never rolls it back. Restart/relaunch, future bidirectional sync, undo and restore must preserve summary coverage without upgrading it to ordinary SHOWN/native identities. Migration/recovery must preserve existing links and old data.

## 3. B2 — native Codex safety and separate review

Owner: engine worker after E10. Paths: `baton/adapters/codex/`, fixture builder/tests, additive shared adapter checks only when generic. No real chat reads or execution during this package's fixture phase.

Confirmed new concerns to close:

- Created-row rollback checks only ID/path. Save the full expected row, compare it transactionally and delete with conditional matching/affected-row checks. A renamed or otherwise externally changed created row must survive stale take-back.
- Holder check is sampled and released before write. Test a competing process and hold the appropriate native exclusion through final recheck/publication/rollback; verify the actual native lock lifecycle in the live gate. If native coordination cannot be established, refuse rather than claiming safety.
- Validate the particular target's format before every mutation, including rename; global tail screening is not target validation.
- Guessed trust path/event substring plus nonempty hash is insufficient. Do not claim hooks ready without exact verified identity/schema; report not ready until measured. Never set trust on Ibrahim's behalf.
- Enforce an explicit throwaway identity allowlist for locator, global format screening, template selection and all content reads/writes. Current global newest-three-rollout screening and replying inventory can read unrelated chats. If quitting safety cannot be established within the allowlist, ask Ibrahim to close manually; never weaken the global safeguard. Include all created descendants and rollback artifacts in scope/cleanup, not just two source chats.

Acceptance: shared suite on made-up native files; stale external row mutation, competing lock, unknown-target mutation, reverse-order rollback, index publication/recovery, truthful hook readiness; separate reviewer checks only the B2 diff/spec. Native schema/index/marker/trust assumptions remain unverified until live; fixture success is explicitly not live acceptance.

## 4. D6 — precise actions and display approval

Owner: app worker, after root settles P3/P4 shared models; D6 then D7. Paths: `Screens/PlanReview/`, its tests, additive BatonKit plan/transport models and shared display gate; existing D5 regressions if shared code changes. No independent engine/catalogue edits by this worker.

- Introduce internal action identity containing plan ID/revision, note origin/path/button index and offering tool. Route using original request + note + step provenance. Preserve separate per-side offers even when IDs repeat. Unknown/ambiguous actions never confirm.
- Copy-and-link repreviews the same source/target with linking enabled. Add-now targets its offered side. Relaunch-when-idle changes only an actual relaunch request; ordinary write.when_idle never closes an app.
- Keep immutable original operation through alternatives. No bare relaunch may discard creation parameters; no attach completion without a real counterpart. Unavailable or selection-needed plans have no enabled apply primary; retain Cancel and original source/destination/mode/linking intent. Unsupported composition remains non-applied with engine/catalogue explanation.
- Bind displayed-note receipt to exact plan ID **and revision**, not just equal text. A same-notes replacement still requires a fresh displayed receipt. Key rendered note identity accordingly; target/mode/writer changes invalidate approval.
- Primary controls come from Plan.confirmation/catalogue. Never synthesize action sentences or treat every offered button as confirm. Confirm exact preview ID once; cancellation and refusals retain correct outcome.

Acceptance: unknown offered button zero mutations; duplicate ID opposite-side ordering retains side; copy-and-link changes actual semantics; original creation survives alternatives; no deferred-sync relaunch; same-note stale receipts refused; no confirm before display; double-click/stale confirm/cancel/refusal tests. Replace the transport that blindly sets applied on any --confirm with a plan book validating the full request. Service-backed contract tests assert real chat/link effects where services exist.

## 5. D7 — coherent hand-off and limit offer

Owner: app worker after D6 and E9/E10 output contracts. Paths: `Screens/HandOff/`, tests, coordinated BatonKit additions. C2 owns final fixture generation.

- Clear prior status/chat/offer/target/brief/actions at reload start and after failures; reset defaults for a new hand-off. Validate returned link ID and destination membership. Reject stale responses and disable actions during loading/error.
- Full previews Continue and never asks for a brief. Brief first previews cost/writer policy, then the confirmed-generation artifact and creation plan. Switching writer/target/mode invalidates stale previews and display approval.
- Automatic/Offline choice is explicit; Offline never calls a runner. Automatic explains the selected writer/fallback using actual engine notes.
- Offer routes from immutable metadata, independent of the selected target or whichever side reports a limit. Unlinked offers retain the named destination when opening the link dialog.
- Consume real catalogue IDs for context/no-size/nearly-full, limit/reset/available, writer/skipped/fallback and large-chat recommendation. New headings approved once in catalogue. No edited semantic notes or invented fixture sentences.

Acceptance: V1–V6 plus failed reload leaves no old-link actions; mismatched status/destination rejection; out-of-order results; actual full-mode zero brief/runner calls; Offline preserved; fixed offer destination; real no-size/fallback notes; correct generated summary receipt; fresh notes gate for generated plan. Render all required states in light/Graphite and inspect PNGs; do not claim production window integration at CP2.

## 6. C2 — safe reads and reproducible fixtures

Owner: engine worker after E9/E10/B2 serializers settle; root coordinates a temporary fixture-edit pause on the app track. Paths: read command modules, `cli/{wiring,output}.py`, new `services/{read_views,settings_read,setup_read}.py`, additive store/settings ledger methods, `tests/contract/test_read_commands.py`, `tests/contract/fixture_manifest.py`, `tests/contract/generate_fixtures.py`, generated `app/Fixtures/`. APIs: ReadViews.{suggestions,merge_show,link_summary}; SettingsRead.get(); SetupRead.tools(). Providers call ports/refresh/preview without recovery constructors. Regenerate explicitly with `python3 -m tests.contract.generate_fixtures --output app/Fixtures`; tests use temporary outputs.

- Implement setup, chats, suggestions, links, status, history, merge-show and settings-get as thin read adapters. Linker and Merger constructors currently trigger recovery, so extract their read projections. No read may construct recovery/writer services or call runner.ask/app mutators; runner.available() and other read-only readiness checks are permitted with injected temporary controls in tests.
- Use UsageService's resolved usage contract directly; remove duplicate percent/reset policy from serializers. Stable IDs, labels, missing-chat names, truthful receipt/digest/counts remain authoritative.
- Deterministic generator uses temporary tool roots, fixed clock, real service/serializer outputs and the approved P5 boundary. Manifest maps each built D0–D7/UI fixture to its source requirement/provider. Future-only contract samples are explicitly distinguishable and cannot be executable success evidence.
- Normal tests generate into a temporary directory. An explicit regenerate command updates repo fixtures. Two runs yield identical bytes; tracked fixtures match; Swift decodes every output.
- Recursive audit requires all notes to be known and exact rendered tone/text/buttons/status lines, with every field filled. Assert receipt/counter/turn-state consistency and no private content.

Acceptance: every read preserves a begun journal/native write with writer/runner/app-mutator fail-on-call guards; all contract fields/labels/usage/settings states; deterministic regeneration; complete current-screen manifest; zero catalogue drift; full app render/model tests against generated fixtures. No production action CLI, hook, notification or relaunch runtime acceptance is inferred.

## 7. CP2 final gate and live evidence

Run after all package-specific blockers are closed and independent reviewers have no blocking findings:

1. Full engine suite and `app/scripts/check.sh`; zero failures. Layer/tool-name/copy audits and staged scope checks. Add tests that fail when privacy filters, stale gates, process exclusion or atomic finalization are intentionally bypassed.
2. Coverage sheet maps U1–U9, T7–T11, V1–V8/V13/V14 and M12 to real assertions; green intent-only or unconditional fake-applied tests do not satisfy a row.
3. Both native adapter fixture suites and all generated fixtures checked/reproduced. App snapshots inspected in both themes; relevant view-model behavior verified.
4. Before any live write, list exactly which two throwaway chats/files will be created/read/written, what app will close/reopen and how cleanup works. Use named "Baton test (safe to delete)" chats in the Baton folder, backup every changed file under `.baton-spike/backup/`, and use only those test identities/templates. Reuse prior go only for that explicitly scoped run; ask for each closure and never close during a reply. Never approve trust/sign-in/permissions.
5. Verify Claude visibility after relaunch/release and Codex non-held delivery/held refusal as measured in specs. If live behavior differs, stop the adapter's acceptance and investigate; do not change capabilities to make a fixture test green.
6. Record cleanup and any retained artifacts. Paste real output and mark every CHECKPOINTS CP2 row pass/fail in the final hand-back report; mark CP2 passed only when all required gates—including live—pass.

## Review corrections and remaining limits

Both planning agents checked current code and challenged the previous report. Refinements retained here: Automatic/Offline is the required minimum, not an arbitrary writer dropdown; missing D12 integration is not a CP2 bug; a fake-transport applied flag proves no native mutation; creating a summary needs separate coverage rather than generic full-copy finalization; read constructors can recover pending writes; UI display approval needs revision identity; new chat/copy alternatives cannot silently change the original operation.

Planning itself does not fix E9/E10/B2/D6/D7 or makes CP2 pass. The existing reviewed G2/G3/C1 commits clear the commit boundary; this approved plan defines the repairs and the evidence required to accept them.
