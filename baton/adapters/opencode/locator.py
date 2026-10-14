"""Locate OpenCode sessions inside one injectable home root."""
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from ...ports.budget import sqlite_timeout
import stat

from ...domain.errors import ChatHeld, NotAvailable
from ...ports.tool import ChatRef


def iso(milliseconds):
    """Convert native milliseconds to UTC."""
    return datetime.fromtimestamp(milliseconds / 1000, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class OpenCodeLocator:
    """Read the sidebar metadata, excluding child sessions."""

    def __init__(self, root, require_chat=None):
        self.root = Path(root)
        self.require_chat = require_chat

    def inside(self, path):
        """Reject paths or symlink components outside the injected root."""
        path = Path(path).absolute()
        if self.root.is_symlink():
            raise NotAvailable()
        if not path.is_relative_to(self.root) or ".." in path.relative_to(self.root).parts:
            raise NotAvailable()
        current = self.root
        for piece in path.relative_to(self.root).parts:
            current /= piece
            if current.is_symlink():
                raise NotAvailable()
            if current.exists() and not current.is_dir():
                info = current.stat()
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise NotAvailable()
        return path

    @property
    def database(self):
        """The database and its SQLite companion files, confined to the root."""
        path = self.inside(self.root / ".local/share/opencode/opencode.db")
        for suffix in ("-wal", "-shm", "-journal"):
            self.inside(Path(str(path) + suffix))
        return path

    @contextmanager
    def connect(self, write=False):
        """Open an existing database without implicitly creating one."""
        mode = "rw" if write else "ro"
        db = None
        try:
            db = sqlite3.connect(self.database.as_uri() + "?mode=" + mode, uri=True, timeout=sqlite_timeout(0.1))
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            yield db
        except sqlite3.OperationalError as error:
            if "locked" in str(error).lower() or "busy" in str(error).lower():
                raise ChatHeld() from None
            raise
        finally:
            if db is not None:
                db.close()

    def row(self, chat_id):
        """Return every column of a session row."""
        if self.require_chat:
            self.require_chat(chat_id)
        with self.connect() as db:
            row = db.execute("SELECT * FROM session WHERE id=?", (chat_id,)).fetchone()
        if row is None or row["parent_id"]:
            raise KeyError(chat_id)
        return dict(row)

    @staticmethod
    def ref(row):
        """Convert sidebar metadata to the shared chat reference."""
        return ChatRef(row["id"], row["title"], row["directory"], iso(row["time_updated"]))

    def chats(self):
        """List top-level sessions in newest-first order."""
        if not self.database.exists():
            return []
        with self.connect() as db:
            rows = db.execute("SELECT * FROM session WHERE parent_id IS NULL ORDER BY time_updated DESC,id").fetchall()
        return [self.ref(row) for row in rows]

    def resolve(self, chat_id):
        """Resolve a stable native session ID."""
        return self.ref(self.row(chat_id))

    def name(self, chat_id):
        """Return the title used in the sidebar."""
        return self.resolve(chat_id).name
