"""SQLite history records sharing the owning Ledger connection."""
from __future__ import annotations

import json
from typing import Any, Sequence
from ..domain.link import Event


class HistoryRecords:
    """Internal method group; transaction boundaries remain on the shared connection."""

    def record_event(self, link_id: int, kind: str, side: str, at: str,
                     turn_ids: Sequence[int] = (), detail: dict[str, Any] | None = None) -> int:
        """Persist a non-delivery action in the link history."""
        with self.db:
            return self._event(link_id, at, kind, side, detail, turn_ids)


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


    def _event(self, link_id: int, at: str, kind: str, side: str = "",
               detail: dict[str, Any] | None = None, turn_ids: Sequence[int] = ()) -> int:
        cur = self.db.execute(
            "insert into events(link_id, at, kind, side, detail) values(?,?,?,?,?)",
            (link_id, at, kind, side, json.dumps(detail or {})))
        self.db.executemany("insert into event_turns(event_id, turn_id) values(?,?)",
                            [(cur.lastrowid, turn_id) for turn_id in turn_ids])
        return cur.lastrowid
