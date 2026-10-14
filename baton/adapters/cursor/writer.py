"""Closed-app display writes with durable intent and transactional comparison."""
import base64
from contextlib import closing
import json
import os
from pathlib import Path
import tempfile
import sqlite3
from uuid import uuid4

from ...domain.errors import AppMustBeClosed, ChatChanged, NotAvailable, UnknownFormat
from ...ports.tool import WriteReceipt, WriteResult
from .locator import valid_id
from .records import turn_records, selected, CHAT_FIELDS, HEADER_FIELDS


def pack(value):
    return {'bytes': base64.b64encode(value).decode()} if isinstance(value, bytes) else value


def unpack(value):
    return base64.b64decode(value['bytes']) if isinstance(value, dict) else value


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix='.intent-')
    try:
        with os.fdopen(descriptor, 'w') as stream:
            json.dump(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        Path(temporary).unlink(missing_ok=True)


class CursorWriter:
    def __init__(self, adapter):
        self.adapter = adapter
        self.prepared = None

    @property
    def receipts(self):
        return self.adapter.rollback_locator.root

    def _closed(self):
        if self.adapter.process.running():
            raise AppMustBeClosed()

    def _check(self, chat_id=None):
        self._closed()
        if not self.adapter.state.format_version().known:
            raise UnknownFormat()
        if chat_id is not None:
            if chat_id not in self.adapter.allowed_chat_ids:
                raise NotAvailable()
            self.adapter.locator.resolve(chat_id)
        elif not self.adapter.original_chat_ids:
            raise NotAvailable()

    def _snapshot(self, db, chat_id):
        db.row_factory = sqlite3.Row
        rows = db.execute('SELECT * FROM composerHeaders WHERE composerId=?', (chat_id,)).fetchall()
        header = {k: pack(v) for k, v in dict(rows[0]).items()} if rows else None
        keys = ('composerData:' + chat_id, 'bubbleId:' + chat_id + ':')
        values = {key: pack(value) for key, value in db.execute(
            'SELECT key,value FROM cursorDiskKV WHERE key=? OR substr(key,1,?)=?',
            (keys[0], len(keys[1]), keys[1]))}
        transcript = self.adapter.locator.transcript(chat_id)
        return {'header': header, 'rows': values,
                'transcript': {'path': str(transcript), 'bytes': pack(transcript.read_bytes())} if transcript else None}

    def prepare(self, chat_id, kind):
        if kind not in ('create', 'add', 'place', 'rename', 'cut', 'restore'):
            raise ValueError(kind)
        self._check(chat_id)
        if kind in ('cut', 'restore'):
            raise NotAvailable()
        if (chat_id is None) != (kind == 'create'):
            raise ValueError(kind)
        if chat_id is None:
            chat_id = str(uuid4())
        token = uuid4().hex
        with closing(self.adapter.locator.connect()) as db:
            before = self._snapshot(db, chat_id)
        data = {'token': token, 'before': before, 'after': None,
                'scope': sorted(self.adapter.original_chat_ids)}
        receipt = WriteReceipt('cursor', chat_id, kind, data)
        save_json(self.adapter.rollback_locator.inside(self.receipts / (token + '.json')), self._manifest(receipt))
        self.prepared = receipt
        if kind == 'create':
            self.adapter.allowed_chat_ids.add(chat_id)
        return receipt

    @staticmethod
    def _manifest(receipt):
        return {'tool': receipt.tool, 'chat_id': receipt.chat_id, 'kind': receipt.kind, 'data': receipt.data}

    def _begin(self, chat_id, kind):
        self._check(chat_id)
        receipt = self.prepared
        if receipt is None or receipt.kind != kind or (chat_id is not None and receipt.chat_id != chat_id):
            receipt = self.prepare(chat_id, kind)
        self.prepared = None
        return receipt

    def _replace(self, db, ident, snapshot):
        prefix = 'bubbleId:' + ident + ':'
        db.execute('DELETE FROM cursorDiskKV WHERE key=? OR substr(key,1,?)=?',
                   ('composerData:' + ident, len(prefix), prefix))
        db.execute('DELETE FROM composerHeaders WHERE composerId=?', (ident,))
        for key, value in snapshot['rows'].items():
            db.execute('INSERT INTO cursorDiskKV(key,value) VALUES(?,?)', (key, unpack(value)))
        header = snapshot['header']
        if header is not None:
            columns = list(header)
            # Names come from PRAGMA/SQLite rows, not any user argument.
            sql = 'INSERT INTO composerHeaders (' + ','.join('"' + k.replace('"', '""') + '"' for k in columns) + ') VALUES (' + ','.join('?' for _ in columns) + ')'
            db.execute(sql, tuple(unpack(header[k]) for k in columns))

    def _publish(self, receipt, after, turns):
        data = {**receipt.data, 'after': after}
        result_receipt = WriteReceipt('cursor', receipt.chat_id, receipt.kind, data)
        # Intent contains both complete row sets before the transaction starts.
        save_json(self.adapter.rollback_locator.inside(self.receipts / (data['token'] + '.json')), self._manifest(result_receipt))
        with closing(self.adapter.locator.connect(writable=True)) as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                self._check(None if receipt.kind == 'create' else receipt.chat_id)
                if self._snapshot(db, receipt.chat_id) != data['before']:
                    raise ChatChanged()
                self._replace(db, receipt.chat_id, after)
                self._closed()
                db.commit()
            except BaseException:
                db.rollback()
                raise
        return WriteResult(receipt.chat_id, tuple(t.id for t in turns), result_receipt)

    def _template(self):
        for ident in sorted(self.adapter.original_chat_ids):
            try:
                return self.adapter.locator.header(ident), self.adapter.locator.data(ident)
            except KeyError:
                continue
        raise NotAvailable()

    def _bubble_templates(self, chat_id=None):
        ids = (chat_id,) if chat_id in self.adapter.original_chat_ids else sorted(self.adapter.original_chat_ids, key=lambda ident: self.adapter.locator.header(ident).get('lastUpdatedAt', 0))
        templates = {}
        for ident in ids:
            data = self.adapter.locator.data(ident)
            for head, bubble in zip(data['fullConversationHeadersOnly'], self.adapter.locator.bubbles(ident, data)):
                if (bubble.get('type') in (1, 2) and isinstance(bubble.get('text'), str)
                        and not any(key in bubble for key in ('toolCall', 'toolResult', 'batonMessage'))
                        and not bubble.get('isInserted') and not bubble.get('inserted')):
                    role = bubble['type']
                    templates[role] = (bubble, head)
        return templates

    def create(self, turns, name, folder):
        receipt = self._begin(None, 'create')
        header, template = self._template()
        ms = int(self.adapter.now().timestamp() * 1000)
        ident = receipt.chat_id
        bubbles, heads = turn_records(turns, self._bubble_templates())
        self._validate_ids(turns, {})
        data = {**selected(template, CHAT_FIELDS), 'folder': folder, 'workspacePath': folder, 'composerId': ident, 'name': name, 'createdAt': ms, 'lastUpdatedAt': ms,
                'fullConversationHeadersOnly': heads, 'conversationState': '~',
                'generatingBubbleIds': [], 'latestChatGenerationUUID': None,
                'contextTokensUsed': 0, 'contextUsagePercent': 0,
                'subtitle': turns[-1].reply_text[:60] if turns else ''}
        value = {}
        value.update(composerId=ident, name=name, folder=folder, workspacePath=folder,
                     createdAt=ms, lastUpdatedAt=ms, subtitle=data['subtitle'])
        header = {**dict.fromkeys(header), **selected(header, HEADER_FIELDS)}
        header.update(composerId=ident, value=json.dumps(value))
        for key in ('createdAt', 'lastUpdatedAt', 'lastOpenedAt'):
            header[key] = ms
        for key in ('isArchived', 'isDeleted'):
            header[key] = 0
        rows = {'composerData:' + ident: json.dumps(data)}
        rows.update({'bubbleId:' + ident + ':' + key: json.dumps(value) for key, value in bubbles.items()})
        after = {'header': header, 'rows': rows, 'transcript': None}
        return self._publish(receipt, after, turns)

    @staticmethod
    def _validate_ids(turns, rows):
        ids = [m.id for t in turns for m in (t.prompt, *t.messages)]
        existing = {key.rsplit(':', 1)[-1] for key in rows if key.startswith('bubbleId:')}
        if len(ids) != len(set(ids)) or existing.intersection(ids) or any(not valid_id(i) for i in ids):
            raise ValueError('message_ids')

    def _edit(self, chat_id, turns, kind, before_id=None, name=None):
        receipt = self._begin(chat_id, kind)
        before = receipt.data['before']
        self._validate_ids(turns, before['rows'])
        data = json.loads(unpack(before['rows']['composerData:' + chat_id]))
        bubbles, heads = turn_records(turns, self._bubble_templates(chat_id))
        if kind == 'place':
            indices = [i for i, h in enumerate(data['fullConversationHeadersOnly']) if h['bubbleId'] == before_id]
            if len(indices) != 1:
                raise KeyError(before_id)
            index = indices[0]
            data['fullConversationHeadersOnly'][index:index] = heads
        elif kind == 'add':
            data['fullConversationHeadersOnly'].extend(heads)
        else:
            data['name'] = name
        header = dict(before['header'])
        value = json.loads(unpack(header['value']))
        if kind == 'rename':
            value['name'] = name
        else:
            ms = int(self.adapter.now().timestamp() * 1000)
            data['lastUpdatedAt'] = value['lastUpdatedAt'] = ms
            if 'lastUpdatedAt' in header:
                header['lastUpdatedAt'] = ms
        header['value'] = json.dumps(value)
        rows = dict(before['rows'])
        rows['composerData:' + chat_id] = json.dumps(data)
        rows.update({'bubbleId:' + chat_id + ':' + k: json.dumps(v) for k, v in bubbles.items()})
        return self._publish(receipt, {**before, 'header': header, 'rows': rows}, turns)

    def add(self, chat_id, turns):
        return self._edit(chat_id, turns, 'add')

    def place(self, chat_id, turns, before_local_id):
        return self._edit(chat_id, turns, 'place', before_id=before_local_id)

    def rename(self, chat_id, name):
        return self._edit(chat_id, (), 'rename', name=name)

    def cut(self, chat_id, keep_through_local_id):
        self._check(chat_id)
        raise NotAvailable()

    def restore(self, receipt):
        self._check(receipt.chat_id)
        raise NotAvailable()

    def take_back(self, receipt):
        self._closed()
        if receipt.tool != 'cursor' or receipt.data.get('scope') != sorted(self.adapter.original_chat_ids):
            raise NotAvailable()
        token = receipt.data.get('token')
        if not valid_id(token):
            raise NotAvailable()
        path = self.adapter.rollback_locator.inside(self.receipts / (token + '.json'))
        manifest = json.loads(path.read_text())
        if manifest['chat_id'] != receipt.chat_id or manifest['kind'] != receipt.kind:
            raise NotAvailable()
        data = manifest['data']
        with closing(self.adapter.locator.connect(writable=True)) as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                current = self._snapshot(db, receipt.chat_id)
                if current == data['before']:
                    db.rollback()
                    return
                if data['after'] is None or current != data['after']:
                    raise ChatChanged()
                self._replace(db, receipt.chat_id, data['before'])
                self._closed()
                db.commit()
            except BaseException:
                db.rollback()
                raise
