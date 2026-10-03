# M0 spike: findings

Answers to the open questions in [DESIGN.md](DESIGN.md) section 9, as they come in. Each line says how it was found.

Environment: Claude desktop app with its bundled Claude Code 2.1.284, Codex Desktop (inside the ChatGPT app) with engine 0.159.2, macOS 27.

## Found so far

**How long a Claude chat stays open (Q3)**
- A chat that has been used keeps a live process long after the user leaves it. Observed from the session registry: one chat idle for 103 minutes and another for 108 minutes, both still alive; one process was 46 hours old.
- Only chats used since the app started have a process: 4 of 36 sidebar chats.
- Consequence: on the Claude side, the chat you hand back to is almost always still open. Catch-up at send is the main path there. Appending to the file applies to chats that have not been opened since the app started.

**Appending to an open Claude chat (Q1): it does not work, and the turn is lost**
- Test: one turn appended to the test chat's file while its process was alive and idle, then "what is the codeword?" sent in the app.
- The app did not show the appended turn.
- The agent did not know the codeword. It answered from memory, not from the file.
- The new prompt was written with the old last message as its parent, not the appended turn. The appended turn is left on a dead side branch of the history, so a later reload would not pick it up either.
- Conclusion: never append to a chat whose process is alive. This is the rule already in the design; it is now observed, not assumed.

**A Claude chat can change its session ID without compaction (Q8)**
- Observed on a normal chat when its working folder was changed: the app restarted the chat's process and continued it under a new session ID, in a new file. 494 message IDs are shared between the old and the new file, so the history was carried across with the same IDs.
- Nothing inside the new file points back at the old session. The only link is the desktop sidebar entry (`claude-code-sessions/.../local_*.json`): its own `sessionId` stayed the same and its `cliSessionId` now names the new file.
- Consequences: a link must be keyed on the sidebar entry, which is the stable identity of a chat, and follow `cliSessionId`. Message IDs survive the move, so the ledger's per-message tracking still holds.
- The same event shows the app does load a chat's history from disk when its process starts. Appending to a chat with no live process should therefore work; that is still to be tested cleanly.

**Appending to a closed Codex chat (Q2): it works**
- Test: with the ChatGPT app quit, one turn appended to the test thread's rollout in the shape Codex uses for its own Claude imports, and the `threads` row's timestamps bumped. Then the app reopened.
- The chat showed the appended turn as a normal turn, with its own time.
- Asked "what is the codeword?", the agent answered with it. The appended turn was in its context.
- Codex's own data agrees: it projected the appended turns as completed turns, continued its ordinals after them, and wrote the next real turn into the same rollout file.
- The turn appears twice only because the command was run twice. Baton's ledger exists to prevent exactly that.

**How long a Codex chat stays open (Q3)**
- The test thread was still held 14 minutes after its last reply, after the user had moved to other chats. Codex held five threads at once at that point. Like Claude, it keeps chats loaded after you leave them.
- Codex keeps a lock file per thread in `~/.codex/thread-writer-locks/` and holds it with a file lock while the thread is loaded. The test thread was still held several minutes after its last reply.
- Lock files of older threads disappeared between two listings, so a missing lock file means the thread is released.
- Not yet known: what makes Codex release a thread (leaving it, a timeout, closing the window).

**How Codex shows a chat's history**
- The rollout file is not read directly by the UI. `~/.codex/thread_history_1.sqlite` holds a projection of it (`thread_turns`, `thread_items`) and remembers how far it has read (`thread_history_projection_state`: next byte offset and next ordinal).
- Turns come from `task_started` / `task_complete` events and items from `item_completed` events, so an appended turn needs those events, not only the message records.
- Expected, not yet confirmed: after an append, Codex projects the new records the next time it loads the thread.

**Record shapes to write**
- Codex writes its own Claude imports as `task_started`, `item_completed` (UserMessage), `response_item` (user), `item_completed` (AgentMessage), `task_complete`, with plain incrementing ordinals. The spike script writes the same shape.
- A native Claude prompt record carries `promptId`, `promptSource`, `turnOrigin`, `turnPosition`, `permissionMode` and `origin`. The spike script copies them from the chat's last real prompt.

**Hooks (Q4, Q11)**
- Claude desktop: prompt hooks run and their text reaches the agent. Seen in use.
- Codex: documented to do the same (`hookSpecificOutput.additionalContext`, plus `systemMessage` for a user-facing notice). A new hook runs only after the user trusts it once with `/hooks`. Not yet run live.

**Codex is strict about what a hook prints**
- Seen in the Codex hooks panel for a new chat: a plugin written for Claude ran three hooks. `UserPromptSubmit` completed. `SessionStart` failed with "hook returned invalid session start JSON output" and `Stop` failed with "hook returned invalid stop hook JSON output".
- So hooks do run in Codex Desktop, per event, and the app shows each run and its result.
- Consequence: Baton's hooks must print exactly what each tool accepts for each event. A turn-end hook for Codex prints valid JSON and nothing else. One script per tool, or one script that knows which tool called it.

**Headless runners (Q10)**
- Both exist. The ChatGPT app bundles the Codex CLI at `Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex`, same version as the desktop engine, with `exec --ephemeral`.

## Waiting

**Append to a real chat (Q1, Q2).** `spike/m0_append.py` is ready and passed a dry run on a sandbox copy (append on both sides, shapes checked, undo restores the original size). The automated permission check declined to let the assistant write into real chat files, so these two runs are done by hand:

- Claude test chat, while its process is alive and idle: done, see above.
- Codex test chat, once Codex releases it: done, see above. Quitting the ChatGPT app released every thread lock at once; what else releases a thread is still unknown.

**Append to a closed Claude chat (Q1).** Still untested: no way found yet to close one chat without restarting the app.

**Catch-up hook (Q11, Q12).** Set up, not observed yet. `spike/m0_hook.py` is registered as a prompt hook for both tools in this folder only: `.claude/settings.local.json` for Claude and `.codex/hooks.json` for Codex, neither in the repo because they hold an absolute path. It acts only when the prompt mentions "codeword": it attaches one pretend missed turn and a short notice, and logs what the app passed in to `.baton-spike/hook-log.jsonl`. Codex needs the hook trusted once with `/hooks`. To observe in a new chat on each side: does the agent know the codeword, is the notice shown, and is the session ID in the hook input.
