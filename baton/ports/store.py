"""The record store interface."""
from __future__ import annotations

from typing import Any, Iterable, Mapping, Protocol, Sequence, runtime_checkable

from ..domain.link import Event, LedgerTurn, Link
from ..domain.model import Turn


@runtime_checkable
class RecordStore(Protocol):
    """Keep links, turn states and history."""
    def close(self) -> None:
        """Close the store."""
        ...

    def link(self, chats: Mapping[str, str], mode: str, at: str = "") -> Link:
        """Link two unlinked chats."""
        ...

    def get_link(self, link_id: int) -> Link:
        """Return a link by id."""
        ...

    def link_for(self, side: str, chat: str) -> Link | None:
        """Find the active link for a chat."""
        ...

    def links(self) -> list[Link]:
        """List active links."""
        ...

    def remove_link(self, link_id: int, at: str = "") -> None:
        """End a link while keeping its history."""
        ...

    def set_paused(self, link_id: int, paused: bool, at: str = "") -> None:
        """Pause or resume a link."""
        ...

    def move_link(self, link_id: int, side: str, chat: str, at: str = "") -> None:
        """Point one side at another chat."""
        ...

    def record_turns(self, link_id: int, side: str, turns: Iterable[Turn]) -> list[int]:
        """Record new turns read from one side."""
        ...

    def turns(self, link_id: int) -> list[LedgerTurn]:
        """Read turns and their states in conversation order."""
        ...

    def set_order(self, link_id: int, turn_ids: Sequence[int]) -> None:
        """Reorder turns within their existing positions."""
        ...

    def deliver(self, link_id: int, side: str, turn_ids: Sequence[int], state: str, kind: str,
                at: str = "", local_ids: Sequence[str] = (), detail: dict[str, Any] | None = None) -> int:
        """Record delivery and return its history id."""
        ...

    def mark_shown(self, link_id: int, side: str, turn_ids: Sequence[int] | None = None) -> int:
        """Mark added turns as shown."""
        ...

    def keep_back(self, link_id: int, turn_id: int, at: str = "") -> None:
        """Keep an undelivered turn on its originating side."""
        ...

    def send_after_all(self, link_id: int, turn_id: int, at: str = "") -> None:
        """Make a kept-back turn available for delivery."""
        ...

    def skip(self, link_id: int, turn_id: int, side: str, at: str = "") -> None:
        """Skip delivery of a turn to one side."""
        ...

    def set_pinned(self, link_id: int, turn_id: int, pinned: bool) -> None:
        """Set whether a turn is pinned."""
        ...

    def history(self, link_id: int) -> list[Event]:
        """Return a link’s history, newest first."""
        ...

    def journal_begin(self, link_id: int | None, tool: str, chat_id: str,
                      action: str, at: str, receipt: dict[str, Any]) -> int: ...
    def journal_entry(self, entry_id: int) -> dict[str, Any]: ...
    def journal_entries(self, pending: bool = False) -> list[dict[str, Any]]: ...
    def journal_finish(self, entry_id: int, state: str, at: str,
                       receipt: dict[str, Any] | None = None, error: str = "") -> None: ...
    def journal_prune(self, before: str) -> int: ...

    def local_ids(self, link_id: int, side: str) -> dict[int, str]:
        """Return persisted local identities for recorded turns on one side."""
        ...
    def reset_delivery(self, link_id: int, side: str, turn_ids: Sequence[int], at: str) -> None:
        """Return bypassed deliveries to waiting while retaining their identities."""
        ...
    def record_event(self, link_id: int, kind: str, side: str, at: str,
                     turn_ids: Sequence[int] = (), detail: dict[str, Any] | None = None) -> int:
        """Record an observed action without changing delivery states."""
        ...
    def complete_write(self, entry_id: int, receipt: dict[str, Any], at: str,
                       link_id: int | None, side: str, turn_ids: Sequence[int], state: str,
                       kind: str, local_ids: Sequence[str], detail: dict[str, Any] | None = None) -> int | None:
        """Commit verified delivery metadata and the journal in one transaction."""
        ...
