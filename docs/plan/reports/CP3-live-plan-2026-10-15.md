# CP3 live check — the plan put to Ibrahim, 2026-10-15

Nothing below runs before Ibrahim's go. Each app close is asked again at that moment. Only chats named "Baton test (safe to delete)" in the Baton folder are used.

## 0. Look first (read only)
- `baton setup --json` and `baton setup install --tool T` previews for all four tools: show the exact file, entries and backups before anything is written.

## 1. Install
- `tools/install/install-baton.sh` → `~/.local/bin/baton`.
- Hooks, project scope, each with its tool closed: Claude `.claude/settings.local.json` (already exists, Baton's two entries are merged in), Codex `.codex/hooks.json`, Cursor `.cursor/hooks.json`, OpenCode `.opencode/plugins/baton.js`.
- Ibrahim: in Codex type `/hooks` and trust both entries; restart Cursor and OpenCode once.

## 2. Test chats
- Kept from CP2: Claude and Codex "Baton test (safe to delete)".
- New, by Ibrahim: one each in OpenCode and Cursor, in the Baton folder, with one "hello".

## 3. Runs
1. Link Claude ↔ Codex test chats (full copy), then OpenCode ↔ Cursor (history attached).
2. Write a turn on each side; check catch-up at send (attached text reaches the agent) and sync at turn end (turn arrives on the other side), in all four tools.
3. Close-sync-reopen offer for Claude and Cursor: confirm it, see the app close, the write, the reopen; refuses while a chat is replying.
4. Create a new chat through linking and cut (undo) through the adapters on each tool.
5. Unlink, uninstall hooks (`baton setup uninstall`), remove what the test created; say what is left.

## Evidence
Every step's command, result and what Ibrahim saw goes into `reports/CP3-live-2026-10-xx.md`; a difference from SPIKE-M0.md or more-tools.md stops that tool until understood.
