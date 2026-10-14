# CP2 live run, step B: writes on two throwaway chats

2026-10-13 and 14. Run by Claude with `tools/live/cp2_live.py`, one step at a time, with Ibrahim's go; Ibrahim looked at the apps. Only the two chats named "Baton test (safe to delete)" in the Baton folder were touched. Backups of every step are under `.baton-spike/backup/cp2/` (not in git).

## Codex (0.160, chat `01a136c3…`)

| Step | Result |
|---|---|
| Name guard | Refused the chat while its name was not exact; passed after Ibrahim renamed it. |
| inspect | First said "format not known": current Codex writes two record types Baton did not list, `world_state` and `token_usage_record`. Neither carries a message. Added (`3ceb…` commit "Know the two bookkeeping records"). |
| refuse-held (Codex running, chat loaded) | Refused with ChatHeld. File hash equal before and after. |
| add (Codex closed) | One turn added, read back, old bytes are a prefix of the new file. |
| take-back | Rollout file and thread row byte-identical to the backup. |
| rename, rename-back | Both done. |
| add, left in place (codeword birch-887e) | Ibrahim reopened Codex: the turn is shown, and the agent answered the codeword. |

## Claude (2.1.295, chat `local_31e9f378…`)

| Step | Result |
|---|---|
| inspect | "Format not known": the checked list held only 2.1.284. 2.1.295 added after this run proved it. |
| refuse-held (chat open) | Refused with ChatHeld. File hash equal before and after. |
| release (Claude stays open) | First refused with NotAvailable: current Claude no longer names the chat on the process command line, so the ownership proof failed. Proof rebuilt on the session registry (pid in the file name, exact start time, desktop executable); built by Codex Sol, returned once by a separate reviewer (a failed new proof could fall back to the old one), fixed. Then: released. |
| add, right after release | Refused once with ChatChanged: the ending process was still writing. Second try done. |
| take-back | Session file and sidebar entry byte-identical to the backup. |
| rename (Claude running) | Refused with AppMustBeClosed, as designed. |
| add, left in place (codeword fjord-515a) | Ibrahim: not shown in the open app; the agent answered the codeword on the next message; after quitting and reopening Claude the turn is shown. |

## Differences from what was measured before, and what follows

1. **Codex keeps many chats loaded** (eight lock files at one point); switching to another chat does not release one, quitting Codex does. So for Codex, "close Codex, sync, reopen" is the usual offer, not the exception. more-tools.md's Codex row and the notes need this (E12, with Ibrahim).
2. **Claude's checked-version pin is exact.** Claude updates often, so writing would switch off after every update. A rule by record shape is needed (proposal owed to Ibrahim).
3. **Claude writes for a moment after a release.** The applier must wait until the files are still before preparing its write (E13 / C5).
4. **Rename changed a title that had backticks to the plain name** on the way back. Harmless here; `rename` should restore the exact earlier title.
5. Rollback notes were left in `~/.baton-rollback/` (five files, two of them copies of the chat). Moved to `.baton-spike/backup/cp2/rollback-notes/`. The adapters should clear a note once its write is verified or taken back, and keep them under Baton's own folder, not the home folder.

## Not run live

Creating a new chat through the adapter, and cutting a Claude chat. Both were measured by hand in M0; through the adapters they are run at the CP3 live check, where linking creates chats anyway.

## Left on the machine

The two test chats, each with one added turn. They are kept for the CP3 live check.
