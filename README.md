# Baton

Hand a conversation from Claude Code to Codex and back, and keep working in the same chat on each side.

**Status:** nothing usable yet. The design is agreed and the spike against the real desktop apps is finished ([findings](docs/SPIKE-M0.md)). The engine is being built; so far it can read a chat from either tool into turns.

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
| `baton/` | The engine. Python, standard library only |
| `tests/` | Engine tests. They build made-up chats; no real conversation is stored here |
| `docs/` | Design and spike findings |
| `spike/` | Throwaway scripts that tested real app behaviour before the engine was written |
| `reference/` | Not in the repo. A local checkout of another tool, kept to study the session formats |

Still to come: the rest of the engine with a CLI, hooks for both tools, and a SwiftUI menu-bar app.

## Tests

```bash
python3 -m unittest discover -s tests -t .
```

## Credit

The session formats were first worked out by studying
[Chamotrans/codex-claude-session-sync](https://github.com/Chamotrans/codex-claude-session-sync) (MIT). Baton is its own code.
