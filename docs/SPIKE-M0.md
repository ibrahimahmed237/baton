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
- Eight hours later, with the app still running: the two test threads the user had left were released (no lock file), and the last one opened was still held.
- That did not turn out to be a rule. In a later 27-minute watch nothing was released, and chats idle for 67, 70, 105 and 581 minutes were all still held, including ones no longer on screen. What released the first two is not known. In practice a Codex chat that was opened stays held until the app is relaunched, and Baton checks the lock before every write instead of assuming.
- A turn added to a released chat while the app was running showed up as soon as the chat was reopened, with no relaunch. The user saw it in the app.

**How long a Claude chat stays open, measured again**
- Three chats sat idle for over eight hours and all still had a live process. There is no idle timeout at that scale: a Claude chat that was opened stays open until the app quits.

**Creating a chat from outside (the twin)**
- Codex: `spike/m0_create.py codex` wrote a new rollout and one row in `threads`, copying settings and base instructions from the user's newest thread. A second turn was then appended. Codex's own engine, run headless, resumed the thread and listed both codewords. The running desktop app loaded the thread when its link was opened. Works.
- Claude: `spike/m0_create.py claude` wrote a new session file and a sidebar entry. The running app does not notice a new sidebar entry: the chat was absent from its list and its link did nothing. After a relaunch both created chats were listed. Works, but only after a relaunch.
- The created Codex thread also answered correctly when the user typed in it in the desktop app.

**Appending to a closed Claude chat (Q1): it works**
- Clean run: a chat created from outside with one turn (APRICOT-4), a second turn appended while nothing held it (MELON-7), then the app relaunched.
- Asked inside the app to list the codewords, the agent answered "APRICOT-4 MELON-7". The new prompt's chain of parents runs through all four messages Baton wrote, and the chat kept its session ID.
- So on both sides: a closed chat accepts appended turns, and the agent has them when the chat is next opened.

**Opening an app at a chat**
- Codex: `open codex://threads/<thread id>` made the running app load that thread within two seconds (its lock appeared).
- Claude: `open claude://claude.ai/epitaxy/<sidebar id>` switched the app to that chat (its last-focused time updated). The ID is the sidebar entry's, not the session's.

**Running the agents headless**
- Codex: the CLI bundled in the ChatGPT app uses the app's login. `exec resume <id> "<prompt>"` continued a thread, and `exec --ephemeral` wrote a good four-part hand-off brief from a small transcript in 20 seconds for about 14k tokens, leaving no thread and no file behind.
- Claude: works once the `claude` command is logged in. Before that, both the desktop app's own engine and the installed command answered "Not logged in" when run outside the app; the app's login is not shared. After the user logged in once, `claude -p --no-session-persistence --setting-sources project --allowedTools Read` wrote a good four-part brief from the same transcript in 10 seconds, leaving no session file and no sidebar entry. `--setting-sources project` keeps the user's plugins and hooks out of the run, so the brief is not shaped by them.
- A failed headless Claude resume still wrote about 30 records into the session it was pointed at. Baton must never run a headless agent against a linked chat's own session; briefs run in a separate session that is not saved.

**Hook trust in Codex is per entry, not per script**
- The trusted prompt hook kept running after its script was edited. A newly added turn-end entry did not run until trusted.

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

**Catch-up through a prompt hook (Q4, Q11, Q12): it works on both sides**
- Test: `spike/m0_hook.py` registered as a prompt hook in this folder. When the prompt mentions "codeword" it attaches one pretend missed turn and returns a short notice.
- Claude: the agent answered with the attached codeword in a chat that was already open, in an old chat after the app was relaunched, and in a brand-new chat.
- Codex: the agent answered with the attached codeword in a new chat, after the hook was trusted once.
- What the hook receives. Claude: `session_id`, `transcript_path`, `prompt`, `prompt_id`, `session_title`, `cwd`, `permission_mode`, `scratchpad_dir`. Codex: `session_id`, `transcript_path`, `prompt`, `turn_id`, `model`, `cwd`, `permission_mode`. The session ID is there on both sides, which is what the real hook needs to find the link.
- How it is stored. Claude writes the attached text as an attachment record of type `hook_additional_context` and the notice as `hook_system_message`; the user's prompt record stays clean. Codex writes the attached text as its own `developer` message next to the prompt; the notice is not stored in the rollout.
- The notice: Claude shows it as a "Claude Code notice" line above the reply. Codex Desktop showed nothing in two tries and does not store it. On the Codex side the notice has to come from Baton itself, as a macOS notification or in the menu bar.

**Turn-end hooks (Q4): they fire in both desktop apps**
- Claude passes `session_id`, `transcript_path`, `last_assistant_message`, `stop_hook_active`, `prompt_id`, `cwd` and more. Printing nothing is accepted.
- Codex passes `session_id`, `transcript_path`, `last_assistant_message`, `stop_hook_active`, `turn_id`, `model`, `cwd`. It ran after being trusted once, with `{}` as output.
- So both apps tell Baton the moment a reply finishes, and which chat it was in.

**An appended turn on a dead branch is shown but not known**
- After the Claude app was relaunched, the old test chat displayed the turn that had been appended while it was open, in file order. The agent still did not have it: the later prompt had bypassed it.
- So the chat view follows the file, the agent follows the parent chain. A turn written to an open chat can end up visible to the user and unknown to the agent, which is worse than not being there.

**Chat processes start when a chat is opened**
- After the relaunch only the three chats opened since had a process. Quitting the app ends all of them.
- The project folder also holds session files that are not chats in the sidebar (short background sessions). Baton takes its list of chats from the sidebar entries, not from the files.

**Codex is strict about what a hook prints**
- Seen in the Codex hooks panel for a new chat: a plugin written for Claude ran three hooks. `UserPromptSubmit` completed. `SessionStart` failed with "hook returned invalid session start JSON output" and `Stop` failed with "hook returned invalid stop hook JSON output".
- So hooks do run in Codex Desktop, per event, and the app shows each run and its result.
- Consequence: Baton's hooks must print exactly what each tool accepts for each event. A turn-end hook for Codex prints valid JSON and nothing else. One script per tool, or one script that knows which tool called it.

**Headless runners (Q10)**
- Both exist. The ChatGPT app bundles the Codex CLI at `Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex`, same version as the desktop engine, with `exec --ephemeral`.

## Checks before building (2026-10-04)

The feature specs listed five things to confirm on throwaway chats. All five were run.

**Both tools record a usage limit, with the reset time**
- Claude writes an assistant record that is not a model reply: `isApiErrorMessage: true`, `error: "rate_limit"`, `apiErrorStatus: 429`, a text such as "You've hit your session limit · resets 4:20pm (Africa/Cairo)", and `quotaLimits` with `status`, `resetsAt` (seconds since 1970) and `rateLimitType` (`five_hour` seen).
- Codex writes `rate_limits` into every `token_count` event: `primary` and `secondary`, each with `used_percent`, `window_minutes` and `resets_at`, plus `rate_limit_reached_type` once a limit is hit.
- So a limit can be told from the chat file on both sides. Codex also says how close a limit is before it is reached.

**Context in use can be read on both sides**
- Claude: the `usage` of the latest real reply, `input_tokens + cache_creation_input_tokens + cache_read_input_tokens + output_tokens`. Checked on chats that were compacted: the sum just before each compaction matches the `preTokens` the tool recorded (median ratio 0.999). The context size is not in the file.
- Codex: `token_count.info.last_token_usage`, with the size next to it as `model_context_window` (258,400 here).
- So Codex gets tokens and a percentage. Claude gets tokens, and a percentage only where Baton knows the size for the model.

**Background runs can be limited to reading**
- Codex: `exec -s read-only`. Claude: `--allowedTools "Read,Grep,Glob"`.
- Both read a file when asked. Both refused to create one; Claude also refused to run a shell command.

**One Claude chat can be released without relaunching the app**
- Ending the `claude` process of one idle chat (a normal terminate signal) closed it cleanly within a second and removed its entry from the session registry. The app started a new process for that chat on the next message, with the same session ID, and loaded the file again.
- A turn appended after the release was known to the agent on the next message: asked for the codewords, it listed all three, including the one just added.
- The chat view did not change. It did not show the appended turn; the view is filled when the app starts.
- So for an idle Claude chat, real turns can be delivered with nothing relaunched: release the chat, add the turns. The agent has them at once and the chat shows them after the next relaunch, whenever that is. Attached turns, by comparison, are never shown.

**Cutting a Claude chat back works, with the same split**
- With the chat released, its file was cut back to an earlier point. On the next message the agent no longer had the removed part.
- The chat view still displayed the removed exchange. It should follow the file after a relaunch, as it did for appended turns; that last step was not run.

**Cutting a Codex chat back is not accepted**
- With the app quit and no lock held, the test chat's file was cut from 297,015 to 291,281 bytes. After reopening, Codex's own index of the chat (`thread_history_1.sqlite`) still said it had read up to byte 297,015, still listed the removed turn, and the chat displayed it. Codex then wrote its next record at a position below the point its index says it has read.
- So after a cut the chat view and the file disagree, and stay that way. Putting the file back from the saved copy, with the app closed, brought them back in step.
- Whether the Codex agent still had the removed turn was not tested; the view alone rules this out.
- Consequence: a Codex chat is only ever cut when Codex has not yet read past the cut point, which its index states (this covers taking back a write that just failed). In every other case undo creates a new Codex chat that ends at the chosen point and moves the link to it. Baton does not edit Codex's index.

**A name changed from outside**
- Codex keeps it in the `threads` table (`title` and `name`). After a restart, Codex showed the changed name in the sidebar and the title bar. It was not seen to change while Codex was running.
- Claude keeps it in the sidebar entry (`title`). The running app did not pick the change up, and later wrote its own name back over it. A Claude chat can therefore be renamed from outside only while the app is closed, in the same step as a relaunch. That step was not run; it uses the same path as a chat created from outside, which Claude lists at start.

`spike/m0_cut.py` did the cuts. It copies the whole file first and refuses while the chat is held.

## Waiting

**Append to a real chat (Q1, Q2).** `spike/m0_append.py` is ready and passed a dry run on a sandbox copy (append on both sides, shapes checked, undo restores the original size). The automated permission check declined to let the assistant write into real chat files, so these two runs are done by hand:

- Claude test chat, while its process is alive and idle: done, see above.
- Codex test chat, once Codex releases it: done, see above. Quitting the ChatGPT app released every thread lock at once; what else releases a thread is still unknown.

**Append to a closed Claude chat (Q1).** Done, see above.

**Catch-up hook (Q11, Q12).** Done, see above. The test hook is still registered for this folder (`.claude/settings.local.json`, `.codex/hooks.json`, neither in the repo) and should be removed once the real hook replaces it.

**Still open after M0**
Two small steps were not run, because both need Claude relaunched from outside the chat doing the test: that Claude's view follows a cut file after a relaunch, and that a Claude chat renamed while the app is closed keeps the name. Two design choices came out of the spike:
- A twin chat written by Baton shows up in Claude only after a relaunch. The alternative that needs no relaunch: the user starts a new chat in Claude, Baton links it, and the history arrives through the prompt hook on the first message.
- Claude-written briefs: settled. They use the `claude` command after a one-time login, and Baton checks for that login and says what to do when it is missing.
