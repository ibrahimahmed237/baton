"""What the other side did since the user last wrote here (working-across W7, W8).

Plain numbers only: turns, files changed and commands run. A turn kept back or
skipped for this side is not counted, so the digest never reveals work this side
was told it would not get.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, tzinfo
from typing import Any, Mapping, Sequence

from ..domain.link import AGENT_HAS, KEPT_BACK, SKIPPED, SUMMARIZED, LedgerTurn
from ..domain.errors import ChatChanged
from ..notes.catalogue import get
from ..ports.clock import Clock
from ..ports.store import RecordStore
from ..ports.tool import ChatReader
from .noteformat import Label, NoteRef, clock_time, day_of, parse_time, plural
from .observations import canonical_sources, verified_source

_EARLIEST = datetime.min.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class Digest:
    """The work of one side since the other side's user last wrote."""
    side: str            # the side whose status shows it
    other: str           # the side that moved on
    since: str           # when the user last wrote on `side`
    until: str           # when the other side's latest counted turn ended
    turns: int
    files: tuple[str, ...]
    commands: int

    def as_contract(self) -> dict[str, Any]:
        """The `since_you_left` object of CONTRACT.md."""
        return {"turns": self.turns, "files": len(self.files), "commands": self.commands,
                "since": self.since}


def _started(turn: LedgerTurn) -> datetime:
    return parse_time(turn.started_at) or _EARLIEST


def _after(turn: LedgerTurn, last: LedgerTurn) -> bool:
    # Times decide when both are known; otherwise the order of the conversation does.
    if parse_time(turn.started_at) and parse_time(last.started_at):
        return _started(turn) > _started(last)
    return turn.seq > last.seq


class DigestBuilder:
    """Build the digest of a link side, and the words and attached text that carry it."""

    def __init__(self, store: RecordStore, readers: Mapping[str, ChatReader], clock: Clock,
                 label: Label, tz: tzinfo = timezone.utc):
        self.store, self.readers, self.clock, self.label, self.tz = store, readers, clock, label, tz

    def for_side(self, link_id: int, side: str) -> Digest | None:
        """The digest for `side`, or None when its user never wrote there or the other side has not moved on.

        Reads the other side's chat for files and commands, so the chat has to exist.
        """
        link = self.store.get_link(link_id)
        (other,) = link.others(side)
        rows = self.store.turns(link_id)
        eligible = [turn for turn in rows if turn.states.get(side) not in (KEPT_BACK, SKIPPED)]
        if all(turn.states.get(side) in (*AGENT_HAS, SUMMARIZED) for turn in eligible):
            return None
        own = [turn for turn in rows if turn.origin == side]
        if not own:
            return None
        # Canonical order preserves each app's prompt order, even when its
        # newest prompt has no timestamp. An older clock cannot replace it.
        last = max(own, key=lambda turn: turn.seq)
        later = [turn for turn in rows if turn.origin == other and _after(turn, last)
                 and turn.states.get(side) not in (KEPT_BACK, SKIPPED, SUMMARIZED)]
        evidence = self.store.turn_evidence(link_id)
        later = [turn for turn in later if evidence.get(turn.id, {}).get('complete', True)]
        if not later:
            return None
        reader = self.readers[other]
        try:
            content = {turn.id: turn for turn in reader.read(link.chat(other))}
            own_content = {turn.id: turn for turn in self.readers[side].read(link.chat(side))}
        except KeyError:
            raise ChatChanged() from None
        resolved = canonical_sources(self.store, link_id,
                                     {other: list(content.values()), side: list(own_content.values())})
        verified_source(self.store, link_id, last, resolved.get(last.id), evidence)
        files: list[str] = []
        commands = 0
        for row in later:
            turn = verified_source(self.store, link_id, row, resolved.get(row.id), evidence)
            files.extend(path for path in reader.files_changed(turn) if path not in files)
            commands += reader.commands_run(turn)
        until = max((resolved[row.id].ended_at or row.started_at for row in later),
                    key=lambda t: parse_time(t) or _EARLIEST)
        return Digest(side, other, last.started_at, until, len(later), tuple(files), commands)

    def note(self, digest: Digest) -> NoteRef:
        """The catalogue note that says it; its values are ready to substitute."""
        return NoteRef("digest.since_you_left", {
            "at": clock_time(digest.since, self.tz, day_of(self.clock.now(), self.tz)),
            "tool": digest.other,
            "turns": plural("digest.turns_one", "digest.turns_other", digest.turns),
            "files": plural("digest.files_one", "digest.files_other", len(digest.files)),
            "commands": plural("digest.commands_one", "digest.commands_other", digest.commands)})

    def text(self, digest: Digest) -> str:
        """The digest as one sentence, with the other tool's display name."""
        ref = self.note(digest)
        return get(ref.id).render({**ref.values, "tool": self.label(digest.other)}).template

    def attached_text(self, digest: Digest | None, blocks: Sequence[str]) -> str:
        """The text attached to a message: the digest first, then the turns, inside the catch-up marker.

        `blocks` are the waiting turns already written out, one string each, in order.
        """
        parts = ([self.text(digest)] if digest else []) + list(blocks)
        return get("catch_up.block").render({"body": "\n\n".join(parts)}).template
