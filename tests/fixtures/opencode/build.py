"""Independent native-shaped fixtures from spike/m0b_opencode.py; no real data."""
from contextlib import closing
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3

from baton.domain.model import TOOL_CALL, TOOL_RESULT, TOOL_TEXT

SCHEMA = '''
CREATE TABLE project(id TEXT PRIMARY KEY,worktree TEXT NOT NULL,vcs TEXT,time_created INTEGER NOT NULL,
 time_updated INTEGER NOT NULL,sandboxes TEXT NOT NULL);
CREATE TABLE project_directory(project_id TEXT REFERENCES project(id),directory TEXT,time_created INTEGER,
 PRIMARY KEY(project_id,directory));
CREATE TABLE session(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES project(id),parent_id TEXT,
 slug TEXT NOT NULL,directory TEXT NOT NULL,title TEXT NOT NULL,version TEXT NOT NULL,
 summary_additions INTEGER DEFAULT 0,summary_deletions INTEGER DEFAULT 0,summary_files INTEGER DEFAULT 0,
 time_created INTEGER NOT NULL,time_updated INTEGER NOT NULL,path TEXT DEFAULT '',cost REAL DEFAULT 0,
 tokens_input INTEGER DEFAULT 0,tokens_output INTEGER DEFAULT 0,tokens_reasoning INTEGER DEFAULT 0,
 tokens_cache_read INTEGER DEFAULT 0,tokens_cache_write INTEGER DEFAULT 0);
CREATE TABLE message(id TEXT PRIMARY KEY,session_id TEXT NOT NULL REFERENCES session(id),
 time_created INTEGER NOT NULL,time_updated INTEGER NOT NULL,data TEXT NOT NULL);
CREATE TABLE part(id TEXT PRIMARY KEY,message_id TEXT NOT NULL REFERENCES message(id),
 session_id TEXT NOT NULL REFERENCES session(id),time_created INTEGER NOT NULL,time_updated INTEGER NOT NULL,data TEXT NOT NULL);
'''
MODEL = {"providerID": "fixture-provider", "modelID": "fixture-model"}
EARLY = 1767225600000


def database(root):
    """The native database below an explicit fixture root."""
    return Path(root) / ".local/share/opencode/opencode.db"


def run_sql(root, sql, params=()):
    """Execute fixture SQL without using adapter implementation helpers."""
    with closing(sqlite3.connect(database(root))) as db:
        db.execute("PRAGMA foreign_keys=ON")
        result = db.execute(sql, params).fetchall()
        db.commit()
        return result


def create_database(root):
    """Create the independently defined native schema."""
    path = database(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as db:
        db.executescript(SCHEMA)
        db.execute("INSERT INTO project VALUES(?,?,?,?,?,?)", ("fixture-first-commit", "/fixture/project", "git", EARLY, EARLY, "[]"))
        db.execute("INSERT INTO project_directory VALUES(?,?,?)", ("fixture-first-commit", "/fixture/project", EARLY))
        db.commit()


def insert_message(root, chat, ident, role, at, parts, **fields):
    """Insert a native message and its independently built parts."""
    data = {"role": role, "time": {"created": at}, **fields}
    run_sql(root, "INSERT INTO message VALUES(?,?,?,?,?)", (ident, chat, at, at, json.dumps(data)))
    for index, part in enumerate(parts):
        value = dict(part)
        part_id = value.pop("fixture_id", ident + "-part-" + str(index))
        run_sql(root, "INSERT INTO part VALUES(?,?,?,?,?,?)", (part_id, ident, chat, at + index, at + index, json.dumps(value)))


def build(root, turns, chat="ses_fixture", folder="/fixture/project", title="fixture"):
    """Build a three-turn sidebar session; metadata preserves supplied public IDs."""
    if not database(root).exists():
        create_database(root)
    run_sql(root, "INSERT INTO session(id,project_id,slug,directory,title,version,time_created,time_updated) VALUES(?,?,?,?,?,?,?,?)",
            (chat, "fixture-first-commit", "fixture", folder, title, "1.2.future", EARLY - 1, EARLY + 10000))
    for index, turn in enumerate(turns):
        at = EARLY + index * 10000
        diffs = [{"file": m.tool_input["path"]} for m in turn.messages if m.kind == TOOL_CALL and m.tool == "write"]
        insert_message(root, chat, turn.id, "user", at,
                       [{"type": "text", "text": turn.prompt.text}], model=MODEL, agent="build",
                       summary={"diffs": diffs}, baton=asdict(turn.prompt))
        for offset, message in enumerate(turn.messages):
            moment = at + (offset + 1) * 100
            if message.kind in (TOOL_CALL, TOOL_RESULT):
                part = {"type": "tool", "tool": message.tool, "callID": message.call_id or message.id,
                        "state": {"status": "pending" if message.kind == TOOL_CALL else "completed",
                                  "input": message.tool_input or {}, "output": message.text}, "baton": asdict(message)}
            else:
                part = {"type": "text", "text": message.text, "baton": asdict(message)}
            insert_message(root, chat, message.id, "assistant", moment, [part], parentID=turn.id,
                           providerID=MODEL["providerID"], modelID=MODEL["modelID"],
                           tokens={"total": 1234, "input": 1200, "output": 34, "cache": {"read": 0, "write": 0}},
                           finish="stop")
    return chat


def tick_clock():
    """Supply a deterministic clock that advances on each call."""
    value = [datetime(2026, 1, 2, tzinfo=timezone.utc)]
    def now():
        value[0] += timedelta(seconds=1)
        return value[0]
    return now


class FixtureProcess:
    """Fake desktop actions and per-chat open observations."""

    def __init__(self):
        self.is_running = False
        self.calls = []
        self.open_chats = set()

    def running(self):
        return self.is_running

    def started_at(self):
        return "2026-01-02T00:00:00Z" if self.is_running else ""

    def open_url(self, url):
        self.calls.append(("open_url", url))
        self.is_running = True

    def quit(self):
        self.calls.append(("quit",))
        self.is_running = False
        self.open_chats.clear()
