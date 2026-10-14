"""Locate app composers, never the separate cursor-agent store."""
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import re
import os
import stat

from ...domain.errors import NotAvailable
from ...ports.tool import ChatRef


def valid_id(ident):
    return isinstance(ident, str) and re.fullmatch(r'[A-Za-z0-9_-]+', ident) is not None


class CursorLocator:
    def __init__(self, root):
        raw = Path(root).absolute()
        # Inspect the supplied root before resolve can erase a symlink boundary.
        for path in (raw, *raw.parents):
            if path.is_symlink():
                raise NotAvailable()
        self.root = raw.resolve()

    def inside(self, path):
        path = Path(path).absolute()
        if not path.is_relative_to(self.root) or '..' in path.relative_to(self.root).parts:
            raise NotAvailable()
        current = self.root
        for part in path.relative_to(self.root).parts:
            current /= part
            try:
                info = current.lstat()
            except FileNotFoundError:
                continue
            if (stat.S_ISLNK(info.st_mode) or info.st_uid != os.getuid() or
                    (not stat.S_ISDIR(info.st_mode) and
                     (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1))):
                raise NotAvailable()
        return path

    @property
    def state_db(self):
        return self.inside(self.root / 'Library/Application Support/Cursor/User/globalStorage/state.vscdb')

    def connect(self, *, writable=False):
        path = self.state_db
        for suffix in ('-wal', '-shm', '-journal'):
            self.inside(Path(str(path) + suffix))
        from ...ports.budget import sqlite_timeout
        return sqlite3.connect(path.as_uri() + ('?mode=rw' if writable else '?mode=ro'), uri=True, timeout=sqlite_timeout())

    def headers(self):
        if not self.state_db.exists():
            return []
        with closing(self.connect()) as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute('SELECT * FROM composerHeaders')]

    def header(self, ident):
        if not valid_id(ident):
            raise NotAvailable()
        matches = [row for row in self.headers() if row['composerId'] == ident]
        if len(matches) != 1:
            raise KeyError(ident)
        return matches[0]

    def data(self, ident):
        if not valid_id(ident):
            raise NotAvailable()
        with closing(self.connect()) as db:
            row = db.execute('SELECT value FROM cursorDiskKV WHERE key=?', ('composerData:' + ident,)).fetchone()
        if row is None:
            raise KeyError(ident)
        return json.loads(row[0])

    def bubbles(self, ident, data=None):
        data = data if data is not None else self.data(ident)
        with closing(self.connect()) as db:
            values = []
            for head in data['fullConversationHeadersOnly']:
                row = db.execute('SELECT value FROM cursorDiskKV WHERE key=?',
                                 ('bubbleId:' + ident + ':' + head['bubbleId'],)).fetchone()
                if row is None:
                    raise KeyError(head['bubbleId'])
                values.append(json.loads(row[0]))
            return values

    def chats(self):
        refs = []
        for row in self.headers():
            value = json.loads(row['value'])
            if not value.get('isArchived') and not value.get('scriptStarted'):
                refs.append(self.resolve(row['composerId']))
        return refs

    def resolve(self, ident):
        row = self.header(ident)
        value = json.loads(row['value'])
        ms = value.get('lastUpdatedAt', row.get('lastUpdatedAt', 0))
        stamp = datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat().replace('+00:00', 'Z')
        folder = value.get('folder', value.get('workspacePath', ''))
        return ChatRef(ident, value.get('name', ''), folder, stamp)

    def name(self, ident):
        return self.resolve(ident).name

    def transcript(self, ident):
        if not valid_id(ident):
            raise NotAvailable()
        projects = self.inside(self.root / '.cursor/projects')
        paths = [self.inside(p) for p in projects.glob('*/agent-transcripts/' + ident + '/' + ident + '.jsonl')]
        if len(paths) > 1:
            raise NotAvailable()
        return paths[0] if paths else None
