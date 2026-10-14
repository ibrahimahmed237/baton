"""The offer to carry on in the other tool when one reaches its usage limit (W2).

The owning store atomically claims each limit once across processes. Tests may
inject an isolated OfferMemory; the status line about the limit (W3) does not
depend on the claim and stays until the limit is over.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timezone, tzinfo
import json
from typing import Mapping, Protocol

from ..domain.link import AGENT_HAS, ATTACHED_HISTORY, FULL_COPY, KEPT_BACK, SKIPPED, Link
from ..ports.clock import Clock
from ..ports.store import RecordStore
from ..ports.tool import ChatReader
from .noteformat import NoteRef, clock_time, day_of
from .usage import limit_state


class OfferMemory(Protocol):
    """Remember which limits have been offered about."""

    def claim(self, key: str) -> bool:
        """Claim a limit once; return false when it was offered already."""
        ...


class MemoryOffers:
    """Remember offers for the life of the process, for callers that run once and for tests."""

    def __init__(self) -> None:
        self._keys: set[str] = set()

    def was_offered(self, key: str) -> bool:
        """Whether this limit was offered already."""
        return key in self._keys

    def remember(self, key: str) -> None:
        """Record that this limit was offered."""
        self._keys.add(key)

    def claim(self, key: str) -> bool:
        """Claim an offer in an isolated in-memory test."""
        if self.was_offered(key):
            return False
        self.remember(key)
        return True


@dataclass(frozen=True)
class LimitOffer:
    """What to show when a tool is at its limit, and where accepting it leads."""
    key: str
    side: str
    chat_id: str
    link_id: int | None       # None: the chat is not linked, accepting opens the link dialog (V3)
    to_side: str
    to_chat: str | None       # the linked chat to sync and open; None when not linked
    resets_at: str | None
    ways: tuple[str, ...]     # the ways of linking to offer, when not linked
    note: NoteRef


class LimitOffers:
    """Decide whether a chat that reached its limit should be offered a switch."""

    def __init__(self, store: RecordStore, readers: Mapping[str, ChatReader], clock: Clock,
                 memory: OfferMemory | None = None, tz: tzinfo = timezone.utc):
        self.store, self.readers, self.clock, self.memory, self.tz = store, readers, clock, memory, tz

    def check(self, side: str, chat_id: str, *, enabled: bool = True,
              to: str | None = None) -> LimitOffer | None:
        """Return the offer for a chat whose latest turn ended on a limit, once per limit.

        `enabled` is the Settings switch (offer_switch_at_limit). `to` picks the
        tool to suggest for a chat that is not linked; the first other tool is the default.
        """
        reader = self.readers[side]
        usage = reader.usage(chat_id)
        limit = limit_state(usage, self.clock.now())
        if not enabled or not limit.blocking:
            return None
        link = self.store.link_for(side, chat_id)
        other = link.others(side)[0] if link else to or next((t for t in self.readers if t != side), None)
        if other is None or other == side or other not in self.readers:
            return None
        key = self._key(side, chat_id, reader)
        offer = self._offer(key, side, chat_id, other, link, limit.resets_at)
        claimed = (self.memory.claim(key) if self.memory is not None else
                   self.store.claim_limit_offer(key, self.clock.now()))
        if not claimed:
            return None
        return offer

    @staticmethod
    def _key(side: str, chat_id: str, reader: ChatReader) -> str:
        # A new limit is a new latest turn that ended on it; the same turn is the same limit.
        turns = reader.read(chat_id)
        return json.dumps((side, chat_id, turns[-1].id if turns else ''), separators=(',', ':'))

    def _offer(self, key: str, side: str, chat_id: str, other: str, link: Link | None,
               resets_at: str | None) -> LimitOffer:
        values = {"tool": side, "other_tool": other, "offer_key": key,
                  "link_id": link.id if link else None,
                  "source_tool_id": side, "source_chat_id": chat_id,
                  "destination_tool_id": other, "destination_chat_id": link.chat(other) if link else None}
        if resets_at:
            values["time"] = clock_time(resets_at, self.tz, day_of(self.clock.now(), self.tz))
        suffix = "" if resets_at else "_no_reset"
        if link is None:
            note = NoteRef("limit.offer_unlinked" + suffix, values)
            return LimitOffer(key, side, chat_id, None, other, None, resets_at,
                              (FULL_COPY, ATTACHED_HISTORY), note)
        complete = all(turn.states.get(other) in (*AGENT_HAS, KEPT_BACK, SKIPPED)
                       for turn in self.store.turns(link.id))
        name = "limit.offer_linked" + suffix + ("" if complete else "_behind")
        return LimitOffer(key, side, chat_id, link.id, other, link.chat(other), resets_at, (),
                          NoteRef(name, values))
