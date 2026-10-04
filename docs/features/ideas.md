# Ideas beyond the first version

Not agreed, not planned. Each is here so it can be picked, changed or dropped. Ordered by how much it would help someone who works in both tools every day.

## Switching at the right moment

**1. Offer the switch when a tool hits its limit.** When Claude or Codex stops because of a usage limit, Baton shows "Claude has reached its limit. Continue this chat in Codex?" with one button. The most common reason to switch becomes one click instead of a decision to remember.
- Needs: recognising a limit stop from the turn-end hook or the chat file. Not checked yet.

**2. How full each side is.** Per side, how much of the agent's context the chat is using ("Claude 82%, Codex 35%"), read from the token counts both tools already write. It tells the user when a chat is about to compact, and which side has room.
- Feeds the existing size and cost preview and the suggestion to hand off with a brief.

**3. A note for the other agent.** When pressing Continue, the user can type one line ("pick up at the failing test in auth"). It goes across as the first thing the other agent reads.

**4. "Since you left."** When the user comes back to a tool, the top of the status says what the other agent did meanwhile in plain numbers: turns, files changed, commands run, whether tests were run. The detail is one click away.

## Using both agents on purpose

**5. Second opinion.** From any turn: "Ask Codex about this" (or Claude). Baton runs the other agent in the background with the conversation so far and the question, shows the answer in Baton, and can add it to the chat as a turn. Two agents checking each other without the user switching apps.
- Uses the background runs proven in the spike, in a separate session that is not saved.

## Control and trust

**6. Keep a turn on one side.** Mark a turn "keep in Claude only". It is never sent to Codex, and the status shows it as kept back, not as waiting. For the user who does not want everything in both tools.

**7. Pin what matters.** Mark turns as key. A brief always includes pinned turns in full, however long the chat gets, so decisions do not get summarised away.

**8. Check a link.** Re-read both chats against Baton's record and report or repair anything that does not match. (Listed in link-actions.md as later.)

## The project around the chats

**9. Same instructions for both agents.** Claude reads `CLAUDE.md`, Codex reads `AGENTS.md`. Baton can show when they differ and offer to make one point at the other, so both agents follow the same project rules.

**10. Folder and branch check.** Warn when the two linked chats work in different folders or on different git branches. (Listed in link-actions.md as later.)

## Finding things

**11. Search across both tools.** One search box over every chat in Claude and Codex, linked or not.

**12. Save a conversation as a file.** (Listed in link-actions.md as later.)

## Suggested order if any are taken up

1, 2 and 4 make the switch itself better and need no new kind of write. 5 is the one that adds something neither tool has alone. 6 and 7 are small once the ledger exists.
