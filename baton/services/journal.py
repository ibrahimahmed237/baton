"""Durable rollback receipts and capability-based write guards."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Mapping, Sequence

from ..domain.capabilities import WriteWindow
from ..domain.errors import (AppMustBeClosed, ChatChanged, ChatHeld, ChatReplying,
                             NotAvailable, UnknownFormat)
from ..domain.model import Turn
from ..ports.clock import Clock
from ..ports.store import RecordStore
from ..ports.tool import ToolAdapter, WriteReceipt


class Journal:
    """Persist rollback data before a writer is allowed to mutate a chat."""
    def __init__(self, store: RecordStore, adapters: Mapping[str, ToolAdapter], clock: Clock):
        self.store, self.adapters, self.clock = store, adapters, clock

    def begin(self, link_id: int | None, tool: str, chat_id: str | None, action: str) -> int:
        receipt = self.adapters[tool].writer.prepare(chat_id, action)
        if receipt.tool != tool or receipt.kind != action or (chat_id is not None and receipt.chat_id != chat_id):
            raise ValueError("receipt_identity_mismatch")
        return self.store.journal_begin(link_id, tool, receipt.chat_id, action,
                                        self.clock.now(), asdict(receipt))

    def commit(self, entry_id: int, receipt: WriteReceipt) -> None:
        entry = self.store.journal_entry(entry_id)
        if (receipt.tool, receipt.chat_id, receipt.kind) != (entry['tool'], entry['chat_id'], entry['action']):
            raise ValueError("receipt_identity_mismatch")
        self.store.journal_finish(entry_id, "committed", self.clock.now(), asdict(receipt))

    def fail(self, entry_id: int, error: Exception | str) -> None:
        self.store.journal_finish(entry_id, "failed", self.clock.now(), error=type(error).__name__
                                  if isinstance(error, Exception) else error)

    def take_back(self, entry_id: int) -> None:
        entry = self.store.journal_entry(entry_id)
        if entry['state'] == 'taken_back':
            return
        receipt = entry['post_receipt'] if entry['state'] == 'committed' else entry['pre_receipt']
        if receipt is None:
            raise NotAvailable()
        self.adapters[entry['tool']].writer.take_back(WriteReceipt(**receipt))
        self.store.journal_finish(entry_id, 'taken_back', self.clock.now(), error=entry['error'])

    def recover(self) -> list[dict]:
        """Retry pending entries; failures remain recoverable rather than being forgotten."""
        results = []
        for entry in reversed(self.store.journal_entries(pending=True)):
            try:
                self.take_back(entry['id'])
            except Exception as error:
                self.fail(entry['id'], error)
                results.append(self.store.journal_entry(entry['id']))
                break
            results.append(self.store.journal_entry(entry['id']))
        return results

    def prune(self) -> int:
        cutoff = datetime.fromisoformat(self.clock.now().replace('Z', '+00:00')) - timedelta(days=30)
        return self.store.journal_prune(cutoff.isoformat(timespec='seconds'))


class Guard:
    """Check the current state afresh, separately for release and for writing."""
    def __init__(self, store: RecordStore):
        self.store = store

    def _linked(self, adapter: ToolAdapter, chat_id: str, link_id: int | None) -> None:
        link = self.store.link_for(adapter.name, chat_id)
        if link is None or (link_id is not None and link.id != link_id):
            raise NotAvailable()

    def check_release(self, adapter: ToolAdapter, chat_id: str, link_id: int | None = None) -> None:
        self._linked(adapter, chat_id, link_id)
        condition = adapter.state.condition(chat_id)
        if condition.replying:
            raise ChatReplying()
        if not condition.exists or not condition.open or not adapter.facts.can_release_chat:
            raise NotAvailable()

    def check_write(self, adapter: ToolAdapter, chat_id: str | None,
                    link_id: int | None = None, expected: Sequence[Turn] | None = None,
                    action: str = 'add') -> None:
        if not adapter.state.format_version().known:
            raise UnknownFormat()
        if chat_id is None:
            if action != 'create':
                raise NotAvailable()
            running = adapter.app.running()
        else:
            self._linked(adapter, chat_id, link_id)
            condition = adapter.state.condition(chat_id)
            if not condition.exists:
                raise ChatChanged()
            if not condition.format_known:
                raise UnknownFormat()
            if condition.replying and adapter.facts.write_window != WriteWindow.ANY_TIME:
                raise ChatReplying()
            if adapter.facts.write_window in (WriteWindow.NOT_HELD, WriteWindow.CLOSED_OR_RELEASED) and condition.open:
                raise ChatHeld()
            running = condition.app_running
            if expected is not None and adapter.reader.read(chat_id) != list(expected):
                raise ChatChanged()
        if adapter.facts.write_window == WriteWindow.APP_CLOSED and running:
            raise AppMustBeClosed()
        if action == 'cut' and not adapter.facts.can_cut:
            raise NotAvailable()
        if action == 'place' and not adapter.facts.can_place:
            raise NotAvailable()
