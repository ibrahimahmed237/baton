# CP2 live run, step A: read-only look at the real stores

2026-10-13, by Claude with Ibrahim's go. Nothing was written, no app was closed, no chat text was read. Structure, names and counts only.

## Codex

| Assumed by the adapter | Found | Result |
|---|---|---|
| `state_5.sqlite`, table `threads`, 27 required columns | All 27 exist. Every NOT NULL column without a default is one the adapter fills (`id`, `rollout_path`, `created_at`, `updated_at`, `source`, `model_provider`, `cwd`, `title`, `sandbox_policy`, `approval_mode`). 262 rows. Newest migration 59. | Matches |
| `history_mode` is `paginated` for a created chat | 250 `paginated`, 12 `legacy`. | Matches |
| `thread_history_1.sqlite`, table `thread_history_projection_state` with `next_byte_offset`, `next_ordinal` | Columns are `next_rollout_byte_offset`, `next_rollout_ordinal` (both NOT NULL). | **Differs. Fixed in `006ce07`.** Before the fix Baton could never tell whether Codex had read past its write, and always refused a take-back. |
| Lock files in `thread-writer-locks/<id>.lock`; a loaded chat's file cannot be locked by us | 4 files for 262 chats, all empty, all four refuse a shared non-blocking lock; `lsof` shows the Codex process holding exactly those four. One of them is the orchestrator chat that is open in Codex Desktop. | Matches. Hold detection by lock is real: loaded chat = file exists and is locked; released chat = no file. |
| Hook trust in `config.toml` under `[hooks.state."…"]` with `trusted_hash` | Four such tables with `trusted_hash` exist. No `hooks.json` in the Codex home yet. | Layout matches; contents not read. |
| Rollout record types | Not checked: reading a real rollout was not allowed by the session's safety check. It is checked in step B on the throwaway chat only. | Open |

## Claude

| Assumed | Found | Result |
|---|---|---|
| `~/.claude/projects/<folder>/<id>.jsonl` | 49 such files for the Baton folder, plus 7 folders named by id and one `<id>.desktop-released.json`. | Matches. The `.desktop-released.json` file and the id-named folders are not known to the adapter; step B looks at what they are on the throwaway chat. |
| Sidebar entries under `Library/Application Support/Claude/claude-code-sessions/*/*/local_*.json` | Not opened in step A. | Step B |

## What step B must still prove

1. Codex: a chat that is not loaded accepts Baton's added turn and shows it at once when opened; a loaded chat is refused; the index offset is read correctly after Codex opens the chat.
2. Whether Codex waits, fails or ignores when Baton holds a chat's lock file during its write (milliseconds).
3. Record types of a real rollout written by the current Codex version.
4. Claude: added turn shown after relaunch; refused while the chat is open; what the released file means.
