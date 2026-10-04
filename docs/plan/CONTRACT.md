# Contract between the engine and the app

The app never reads a chat or Baton's record. It runs `baton <command> --json` and shows what comes back. This file is that interface. Track D builds against it with fixture files; track C makes the engine produce it. It is frozen at checkpoint CP0 and after that only grows.

## Rules

- Every command prints one JSON object on stdout and exits 0, also for an expected refusal. A crash exits non-zero with `{"error": {"kind": "internal", ...}}`.
- Every command that changes anything takes `--dry-run`, which returns the same object with `"applied": false`, and `--confirm <plan_id>`, which carries out exactly the plan that was shown. A plan id is refused if the chats changed since (`ChatChanged`).
- Text for the user is never built in the app. The engine returns **notes**: `{"id", "values", "text", "buttons", "status_line"}`. The app shows `text`; `id` and `values` are there for tests and for future translation.
- Tools are named `claude`, `codex`, `opencode`, `cursor`. Times are ISO 8601 in UTC.
- Unknown fields are ignored by the app, so the engine can add fields without breaking it.

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
| `baton ask --from T:ID --turn N --tool T --question Q` | Second opinion | `{"answer", "tokens", "seconds", "notes": [Note]}` |
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
