"""RecordStore implementation with one connection and shared atomic transactions."""
from __future__ import annotations

import sqlite3

from .history import HistoryRecords
from .journal import JournalRecords
from .links import LinksRecords
from .turns import TurnsRecords
from .undo import UndoRecords
from .evidence import EvidenceRecords
from .brief import BriefRecords
from .read_metadata import ReadMetadata
from .schema import BRIEF_SCHEMA, COPY_SCHEMA, EVIDENCE_SCHEMA, JOURNAL_SCHEMA, LINK_SCHEMA, READ_METADATA_SCHEMA
from .records import now


class Ledger(LinksRecords, TurnsRecords, HistoryRecords, JournalRecords, UndoRecords, EvidenceRecords, BriefRecords, ReadMetadata):
    """Combine record concerns without introducing per-concern connections or commits."""
    def __init__(self, path: str):
        from ..ports.budget import sqlite_timeout
        self.db = sqlite3.connect(path, timeout=sqlite_timeout())
        self.db.row_factory = sqlite3.Row
        self.db.execute("pragma foreign_keys = on")
        self.db.executescript(LINK_SCHEMA)
        self.db.executescript(JOURNAL_SCHEMA)
        self.db.execute(COPY_SCHEMA)
        self.db.executescript(EVIDENCE_SCHEMA)
        self.db.executescript(BRIEF_SCHEMA)
        self.db.executescript(READ_METADATA_SCHEMA)
        self.db.execute("pragma user_version = 1")
        self.db.commit()


    def close(self) -> None:
        """Close the owned SQLite connection."""
        self.db.close()
