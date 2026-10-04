# Feature: working across both tools

Part of [the Baton design](../DESIGN.md). Status: requirements agreed for the first version, not built. Related: [sync-status.md](sync-status.md), [link-actions.md](link-actions.md), [merge.md](merge.md).

## Problem

Keeping two chats in sync answers "does the other side have it?". The user who works in both tools every day has more questions: when should I switch, which side has room left, what happened while I was away, what does the other agent think of this, and how do I keep some things out of the other tool or make sure the important ones are never lost in a summary.

## Goals

1. Switching happens **at the right moment with one click**, including when a tool runs out.
2. The user can see **how much room each side has** before deciding where to continue.
3. Coming back to a tool, the user sees **what the other agent did** without reading the whole chat.
4. The user can **get the other agent's view** on a turn without switching apps.
5. The user controls **what crosses over** and **what must never be summarised away**.

## Non-goals

- **Running the other agent on the user's files without being asked.** A second opinion only reads; it changes nothing.
- **Predicting limits.** Baton reports a limit when a tool says it was reached, and the reset time if the tool gives one. It does not estimate remaining quota.
- **Hiding a turn that was already delivered.** A turn can be kept back before it is sent, not recalled afterwards.

## Requirements

All in the first version.

### Switch when a tool runs out

**W1. Notice a limit.** When Claude or Codex ends a reply because a usage limit was reached, Baton notices it from that turn's end.

**W2. Offer the switch.** Baton then offers, in the menu bar and as a notification: "Claude has reached its usage limit. Continue this chat in Codex?", with the reset time when the tool reported one.
- For a linked chat, *Continue in Codex* syncs and opens the Codex chat, as the Continue button does.
- For a chat that is not linked, the offer leads to the link dialog with both ways of linking.
- The offer is shown once per limit, can be dismissed, and can be turned off in Settings.

**W3. Say when it is back.** If a reset time was given, the chat's status shows "Claude is available again at 15:00", and after that time "Claude is available again".

**W4. Briefs use the tool that still has room.** While a tool is at its limit, Baton does not ask it to write a brief; the other tool writes it, or the offline brief is used.

### How full each side is

**W5. Context in use.** Each side's status shows how much of its agent's context the chat is using, from the numbers the tool records for its latest turn: as tokens, and as a share of the context size when the tool records that size or the model is known.
- Example: "About 164,000 tokens in use, 82% of 200,000."
- When the size is not known, only the token count is shown; Baton does not guess a percentage.

**W6. Say what a full chat means.** Above 80% the status adds that the tool will soon summarise the chat by itself, and suggests continuing on the other side or handing off with a brief. The hand-off dialog shows both sides' numbers next to the choice between a full sync and a brief.

### Since you left

**W7. A digest per side.** When the other side has moved on since the user's last message on this side, this side's status says what happened there in plain numbers: how many turns, which files were changed, how many commands were run, and the time span.
- Example: "Since your last message here at 13:40, Codex did 4 turns, changed 6 files and ran 9 commands."
- The list of files and the turns themselves are one click away.

**W8. The digest travels with the catch-up.** When waiting turns are attached to a message, the attached text starts with the same digest, so the agent gets the summary before the detail.

### Second opinion

**W9. Ask the other agent about a turn.** From any turn, or for the whole chat, the user can choose "Ask Codex about this" or "Ask Claude about this", type a question or use the default ("Review this and point out problems"), and get an answer shown in Baton.
- Baton runs the other agent in the background, in a session of its own that is not saved. It is given a brief of the conversation, the chosen turn in full, and read access to the project folder.
- It can read; it cannot change files or run commands that change anything.
- Before running, Baton shows roughly how many tokens the request will use.
- It works for linked and unlinked chats, and never touches either chat's own session.

**W10. What to do with the answer.** The answer stays in Baton until the user decides: *Add to this chat* puts it in as a turn labelled as a second opinion from the other agent, delivered by the usual rules (added if the chat is closed, attached to the next message if it is open); *Copy*; or *Discard*.

**W11. When it cannot run.** If the other tool's background runner is missing, not logged in or at its limit, Baton says which and what to do, as in the setup check.

### Keep a turn on one side

**W12. Mark a turn "keep here".** A turn that has not been delivered yet can be marked to stay on the side it was written. It is then never sent across, by adding or by attaching, and never included in a brief or a second opinion for the other tool.
- Its state on the other side reads "Kept in Claude" (or Codex), which is different from waiting: nothing is pending and no relaunch is offered for it.
- The mark can be removed, after which the turn is delivered like any other.
- A turn already delivered cannot be kept back; the control says so instead of being offered.

**W13. Say what it costs.** When a later turn is sent across while an earlier one is kept back, the status notes that the other agent is missing a turn the conversation may refer to.

### Pin what matters

**W14. Pin a turn.** Any turn can be pinned. Pinned turns are listed together and can be filtered for.

**W15. Pins survive a brief.** A brief, written by an agent or offline, always includes every pinned turn in full, in addition to its summary. If the pinned turns alone are large, the hand-off dialog shows their size.
- A turn that is both pinned and kept on one side stays out of briefs for the other tool; keeping back wins.

## Wording

Following the message rules in the design (section 7a).

| Where | Message |
|---|---|
| Limit reached, linked chat | **Claude has reached its usage limit.** It resets at 15:00. Continue this chat in Codex? Codex already has every turn. Buttons: *Continue in Codex*, *Not now* |
| Limit reached, not linked | **Claude has reached its usage limit.** It resets at 15:00. This chat is not linked to a Codex chat yet. Buttons: *Link it and continue in Codex*, *Not now* |
| Available again | Claude is available again. |
| Context in use | About 164,000 tokens in use, 82% of 200,000. Claude will soon summarise this chat by itself. Continuing in Codex, or handing off with a brief, avoids that. |
| Since you left | Since your last message here at 13:40, Codex did 4 turns, changed 6 files and ran 9 commands. Button: *Show what changed* |
| Second opinion, before running | **Ask Codex about this turn?** Codex gets a brief of the chat, this turn in full, and can read the project folder. It cannot change anything. About 9,000 tokens. Buttons: *Ask Codex*, *Cancel* |
| Second opinion, cannot run | **Codex can't be asked right now.** It has reached its usage limit and resets at 16:30. |
| Keep here | This turn stays in Claude. It will not be sent to Codex, and briefs for Codex leave it out. Button: *Send it after all* |
| Keep here, too late | This turn was already sent to Codex at 14:10, so it can't be kept back. |
| A kept turn is being skipped | Codex is missing 1 turn that was kept in Claude. Later turns may refer to it. |
| Pinned | Pinned. Briefs always include this turn in full. |

## Acceptance scenarios

| # | Given | When | Then |
|---|---|---|---|
| V1 | A linked chat; Claude's reply ends on a usage limit with a reset time | — | The offer names Claude, the reset time and Codex; *Continue in Codex* syncs and opens the Codex chat. |
| V2 | V1, offer dismissed | Claude hits no new limit | The offer is not shown again; the status still shows the reset time. |
| V3 | An unlinked chat hits a limit | the user accepts | The link dialog opens with both ways of linking. |
| V4 | Claude is at its limit | a brief is needed for a hand-off to Codex | Codex writes it; Claude is not asked. |
| V5 | The latest turn records 164k tokens and a context size of 200k | — | The status reads the token count and 82%, with the note about summarising. |
| V6 | The latest turn records tokens but no context size and the model is unknown | — | Only the token count is shown. |
| V7 | The user's last message in Claude was at 13:40; Codex has 4 later turns that changed 6 files and ran 9 commands | — | Claude's status shows exactly that digest. |
| V8 | V7, Claude chat open | the user sends a message in Claude | The attached text starts with the digest, then the turns. |
| V9 | Any turn | "Ask Codex about this", confirmed | A background run happens in an unsaved session; neither chat file changes; the answer is shown in Baton. |
| V10 | V9 | *Add to this chat* | The answer becomes a turn labelled as a second opinion and is delivered by the usual rules. |
| V11 | A turn written in Claude, not yet delivered | the user marks it "keep here", then a later turn is written | The later turn is delivered; the kept turn is not; Codex's state for it reads "Kept in Claude" and the missing-turn note is shown. |
| V12 | A turn already delivered | the user tries to keep it back | The control explains it was already sent and when. |
| V13 | Two pinned turns in a long chat | a brief is written | The brief contains both turns in full besides its summary. |
| V14 | A turn that is pinned and kept in Claude | a brief is written for Codex | The brief does not contain it. |

## Verified before building

All three were checked against real chats; field names and details in [SPIKE-M0.md](../SPIKE-M0.md).

- **How each tool records a limit.** Both write it into the chat file with the reset time: Claude as a marked error reply with the reset time and the kind of limit, Codex as limit figures on every turn, including how much of each limit is used before it is reached. W1 to W3 read these.
- **Where the token numbers are.** Claude: the usage of the latest reply, summed; it matches what Claude itself records when it summarises a chat. Codex: the last turn's token usage, with the context size next to it. Claude does not record the size, so W5 shows a percentage for Claude only where Baton knows the size for the model.
- **Read-only background runs.** Both runners can be limited to reading, and both refused to create a file when asked. W9 uses that.
