# Architecture

## The shape

Four layers. A layer may use the ones below it and never the ones above.

```
app/            SwiftUI. Shows what the engine says. Never reads or writes a chat.
  │  calls the `baton` command, reads JSON  (CONTRACT.md)
cli/, hooks/    Thin entry points: parse arguments, call one service, print JSON.
  │
services/       Use cases: status, plan, apply, link, merge, undo, brief, digest, setup, relaunch.
  │  depend on ports only
ports/          Interfaces a tool must implement, and the record store interface.
domain/         Plain data and rules: turns, links, states, capabilities, errors. No I/O.
  ▲
adapters/       One package per tool, implementing ports. The only place a tool's format is known.
ledger/         SQLite implementation of the record store port.
```

Dependencies point inward: `adapters` and `ledger` depend on `ports` and `domain`; `services` depend on `ports` and `domain`; nothing in `domain`, `ports` or `services` imports an adapter. The adapters are handed to the services by `cli/wiring.py`, the single place where concrete classes are chosen.

## Package layout

```
baton/
  domain/
    model.py          Message, Turn                      (exists: baton/model.py)
    link.py           Link, LedgerTurn, Event, states    (from baton/ledger.py dataclasses and constants)
    capabilities.py   Capabilities, Visibility, WriteWindow
    conditions.py     SideCondition
    errors.py         every error Baton raises
  ports/
    tool.py           ToolAdapter and the small interfaces it is made of
    store.py          RecordStore
    clock.py          Clock (now), for tests
  ledger/
    sqlite_store.py   Ledger/RecordStore facade; one SQLite connection
    links.py          link identity and atomic creation/replacement
    turns.py          turn identity, order and per-side states
    history.py        event records
    journal.py        rollback receipts and atomic delivery completion
    records.py        shared validation and metadata helpers
    schema.py         tables and migrations
  services/
    status.py         where each side stands              (exists: baton/status.py)
    planner.py        what a sync or merge would do       (exists: baton/planner.py)
    applier.py        carries a plan out
    delivery_plan.py  confirmation and delivery data types (reexported by applier)
    preview.py        complete observation snapshots and confirmation fingerprints
    refresh.py        reconcile content, names and explicit visibility evidence
    observations.py   shared condition, history and local identity helpers
    linker.py         link, copy, change, remove
    merger.py         applies a chosen merge
    undo.py           back to a history entry
    journal.py        journal, saved copies, take-back
    brief.py          offline brief; agent brief with fallback
    digest.py         "since you left"
    usage.py          context in use, limits
    setup_check.py    what is missing per tool, with its fix
    relaunch.py       wait idle, close, write, reopen
    notes.py          builds the "what will happen" block for a plan
  notes/
    catalogue.py      note ids -> sentence templates, buttons, status line
  adapters/
    fake/             in-memory tool for tests
    claude/  codex/  opencode/  cursor/
      reader.py  writer.py  locator.py  state.py  hooks.py  runner.py  app.py  facts.py
  cli/
    main.py  wiring.py  output.py  commands/<one file per command>
  hooks/
    prompt.py  turn_end.py                              entry points the tools call
    opencode_plugin.js
app/                  Swift package: BatonKit, BatonUI, thin Baton executable (track D)
tests/
  unit/  adapters/  scenarios/  contract/  fixtures/
```

`spike/` stays as it is: it is the record of how each fact was measured, and adapters are written by reading it, not by importing it.

## The interfaces

Small, one job each (interface segregation). A tool implements the ones it can; `Capabilities` says which.

```python
class ChatLocator(Protocol):
    def chats(self) -> list[ChatRef]: ...            # id, name, folder, updated
    def resolve(self, chat_id: str) -> ChatRef: ...  # follows a chat that moved to a new id
    def name(self, chat_id: str) -> str: ...

class ChatReader(Protocol):
    def read(self, chat_id: str) -> list[Turn]: ...
    def usage(self, chat_id: str) -> Usage: ...      # tokens in context, size if known, limit if hit
    def files_changed(self, turn: Turn) -> list[str]: ...   # for the same-file warning and the digest

class ChatState(Protocol):
    def condition(self, chat_id: str) -> SideCondition: ...   # exists, open, replying, hooks_ready
    def format_version(self) -> FormatCheck: ...              # known / unknown, with the version seen

class ChatWriter(Protocol):
    def prepare(self, chat_id: str | None, kind: str) -> WriteReceipt: ... # rollback data before any mutation; None for create
    def create(self, turns: Sequence[Turn], name: str, folder: str) -> WriteResult: ...
    def add(self, chat_id: str, turns: Sequence[Turn]) -> WriteResult: ...
    def place(self, chat_id: str, turns: Sequence[Turn], before_local_id: str) -> WriteResult: ...
    def cut(self, chat_id: str, keep_through_local_id: str) -> WriteResult: ...
    def rename(self, chat_id: str, name: str) -> WriteResult: ...
    def take_back(self, receipt: WriteReceipt) -> None: ...   # undo one write of this adapter

class HookSupport(Protocol):
    def install(self) -> SetupFinding: ...
    def uninstall(self) -> None: ...
    def check(self) -> SetupFinding: ...
    def attach_reply(self, text: str, notice: str | None) -> str: ...   # what the prompt hook prints
    def turn_end_reply(self) -> str: ...

class BackgroundRunner(Protocol):
    def available(self) -> SetupFinding: ...
    def ask(self, prompt: str, folder: str, read_only: bool = True) -> str: ...

class AppControl(Protocol):
    def running(self) -> bool: ...
    def close(self) -> None: ...                     # asks the app to quit; never forces
    def open(self, chat_id: str | None, folder: str | None) -> None: ...
    def release(self, chat_id: str) -> None: ...     # Claude only: end one idle chat's process

class ToolAdapter(Protocol):
    name: str                                        # "claude", "codex", "opencode", "cursor"
    facts: Capabilities
    locator: ChatLocator; reader: ChatReader; state: ChatState; writer: ChatWriter
    hooks: HookSupport; runner: BackgroundRunner | None; app: AppControl
```

Notes on these interfaces, settled at CP0:
- An adapter reports chat content, not the screen. Visibility uses added_turn_visible and SideCondition.app_started_at: AT_ONCE immediately; AFTER_RELAUNCH after a later app start; ON_REOPEN_CHAT after a later app start or explicit user mark_shown. A hook call never proves reopening.
- `write_window` covers adding, creating, placing and cutting. Renaming has its own answer per tool, given by the writer raising `AppMustBeClosed` or returning a result with `needs`.
- `checked_versions` is a tuple of strings; an adapter compares it with what `state.format_version()` reports.
- The record store and its row type are still named `Ledger` and `LedgerTurn` in code. They are internal names; nothing shown to the user uses them. Renaming them is not worth the churn now.

`Capabilities` is data, filled in per tool from more-tools.md:

| Field | Values | Claude | Codex | OpenCode | Cursor |
|---|---|---|---|---|---|
| `write_window` | when real turns can be written | `CLOSED_OR_RELEASED` | `NOT_HELD` | `ANY_TIME` | `APP_CLOSED` |
| `new_chat_visible` | when a created chat shows | `AFTER_RELAUNCH` | `AT_ONCE` | `AT_ONCE` | `AFTER_RELAUNCH` |
| `added_turn_visible` | when an added turn shows | `AFTER_RELAUNCH` | `AT_ONCE` | `ON_REOPEN_CHAT` | `AFTER_RELAUNCH` |
| `can_cut` | chat can be made shorter | yes | no | yes | no |
| `can_place` | turn can be placed before another | no | no | yes | yes |
| `can_release_chat` | one idle chat can be released | yes | no | no | no |
| `opens_at_chat` | app opens at a given chat | yes | yes | no | no |
| `limit_has_reset_time` | | yes | yes | no | no |
| `context_size_known` | | per model | yes | no | yes |
| `hooks_need` | first-use step | none | trust once | restart once | none |
| `checked_versions` | format versions writing is allowed for | from files | from schema | schema | record `_v` 18 |
| `replays_tool_calls` | real tool-call blocks can be written | yes | no | yes | no |

The planner, applier, undo and notes read these fields. A new tool is a new `facts.py` plus the classes above.

## Errors

All in `domain/errors.py`, each with a note id so the app can show the right sentence.

| Error | Raised when | Note |
|---|---|---|
| `AlreadyLinked` | linking a chat that is in a link | `link.already_linked` |
| `ChatHeld` | a write is asked for a chat the app holds | `write.chat_open` |
| `AppMustBeClosed` | a write needs the app closed and it runs | `write.app_must_close` |
| `ChatReplying` | closing or releasing would stop a reply | `relaunch.replying` |
| `UnknownFormat` | the tool saves chats in a version not checked | `format.unknown_version` |
| `ChatChanged` | the chat changed between plan and write | `write.chat_changed` |
| `DecisionNeeded` | both sides have unsynced turns | `merge.decision_needed` |
| `OrderNotAllowed` | a merge order breaks one app's own order | `merge.order_not_allowed` |
| `AlreadyDelivered` | keeping back a turn already sent | `keep.too_late` |
| `NotAvailable` | a tool lacks what the action needs | `tool.cannot` |
| `SetupIncomplete` | hooks, trust, command or sign-in missing | `setup.<finding>` |

Services never print and never exit. They return results or raise these. `cli/` turns them into JSON.

## Rules for the code

**Clean code**
- Names say what a thing is in the user's words: chat, turn, link, attach, add, cut. No "ledger", "rollout" or "session" in a public name outside its adapter.
- A function does one thing and fits on a screen. A module has one reason to change.
- No comments that repeat the code. A comment gives a reason or a fact from the spike, with the file it came from.
- No tool name in a branch outside `adapters/`: not `if tool == "codex"`, but `if not adapter.facts.can_cut`.
- No sentence for the user in services or adapters. They return note ids and values; `notes/catalogue.py` holds the words.
- Standard library only in the engine.

**SOLID, as it applies here**
- *Single responsibility:* reader, writer, state, hooks, runner and app control are separate classes per tool.
- *Open/closed:* a tool is added by a new adapter package; nothing in `services/` changes.
- *Liskov:* every adapter passes the same adapter test suite (`tests/adapters/suite.py`); a service cannot tell them apart except through `facts`.
- *Interface segregation:* a service asks for the smallest interface it needs (the digest takes a `ChatReader`, not a whole adapter).
- *Dependency inversion:* services get adapters and the store through their constructor; `cli/wiring.py` builds them.

**State and time**
- Only the record store keeps state. Services are stateless between calls.
- Time comes from a `Clock` passed in, never from `datetime.now()` inside a service.
- A write is always: plan, prepare rollback receipt, journal begin, write, verify, record, journal commit. If verify fails, take back, and record that too. Journal.begin persists the pre-write receipt; commit saves the post-write receipt. Startup recovery takes back every begun/uncommitted entry with its pre-write receipt, including create receipts that record that no chat existed. Fake and shared adapter suite test this additive port.

## Testing

| Kind | Where | What it proves |
|---|---|---|
| Unit | `tests/unit/` | One module, with the fake adapter and an in-memory store. |
| Adapter suite | `tests/adapters/suite.py`, run once per tool | Every adapter behaves the same: what it writes it reads back, ids are stable, a second read adds nothing, facts match behaviour. Runs on files built in a temp folder, never on real chats. |
| Fixtures | `tests/fixtures/<tool>/` | Small real-shaped chats, made by hand from the shapes recorded in the spike. No user content. |
| Scenarios | `tests/scenarios/` | The spec's scenarios (S, T, U, V, X) end to end on the fake adapter, one test per scenario, named after it. |
| Contract | `tests/contract/` | Every command's JSON matches CONTRACT.md; the app's fixture files are generated from these tests. |
| Live | `tests/live/`, off by default | The same adapter suite against throwaway chats in the real apps. Run by hand before a checkpoint. |

A scenario test reads like its row in the spec: given, when, then. If a spec row changes, its test changes in the same commit.

## For contributors later

- `docs/plan/ARCHITECTURE.md` (this file) and `CONTRACT.md` are the two things to read.
- To add a tool: copy `adapters/fake/`, fill in `facts.py` from measurements, make the adapter suite pass, add the tool's entries to the note catalogue. Nothing else changes.
- To add a feature: a service, its note ids, its command, its contract entry, its screen. In that order.

### Mapped tool activity

Mapping uses additive `TOOL_TEXT` (`tool_text`) for flattened tool activity. It remains ordinary labelled text and never becomes the final reply when a turn has no reply. Replay-capable targets preserve native call/result blocks. Adapter writers must serialize TOOL_TEXT as ordinary text; mapping and user wording stay in services/catalogue. Prompt content stays unchanged; configurable created-chat tags belong on the title.

### Atomic completion and confirmations

E5 confirmations fingerprint full chat contents, chat references, side conditions, capabilities, and link/turn records. A changed fingerprint requires a new preview. SQLite delivery states and committed journal receipts complete in one transaction; unfinished recovery must not leave content marked delivered. E6 must avoid a live link to a creation rolled back during recovery.

Real adapters must preserve the TOOL_TEXT distinction across their wire-format writer/reader round trip, including an incomplete turn with no final reply. Serializing it as ordinary text alone is insufficient if the reader then mistakes it for the final reply; adapter fixtures and shared-suite checks must cover that.

### E5 conflict precedence clarification

Reviewer decision: bypass marks the missing delivery waiting. If a new completed destination turn also exists, S7 takes precedence and both directions hold until the merge decision; S9 redelivery follows merge (E7). Without a competing completed turn, S9 can redeliver directly.


### E6 creation and visibility metadata

Link creation/replacement and journal completion commit together after read-back verification. A failed transaction preserves the prior link and removes the uncommitted created chat via its pre-write receipt. Full-copy replacement preserves the link and canonical turn IDs, order and pins; it reconciles local and originating IDs for the replaced side. Copies from a linked side reconstruct the canonical public conversation, including attached history, and refuse stale unrecorded native turns until refresh.

Canonical copy payloads confirm the exact record snapshot used to choose turns, including keep/skip/order, rather than a later record read. Unlinked creation time and monotonic visibility are stored separately in created_copies, keyed by tool/chat, independently of 30-day rollback-receipt retention. Unlink observes metadata only and never requires readable chat content.

### R10 responsibility boundaries (Reviewer)

Ledger combines internal links, turns, history and journal method groups behind the existing RecordStore interface. All groups share the connection owned by Ledger; they do not open their own connections or introduce extra commits. Atomic delivery/history/journal completion and atomic creation/replacement retain their original transaction boundaries. Applier delegates confirmation construction to PreviewBuilder and reconciliation to ChatRefresh. ApplyStep and PreparedPlan remain importable from applier for compatibility. This extraction changes ownership only, not delivery decisions or recovery behavior.
