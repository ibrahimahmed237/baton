# Baton

Hand a conversation from Claude Code to Codex and back, and keep working in the same chat on each side.

**Status:** design agreed, nothing usable yet. The first milestone is a spike against the real desktop apps.

## What it does

- You link a Claude chat with a Codex chat. Only linked chats are ever touched.
- When a reply finishes on one side, the new turn is appended to the linked chat on the other side. No new chat per sync.
- If the other side's chat is open, the missing turns are attached to your next message there instead, with their times.
- A summary never goes into an existing chat. A brief always starts a new one.
- Every write is journaled first and can be undone.

The full design, with the decisions behind it and what is still unverified, is in [docs/DESIGN.md](docs/DESIGN.md).

## Layout

| Path | Contents |
|---|---|
| `docs/` | Design and spike findings |
| `spike/` | Throwaway scripts that test real app behaviour before the engine is written |
| `reference/` | Not in the repo. A local checkout of another tool, kept to study the session formats |

Planned: a Python engine with a CLI, hooks for both tools, and a SwiftUI menu-bar app.

## Credit

The session formats were first worked out by studying
[Chamotrans/codex-claude-session-sync](https://github.com/Chamotrans/codex-claude-session-sync) (MIT). Baton is its own code.
