"""RecordStore implementation with one connection and shared atomic transactions."""
from __future__ import annotations

import sqlite3

from .history import HistoryRecords
from .journal import JournalRecords
from .links import LinksRecords
from .turns import TurnsRecords
from .schema import COPY_SCHEMA, JOURNAL_SCHEMA, LINK_SCHEMA
from .records import now


class Ledger(LinksRecords, TurnsRecords, HistoryRecords, JournalRecords):
    """Combine record concerns without introducing per-concern connections or commits."""
    def __init__(self, path: str):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("pragma foreign_keys = on")
        self.db.executescript(LINK_SCHEMA)
        self.db.executescript(JOURNAL_SCHEMA)
        self.db.execute(COPY_SCHEMA)
        self.db.execute("pragma user_version = 1")
        self.db.commit()


    def close(self) -> None:
        """Close the owned SQLite connection."""
        self.db.close()
