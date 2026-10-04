# Working in this repository

Baton links a chat in one coding agent with a chat in another (Claude Code, Codex, OpenCode, Cursor) and keeps them in sync.

Read before doing anything:
1. `docs/plan/STATUS.md` — where the work stands right now and what is next.
2. `docs/plan/ORCHESTRATOR.md` — how work is run, checked and handed back.
3. `docs/plan/README.md`, then `ARCHITECTURE.md` and `CONTRACT.md` in the same folder.

Rules that always apply:
- One branch: `chore/project-setup`. Never commit to `main`. Never push. No pull requests.
- Commit messages say why, in plain words. Never add `Co-Authored-By` or any tool attribution.
- Never touch real chats of any tool. Tests run on files built in temporary folders.
- Engine: Python standard library only. Tests: `python3 -m unittest discover -s tests -t .`
- App: `cd app && swift build && swift test`.
- `docs/plan/CONTRACT.md` is frozen: add, never rename or remove.
