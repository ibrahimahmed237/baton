"""Small Cursor app DB and transcript shapes from the M0b spike."""
from contextlib import closing
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3


def db_path(root):
    return Path(root) / 'Library/Application Support/Cursor/User/globalStorage/state.vscdb'


def run_sql(root, sql, values=()):
    with closing(sqlite3.connect(db_path(root))) as db, db:
        return db.execute(sql, values).fetchall()


def data(root, ident):
    return json.loads(run_sql(root, 'SELECT value FROM cursorDiskKV WHERE key=?', ('composerData:' + ident,))[0][0])


def put_data(root, ident, value):
    run_sql(root, 'UPDATE cursorDiskKV SET value=? WHERE key=?', (json.dumps(value), 'composerData:' + ident))


def native_rich_text(text):
    return json.dumps({'root': {'children': [{'type': 'paragraph', 'children': [
        {'type': 'text', 'text': text}]}]}})


def build(root, turns, ident='cursor-fixture', transcript=False):
    path = db_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    ms = 1767225600000
    with closing(sqlite3.connect(path)) as db, db:
        db.execute('CREATE TABLE IF NOT EXISTS cursorDiskKV(key TEXT PRIMARY KEY,value BLOB NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS composerHeaders(composerId TEXT PRIMARY KEY,workspaceId TEXT,createdAt INTEGER,lastUpdatedAt INTEGER,isArchived INTEGER,isDeleted INTEGER,lastOpenedAt INTEGER,unused TEXT,value BLOB,version INTEGER)')
        heads = []
        for turn in turns:
            for message in (turn.prompt, *turn.messages):
                typ = 1 if message.kind == 'prompt' else 2
                bubble = {'bubbleId': message.id, 'type': typ, 'text': message.text,
                          'createdAt': message.at, 'richText': native_rich_text(message.text)}
                if message.kind == 'tool_call':
                    bubble['toolCall'] = {'name': message.tool, 'arguments': message.tool_input, 'id': message.call_id}
                elif message.kind == 'tool_result':
                    bubble['toolResult'] = {'id': message.call_id}
                elif message.kind == 'tool_text':
                    bubble['batonMessage'] = asdict(message)
                heads.append({'bubbleId': message.id, 'type': typ, 'createdAt': message.at,
                              'grouping': {'hasText': True, 'textPreview': message.text[:80]}})
                db.execute('INSERT INTO cursorDiskKV VALUES(?,?)',
                           ('bubbleId:' + ident + ':' + message.id, json.dumps(bubble)))
        value = {'composerId': ident, 'name': 'fixture', 'folder': '/fixture/project',
                 'workspacePath': '/fixture/project', 'createdAt': ms, 'lastUpdatedAt': ms}
        chat = {**value, '_v': 18, 'fullConversationHeadersOnly': heads,
                'conversationState': 'ENCODED-AGENT-STATE', 'contextTokensUsed': 5000,
                'contextTokenLimit': 200000, 'contextUsagePercent': 2.5}
        db.execute('INSERT INTO cursorDiskKV VALUES(?,?)', ('composerData:' + ident, json.dumps(chat)))
        db.execute('INSERT INTO composerHeaders VALUES(?,?,?,?,?,?,?,?,?,?)',
                   (ident, 'workspace-fixture', ms, ms, 0, 0, ms, None, json.dumps(value), 1))
    if transcript:
        write_transcript(root, ident, turns)
    return ident


def write_transcript(root, ident, turns):
    path = Path(root) / '.cursor/projects/fixture-project/agent-transcripts' / ident / (ident + '.jsonl')
    path.parent.mkdir(parents=True, exist_ok=True)
    records = []
    for turn in turns:
        records.append({'role': 'user', 'message': {'role': 'user', 'content': [
            {'type': 'text', 'text': '[2026-01-01T00:00:00Z]\n<user_query>\n' + turn.prompt.text + '\n</user_query>'}]}})
        for message in turn.messages:
            if message.kind == 'tool_call':
                block = {'type': 'tool_use', 'id': message.id, 'name': message.tool, 'input': message.tool_input}
            elif message.kind == 'tool_result':
                block = {'type': 'tool_result', 'tool_use_id': message.call_id, 'content': message.text}
            else:
                block = {'type': 'text', 'text': message.text}
            records.append({'role': 'assistant', 'message': {'role': 'assistant', 'content': [block]}})
        records.append({'type': 'turn_ended', 'reason': 'completed'})
    path.write_text(''.join(json.dumps(r) + '\n' for r in records))
    return path


def insert_text(root, ident, message):
    chat = data(root, ident)
    bubble = {'bubbleId': message.id, 'type': 1, 'text': message.text, 'createdAt': '', 'isInserted': True}
    run_sql(root, 'INSERT INTO cursorDiskKV VALUES(?,?)', ('bubbleId:' + ident + ':' + message.id, json.dumps(bubble)))
    chat['fullConversationHeadersOnly'].insert(1, {'bubbleId': message.id, 'type': 1})
    put_data(root, ident, chat)


def observation(root, ident, **values):
    path = Path(root) / '.baton/cursor-turns.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    current = json.loads(path.read_text()) if path.exists() else {}
    current[ident] = {**current.get(ident, {}), **values}
    path.write_text(json.dumps(current))


def tick_clock():
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    def now():
        nonlocal stamp
        stamp += timedelta(seconds=1)
        return stamp
    return now


class FixtureProcess:
    def __init__(self, root):
        self.root = Path(root)
        self.is_running = False
        self.started = ''
        self.visible = {}
        self.opened = []
        self.quits = 0

    def running(self):
        return self.is_running

    def started_at(self):
        return self.started

    def quit(self):
        self.is_running = False
        self.quits += 1

    def open_folder(self, folder):
        from baton.adapters.cursor import CursorAdapter
        self.opened.append(folder)
        self.is_running = True
        self.started = '2026-01-02T00:00:00Z'
        adapter = CursorAdapter(self.root)
        self.visible = {ref.id: adapter.reader.read(ref.id) for ref in adapter.locator.chats()}
