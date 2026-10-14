"""Transactional OpenCode writes with durable pre-write row receipts."""
import hashlib
import json
import os
import re
from uuid import uuid4

from ...domain.errors import ChatChanged, ChatReplying, NotAvailable, UnknownFormat
from ...ports.tool import WriteReceipt, WriteResult
from .records import milliseconds, new_id, pack, serialize_turns, snapshot, unpack

KINDS = {"create", "add", "place", "cut", "rename", "restore"}


class OpenCodeWriter:
    """Mutate only scoped chats and recover exact native rows without clobbering edits."""

    def __init__(self, adapter):
        self.adapter = adapter
        self.prepared = None
        self.created = set()
        self.scope_key = hashlib.sha256(json.dumps(sorted(adapter.allowed_chat_ids)).encode()).hexdigest()[:24]
        folder = self.adapter.receipt_locator.inside(adapter.rollback_root)
        if folder.exists():
            info = folder.stat()
            if info.st_uid != os.getuid() or info.st_mode & 0o777 != 0o700:
                raise NotAvailable()
            for path in folder.glob(self.scope_key + "-*.json"):
                manifest = self._load_path(path)
                if manifest["kind"] == "create":
                    self.created.add(manifest["chat_id"])

    def _require(self, chat_id):
        if chat_id not in self.adapter.allowed_chat_ids | self.created:
            raise NotAvailable()

    def _check(self, chat_id=None, kind=None):
        if not self.adapter.state.format_version().known:
            raise UnknownFormat()
        if chat_id is not None:
            self._require(chat_id)
            self.adapter.locator.row(chat_id)
            if kind != "add" and self.adapter.state.condition(chat_id).replying:
                raise ChatReplying()
        elif not self.adapter.allowed_chat_ids:
            raise NotAvailable()

    def _intent(self, token):
        if not re.fullmatch(r"[a-f0-9]{32}", token):
            raise NotAvailable()
        return self.adapter.receipt_locator.inside(self.adapter.rollback_root / (self.scope_key + "-" + token + ".json"))

    def _load_path(self, path):
        path = self.adapter.receipt_locator.inside(path)
        info = path.stat()
        if info.st_uid != os.getuid() or info.st_mode & 0o777 != 0o600 or info.st_nlink != 1:
            raise NotAvailable()
        data = json.loads(path.read_text())
        if (data.get("scope") != sorted(self.adapter.allowed_chat_ids) or data.get("tool") != self.adapter.name
                or path != self._intent(data["token"])):
            raise NotAvailable()
        return data

    def _save(self, data):
        path = self._intent(data["token"])
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if path.parent.stat().st_mode & 0o777 != 0o700:
            raise NotAvailable()
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream)
            stream.flush()
            os.fsync(stream.fileno())
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def prepare(self, chat_id, kind):
        """Capture an immutable row snapshot or reserve the ID of a future chat."""
        if kind not in KINDS or (chat_id is None) != (kind == "create"):
            raise ValueError(kind)
        self._check(chat_id, kind)
        if chat_id is None:
            chat_id = new_id("ses", self._now(), descending=True)
            before = {"session": [], "message": [], "part": []}
        else:
            with self.adapter.locator.connect() as db:
                db.execute("BEGIN")
                before = snapshot(db, chat_id)
        receipt = WriteReceipt(self.adapter.name, chat_id, kind,
                               {"token": uuid4().hex, "before": before, "prepared": True})
        self.prepared = receipt
        return receipt

    def _begin(self, chat_id, kind):
        receipt = self.prepared
        if receipt is None or receipt.kind != kind or (chat_id is not None and receipt.chat_id != chat_id):
            receipt = self.prepare(chat_id, kind)
        self.prepared = None
        return receipt

    def _now(self):
        return int(self.adapter.now().timestamp() * 1000)

    @staticmethod
    def _replace(db, before, after):
        """Apply a row diff, leaving unchanged rows and unrelated chats untouched."""
        before, after = unpack(before), unpack(after)
        for table in ("part", "message", "session"):
            gone = {r["id"] for r in before[table]} - {r["id"] for r in after[table]}
            for ident in gone:
                db.execute('DELETE FROM "%s" WHERE id=?' % table, (ident,))
        for table in ("session", "message", "part"):
            old = {r["id"]: r for r in before[table]}
            for row in after[table]:
                if row == old.get(row["id"]):
                    continue
                columns = list(row)
                if row["id"] in old:
                    db.execute('UPDATE "%s" SET %s WHERE id=?' %
                               (table, ",".join('"%s"=?' % c.replace('"', '""') for c in columns)),
                               [row[c] for c in columns] + [row["id"]])
                else:
                    db.execute('INSERT INTO "%s" (%s) VALUES (%s)' %
                               (table, ",".join('"%s"' % c.replace('"', '""') for c in columns), ",".join("?" for _ in columns)), list(row.values()))

    @staticmethod
    def _project_rows(db, ident):
        return pack({"project": [dict(r) for r in db.execute("SELECT * FROM project WHERE id=?", (ident,))],
                     "project_directory": [dict(r) for r in db.execute("SELECT * FROM project_directory WHERE project_id=? ORDER BY directory", (ident,))]})

    def _write(self, receipt, after, turns=(), project=None):
        before = receipt.data["before"]
        manifest = {"tool": self.adapter.name, "scope": sorted(self.adapter.allowed_chat_ids),
                    "token": receipt.data["token"], "chat_id": receipt.chat_id, "kind": receipt.kind,
                    "before": before, "after": after, "project": project}
        with self.adapter.locator.connect(write=True) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                if not self.adapter.state.shape_known(db):
                    raise UnknownFormat()
                if receipt.kind not in ("create", "add") and self.adapter.state.condition(receipt.chat_id).replying:
                    raise ChatReplying()
                # Compare full session AND child rows after obtaining SQLite's writer lock.
                if snapshot(db, receipt.chat_id) != before:
                    raise ChatChanged()
                if project and db.execute("SELECT 1 FROM project WHERE id=?", (project["id"],)).fetchone():
                    raise ChatChanged()
                if project:
                    manifest["project_after"] = pack({
                        "project": [self._with_defaults(db, "project", dict(id=project["id"], worktree=project["folder"],
                            vcs="git", time_created=project["at"], time_updated=project["at"], sandboxes="[]"))],
                        "project_directory": [self._with_defaults(db, "project_directory", dict(project_id=project["id"],
                            directory=project["folder"], time_created=project["at"]))]})
                self._save(manifest)
                if project:
                    db.execute("INSERT INTO project(id,worktree,vcs,time_created,time_updated,sandboxes) VALUES(?,?,?,?,?,?)",
                               (project["id"], project["folder"], "git", project["at"], project["at"], "[]"))
                    db.execute("INSERT INTO project_directory(project_id,directory,time_created) VALUES(?,?,?)",
                               (project["id"], project["folder"], project["at"]))
                self._replace(db, before, after)
                # Defaults and added nullable columns must be part of exact rollback comparisons.
                actual = snapshot(db, receipt.chat_id)
                if actual != after:
                    raise UnknownFormat()
                db.commit()
            except BaseException:
                db.rollback()
                raise
        if receipt.kind == "create":
            self.created.add(receipt.chat_id)
        post = WriteReceipt(self.adapter.name, receipt.chat_id, receipt.kind,
                            {**receipt.data, "prepared": False, "after": after})
        return WriteResult(receipt.chat_id, tuple(t.id for t in turns), post)

    @staticmethod
    def _with_defaults(db, table, row):
        # Projected rows include defaults, so the fsynced intent knows the exact
        # post-write rows before a single native row is changed.
        for column in db.execute('PRAGMA table_info("%s")' % table):
            if column[1] not in row:
                row[column[1]] = db.execute("SELECT " + column[4]).fetchone()[0] if column[4] is not None else None
        return row

    def create(self, turns, name, folder):
        """Create a session in its first-commit project in one transaction."""
        self._check()
        ids = [m.id for t in turns for m in (t.prompt, *t.messages)]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate_message")
        receipt = self._begin(None, "create")
        now = self._now()
        project_id = self.adapter.project_for_folder(folder)
        if not project_id:
            raise NotAvailable()
        with self.adapter.locator.connect() as db:
            existing = db.execute("SELECT * FROM project WHERE id=?", (project_id,)).fetchone()
            model = self.adapter.model
            if not model:
                for ident in sorted(self.adapter.allowed_chat_ids | self.created):
                    template = snapshot(db, ident)
                    if template["session"]:
                        try:
                            model = self._model(template)
                            break
                        except NotAvailable:
                            continue
            if not model:
                raise NotAvailable()
            row = dict(id=receipt.chat_id, project_id=project_id, parent_id=None, slug="baton-" + receipt.chat_id,
                       directory=folder, title=name, version="local", time_created=now, time_updated=now)
            row = self._with_defaults(db, "session", row)
            start = milliseconds(turns[0].started_at, now) - 1 if turns else now - 1
            messages, parts, end = serialize_turns(turns, receipt.chat_id, folder, model, start, now)
            row["time_updated"] = max(now, end)
            after = pack({"session": [row], "message": [self._with_defaults(db, "message", r) for r in messages],
                          "part": [self._with_defaults(db, "part", r) for r in parts]})
        project = None if existing else {"id": project_id, "folder": folder, "at": now}
        return self._write(receipt, after, turns, project)

    def _model(self, before):
        for row in reversed(sorted(unpack(before)["message"], key=lambda r: (r["time_created"], r["id"]))):
            data = json.loads(row["data"])
            if data.get("model"):
                return data["model"]
            if data.get("providerID") and data.get("modelID"):
                return {"providerID": data["providerID"], "modelID": data["modelID"]}
        if self.adapter.model:
            return self.adapter.model
        raise NotAvailable()

    def _insert(self, chat_id, turns, kind, target=None):
        self._check(chat_id, kind)
        receipt = self._begin(chat_id, kind)
        after = unpack(receipt.data["before"])
        existing = self.adapter.reader.read(chat_id)
        ids = [m.id for t in turns for m in (t.prompt, *t.messages)]
        existing_ids = {m.id for t in existing for m in (t.prompt, *t.messages)}
        if len(ids) != len(set(ids)) or set(ids) & existing_ids:
            raise ValueError("duplicate_turn")
        row = after["session"][0]
        ordered = sorted(after["message"], key=lambda r: (r["time_created"], r["id"]))
        now = self._now()
        if target is None:
            timestamps = [r["time_created"] for r in ordered] + [p["time_created"] for p in after["part"]]
            start = max(timestamps) if timestamps else milliseconds(turns[0].started_at, now) - 1 if turns else now - 1
        else:
            boundary = next((r for r in ordered if r["id"] == target or json.loads(r["data"]).get("baton", {}).get("id") == target), None)
            if boundary is None or json.loads(boundary["data"]).get("role") != "user":
                raise KeyError(target)
            earlier = [r["time_created"] for r in ordered if r["time_created"] < boundary["time_created"]]
            earlier += [p["time_created"] for p in after["part"] if p["time_created"] < boundary["time_created"]]
            slots = sum(1 + len(t.messages) for t in turns)
            start = max(earlier) if earlier else boundary["time_created"] - slots - 1
        messages, parts, end = serialize_turns(turns, chat_id, row["directory"], self._model(receipt.data["before"]), start, now, honor_times=target is None)
        if target is not None and end >= boundary["time_created"]:
            # Make room without losing content; exact prior times are saved in the receipt.
            boundary_at = boundary["time_created"]
            shift = end - boundary_at + 1
            for r in (*after["message"], *after["part"]):
                if r["time_created"] >= boundary_at:
                    data = json.loads(r["data"])
                    data.setdefault("batonRowTime", r["time_created"])
                    data.setdefault("batonRowUpdated", r["time_updated"])
                    r["data"] = json.dumps(data)
                    r["time_created"] += shift
                    r["time_updated"] += shift
        with self.adapter.locator.connect() as db:
            after["message"].extend(self._with_defaults(db, "message", r) for r in messages)
            after["part"].extend(self._with_defaults(db, "part", r) for r in parts)
        after["message"].sort(key=lambda r: r["id"])
        after["part"].sort(key=lambda r: r["id"])
        row["time_updated"] = max(now, row["time_updated"] + 1, end)
        return self._write(receipt, pack(after), turns)

    def add(self, chat_id, turns):
        """Append after the latest user turn, including during a native reply."""
        return self._insert(chat_id, turns, "add")

    def place(self, chat_id, turns, before_local_id):
        """Place real rows before a target user message."""
        return self._insert(chat_id, turns, "place", before_local_id)

    def cut(self, chat_id, keep_through_local_id):
        """Delete the turn suffix while saving all removed rows exactly."""
        self._check(chat_id)
        receipt = self._begin(chat_id, "cut")
        after = unpack(receipt.data["before"])
        ordered = sorted(after["message"], key=lambda r: (r["time_created"], r["id"]))
        if keep_through_local_id:
            users = [r for r in ordered if json.loads(r["data"]).get("role") == "user"]
            index = next((i for i, r in enumerate(users) if r["id"] == keep_through_local_id or
                          json.loads(r["data"]).get("baton", {}).get("id") == keep_through_local_id), None)
            if index is None:
                raise KeyError(keep_through_local_id)
            end = users[index + 1]["time_created"] if index + 1 < len(users) else float("inf")
            kept_users = {r["id"] for r in users if r["time_created"] < end}
            kept = {r["id"] for r in ordered if r["id"] in kept_users or
                    json.loads(r["data"]).get("parentID") in kept_users}
        else:
            kept = set()
        after["message"] = [r for r in after["message"] if r["id"] in kept]
        after["part"] = [r for r in after["part"] if r["message_id"] in kept]
        after["session"][0]["time_updated"] = max(self._now(), after["session"][0]["time_updated"] + 1)
        return self._write(receipt, pack(after))

    def rename(self, chat_id, name):
        """Rename the sidebar row immediately, preserving the exact old title."""
        self._check(chat_id)
        receipt = self._begin(chat_id, "rename")
        after = unpack(receipt.data["before"])
        after["session"][0]["title"] = name
        after["session"][0]["time_updated"] = max(self._now(), after["session"][0]["time_updated"] + 1)
        return self._write(receipt, pack(after))

    def _manifest(self, receipt):
        if receipt.tool != self.adapter.name:
            raise NotAvailable()
        path = self._intent(receipt.data["token"])
        manifest = self._load_path(path)
        if (manifest["chat_id"], manifest["kind"]) != (receipt.chat_id, receipt.kind):
            raise NotAvailable()
        return manifest

    def restore(self, receipt):
        """Restore a saved cut through a fresh pre-write receipt."""
        if receipt.kind != "cut":
            raise NotAvailable()
        self._check(receipt.chat_id)
        manifest = self._manifest(receipt)
        fresh = self._begin(receipt.chat_id, "restore")
        if fresh.data["before"] != manifest["after"]:
            raise ChatChanged()
        return self._write(fresh, manifest["before"])

    @staticmethod
    def _streaming_take_back(manifest, current):
        """Undo an append while preserving only its pre-existing reply's progress.

        Baton rows must still match the receipt exactly. Only assistants that
        were unfinished before add, their continuation messages/parts, and
        session time_updated may have changed; unrelated edits still refuse.
        """
        if manifest["kind"] != "add":
            raise ChatChanged()
        before, after, live = (unpack(value) for value in
                               (manifest["before"], manifest["after"], current))
        streaming = {r["id"] for r in before["message"]
                     if json.loads(r["data"]).get("role") == "assistant"
                     and not json.loads(r["data"]).get("finish")
                     and not json.loads(r["data"]).get("batonWritten")}
        if not streaming or len(live["session"]) != 1:
            raise ChatChanged()
        parents = {json.loads(r["data"]).get("parentID") for r in before["message"] if r["id"] in streaming}
        old_messages = {r["id"] for r in after["message"]}
        for row in live["message"]:
            if row["id"] not in old_messages:
                native = json.loads(row["data"])
                if (native.get("role") != "assistant" or native.get("parentID") not in parents
                        or native.get("parentID") is None or native.get("batonWritten")):
                    raise ChatChanged()
                streaming.add(row["id"])
        session = dict(live["session"][0])
        session["time_updated"] = after["session"][0]["time_updated"]
        if session != after["session"][0]:
            raise ChatChanged()
        target = {"session": live["session"], "message": [], "part": []}
        for table in ("message", "part"):
            old = {r["id"]: r for r in before[table]}
            written = {r["id"]: r for r in after[table]}
            present = {r["id"]: r for r in live[table]}
            if not set(written) <= set(present):
                raise ChatChanged()
            for ident, row in present.items():
                owned = ident if table == "message" else row["message_id"]
                if ident not in old and ident in written:
                    if row != written[ident]:
                        raise ChatChanged()
                    continue
                if owned not in streaming and row != written.get(ident):
                    raise ChatChanged()
                if table == "message" and owned in streaming:
                    native = json.loads(row["data"])
                    prior = json.loads(old[ident]["data"]) if ident in old else native
                    if native.get("role") != "assistant" or native.get("parentID") != prior.get("parentID"):
                        raise ChatChanged()
                if ident in old:
                    fixed = dict(row)
                    fixed["data"] = old[ident]["data"]
                    fixed["time_updated"] = old[ident]["time_updated"]
                    if fixed != old[ident]:
                        raise ChatChanged()
                target[table].append(row)
        # Revert Baton's timestamp only if native streaming did not replace it.
        if live["session"][0]["time_updated"] == after["session"][0]["time_updated"]:
            target["session"][0]["time_updated"] = before["session"][0]["time_updated"]
        return pack(target)

    def take_back(self, receipt):
        """Undo exactly this write or refuse later outside changes."""
        if receipt.tool != self.adapter.name:
            raise NotAvailable()
        path = self._intent(receipt.data["token"])
        if not path.exists():
            if receipt.data.get("prepared"):
                return
            raise ChatChanged()
        manifest = self._manifest(receipt)
        self._require(receipt.chat_id) if receipt.kind != "create" else None
        with self.adapter.locator.connect(write=True) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                if not self.adapter.state.shape_known(db):
                    raise UnknownFormat()
                if self.adapter.state.condition(receipt.chat_id).replying:
                    raise ChatReplying()
                current = snapshot(db, receipt.chat_id)
                target = manifest["before"]
                if current not in (manifest["before"], manifest["after"]):
                    target = self._streaming_take_back(manifest, current)
                project = manifest["project"]
                if project:
                    other = db.execute("SELECT 1 FROM session WHERE project_id=? AND id<>?", (project["id"], receipt.chat_id)).fetchone()
                    if other:
                        raise ChatChanged()
                    if self._project_rows(db, project["id"]) not in (
                            {"project": [], "project_directory": []}, manifest["project_after"]):
                        raise ChatChanged()
                self._replace(db, current, target)
                if project:
                    db.execute("DELETE FROM project_directory WHERE project_id=?", (project["id"],))
                    db.execute("DELETE FROM project WHERE id=?", (project["id"],))
                db.commit()
            except BaseException:
                db.rollback()
                raise
        path.unlink()
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
