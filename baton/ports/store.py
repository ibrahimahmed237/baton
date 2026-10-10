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

    def remember_chat(self, tool: str, chat: str, payload: dict) -> None:
        """Cache observed identity/name metadata without touching a native chat."""
        ...

    def known_chat(self, tool: str, chat: str) -> dict | None:
        """Return the last observed chat reference, including for a missing chat."""
        ...

    def settings_values(self) -> dict:
        """Read stored configuration values."""
        ...

    def save_setting(self, key: str, value: Any) -> None:
        """Store a configuration value; no native mutation or recovery."""
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

    def record_turns(self, link_id: int, side: str, turns: Iterable[Turn],
                     in_progress: str = "") -> list[int]:
        """Record new turns read from one side."""
        ...

    def turn_evidence(self, link_id: int) -> dict[int, dict[str, Any]]:
        """Read canonical payloads, including whether their baseline was verified and completed."""
        ...

    def claim_limit_offer(self, key: str, at: str) -> bool:
        """Atomically claim an offer once, including for an unlinked chat."""
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

    def complete_link(self, chats: Mapping[str, str], mode: str, rows: Sequence[dict], at: str,
                      entry_id: int | None = None, receipt: dict | None = None,
                      replace_link_id: int | None = None) -> Link:
        """Atomically align a new link, replace its predecessor and commit any creation."""
        ...

    def complete_link_copy(self, link_id: int, side: str, chat_id: str,
                           turn_ids: Sequence[int], local_ids: Sequence[str], state: str,
                           at: str, entry_id: int, receipt: dict) -> Link:
        """Atomically move a full-copy twin while preserving conversation identity."""
        ...

    def copy_info(self, tool: str, chat_id: str) -> dict | None:
        """Read durable creation time and visibility independently of rollback receipts."""
        ...

    def mark_copy_shown(self, tool: str, chat_id: str, at: str) -> None:
        """Persist confirmed copy visibility without changing writer receipts."""
        ...

    def complete_copy(self, entry_id: int, receipt: dict, at: str) -> None:
        """Commit an unlinked creation and durable visibility metadata atomically."""
        ...

    def complete_merge(self, link_id: int, order: Sequence[int], writes: Sequence[dict],
                       skips: Sequence[tuple[int, str]], at: str, detail: dict) -> int:
        """Atomically record all sides, journal receipts and one recoverable merge event."""
        ...

    def complete_undo(self, link_id: int, expected: dict, writes: Sequence[dict],
                      at: str, detail: dict) -> int:
        """Atomically pause, restore identities/states and finalize undo write receipts."""
        ...

    def save_brief_plan(self, ident: str, stage: str, payload: dict) -> None:
        """Persist one exact stage approval before returning its token."""
        ...
    def brief_plan(self, ident: str) -> dict:
        """Read the persisted stage, payload and consumption state."""
        ...
    def consume_brief_plan(self, ident: str, stage: str) -> dict:
        """Atomically consume one matching stage approval exactly once."""
        ...
    def save_brief_artifact(self, ident: str, payload: dict) -> None:
        """Persist immutable generated content, refusing changed identity reuse."""
        ...
    def brief_artifact(self, ident: str) -> dict:
        """Read the immutable artifact required for native creation."""
        ...
    def brief_cache_get(self, key: str) -> dict | None:
        """Read the summary cached for a privacy-bound writer input."""
        ...
    def brief_cache_put(self, key: str, payload: dict) -> None:
        """Replace only the cache for one privacy-bound writer input."""
        ...
    def summary_coverage(self, link_id: int, side: str, chat_id: str | None = None) -> dict | None:
        """Read coverage belonging to the selected or current native chat."""
        ...
    def archived_brief_origins(self, link_id: int) -> dict:
        """Read missing origins only through active sanctioned summary coverage."""
        ...
    def complete_brief(self, link_id: int, side: str, chat_id: str, artifact_id: str,
                       opening_id: str, original_ids: list[int], local_ids: list[str], state: str,
                       entry_id: int, receipt: dict, expected: dict, at: str, after_snapshot: dict) -> int:
        """Atomically finalize a verified brief replacement and its receipt."""
        ...

    def complete_brief_link(self, request: dict, chat_id: str, artifact_id: str,
                            opening_id: str, original_ids: list[int], local_ids: list[str], state: str,
                            entry_id: int, receipt: dict, at: str, after_snapshot: dict) -> tuple[int, int]:
        """Atomically create or relink source-scoped brief coverage and its receipt."""
        ...
