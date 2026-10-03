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

**Headless runners (Q10)**
- Both exist. The ChatGPT app bundles the Codex CLI at `Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex`, same version as the desktop engine, with `exec --ephemeral`.

## Waiting

**Append to a real chat (Q1, Q2).** `spike/m0_append.py` is ready and passed a dry run on a sandbox copy (append on both sides, shapes checked, undo restores the original size). The automated permission check declined to let the assistant write into real chat files, so these two runs are done by hand:

- Claude test chat, while its process is alive and idle: done, see above.
- Codex test chat, once Codex releases it: does the appended turn show up after reopening, and does the agent know it? Waiting for a release; quitting the ChatGPT app is the sure way to get one.

**Append to a closed Claude chat (Q1).** Still untested: no way found yet to close one chat without restarting the app.

**Catch-up hook (Q11, Q12).** Not started. Needs a test hook in this folder and one trust step in Codex.
