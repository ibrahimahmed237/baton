"""SQLite turns records sharing the owning Ledger connection."""
from __future__ import annotations

from typing import Any, Iterable, Sequence
from ..domain.model import Turn
from ..domain.link import ADDED, DELIVERED, KEPT_BACK, SHOWN, SKIPPED, WAITING, WRITTEN_HERE, LedgerTurn
from ..domain.errors import AlreadyDelivered
from .records import _FIRST_LINE_CHARS, _size, now


class TurnsRecords:
    """Internal method group; transaction boundaries remain on the shared connection."""

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
