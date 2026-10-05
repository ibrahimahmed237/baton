"""Baton's own record of links and of where every turn stands on each side.

One SQLite file. A link joins two chats from two different tools, and a chat is
in one link at a time. For every turn of a linked conversation the ledger holds
one state per side (docs/features/sync-status.md), and everything Baton does to
a link is listed in its history (docs/features/link-actions.md, A8).

A side is named by its tool. Nothing here is specific to one tool, so a new tool
only has to be added to TOOLS.

The ledger never touches a chat. Callers read chats with the readers, write them
with the writers, and tell the ledger what happened.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

from ..domain.model import Turn
from .schema import JOURNAL_SCHEMA
from ..domain.link import (ADDED, ATTACHED, DELIVERED, KEPT_BACK, MODES, SHOWN, SKIPPED, TOOLS,
                           WAITING, WRITTEN_HERE, Event, LedgerTurn, Link)
from ..domain.errors import AlreadyDelivered, AlreadyLinked

_FIRST_LINE_CHARS = 200

_SCHEMA = """
create table if not exists links(
  id integer primary key,
  mode text not null,
  paused integer not null default 0,
  created_at text not null,
  removed_at text
);
create table if not exists link_chats(
  link_id integer not null references links(id),
  tool text not null,
  chat text not null,
  active integer not null default 1,
  primary key(link_id, tool)
);
create unique index if not exists one_link_per_chat
  on link_chats(tool, chat) where active = 1;
create table if not exists events(
  id integer primary key,
  link_id integer not null references links(id),
  at text not null,
  kind text not null,
  side text not null default '',
  detail text not null default '{}'
);
create table if not exists turns(
  id integer primary key,
  link_id integer not null references links(id),
  seq integer not null,
  origin text not null,
  origin_id text not null,
  started_at text not null default '',
  ended_at text not null default '',
  first_line text not null default '',
  size integer not null default 0,
  pinned integer not null default 0,
  unique(link_id, origin, origin_id)
);
create table if not exists turn_states(
  turn_id integer not null references turns(id),
  side text not null,
  state text not null,
  local_id text not null default '',
  event_id integer references events(id),
  primary key(turn_id, side)
);
create table if not exists event_turns(
  event_id integer not null references events(id),
  turn_id integer not null references turns(id),
  primary key(event_id, turn_id)
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Ledger:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("pragma foreign_keys = on")
        self.db.executescript(_SCHEMA)
        self.db.executescript(JOURNAL_SCHEMA)
        self.db.execute("pragma user_version = 1")
        self.db.commit()

    def close(self) -> None:
        self.db.close()

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

    def local_ids(self, link_id: int, side: str) -> dict[int, str]:
        """Read local identities, including unconfirmed prior deliveries."""
        return {row["turn_id"]: row["local_id"] for row in self.db.execute(
            "select s.turn_id,s.local_id from turn_states s join turns t on t.id=s.turn_id"
            " where t.link_id=? and s.side=? and s.local_id<>''", (link_id, side))}

    def reset_delivery(self, link_id: int, side: str, turn_ids: Sequence[int], at: str) -> None:
        """Keep bypassed identities while making their delivery state truthful."""
        with self.db:
            for turn_id in turn_ids:
                current = self._state(link_id, turn_id, side)
                if current not in (ADDED, SHOWN):
                    continue
                self.db.execute("update turn_states set state=?,event_id=null where turn_id=? and side=?",
                                (WAITING, turn_id, side))
            if turn_ids:
                self._event(link_id, at, "not_confirmed", side, turn_ids=turn_ids)

    def record_event(self, link_id: int, kind: str, side: str, at: str,
                     turn_ids: Sequence[int] = (), detail: dict[str, Any] | None = None) -> int:
        """Persist a non-delivery action in the link history."""
        with self.db:
            return self._event(link_id, at, kind, side, detail, turn_ids)

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

    # Links

    def link(self, chats: Mapping[str, str], mode: str, at: str = "") -> Link:
        """Link two chats, given as tool -> chat. Each must be free of any other link."""
        if mode not in MODES:
            raise ValueError("unknown way of linking: %s" % mode)
        if len(chats) != 2:
            raise ValueError("a link joins two chats from two different tools")
        for side, chat in chats.items():
            existing = self.link_for(_tool(side), chat)
            if existing:
                raise AlreadyLinked(side, existing)
        at = at or now()
        with self.db:
            cur = self.db.execute("insert into links(mode, created_at) values(?,?)", (mode, at))
            self.db.executemany("insert into link_chats(link_id, tool, chat) values(?,?,?)",
                                [(cur.lastrowid, side, chat) for side, chat in chats.items()])
            self._event(cur.lastrowid, at, "linked", detail={"mode": mode})
        return self.get_link(cur.lastrowid)

    def get_link(self, link_id: int) -> Link:
        row = self.db.execute("select * from links where id=?", (link_id,)).fetchone()
        if row is None:
            raise KeyError(link_id)
        chats = {r["tool"]: r["chat"] for r in self.db.execute(
            "select tool, chat from link_chats where link_id=?", (link_id,))}
        ordered = {tool: chats[tool] for tool in sorted(chats, key=TOOLS.index)}
        return Link(row["id"], ordered, row["mode"], bool(row["paused"]), row["created_at"],
                    row["removed_at"] or "")

    def link_for(self, side: str, chat: str) -> Link | None:
        row = self.db.execute(
            "select link_id from link_chats where tool=? and chat=? and active=1", (side, chat)).fetchone()
        return self.get_link(row["link_id"]) if row else None

    def links(self) -> list[Link]:
        rows = self.db.execute("select id from links where removed_at is null order by id").fetchall()
        return [self.get_link(row["id"]) for row in rows]

    def remove_link(self, link_id: int, at: str = "") -> None:
        """End a link. No chat is touched and the link's history is kept."""
        at = at or now()
        with self.db:
            self.db.execute("update links set removed_at=? where id=?", (at, link_id))
            self.db.execute("update link_chats set active=0 where link_id=?", (link_id,))
            self._event(link_id, at, "link_removed")

    def set_paused(self, link_id: int, paused: bool, at: str = "") -> None:
        with self.db:
            self.db.execute("update links set paused=? where id=?", (int(paused), link_id))
            self._event(link_id, at or now(), "paused" if paused else "resumed")

    def move_link(self, link_id: int, side: str, chat: str, at: str = "") -> None:
        """Point one side of a link at another chat (a merged or shorter copy)."""
        existing = self.link_for(side, chat)
        if existing and existing.id != link_id:
            raise AlreadyLinked(side, existing)
        before = self.get_link(link_id).chat(side)
        with self.db:
            self.db.execute("update link_chats set chat=? where link_id=? and tool=?", (chat, link_id, side))
            self._event(link_id, at or now(), "link_moved", side, {"from": before, "to": chat})

    # Turns

    def record_turns(self, link_id: int, side: str, turns: Iterable[Turn]) -> list[int]:
        """Take in turns read from one side's chat; return the ids of the new ones.

        A turn is new when it was written on that side: not recorded before, and
        not one Baton put there itself. New turns wait on every other side.
        """
        others = self.get_link(link_id).others(side)
        known = {row[0] for row in self.db.execute(
            "select origin_id from turns where link_id=? and origin=?", (link_id, side))}
        known |= {row[0] for row in self.db.execute(
            "select s.local_id from turn_states s join turns t on t.id=s.turn_id"
            " where t.link_id=? and s.side=? and s.local_id<>''", (link_id, side))}
        seq = self.db.execute(
            "select coalesce(max(seq), 0) from turns where link_id=?", (link_id,)).fetchone()[0]
        added = []
        with self.db:
            for turn in turns:
                if turn.id in known:
                    continue
                known.add(turn.id)
                seq += 1
                cur = self.db.execute(
                    "insert into turns(link_id, seq, origin, origin_id, started_at, ended_at, first_line, size)"
                    " values(?,?,?,?,?,?,?,?)",
                    (link_id, seq, side, turn.id, turn.started_at, turn.ended_at,
                     turn.prompt.text.strip()[:_FIRST_LINE_CHARS], _size(turn)))
                self.db.executemany(
                    "insert into turn_states(turn_id, side, state, local_id) values(?,?,?,?)",
                    [(cur.lastrowid, side, WRITTEN_HERE, turn.id)]
                    + [(cur.lastrowid, tool, WAITING, "") for tool in others])
                added.append(cur.lastrowid)
        return added

    def turns(self, link_id: int) -> list[LedgerTurn]:
        """The conversation of a link, in order, with each turn's state per side."""
        states: dict[int, dict[str, str]] = {}
        for row in self.db.execute(
                "select s.turn_id, s.side, s.state from turn_states s join turns t on t.id=s.turn_id"
                " where t.link_id=?", (link_id,)):
            states.setdefault(row["turn_id"], {})[row["side"]] = row["state"]
        rows = self.db.execute("select * from turns where link_id=? order by seq", (link_id,))
        return [LedgerTurn(row["id"], row["seq"], row["origin"], row["origin_id"], row["started_at"],
                           row["ended_at"], row["first_line"], row["size"], bool(row["pinned"]), states.get(row["id"], {}))
                for row in rows]

    def set_order(self, link_id: int, turn_ids: Sequence[int]) -> None:
        """Put these turns in the given order, in the places they hold in the conversation now."""
        seqs = []
        for turn_id in turn_ids:
            row = self.db.execute("select seq from turns where id=? and link_id=?", (turn_id, link_id)).fetchone()
            if row is None:
                raise KeyError("turn %d is not part of link %d" % (turn_id, link_id))
            seqs.append(row["seq"])
        if len(set(turn_ids)) != len(turn_ids):
            raise ValueError("a turn is named twice")
        with self.db:
            self.db.executemany("update turns set seq=? where id=?", list(zip(sorted(seqs), turn_ids)))

    def deliver(self, link_id: int, side: str, turn_ids: Sequence[int], state: str, kind: str,
                at: str = "", local_ids: Sequence[str] = (), detail: dict[str, Any] | None = None) -> int:
        """Record that waiting turns reached a side, and how; return the history entry's id.

        `local_ids` are the ids the turns got in that side's chat, so they are
        not taken for new turns the next time the chat is read.
        """
        if state not in DELIVERED:
            raise ValueError("not a way of delivering a turn: %s" % state)
        if local_ids and len(local_ids) != len(turn_ids):
            raise ValueError("one local id per turn is needed")
        for turn_id in turn_ids:
            current = self._state(link_id, turn_id, side)
            if current != WAITING:
                raise ValueError("turn %d is %s on %s, not waiting" % (turn_id, current, side))
        with self.db:
            event_id = self._event(link_id, at or now(), kind, side, detail, turn_ids)
            for index, turn_id in enumerate(turn_ids):
                self.db.execute(
                    "update turn_states set state=?, local_id=?, event_id=? where turn_id=? and side=?",
                    (state, local_ids[index] if local_ids else "", event_id, turn_id, side))
        return event_id

    def mark_shown(self, link_id: int, side: str, turn_ids: Sequence[int] | None = None) -> int:
        """After that side's app was relaunched: what was added is now shown."""
        query = ("update turn_states set state=? where side=? and state=?"
                 " and turn_id in (select id from turns where link_id=?)")
        values: list[Any] = [SHOWN, side, ADDED, link_id]
        if turn_ids is not None:
            if not turn_ids:
                return 0
            query += " and turn_id in (" + ",".join("?" for _ in turn_ids) + ")"
            values.extend(turn_ids)
        with self.db:
            cur = self.db.execute(query, values)
        return cur.rowcount

    def keep_back(self, link_id: int, turn_id: int, at: str = "") -> None:
        """Keep a turn on the side it was written; it is no longer waiting anywhere."""
        others = self.get_link(link_id).others(self._origin(link_id, turn_id))
        for side in others:
            if self._state(link_id, turn_id, side) in DELIVERED:
                row = self.db.execute(
                    "select e.at from turn_states s join events e on e.id=s.event_id"
                    " where s.turn_id=? and s.side=?", (turn_id, side)).fetchone()
                raise AlreadyDelivered(turn_id, side, row["at"] if row else "")
        for side in others:
            self._change(link_id, turn_id, side, WAITING, KEPT_BACK, "kept_back", at)

    def send_after_all(self, link_id: int, turn_id: int, at: str = "") -> None:
        for side in self.get_link(link_id).others(self._origin(link_id, turn_id)):
            self._change(link_id, turn_id, side, KEPT_BACK, WAITING, "kept_back_removed", at)

    def skip(self, link_id: int, turn_id: int, side: str, at: str = "") -> None:
        """In a conflict the user kept that side's own version: this turn will not go there."""
        self._change(link_id, turn_id, side, WAITING, SKIPPED, "skipped", at)

    def set_pinned(self, link_id: int, turn_id: int, pinned: bool) -> None:
        self._origin(link_id, turn_id)
        with self.db:
            self.db.execute("update turns set pinned=? where id=?", (int(pinned), turn_id))

    # History

    def history(self, link_id: int) -> list[Event]:
        """Everything Baton did to a link, newest first."""
        turn_ids: dict[int, list[int]] = {}
        for row in self.db.execute(
                "select et.event_id, et.turn_id from event_turns et join events e on e.id=et.event_id"
                " join turns t on t.id=et.turn_id where e.link_id=? order by t.seq", (link_id,)):
            turn_ids.setdefault(row["event_id"], []).append(row["turn_id"])
        rows = self.db.execute("select * from events where link_id=? order by id desc", (link_id,))
        return [Event(row["id"], row["at"], row["kind"], row["side"], json.loads(row["detail"]),
                      tuple(turn_ids.get(row["id"], ()))) for row in rows]

    # Internals

    def _event(self, link_id: int, at: str, kind: str, side: str = "",
               detail: dict[str, Any] | None = None, turn_ids: Sequence[int] = ()) -> int:
        cur = self.db.execute(
            "insert into events(link_id, at, kind, side, detail) values(?,?,?,?,?)",
            (link_id, at, kind, side, json.dumps(detail or {})))
        self.db.executemany("insert into event_turns(event_id, turn_id) values(?,?)",
                            [(cur.lastrowid, turn_id) for turn_id in turn_ids])
        return cur.lastrowid

    def _origin(self, link_id: int, turn_id: int) -> str:
        row = self.db.execute(
            "select origin from turns where id=? and link_id=?", (turn_id, link_id)).fetchone()
        if row is None:
            raise KeyError("turn %d is not part of link %d" % (turn_id, link_id))
        return row["origin"]

    def _state(self, link_id: int, turn_id: int, side: str) -> str:
        self._origin(link_id, turn_id)
        row = self.db.execute(
            "select state from turn_states where turn_id=? and side=?", (turn_id, side)).fetchone()
        if row is None:
            raise ValueError("link %d has no %s side" % (link_id, side))
        return row["state"]

    def _change(self, link_id: int, turn_id: int, side: str, expected: str, state: str,
                kind: str, at: str) -> None:
        current = self._state(link_id, turn_id, side)
        if current != expected:
            raise ValueError("turn %d is %s on %s, not %s" % (turn_id, current, side, expected))
        with self.db:
            event_id = self._event(link_id, at or now(), kind, side, turn_ids=(turn_id,))
            self.db.execute("update turn_states set state=?, event_id=? where turn_id=? and side=?",
                            (state, event_id, turn_id, side))


def _tool(side: str) -> str:
    if side not in TOOLS:
        raise ValueError("unknown tool: %s" % side)
    return side


def _size(turn: Turn) -> int:
    """Characters of text in a turn, for estimating what it costs to send."""
    return len(turn.prompt.text) + sum(len(message.text) for message in turn.messages)
