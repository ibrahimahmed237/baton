"""SQLite journal records sharing the owning Ledger connection."""
from __future__ import annotations

import json
from typing import Any, Sequence
from ..domain.link import ADDED, DELIVERED, SHOWN, WAITING


class JournalRecords:
    """Internal method group; transaction boundaries remain on the shared connection."""

    def journal_begin(self, link_id: int | None, tool: str, chat_id: str,
                      action: str, at: str, receipt: dict[str, Any]) -> int:
        with self.db:
            cur = self.db.execute(
                "insert into journal(link_id,tool,chat_id,action,begun_at,pre_receipt) values(?,?,?,?,?,?)",
                (link_id, tool, chat_id, action, at, json.dumps(receipt)))
        return cur.lastrowid


    def journal_entry(self, entry_id: int) -> dict[str, Any]:
        row = self.db.execute("select * from journal where id=?", (entry_id,)).fetchone()
        if row is None:
            raise KeyError(entry_id)
        entry = dict(row)
        for key in ("pre_receipt", "post_receipt"):
            entry[key] = json.loads(entry[key]) if entry[key] is not None else None
        return entry


    def journal_entries(self, pending: bool = False) -> list[dict[str, Any]]:
        query = "select id from journal"
        if pending:
            query += " where state in ('begun','failed')"
        return [self.journal_entry(row[0]) for row in self.db.execute(query + " order by id")]


    def journal_finish(self, entry_id: int, state: str, at: str,
                       receipt: dict[str, Any] | None = None, error: str = "") -> None:
        if state not in {"committed", "failed", "taken_back"}:
            raise ValueError(state)
        entry = self.journal_entry(entry_id)
        if entry["state"] not in {"begun", "failed"} and not (entry["state"] == "committed" and state == "taken_back"):
            raise ValueError(entry["state"])
        with self.db:
            self.db.execute("update journal set state=?,ended_at=?,post_receipt=?,error=? where id=?",
                            (state, at, json.dumps(receipt) if receipt else None, error, entry_id))


    def journal_prune(self, before: str) -> int:
        with self.db:
            cur = self.db.execute(
                "update journal set pre_receipt=null,post_receipt=null where state in ('committed','taken_back')"
                " and julianday(ended_at)<julianday(?) and pre_receipt is not null", (before,))
        return cur.rowcount


    def complete_write(self, entry_id: int, receipt: dict[str, Any], at: str,
                       link_id: int | None, side: str, turn_ids: Sequence[int], state: str,
                       kind: str, local_ids: Sequence[str], detail: dict[str, Any] | None = None) -> int | None:
        """Atomically persist verified local delivery and journal completion."""
        entry = self.journal_entry(entry_id)
        if (entry["state"] != "begun" or entry["link_id"] != link_id or
                (entry["tool"],entry["chat_id"],entry["action"]) !=
                (receipt["tool"],receipt["chat_id"],receipt["kind"]) or
                side != receipt["tool"] or kind != receipt["kind"]):
            raise ValueError("receipt_identity_mismatch")
        if link_id is not None and kind != 'create' and self.get_link(link_id).chat(side) != receipt['chat_id']:
            raise ValueError("chat_identity_mismatch")
        if link_id is not None:
            if state not in DELIVERED or len(local_ids) != len(turn_ids):
                raise ValueError("delivery_identity_mismatch")
            for turn_id in turn_ids:
                if self._state(link_id, turn_id, side) != WAITING:
                    raise ValueError("delivery_not_waiting")
        # One transaction: a committed journal and its delivery states are inseparable.
        with self.db:
            event_id = None
            if link_id is not None:
                if kind == 'create':
                    before_chat = self.get_link(link_id).chat(side)
                    self.db.execute("update link_chats set chat=? where link_id=? and tool=?",
                                    (receipt['chat_id'], link_id, side))
                    self._event(link_id, at, 'link_moved', side,
                                {'from': before_chat, 'to': receipt['chat_id']})
                event_id = self._event(link_id, at, kind, side, detail, turn_ids)
                for turn_id, local_id in zip(turn_ids, local_ids):
                    self.db.execute("update turn_states set state=?,local_id=?,event_id=? where turn_id=? and side=?",
                                    (state, local_id, event_id, turn_id, side))
            self.db.execute("update journal set state='committed',ended_at=?,post_receipt=? where id=?",
                            (at, json.dumps(receipt), entry_id))
        return event_id


    def copy_info(self, tool: str, chat_id: str) -> dict | None:
        """Read copy creation and visibility independently of rollback retention."""
        row = self.db.execute('select * from created_copies where tool=? and chat_id=?',(tool,chat_id)).fetchone()
        return dict(row) if row else None


    def mark_copy_shown(self, tool: str, chat_id: str, at: str) -> None:
        """Monotonically persist confirmed copy visibility by durable chat identity."""
        with self.db:
            self.db.execute('update created_copies set shown=1,seen_at=? where tool=? and chat_id=?',(at,tool,chat_id))


    def _record_copy(self, receipt, at):
        self.db.execute('insert into created_copies(tool,chat_id,delivered_at) values(?,?,?)',
                        (receipt['tool'],receipt['chat_id'],at))


    def complete_copy(self, entry_id: int, receipt: dict, at: str) -> None:
        """Commit an unlinked creation with durable visibility metadata atomically."""
        self._creation_entry(entry_id,receipt)
        with self.db:
            self._record_copy(receipt,at)
            self.db.execute("update journal set state='committed',ended_at=?,post_receipt=? where id=?",(at,json.dumps(receipt),entry_id))


    def _creation_entry(self, entry_id, receipt, link_id=None):
        entry = self.journal_entry(entry_id)
        if (entry['state'] != 'begun' or entry['link_id'] != link_id or
                (entry['tool'],entry['chat_id'],entry['action']) !=
                (receipt['tool'],receipt['chat_id'],receipt['kind']) or receipt['kind'] != 'create'):
            raise ValueError('receipt_identity_mismatch')
