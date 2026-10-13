"""Shape-based OpenCode format checks and unfinished-reply state."""
import json
import sqlite3

from ...domain.conditions import SideCondition
from ...ports.tool import FormatCheck
from .facts import SCHEMA_VERSION

REQUIRED = {
    "session": {"id", "project_id", "parent_id", "slug", "directory", "title", "version", "time_created", "time_updated"},
    "message": {"id", "session_id", "time_created", "time_updated", "data"},
    "part": {"id", "message_id", "session_id", "time_created", "time_updated", "data"},
    "project": {"id", "worktree", "vcs", "time_created", "time_updated", "sandboxes"},
    "project_directory": {"project_id", "directory", "time_created"},
}


class OpenCodeState:
    """Report format from the columns used, rather than session version strings."""

    def __init__(self, adapter):
        self.adapter = adapter

    @staticmethod
    def shape_known(db):
        """Added nullable/defaulted columns are compatible; required new values are not."""
        for table, required in REQUIRED.items():
            columns = db.execute('PRAGMA table_info("%s")' % table).fetchall()
            if not required <= {r[1] for r in columns}:
                return False
            if any(r[3] and r[4] is None and r[1] not in required for r in columns):
                return False
        return True

    def format_version(self):
        """Return a stable shape identifier for compatible SQLite tables."""
        if not self.adapter.locator.database.exists():
            return FormatCheck(False, "missing")
        try:
            with self.adapter.locator.connect() as db:
                known = self.shape_known(db)
        except (sqlite3.Error, OSError):
            return FormatCheck(False, "unreadable")
        return FormatCheck(known, SCHEMA_VERSION if known else "schema")

    def condition(self, chat_id):
        """Bound stale unfinished replies only while the desktop is stopped."""
        process = self.adapter.process
        try:
            self.adapter.locator.row(chat_id)
        except (KeyError, sqlite3.Error):
            return SideCondition(exists=False, hooks_ready=self.adapter.hooks.check().ok,
                                 app_running=process.running(), format_known=self.format_version().known)
        rows, parts = self.adapter.reader.rows(chat_id)
        observation = self.adapter.chat_status(chat_id) if self.adapter.chat_status else {}
        running = process.running()
        now = self.adapter.now().timestamp() * 1000
        unfinished = []
        for row in rows:
            data = json.loads(row["data"])
            if data.get("role") != "assistant" or data.get("finish") or data.get("batonWritten"):
                continue
            last = max([row["time_created"], row["time_updated"]] +
                       [max(p["time_created"], p["time_updated"]) for p in parts if p["message_id"] == row["id"]])
            unfinished.append(running or now - last <= self.adapter.unfinished_timeout * 1000)
        status = observation.get("status")
        if isinstance(status, dict):
            status = status.get("type")
        busy = observation.get("busy", False) or status == "busy" or observation.get("replying", False)
        return SideCondition(exists=True, open=bool(observation.get("open", False)),
                             replying=bool(busy or any(unfinished)),
                             hooks_ready=self.adapter.hooks.check().ok, app_running=running,
                             app_started_at=process.started_at(), format_known=self.format_version().known)
