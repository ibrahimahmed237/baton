"""SQLite links records sharing the owning Ledger connection."""
from __future__ import annotations

import json
from typing import Mapping, Sequence
from ..domain.link import ADDED, MODES, SHOWN, TOOLS, WAITING, WRITTEN_HERE, Link
from ..domain.errors import AlreadyLinked
from .records import _FIRST_LINE_CHARS, _size, _tool, now


class LinksRecords:
    """Internal method group; transaction boundaries remain on the shared connection."""

    def complete_link(self, chats: Mapping[str, str], mode: str, rows: Sequence[dict], at: str,
                      entry_id: int | None = None, receipt: dict | None = None,
                      replace_link_id: int | None = None) -> Link:
        """Commit aligned link records and any verified creation as one transaction."""
        if len(chats) != 2 or mode not in MODES:
            raise ValueError('link_shape')
        for side,chat in chats.items():
            linked = self.link_for(_tool(side),chat)
            if linked and linked.id != replace_link_id:
                raise AlreadyLinked(side,linked)
        if replace_link_id is not None and self.get_link(replace_link_id).removed_at:
            raise ValueError('link_removed')
        if entry_id is not None:
            self._creation_entry(entry_id,receipt)
            if chats.get(receipt['tool']) != receipt['chat_id']:
                raise ValueError('chat_identity_mismatch')
        for row in rows:
            if (row['origin'] not in chats or set(row['states']) != set(chats) or
                    row['states'][row['origin']] != WRITTEN_HERE or
                    any(state not in (WRITTEN_HERE,SHOWN,ADDED,WAITING) for state in row['states'].values())):
                raise ValueError('turn_shape')
        with self.db:
            if replace_link_id is not None:
                self.db.execute('update links set removed_at=? where id=?',(at,replace_link_id))
                self.db.execute('update link_chats set active=0 where link_id=?',(replace_link_id,))
                self._event(replace_link_id,at,'link_removed')
            cur = self.db.execute('insert into links(mode,created_at) values(?,?)',(mode,at))
            link_id = cur.lastrowid
            self.db.executemany('insert into link_chats(link_id,tool,chat) values(?,?,?)',
                                [(link_id,side,chat) for side,chat in chats.items()])
            self._event(link_id,at,'linked',detail={'mode':mode})
            for seq,row in enumerate(rows,1):
                turn = row['turn']
                cur = self.db.execute('insert into turns(link_id,seq,origin,origin_id,started_at,ended_at,first_line,size) values(?,?,?,?,?,?,?,?)',
                    (link_id,seq,row['origin'],turn.id,turn.started_at,turn.ended_at,
                     turn.prompt.text.strip()[:_FIRST_LINE_CHARS],_size(turn)))
                turn_id = cur.lastrowid
                for side,state in row['states'].items():
                    event_id = self._event(link_id,at,'create' if entry_id else 'aligned',side,turn_ids=(turn_id,)) if state in (SHOWN,ADDED) else None
                    self.db.execute('insert into turn_states(turn_id,side,state,local_id,event_id) values(?,?,?,?,?)',
                                    (turn_id,side,state,row['local_ids'].get(side,''),event_id))
            if entry_id is not None:
                self._record_copy(receipt,at)
                self.db.execute("update journal set state='committed',link_id=?,ended_at=?,post_receipt=? where id=?",
                                (link_id,at,json.dumps(receipt),entry_id))
        return self.get_link(link_id)


    def complete_link_copy(self, link_id: int, side: str, chat_id: str,
                           turn_ids: Sequence[int], local_ids: Sequence[str], state: str,
                           at: str, entry_id: int, receipt: dict) -> Link:
        """Move a verified twin and its local identities without replacing turn records."""
        self._creation_entry(entry_id,receipt,link_id)
        link = self.get_link(link_id)
        if (link.removed_at or side not in link.sides or state not in (SHOWN,ADDED) or
                len(turn_ids) != len(local_ids) or len(set(local_ids)) != len(local_ids) or
                receipt['tool'] != side or receipt['chat_id'] != chat_id):
            raise ValueError('copy_identity_mismatch')
        for turn_id in turn_ids: self._origin(link_id,turn_id)
        if self.link_for(side,chat_id):
            raise AlreadyLinked(side,self.link_for(side,chat_id))
        with self.db:
            self.db.execute('update link_chats set chat=? where link_id=? and tool=?',(chat_id,link_id,side))
            self.db.execute("update links set mode='full_copy' where id=?",(link_id,))
            event_id = self._event(link_id,at,'create',side,{'from':link.chat(side),'to':chat_id},turn_ids)
            for turn_id,local_id in zip(turn_ids,local_ids):
                self.db.execute('update turn_states set state=?,local_id=?,event_id=? where turn_id=? and side=?',
                                (state,local_id,event_id,turn_id,side))
                self.db.execute('update turns set origin_id=? where id=? and origin=?',(local_id,turn_id,side))
            self._record_copy(receipt,at)
            self.db.execute("update journal set state='committed',ended_at=?,post_receipt=? where id=?",(at,json.dumps(receipt),entry_id))
        return self.get_link(link_id)


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
