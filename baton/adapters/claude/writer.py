"""Native records with durable pre-write manifests and conservative rollback."""
from __future__ import annotations
import base64
import json
import os
import tempfile
from pathlib import Path
from uuid import uuid4
from dataclasses import asdict
from ...domain.errors import AppMustBeClosed, ChatChanged, ChatHeld, ChatReplying, NotAvailable, UnknownFormat
from ...domain.model import PROMPT, REPLY, TOOL_CALL, TOOL_RESULT, TOOL_TEXT
from ...ports.tool import WriteReceipt, WriteResult
from .reader import read_records, live_chain


def encode(data):
    """Encode native bytes into a JSON-safe receipt value."""
    return base64.b64encode(data).decode("ascii")
def decode(data):
    """Recover native bytes from a JSON-safe receipt value."""
    return base64.b64decode(data)
def serialize(records):
    """Encode native records as newline-terminated JSONL bytes."""
    return ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in records).encode()


def native_records(turns, session_id, folder, parent=None, version="2.1.284", prompt_index=0, template=None):
    """Build chained native records for public turn content."""
    records = []
    template = template or {}
    for turn in turns:
        prompt_index += 1
        for message in (turn.prompt, *turn.messages):
            envelope = dict(isSidechain=False, userType="external", entrypoint="claude-desktop",
                cwd=folder, sessionId=session_id, version=version, gitBranch="HEAD",
                uuid=message.id, parentUuid=parent, timestamp=message.at)
            if message.kind == PROMPT:
                envelope.update(type="user", promptId=message.id, permissionMode=template.get("permissionMode", "default"), origin={"kind": "human"},
                    promptSource=template.get("promptSource", "sdk"), turnOrigin="human", turnPosition={"promptIndex": prompt_index, "turnIndex": 1},
                    message={"role": "user", "content": message.text})
            elif message.kind == TOOL_RESULT:
                envelope.update(type="user", message={"role": "user", "content": [{"type": "tool_result",
                    "tool_use_id": message.call_id, "content": message.text, "is_error": message.is_error}]})
            elif message.kind in (REPLY, TOOL_TEXT, TOOL_CALL):
                block = {"type": "tool_use", "id": message.call_id or message.id, "name": message.tool, "input": message.tool_input} if message.kind == TOOL_CALL else {"type": "text", "text": message.text}
                envelope.update(type="assistant", message={"id": "msg_" + message.id, "type": "message", "role": "assistant",
                    "model": "codex", "content": [block], "stop_reason": "tool_use" if message.kind == TOOL_CALL else "end_turn", "stop_sequence": None,
                    "usage": {"input_tokens": 0, "output_tokens": 0}})
                if message.kind == TOOL_TEXT: envelope["batonMessageKind"] = TOOL_TEXT
                if message.kind == TOOL_CALL and not message.call_id: envelope["batonOriginalCallId"] = ""
            else: raise ValueError(message.kind)
            records.append(envelope)
            parent = message.id
    return records


class ClaudeWriter:
    """Publish native records with durable, reversible write receipts."""
    def __init__(self, adapter):
        self.adapter = adapter
        self.prepared = None
    def _check(self, chat_id=None, kind=""):
        if not self.adapter.state.format_version().known: raise UnknownFormat()
        if chat_id is not None:
            c = self.adapter.state.condition(chat_id)
            if not c.exists: raise KeyError(chat_id)
            if c.replying: raise ChatReplying()
            if c.open: raise ChatHeld()
        if kind == "rename" and self.adapter.process.running(): raise AppMustBeClosed()
        if kind == "place": raise NotAvailable()
    def _snapshot(self, paths):
        return {str(self.adapter.locator.inside(p)): encode(p.read_bytes()) if p.exists() else None for p in paths}
    def prepare(self, chat_id, kind):
        """Reserve creation identity or snapshot rollback data before mutation."""
        if kind not in ("create", "add", "cut", "rename", "place", "restore"): raise ValueError(kind)
        if (chat_id is None) != (kind == "create"): raise ValueError(kind)
        token = uuid4().hex
        if chat_id is None:
            chat_id, sid = "local_" + str(uuid4()), str(uuid4())
            paths, before = [], {}
        else:
            sid = self.adapter.locator.entry(chat_id)[1]["cliSessionId"]
            paths = [self.adapter.locator.session_path(chat_id), self.adapter.locator.entry(chat_id)[0]]
            before = self._snapshot(paths)
        receipt = WriteReceipt("claude", chat_id, kind, {"prepared": True, "token": token,
            "session_id": sid, "before": before, "intent": str(self.adapter.root / ".baton-rollback" / (token + ".json"))})
        self.prepared = receipt
        return receipt
    def _begin(self, chat_id, kind):
        receipt = self.prepared
        if receipt is None or receipt.kind != kind or (chat_id is not None and receipt.chat_id != chat_id):
            receipt = self.prepare(chat_id, kind)
        self.prepared = None
        return receipt
    def _write(self, receipt, after, turns=()):
        intent = self.adapter.locator.inside(receipt.data["intent"])
        before = receipt.data["before"] or {p: None for p in after}
        manifest = {"token": receipt.data["token"], "before": before, "after": after}
        intent.parent.mkdir(parents=True, exist_ok=True)
        with intent.open("x") as fh:
            json.dump(manifest, fh); fh.flush(); os.fsync(fh.fileno())
        directory = os.open(intent.parent, os.O_RDONLY)
        try: os.fsync(directory)
        finally: os.close(directory)
        # Recheck after reserving the rollback intent, immediately before mutations.
        self._check(None if receipt.kind == "create" else receipt.chat_id, receipt.kind)
        if self._snapshot([Path(p) for p in before]) != before: raise ChatChanged()
        try:
            for path, encoded in after.items():
                path = self.adapter.locator.inside(path)
                path.parent.mkdir(parents=True, exist_ok=True)
                # Publish whole native files atomically: a crash exposes either the
                # complete pre-write or complete post-write bytes, never a torn log.
                fd, temporary = tempfile.mkstemp(prefix=".baton-", dir=path.parent)
                try:
                    with os.fdopen(fd, "wb") as fh:
                        fh.write(decode(encoded)); fh.flush(); os.fsync(fh.fileno())
                    current = encode(path.read_bytes()) if path.exists() else None
                    if current != before.get(str(path)): raise ChatChanged()
                    self._check(None if receipt.kind == "create" else receipt.chat_id, receipt.kind)
                    os.replace(temporary, path)
                    directory = os.open(path.parent, os.O_RDONLY)
                    try: os.fsync(directory)
                    finally: os.close(directory)
                finally:
                    Path(temporary).unlink(missing_ok=True)
        except BaseException:
            self.take_back(receipt)
            raise
        post = WriteReceipt("claude", receipt.chat_id, receipt.kind,
            {**receipt.data, "prepared": False, "before": before, "after": after})
        return WriteResult(receipt.chat_id, tuple(t.id for t in turns), post)
    def create(self, turns, name, folder):
        """Publish a new native chat and its sidebar entry."""
        self._check()
        receipt = self._begin(None, "create")
        sid = receipt.data["session_id"]
        session, entry_path = self.adapter.locator.creation_paths(receipt.chat_id, sid, folder, self.adapter.account)
        records = native_records(turns, sid, folder)
        records.append({"type": "custom-title", "customTitle": name, "sessionId": sid})
        entry = dict(sessionId=receipt.chat_id, cliSessionId=sid, cwd=folder, originCwd=folder,
            lastFocusedAt=0, createdAt=0, lastActivityAt=0, isArchived=False, title=name, titleSource="auto",
            permissionMode="default", completedTurns=len(turns), titleTurn=0, bridgeSessionIds=[],
            alwaysAllowedReasons=[], sessionPermissionUpdates=[], spawnSeed={})
        return self._write(receipt, {str(session): encode(serialize(records)), str(entry_path): encode(json.dumps(entry).encode())}, turns)
    def add(self, chat_id, turns):
        """Append chained native records while preserving the existing byte prefix."""
        self._check(chat_id)
        receipt = self._begin(chat_id, "add")
        path = self.adapter.locator.session_path(chat_id)
        records = read_records(str(path)); chain = live_chain(records)
        existing = {r.get("uuid") for r in records}
        ids = [m.id for t in turns for m in (t.prompt, *t.messages)]
        if len(ids) != len(set(ids)) or existing.intersection(ids): raise ValueError("duplicate message id")
        entry = self.adapter.locator.entry(chat_id)[1]
        data = path.read_bytes()
        if data and not data.endswith(b'\n'): raise UnknownFormat()
        from .reader import is_prompt
        prompt = next((r for r in reversed(chain) if is_prompt(r)), {})
        prompt_index = (prompt.get("turnPosition") or {}).get("promptIndex", 0)
        appended = native_records(turns, entry["cliSessionId"], entry["cwd"], chain[-1]["uuid"] if chain else None,
            prompt_index=prompt_index, template=prompt)
        after = dict(receipt.data["before"]); after[str(path)] = encode(data + serialize(appended))
        return self._write(receipt, after, turns)
    def cut(self, chat_id, keep_through_local_id):
        """Retain a turn prefix with a durable saved copy for restoration."""
        self._check(chat_id)
        receipt = self._begin(chat_id, "cut")
        path = self.adapter.locator.session_path(chat_id)
        turns = self.adapter.reader.read(chat_id)
        if not keep_through_local_id:
            after = dict(receipt.data["before"]); after[str(path)] = encode(b'')
            return self._write(receipt, after, ())
        index = next((i for i, t in enumerate(turns) if keep_through_local_id in (t.id, *(m.id for m in t.messages))), None)
        if index is None: raise KeyError(keep_through_local_id)
        last_id = (turns[index].messages[-1].id if turns[index].messages else turns[index].id).split('#')[0]
        lines = path.read_bytes().splitlines(keepends=True)
        end = next((i for i, line in enumerate(lines) if json.loads(line).get("uuid") == last_id), None)
        if end is None: raise KeyError(last_id)
        after = dict(receipt.data["before"]); after[str(path)] = encode(b''.join(lines[:end + 1]))
        return self._write(receipt, after, turns[:index + 1])
    def restore(self, receipt):
        """Restore exact saved bytes under a fresh durable reversible intent."""
        if receipt.tool != self.adapter.name or receipt.kind != 'cut':
            raise NotAvailable()
        self._check(receipt.chat_id)
        intent = self.adapter.locator.inside(receipt.data['intent'])
        if not intent.exists(): raise ChatChanged()
        manifest = json.loads(intent.read_text())
        if (manifest.get('token') != receipt.data['token'] or
                self._snapshot([Path(p) for p in manifest['after']]) != manifest['after']):
            raise ChatChanged()
        fresh = self._begin(receipt.chat_id, 'restore')
        return self._write(fresh, manifest['before'])

    def place(self, chat_id, turns, before_local_id):
        """Refuse placement because the native tool cannot insert turns safely."""
        self._check(chat_id, "place")
    def rename(self, chat_id, name):
        """Change the sidebar title only while the desktop app is closed."""
        self._check(chat_id, "rename")
        receipt = self._begin(chat_id, "rename")
        path, entry = self.adapter.locator.entry(chat_id)
        entry["title"] = name
        after = dict(receipt.data["before"]); after[str(path)] = encode(json.dumps(entry).encode())
        return self._write(receipt, after)
    def take_back(self, receipt):
        """Restore an owned write without overwriting later outside changes."""
        if receipt.tool != "claude": raise ValueError("wrong adapter")
        intent = self.adapter.locator.inside(receipt.data["intent"])
        if not intent.exists():
            if receipt.data.get("prepared"): return
            raise ValueError("receipt consumed")
        manifest = json.loads(intent.read_text())
        if manifest.get("token") != receipt.data["token"]: raise ValueError("receipt mismatch")
        # Exact manifest ownership allows recovery even if a newly created
        # sidebar/file pair was only partly published. Never bypass live holders.
        try:
            c = self.adapter.state.condition(receipt.chat_id)
        except (KeyError, ValueError):
            c = None
        if c is not None and c.replying: raise ChatReplying()
        if c is not None and c.open: raise ChatHeld()
        if receipt.kind == "rename" and self.adapter.process.running(): raise AppMustBeClosed()
        # Registry ownership survives a partially published/missing sidebar.
        for entry in self.adapter.state.registry():
            if entry.get("sessionId") == receipt.data["session_id"]:
                if entry.get("status") == "busy": raise ChatReplying()
                raise ChatHeld()
        before, after = manifest["before"], manifest["after"]
        for path in before:
            path = self.adapter.locator.inside(path)
            current = encode(path.read_bytes()) if path.exists() else None
            if current not in (before[str(path)], after[str(path)]): raise ChatChanged()
        for path, encoded in before.items():
            path = self.adapter.locator.inside(path)
            if encoded is None: path.unlink(missing_ok=True)
            else:
                fd, temporary = tempfile.mkstemp(prefix=".baton-restore-", dir=path.parent)
                try:
                    with os.fdopen(fd, 'wb') as fh:
                        fh.write(decode(encoded)); fh.flush(); os.fsync(fh.fileno())
                    os.replace(temporary, path)
                finally: Path(temporary).unlink(missing_ok=True)
        for parent in {Path(p).parent for p in before}:
            if not parent.exists():
                continue
            directory = os.open(parent, os.O_RDONLY)
            try: os.fsync(directory)
            finally: os.close(directory)
        intent.unlink()
        directory = os.open(intent.parent, os.O_RDONLY)
        try: os.fsync(directory)
        finally: os.close(directory)
