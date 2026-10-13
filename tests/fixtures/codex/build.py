"""Hand-built Codex state: a rollout file and a state_5.sqlite in a temporary home folder.

The one place the tests know Codex's format. The shapes follow what
docs/SPIKE-M0.md and spike/m0_*.py recorded (rollout records, the `threads`
columns that m0_create.py inserts, the thread-writer lock files); content is
made up. Nothing here uses the production writer.
"""
import fcntl
import json
import os
import sqlite3
import threading
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from baton.domain.model import REPLY, TOOL_CALL, TOOL_RESULT

# Column names are the ones spike/m0_create.py inserts plus agent_role (seen in reference/).
# Types and NOT NULL constraints are a guess: the real table was not read.
THREADS_SCHEMA = """
CREATE TABLE threads (
    id TEXT PRIMARY KEY,
    rollout_path TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    source TEXT NOT NULL,
    model_provider TEXT NOT NULL,
    cwd TEXT NOT NULL,
    title TEXT NOT NULL,
    sandbox_policy TEXT NOT NULL,
    approval_mode TEXT NOT NULL,
    tokens_used INTEGER NOT NULL DEFAULT 0,
    has_user_event INTEGER NOT NULL DEFAULT 0,
    archived INTEGER NOT NULL DEFAULT 0,
    cli_version TEXT NOT NULL DEFAULT '',
    first_user_message TEXT NOT NULL DEFAULT '',
    model TEXT,
    reasoning_effort TEXT,
    created_at_ms INTEGER,
    updated_at_ms INTEGER,
    thread_source TEXT,
    preview TEXT NOT NULL DEFAULT '',
    recency_at INTEGER,
    recency_at_ms INTEGER,
    history_mode TEXT,
    name TEXT,
    is_pinned INTEGER NOT NULL DEFAULT 0,
    originator TEXT,
    agent_role TEXT
)"""

# The index of what Codex's chat view has read. Table names are from the spike; column names are a guess.
HISTORY_SCHEMA = """
CREATE TABLE thread_turns (thread_id TEXT, ordinal INTEGER, turn_id TEXT);
CREATE TABLE thread_items (thread_id TEXT, ordinal INTEGER, turn_id TEXT, item TEXT);
CREATE TABLE thread_history_projection_state (thread_id TEXT PRIMARY KEY, next_rollout_byte_offset INTEGER, next_rollout_ordinal INTEGER);
"""

SANDBOX = '{"type":"workspace-write"}'
BASE_INSTRUCTIONS = {"text": "made-up base instructions"}
EARLY = "2026-01-01T00:00:00.000Z"


def home(root) -> Path:
    return Path(root).resolve() / ".codex"


def rollout_file(root, thread) -> Path:
    return home(root) / "sessions" / "2026" / "01" / "01" / ("rollout-2026-01-01T00-00-00-%s.jsonl" % thread)


def tick_clock(start=datetime(2026, 1, 2, tzinfo=timezone.utc)):
    """A clock that moves one second on every reading, so every write has its own time."""
    moment = [start]

    def now():
        moment[0] += timedelta(seconds=1)
        return moment[0]
    return now


def native_records(turns, thread, folder):
    """Records as a native Codex chat holds them: setup text, events, response items, token counts."""
    records = []

    def add(kind, payload, at=EARLY):
        records.append({"timestamp": at, "ordinal": len(records), "type": kind, "payload": payload})

    add("session_meta", {"session_id": thread, "id": thread, "timestamp": EARLY, "cwd": folder,
                         "originator": "Codex Desktop", "cli_version": "0.159.2", "source": "vscode",
                         "thread_source": "user", "model_provider": "openai", "history_mode": "paginated",
                         "base_instructions": BASE_INSTRUCTIONS})
    for index, turn in enumerate(turns):
        turn_id = "native-turn-%d" % index
        add("turn_context", {"turn_id": turn_id, "cwd": folder, "model": "test-model"})
        add("event_msg", {"type": "task_started", "turn_id": turn_id, "started_at": 1, "model_context_window": 258400,
                          "collaboration_mode_kind": "default"})
        add("response_item", {"type": "message", "role": "developer", "id": "dev-%d" % index,
                              "content": [{"type": "input_text", "text": "<permissions instructions>made up</permissions instructions>"}]})
        add("response_item", {"type": "message", "role": "user",
                              "content": [{"type": "input_text", "text": "<environment_context>cwd</environment_context>"}]})
        add("event_msg", {"type": "item_completed", "thread_id": thread, "turn_id": turn_id, "completed_at_ms": 1,
                          "item": {"type": "UserMessage", "id": "item-u%d" % index,
                                   "content": [{"type": "text", "text": turn.prompt.text, "text_elements": []}]}})
        add("response_item", {"type": "message", "role": "user", "id": turn.prompt.id,
                              "content": [{"type": "input_text", "text": turn.prompt.text}]}, turn.prompt.at)
        add("response_item", {"type": "reasoning", "id": "reason-%d" % index, "encrypted_content": "x"})
        for message in turn.messages:
            if message.kind == TOOL_CALL:
                add("response_item", {"type": "function_call", "id": message.id, "name": message.tool,
                                      "arguments": json.dumps(message.tool_input), "call_id": message.call_id}, message.at)
            elif message.kind == TOOL_RESULT:
                add("response_item", {"type": "function_call_output", "id": message.id, "call_id": message.call_id,
                                      "output": message.text}, message.at)
            elif message.kind == REPLY:
                add("event_msg", {"type": "item_completed", "thread_id": thread, "turn_id": turn_id,
                                  "completed_at_ms": 1, "item": {"type": "AgentMessage", "id": "item-a" + message.id,
                                                                  "content": [{"type": "Text", "text": message.text}]}})
                add("response_item", {"type": "message", "role": "assistant", "id": message.id,
                                      "content": [{"type": "output_text", "text": message.text}]}, message.at)
            else:
                raise ValueError(message.kind)
        add("event_msg", token_count())
        add("event_msg", {"type": "task_complete", "turn_id": turn_id, "last_agent_message": turn.reply_text or None,
                          "started_at": 1, "completed_at": 2})
    return records


def token_count(total=1234, window=258400, used=12.5, reset=None, reached=None):
    """A token_count event as the spike recorded it (SPIKE-M0.md, "Both tools record a usage limit")."""
    limits = {"primary": {"used_percent": used, "window_minutes": 300, "resets_at": reset},
              "secondary": {"used_percent": 3.0, "window_minutes": 10080, "resets_at": reset},
              "rate_limit_reached_type": reached}
    usage = {"input_tokens": total - 34, "cached_input_tokens": 0, "output_tokens": 34, "reasoning_output_tokens": 0,
             "total_tokens": total}
    return {"type": "token_count", "info": {"total_token_usage": usage, "last_token_usage": usage,
                                            "model_context_window": window}, "rate_limits": limits}


def write_lines(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records))


def create_databases(root):
    """The empty state database and chat-view index, as a Codex that has just started would have them."""
    home(root).mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(home(root) / "state_5.sqlite")) as db:
        db.execute(THREADS_SCHEMA)
        db.commit()
    with closing(sqlite3.connect(home(root) / "thread_history_1.sqlite")) as db:
        db.executescript(HISTORY_SCHEMA)


def insert_thread(root, thread, folder="/fixture/project", title="fixture", updated_ms=1_767_225_600_000, **columns):
    row = {"id": thread, "rollout_path": str(rollout_file(root, thread)), "created_at": updated_ms // 1000,
           "updated_at": updated_ms // 1000, "source": "vscode", "model_provider": "openai", "cwd": folder,
           "title": title, "sandbox_policy": SANDBOX, "approval_mode": "on-request", "tokens_used": 10,
           "has_user_event": 1, "archived": 0, "cli_version": "0.159.2", "first_user_message": "first",
           "model": "test-model", "reasoning_effort": "medium", "created_at_ms": updated_ms,
           "updated_at_ms": updated_ms, "thread_source": "user", "preview": "first",
           "recency_at": updated_ms // 1000, "recency_at_ms": updated_ms, "history_mode": "paginated",
           "name": title, "is_pinned": 0, "originator": "Codex Desktop", "agent_role": None, **columns}
    with closing(sqlite3.connect(home(root) / "state_5.sqlite")) as db:
        db.execute("INSERT INTO threads (%s) VALUES (%s)" % (", ".join(row), ", ".join("?" * len(row))), list(row.values()))
        db.commit()


def build(root, turns, thread="thread-fixture", folder="/fixture/project", title="fixture"):
    """A chat of the given turns: its rollout file and its row. Returns the chat id."""
    if not (home(root) / "state_5.sqlite").exists():
        create_databases(root)
    write_lines(rollout_file(root, thread), native_records(turns, thread, folder))
    insert_thread(root, thread, folder, title)
    return thread


def run_sql(root, sql, params=(), database="state_5.sqlite"):
    with closing(sqlite3.connect(home(root) / database)) as db:
        rows = db.execute(sql, params).fetchall()
        db.commit()
    return rows


def read_lines(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines()]


def append_event(root, thread, payload, kind="event_msg"):
    """Append one record to a chat's rollout, numbered after the last one."""
    path = Path(run_sql(root, "SELECT rollout_path FROM threads WHERE id = ?", (thread,))[0][0])
    records = read_lines(path)
    record = {"timestamp": EARLY, "ordinal": records[-1]["ordinal"] + 1, "type": kind, "payload": payload}
    with path.open("a") as fh:
        fh.write(json.dumps(record) + "\n")


def set_index_offset(root, thread, offset):
    run_sql(root, "INSERT OR REPLACE INTO thread_history_projection_state VALUES (?, ?, 0)", (thread, offset),
            "thread_history_1.sqlite")


def trust_hooks(root, events=("UserPromptSubmit", "Stop")):
    """What Codex would record once the user trusts the entries with /hooks (key format is a guess)."""
    hooks = home(root) / "hooks.json"
    lines = []
    for index, event in enumerate(events):
        lines.append('[hooks.state."%s:%s:%d:0"]\ntrusted_hash = "sha256:made-up-%d"\n'
                     % (hooks, event.lower(), index, index))
    (home(root) / "config.toml").write_text("\n".join(lines))


class FixtureProcess:
    """The ChatGPT app as a test sees it: a running flag, and real file locks for the chats it holds."""

    def __init__(self, root):
        self.root = Path(root).resolve()
        self.is_running = False
        self.calls = []
        self._locks = {}
        self.control = threading.RLock()

    def hold(self, thread):
        """Take the thread-writer lock the way Codex does while a thread is loaded."""
        with self.control:
            if thread in self._locks:
                return
            path = home(self.root) / "thread-writer-locks" / (thread + ".lock")
            path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(path, os.O_RDWR | os.O_CREAT)
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            self._locks[thread] = descriptor

    def release(self, thread):
        with self.control:
            descriptor = self._locks.pop(thread, None)
            if descriptor is not None:
                os.close(descriptor)
            (home(self.root) / "thread-writer-locks" / (thread + ".lock")).unlink(missing_ok=True)

    def running(self):
        return self.is_running

    def started_at(self):
        return "2026-01-01T12:00:00Z" if self.is_running else ""

    def open_app(self):
        with self.control:
            self.calls.append(("open_app",))
            self.is_running = True

    def open_url(self, url):
        with self.control:
            self.calls.append(("open_url", url))
            self.is_running = True
            self.hold(url.rsplit("/", 1)[-1])

    def quit(self):
        with self.control:
            self.calls.append(("quit",))
            self.is_running = False
            for thread in list(self._locks):
                self.release(thread)

class FixtureCoordination:
    """An explicitly injected fixture lock protocol; never native verification."""

    @contextmanager
    def global_idle(self, adapter):
        """Fixture-only process transition guard, unsupported by SystemProcess."""
        from baton.domain.errors import NotAvailable
        if not hasattr(adapter.process, 'control'):
            raise NotAvailable()
        with adapter.process.control:
            yield

    @contextmanager
    def exclusive(self, locator, chat_id):
        from baton.domain.errors import ChatChanged, ChatHeld
        path = locator.locks / (chat_id + '.lock')
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise ChatHeld() from None
            info = os.fstat(descriptor)
            parent = path.parent.stat()
            class Lease:
                def check(self):
                    try:
                        current, directory = path.lstat(), path.parent.stat()
                    except OSError:
                        raise ChatChanged() from None
                    if ((current.st_dev, current.st_ino, current.st_nlink) != (info.st_dev, info.st_ino, 1) or
                            (directory.st_dev, directory.st_ino) != (parent.st_dev, parent.st_ino)):
                        raise ChatChanged()
            yield Lease()
        finally:
            os.close(descriptor)
