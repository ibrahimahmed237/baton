# Contract between the engine and the app

The app never reads a chat or Baton's record. It runs `baton <command> --json` and shows what comes back. This file is that interface. Track D builds against it with fixture files; track C makes the engine produce it. **Frozen at checkpoint CP0, 2026-10-05.** From here it only grows: fields and commands are added, none is renamed or removed.

## Rules

- Every command prints one JSON object on stdout and exits 0, also for an expected refusal. A crash exits non-zero with `{"error": {"kind": "internal", ...}}`.
- Every command that changes anything takes `--dry-run`, which returns the same object with `"applied": false`, and `--confirm <plan_id>`, which carries out exactly the plan that was shown. A plan id is refused if the chats changed since (`ChatChanged`).
- Text for the user is never built in the app. The engine returns **notes**: `{"id", "values", "text", "buttons", "status_line"}`. The app shows `text`; `id` and `values` are there for tests and for future translation.
- Tools are named `claude`, `codex`, `opencode`, `cursor`. Times are ISO 8601 in UTC.
- Unknown fields are ignored by the app, so the engine can add fields without breaking it.

## Types and edge cases

Settled at CP0 from the questions the app's first build raised.

- **IDs.** Link, turn and event ids are integers. Chat ids and plan ids are strings.
- **Numbers.** Counts and tokens are integers. `percent`, `seconds` and `glass` are numbers that may have a fraction.
- **Times** are strings, ISO 8601 in UTC, with or without fractional seconds. The app treats them as opaque until it formats them.
- **Fixed words** (tool, state, action, mode, tone, reason) are lower-case strings exactly as written in this file. A value the app does not know is shown as is, never a crash.
- **Null and missing.** A field described as `X | null` may be null or absent; the app treats both the same. `Note.status_line`, `Note.buttons[].primary`, `Turn.messages`, `Turn.ended_at`, `Side.synced_up_to`, `Side.waiting_reason`, `Side.since_you_left`, `usage.size`, `usage.percent`, `usage.limit`, `Plan.link_id`, a history event's `tool`, a setup tool's `version`, `last_shared` and `ends_at` can all be null. Everything else is always present.
- **A missing chat** still has a `Chat` object in its `Side`, with the last known name, and `condition.exists` false.
- **Errors.** `{"error": {"kind": "<error name in snake_case>" | "internal", "note": Note}}`. Expected refusals exit 0; `internal` exits non-zero and may have no note.
- **Capabilities** in `setup` are an object with the field names of ARCHITECTURE.md and lower-case values: `{"write_window": "app_closed", "new_chat_visible": "after_relaunch", "added_turn_visible": "after_relaunch", "can_cut": false, "can_place": true, "can_release_chat": false, "opens_at_chat": false, "limit_has_reset_time": false, "context_size_known": true, "hooks_need": "none", "checked_versions": ["18"], "replays_tool_calls": false}`.
- **Merge presets** are `[{"id": "by_time" | "<tool>_first" | "dont_reorder", "label": "…", "order": [turn ids]}]`.
- **Lists as arguments** (`--order`, `--tools`) are comma-separated.
- **Commands without a plan** (`pause`, `resume`, `keep`, `send`, `pin`, `unpin`, `settings set`, `setup install`, `ask`, `open`, `notify`) act at once and take neither `--dry-run` nor `--confirm`: they change nothing in any chat. Everything that writes to a chat or changes a link returns a Plan first.
- **`ask`** returns an `answer_id`; `ask add --answer <answer_id>` refers to it. Answers are kept for one hour.
- **`catch-up`** is the one command that does not take `--json`; its output is whatever the calling tool expects.
- **Fixture files** are named `<command>.<state>.json`, sub-commands with a hyphen (`ask-add`, `merge-show`, `settings-get`), default state `sample`.

## Shared objects

```jsonc
// Note: one sentence block the user sees
{ "id": "create.needs_relaunch", "tone": "warning",          // info | ok | warning | danger
  "values": {"tool": "claude", "turns": 16},
  "text": "Baton closes Claude, creates the chat, and opens Claude again at it. ...",
  "buttons": [{"id": "close_sync_reopen", "label": "Close Claude, sync, reopen", "primary": true},
              {"id": "sync_relaunch_later", "label": "Sync now, I relaunch later"},
              {"id": "cancel", "label": "Cancel"}],
  "status_line": "Relaunch Claude to see this chat" }

// Chat: one chat in one tool
{ "tool": "claude", "id": "local_3b2…", "name": "Session sync tool", "folder": "/Users/…/baton",
  "updated_at": "2026-10-04T14:05:00Z", "linked": true }

// Side: where one side of a link stands (sync-status R1 to R5)
{ "tool": "claude", "chat": Chat, "condition": {"exists": true, "open": true, "replying": false, "hooks_ready": true},
  "total": 16, "agent_has": 14, "chat_shows": 12, "added": 0, "attached": 2, "waiting": 2,
  "kept_elsewhere": 0, "skipped": 0,
  "synced_up_to": Turn | null, "waiting_reason": "chat_open",
  "next_message": {"turns": 2, "tokens": 3200},
  "usage": {"tokens": 164000, "size": 200000, "percent": 82, "limit": null | {"resets_at": "…" | null}},
  "since_you_left": null | {"turns": 4, "files": 6, "commands": 9, "since": "…"},
  "notes": [Note] }

// Turn: one turn of a linked conversation
{ "id": 41, "seq": 14, "origin": "codex", "first_line": "Fix the failing test", "started_at": "…", "ended_at": "…",
  "tokens": 1600, "pinned": false, "states": {"claude": "waiting", "codex": "written_here"},
  "messages": [{"kind": "prompt" | "reply" | "tool_call" | "tool_result", "text": "…", "tool": "…"}] }  // only with --messages

// Step: what a plan does to one side
{ "tool": "claude", "action": "add" | "add_after_release" | "attach" | "hold" | "create" | "create_shorter" | "cut" | "place",
  "turns": [turn ids], "reason": "", "needs": ["app_closed" | "relaunch_to_see" | "reopen_chat_to_see"], "notes": [Note] }

// Plan: what an action would do
{ "plan_id": "p_…", "applied": false, "link_id": 3, "steps": [Step], "decision_needed": false, "notes": [Note] }
```

## Commands

| Command | Does | Returns |
|---|---|---|
| `baton setup --json` | Checks every tool | `{"tools": [{"tool", "installed", "ready", "version", "findings": [{"id", "ok", "note": Note}], "facts": Capabilities}]}` |
| `baton setup install --tool T` | Installs hooks or plugin | same as `setup` for that tool |
| `baton chats --tool T [--folder F]` | Lists chats | `{"chats": [Chat]}` |
| `baton suggestions` | Chats likely to be the same conversation | `{"suggestions": [{"a": Chat, "b": Chat, "matched_turns": 12}]}` |
| `baton links` | All links with a one-line state | `{"links": [{"link_id", "sides": {tool: Chat}, "mode", "paused", "headline": Note, "in_sync", "decision_needed"}]}` |
| `baton status --link L [--messages]` | Full status of one link | `{"link_id", "mode", "paused", "in_sync", "decision_needed", "sides": {tool: Side}, "turns": [Turn], "notes": [Note]}` |
| `baton link --from T:ID --to T[:ID] --mode full_copy\|attached_history\|brief` | Links, creating the other chat when no id is given | Plan |
| `baton copy --from T:ID --to T [--and-link]` | Copies a chat | Plan |
| `baton relink --link L --to T:ID` | Changes one side | Plan |
| `baton unlink --link L` | Removes the link | Plan |
| `baton pause --link L` / `resume` | | `{"link_id", "paused"}` |
| `baton sync --link L [--to T]` | Delivers waiting turns | Plan |
| `baton continue --link L --in T` | Syncs, then opens that chat | Plan plus `"opened": true` |
| `baton merge --link L --show` | The decision screen's data | `{"last_shared": Turn, "unsynced": [Turn], "order": [turn ids], "presets": […], "outcome": {tool: "keeps_chat"\|"merged_copy"}, "overlaps": [[id, id]], "same_files": [{"file", "turns": [ids]}], "notes": [Note]}` |
| `baton merge --link L --order ids\|--preset P\|--keep T\|--split` | Applies a decision | Plan |
| `baton history --link L` | Everything done to a link | `{"events": [{"id", "at", "kind", "tool", "turns": [ids], "text", "can_undo", "can_restore"}]}` |
| `baton undo --link L --to EVENT` | Back to before an event | Plan, with `"removes": [{"turn": Turn, "only_here": bool}]`, `"ends_at": Turn` |
| `baton restore --event E` | Puts back a cut, or returns to the earlier chat | Plan |
| `baton keep --turn N` / `send --turn N` / `pin` / `unpin` | Per-turn marks | `{"turn": Turn}` |
| `baton brief --link L --to T [--writer T\|offline]` | Brief in a new chat | Plan, with `"brief": {"writer", "tokens", "pinned": [ids]}` |
| `baton ask --from T:ID --turn N --tool T --question Q` | Second opinion | `{"answer_id", "answer", "tokens", "seconds", "notes": [Note]}` |
| `baton ask add --answer A` | Adds it to the chat as a turn | Plan |
| `baton rename --link L --name N [--tools …]` | One name on both sides | Plan |
| `baton relaunch --tool T [--when-idle] [--then-sync L]` | Close, write, reopen | Plan, with `"replying": [Chat]` |
| `baton open --tool T --chat ID` | Opens the app at the chat or its folder | `{"opened": "chat"\|"folder", "note": Note}` |
| `baton settings get` / `set KEY VALUE` | | `{"settings": {...}}` |
| `baton notify --tool T --chat ID` | Called by the turn-end hook | `{"synced": [link ids], "queued": [link ids], "offers": [Note]}` |
| `baton catch-up --tool T --chat ID` | Called by the prompt hook; prints what the tool expects, not this JSON | tool-specific |

## Settings

| Key | Values | Default | From |
|---|---|---|---|
| `notice_on_attach` | bool | true | DESIGN 4 |
| `offer_relaunch` | bool | true | R6 |
| `add_to_idle_claude` | `on_button` \| `automatic` | `on_button` | R5, more-tools |
| `offer_switch_at_limit` | bool | true | W2 |
| `merge` | `ask` \| `by_time` | `ask` | M10 |
| `brief_threshold_tokens` | number | 150000 | DESIGN 6 |
| `hide_script_chats` | bool | true | DESIGN 1 |
| `title_tag` | bool | true | DESIGN 7 |
| `theme` | `system` \| `light` \| `graphite` | `system` | DESIGN 7 |
| `glass` | 40 to 95 | 62 | DESIGN 7 |

## Fixtures for the app

`tests/contract/` writes one JSON file per command and state into `app/Fixtures/`. The app's previews and tests load these, so every screen can be built and reviewed before the engine is connected. The states to cover are listed per screen in [track-d-app.md](track-d-app.md).

## CP1 additive condition fields

Side.condition may also include app_running (boolean), app_started_at (UTC ISO 8601 string, empty when unknown), and format_known (boolean). Existing fields retain their meaning; consumers ignore these additions until needed. A prompt-hook call is not proof that a chat was reopened. Deferred visibility clears only after the app_started_at evidence described in ARCHITECTURE.md, or explicit user mark_shown for ON_REOPEN_CHAT.

For fixture-built CP1 screens, `links` may include an optional top-level `notes: [Note]` for engine-supplied empty-state, Continue and link-recent labels. Missing notes decode as an empty list. This does not change existing links fields.

A link summary may also contain `needs_attention: bool`. The engine decides whether the link belongs in Needs attention; the app does not infer it from prose or tool names. Legacy engines that omit it retain the existing decision_needed fallback.

For mapped, non-replayable tool activity, Turn.messages may additionally use `kind: "tool_text"`. It contains labelled ordinary text, never a native tool call or final reply. Existing kinds retain their meaning. The app groups this kind with expandable tool activity; real adapter writers serialize it as ordinary text.

## CP1 reviewer additions: tool display labels (F2)

Chat, Side, Step, and each setup tool object additionally contain `tool_label: string` next to `tool`. The engine supplies the display labels `Claude`, `Codex`, `OpenCode`, and `Cursor`; `tool` remains the stable lower-case identifier used in commands and map keys. The app displays the supplied label, without constructing tool names. Existing clients ignore this additive field; app models accept its absence in older payloads.

For example: `{"tool": "claude", "tool_label": "Claude", ...}`. Note values referring to a coding app, including `{tool}`, use the display label. Tool-call names inside messages and mapping notes retain their existing meaning; a tool call is not a coding app label. C2 generates these fields and renders the note values; hand-made fixtures supply them through D4b.

## R9 — existing-link copy and retained-side relink

Reviewer decision R9 adds these signatures, preserving all earlier signatures:

- `baton link --link L --replace T --mode full_copy`: create a full copy for existing linked side T, move that side of the link to it and leave its earlier chat untouched (A4).
- `baton relink --link L --to T[:ID] --keep T2`: change the link with side T2 explicitly retained (A0).

Both follow the existing dry-run/confirm plan rules. D5 sends these choices; C3 implements the action commands.

## D5 — engine-supplied link dialog presentation

Additive fields, absent in older payloads:

- `Chat.link_id: integer | null` identifies its current link for an explicit change-link choice.
- `setup.notes: [Note]` supplies dialog headings and action labels (`dialog.link`, `dialog.target`, `dialog.target_chat`, `dialog.new_chat`, `dialog.retained_side`, `dialog.ways`, `dialog.what_will_happen`, `dialog.actions`).
- Each setup tool may contain `link_modes: [{"mode": "full_copy" | "attached_history" | "brief", "available": bool, "label": Note, "tag": Note | null, "reason": Note | null}]`. The engine supplies eligibility and the reason; the app never derives them from capabilities. A missing list provides no new eligibility claim. Tags use the existing specified mode language.

The preview for an already-linked source includes the named current partner and change-link note. Every destination/mode/retained-side change invalidates the previous preview and requires its new notes to be displayed before confirmation. C2 generates this presentation; C3 implements action commands.

### Relink mode (Ibrahim approved, 2026-10-05)

The R9 retained-side relink signature additionally accepts `--mode full_copy|attached_history|brief`, defaulting to `full_copy` when absent. The selected mode describes a new counterpart; brief always creates a new chat. Earlier relink callers keep their default behavior. D5 sends the selected mode and retained side, and C3 implements it.
