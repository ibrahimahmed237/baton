"""Settable chat facts, writes and app behavior without external I/O."""
from __future__ import annotations

import json

from copy import deepcopy
from dataclasses import asdict, replace
from typing import Any, Sequence
from uuid import uuid4

from ...domain.capabilities import Capabilities, HookNeed, Visibility, WriteWindow
from ...domain.conditions import SideCondition
from ...domain.errors import (AppMustBeClosed, ChatChanged, ChatHeld, ChatReplying,
                              NotAvailable, UnknownFormat)
from ...domain.model import Message, Turn
from ...ports.tool import ChatRef, FormatCheck, SetupFinding, Usage, WriteReceipt, WriteResult
from .facts import OPENCODE_LIKE


class FakeAdapter:
    """Build chats and set the facts observed by each small interface."""
    def __init__(self, facts: Capabilities = OPENCODE_LIKE, name: str = "fake"):
        self.name = name
        self.facts = facts
        self.chats: dict[str, list[Turn]] = {}
        self.refs: dict[str, ChatRef] = {}
        self.conditions: dict[str, SideCondition] = {}
        self.inserted_text: dict[str, list[Message]] = {}
        self.visible: dict[str, list[Turn]] = {}
        self.app_running = False
        self.format = FormatCheck(True, facts.checked_versions[0])
        self.usage_values: dict[str, Usage] = {}
        self.changed_files: dict[str, list[str]] = {}
        self.locator = FakeLocator(self)
        self.reader = FakeReader(self)
        self.state = FakeState(self)
        self.writer = FakeWriter(self)
        self.hooks = FakeHooks(self)
        self.runner = FakeBackgroundRunner()
        self.app = FakeAppControl(self)

    def build_chat(self, turns: Sequence[Turn], name: str = "chat", folder: str = "") -> str:
        """Seed a fixture independently of write restrictions."""
        chat_id = uuid4().hex
        self.chats[chat_id] = deepcopy(list(turns))
        self.refs[chat_id] = ChatRef(chat_id, name, folder, turns[-1].ended_at if turns else "")
        self.conditions[chat_id] = SideCondition()
        self.inserted_text[chat_id] = []
        self.visible[chat_id] = deepcopy(list(turns))
        return chat_id

    def set_condition(self, chat_id: str, **values: bool) -> None:
        """Change chat conditions and optionally the app's running state."""
        if "app_running" in values:
            self.app_running = values.pop("app_running")
        before = self.state.condition(chat_id)
        self.conditions[chat_id] = replace(before, **values)
        if values.get("open") and not before.open and self.facts.added_turn_visible == Visibility.ON_REOPEN_CHAT:
            self.visible[chat_id] = deepcopy(self.chats[chat_id])

    def visible_turns(self, chat_id: str) -> list[Turn] | None:
        """Observe the fake UI separately from stored turns."""
        return deepcopy(self.visible.get(chat_id))

    def set_format(self, known: bool, version: str) -> None:
        """Set the observed format check."""
        self.format = FormatCheck(known, version)

    def insert_text(self, chat_id: str, message: Message) -> None:
        """Seed inserted context that does not begin a real turn."""
        self.inserted_text[chat_id].append(deepcopy(message))


class FakeLocator:
    """Locate seeded and written chats."""
    def __init__(self, adapter: FakeAdapter):
        self.adapter = adapter

    def chats(self) -> list[ChatRef]:
        """List existing chats."""
        return [ref for ref in self.adapter.refs.values() if self.adapter.state.condition(ref.id).exists]

    def resolve(self, chat_id: str) -> ChatRef:
        """Find a chat by its stable id."""
        if not self.adapter.state.condition(chat_id).exists:
            raise KeyError(chat_id)
        return self.adapter.refs[chat_id]

    def name(self, chat_id: str) -> str:
        """Return the current chat name."""
        return self.resolve(chat_id).name


class FakeReader:
    """Read stored turns without turning inserted text into prompts."""
    def __init__(self, adapter: FakeAdapter):
        self.adapter = adapter

    def read(self, chat_id: str) -> list[Turn]:
        """Return independent copies of a chat's turns."""
        self.adapter.locator.resolve(chat_id)
        return deepcopy(self.adapter.chats[chat_id])

    def usage(self, chat_id: str) -> Usage:
        """Report configured usage, limited to what the facts expose."""
        self.adapter.locator.resolve(chat_id)
        usage = self.adapter.usage_values.get(chat_id, Usage(0, 100000, False, None))
        return replace(usage, size=usage.size if self.adapter.facts.context_size_known else None,
                       limit_resets_at=usage.limit_resets_at if self.adapter.facts.limit_has_reset_time else None)

    def files_changed(self, turn: Turn) -> list[str]:
        """Return the configured files changed by a turn."""
        return list(self.adapter.changed_files.get(turn.id, []))


class FakeState:
    """Report settable conditions and format support."""
    def __init__(self, adapter: FakeAdapter):
        self.adapter = adapter

    def condition(self, chat_id: str) -> SideCondition:
        """Report chat conditions with the app's current running state."""
        condition = self.adapter.conditions.get(chat_id, SideCondition(exists=False))
        return replace(condition, app_running=self.adapter.app_running)

    def format_version(self) -> FormatCheck:
        """Require both a known format and membership in checked versions."""
        check = self.adapter.format
        return replace(check, known=check.known and check.version in self.adapter.facts.checked_versions)


class FakeWriter:
    """Write only when the configured facts allow it, with exact undo receipts."""
    def __init__(self, adapter: FakeAdapter):
        self.adapter = adapter
        self.writes: dict[str, tuple[WriteReceipt, Any]] = {}
        self._prepared_create: str | None = None
        self._consumed: set[str] = set()

    def prepare(self, chat_id: str | None, kind: str) -> WriteReceipt:
        """Capture JSON rollback data without mutating any chat."""
        if kind not in {"create", "add", "place", "cut", "rename"}:
            raise ValueError(kind)
        if (chat_id is None) != (kind == "create"):
            raise ValueError(kind)
        if chat_id is None:
            chat_id = uuid4().hex
            self._prepared_create = chat_id
            data = {"prepared": True, "exists": False}
        else:
            self.adapter.locator.resolve(chat_id)
            data = {"prepared": True, "exists": True,
                    "turns": [asdict(t) for t in self.adapter.chats[chat_id]],
                    "ref": asdict(self.adapter.refs[chat_id]),
                    "inserted": [asdict(m) for m in self.adapter.inserted_text[chat_id]],
                    "visible": None if chat_id not in self.adapter.visible else
                        [asdict(t) for t in self.adapter.visible[chat_id]]}
        return WriteReceipt(self.adapter.name, chat_id, kind, data)

    @staticmethod
    def _turns(values):
        return [Turn(Message(**v["prompt"]), tuple(Message(**m) for m in v["messages"]))
                for v in values]

    def _restore_prepared(self, receipt: WriteReceipt) -> None:
        if receipt.tool != self.adapter.name:
            raise ValueError("receipt tool mismatch")
        chat_id, data = receipt.chat_id, receipt.data
        if not data["exists"]:
            if self.adapter.state.condition(chat_id).exists:
                self._check(chat_id)
            for values in (self.adapter.chats, self.adapter.refs, self.adapter.conditions,
                           self.adapter.inserted_text, self.adapter.visible):
                values.pop(chat_id, None)
            if self._prepared_create == chat_id:
                self._prepared_create = None
            return
        self._check(chat_id)
        self.adapter.chats[chat_id] = self._turns(data["turns"])
        self.adapter.refs[chat_id] = ChatRef(**data["ref"])
        self.adapter.inserted_text[chat_id] = [Message(**m) for m in data["inserted"]]
        if data["visible"] is None:
            self.adapter.visible.pop(chat_id, None)
        else:
            self.adapter.visible[chat_id] = self._turns(data["visible"])

    def _check(self, chat_id: str | None = None, capability: str = "") -> None:
        if not self.adapter.state.format_version().known:
            raise UnknownFormat()
        if capability and not getattr(self.adapter.facts, capability):
            raise NotAvailable()
        window = self.adapter.facts.write_window
        if window == WriteWindow.APP_CLOSED and self.adapter.app_running:
            raise AppMustBeClosed()
        if chat_id is not None:
            self.adapter.locator.resolve(chat_id)
            condition = self.adapter.state.condition(chat_id)
            if condition.replying and window != WriteWindow.ANY_TIME:
                raise ChatReplying()
            if window in (WriteWindow.CLOSED_OR_RELEASED, WriteWindow.NOT_HELD) and condition.open:
                raise ChatHeld()

    def _result(self, chat_id: str, kind: str, turns: Sequence[Turn], undo: Any) -> WriteResult:
        if kind != "create" and self.adapter.facts.added_turn_visible == Visibility.AT_ONCE:
            self.adapter.visible[chat_id] = deepcopy(self.adapter.chats[chat_id])
        if kind == "create":
            saved = {"turns": [asdict(t) for t in undo[0]], "ref": asdict(undo[1])}
        elif kind == "cut":
            saved = {"index": undo[0], "removed": [asdict(t) for t in undo[1]]}
        else:
            saved = list(undo)
        receipt = WriteReceipt(self.adapter.name, chat_id, kind,
                               {"write_id": uuid4().hex, "undo": saved})
        self.writes[receipt.data["write_id"]] = (receipt, undo)
        return WriteResult(chat_id, tuple(turn.id for turn in turns), receipt)

    def create(self, turns: Sequence[Turn], name: str, folder: str) -> WriteResult:
        """Create a chat with the supplied turns."""
        self._check()
        if len({turn.id for turn in turns}) != len(turns):
            raise ValueError("turn ids must be unique within a chat")
        chat_id = self.adapter.build_chat(turns, name, folder)
        if self._prepared_create is not None:
            reserved, self._prepared_create = self._prepared_create, None
            for values in (self.adapter.chats, self.adapter.refs, self.adapter.conditions,
                           self.adapter.inserted_text, self.adapter.visible):
                values[reserved] = values.pop(chat_id)
            self.adapter.refs[reserved] = replace(self.adapter.refs[reserved], id=reserved)
            chat_id = reserved
        if self.adapter.facts.new_chat_visible != Visibility.AT_ONCE:
            del self.adapter.visible[chat_id]
        return self._result(chat_id, "create", turns,
                            (deepcopy(list(turns)), self.adapter.refs[chat_id]))

    def _insert(self, chat_id: str, turns: Sequence[Turn], index: int, kind: str) -> WriteResult:
        ids = [turn.id for turn in self.adapter.chats[chat_id]] + [turn.id for turn in turns]
        if len(ids) != len(set(ids)):
            raise ValueError("turn ids must be unique within a chat")
        self.adapter.chats[chat_id][index:index] = deepcopy(list(turns))
        return self._result(chat_id, kind, turns, tuple(turn.id for turn in turns))

    def add(self, chat_id: str, turns: Sequence[Turn]) -> WriteResult:
        """Add turns at the end of a chat."""
        self._check(chat_id)
        return self._insert(chat_id, turns, len(self.adapter.chats[chat_id]), "add")

    def place(self, chat_id: str, turns: Sequence[Turn], before_local_id: str) -> WriteResult:
        """Place turns before an existing turn."""
        self._check(chat_id, "can_place")
        return self._insert(chat_id, turns, self._index(chat_id, before_local_id), "place")

    def _index(self, chat_id: str, local_id: str) -> int:
        for index, turn in enumerate(self.adapter.chats[chat_id]):
            if local_id in (turn.id, *(message.id for message in turn.messages)):
                return index
        raise KeyError(local_id)

    def cut(self, chat_id: str, keep_through_local_id: str) -> WriteResult:
        """Keep a chat through one turn, saving the removed turns for undo."""
        self._check(chat_id, "can_cut")
        index = self._index(chat_id, keep_through_local_id) + 1
        removed = self.adapter.chats[chat_id][index:]
        del self.adapter.chats[chat_id][index:]
        return self._result(chat_id, "cut", self.adapter.chats[chat_id], (index, removed))

    def rename(self, chat_id: str, name: str) -> WriteResult:
        """Change a chat's name."""
        self._check(chat_id)
        before = self.adapter.refs[chat_id].name
        self.adapter.refs[chat_id] = replace(self.adapter.refs[chat_id], name=name)
        return self._result(chat_id, "rename", (), (before, name))

    def take_back(self, receipt: WriteReceipt) -> None:
        """Undo one write, preserving unrelated later writes."""
        if receipt.data.get("prepared"):
            self._restore_prepared(receipt)
            return
        key = receipt.data.get("write_id", "")
        if (receipt.tool != self.adapter.name or key in self._consumed or
                not self.adapter.state.condition(receipt.chat_id).exists):
            raise ValueError("receipt does not belong to an outstanding write")
        if key in self.writes:
            if json.dumps(asdict(self.writes[key][0]), sort_keys=True) != json.dumps(asdict(receipt), sort_keys=True):
                raise ValueError("receipt mismatch")
            undo = self.writes[key][1]
        elif "undo" in receipt.data:
            saved = receipt.data["undo"]
            if receipt.kind == "create":
                undo = (self._turns(saved["turns"]), ChatRef(**saved["ref"]))
            elif receipt.kind == "cut":
                undo = (saved["index"], self._turns(saved["removed"]))
            else:
                undo = saved
        else:
            raise ValueError("receipt does not belong to an outstanding write")
        self._check(receipt.chat_id)
        chat_id = receipt.chat_id
        turns = self.adapter.chats[chat_id]
        if receipt.kind == "create":
            original_turns, original_ref = undo
            if turns != original_turns or self.adapter.refs[chat_id] != original_ref:
                raise ChatChanged()
            for values in (self.adapter.chats, self.adapter.refs, self.adapter.conditions,
                           self.adapter.inserted_text):
                del values[chat_id]
        elif receipt.kind in ("add", "place"):
            turns[:] = [turn for turn in turns if turn.id not in undo]
        elif receipt.kind == "cut":
            index, removed = undo
            if {turn.id for turn in turns} & {turn.id for turn in removed}:
                raise ChatChanged()
            turns[index:index] = removed
        elif receipt.kind == "rename":
            before, written = undo
            if self.adapter.refs[chat_id].name != written:
                raise ChatChanged()
            self.adapter.refs[chat_id] = replace(self.adapter.refs[chat_id], name=before)
        if chat_id not in self.adapter.chats:
            self.adapter.visible.pop(chat_id, None)
        elif self.adapter.facts.added_turn_visible == Visibility.AT_ONCE:
            self.adapter.visible[chat_id] = deepcopy(turns)
        self.writes.pop(key, None)
        self._consumed.add(key)


class FakeHooks:
    """Represent installation and first-use approval without real hooks."""
    def __init__(self, adapter: FakeAdapter):
        self.adapter = adapter
        self.installed = True
        self.ready = adapter.facts.hooks_need == HookNeed.NONE

    def install(self) -> SetupFinding:
        """Install hooks and report any remaining first-use step."""
        self.installed = True
        return self.check()

    def uninstall(self) -> None:
        """Remove the fake hooks."""
        self.installed = False

    def check(self) -> SetupFinding:
        """Report whether installation and approval are complete."""
        ok = self.installed and (self.ready or self.adapter.facts.hooks_need == HookNeed.NONE)
        return SetupFinding("hooks", ok, "" if ok else "setup.hooks", {"need": self.adapter.facts.hooks_need.value})

    def attach_reply(self, text: str, notice: str | None) -> str:
        """Return attached context followed by an optional notice."""
        return text if notice is None else text + "\n" + notice

    def turn_end_reply(self) -> str:
        """Return an empty structured hook reply."""
        return "{}"


class FakeBackgroundRunner:
    """Return canned text or raise a configured error."""
    def __init__(self, text: str = "", error: Exception | None = None):
        self.text = text
        self.error = error
        self.finding = SetupFinding("runner", True, "", {})
        self.calls: list[tuple[str, str, bool]] = []

    def available(self) -> SetupFinding:
        """Return the configured availability finding."""
        return self.finding

    def ask(self, prompt: str, folder: str, read_only: bool = True) -> str:
        """Record the request and return text or raise."""
        self.calls.append((prompt, folder, read_only))
        if not self.finding.ok:
            raise NotAvailable()
        if self.error is not None:
            raise self.error
        return self.text


class FakeAppControl:
    """Record app calls and update the fake's conditions."""
    def __init__(self, adapter: FakeAdapter):
        self.adapter = adapter
        self.calls: list[tuple[Any, ...]] = []

    def running(self) -> bool:
        """Record a running check and report the current state."""
        self.calls.append(("running",))
        return self.adapter.app_running

    def close(self) -> None:
        """Close an idle app without interrupting a reply."""
        self.calls.append(("close",))
        if any(condition.replying for condition in self.adapter.conditions.values() if condition.exists):
            raise ChatReplying()
        self.adapter.app_running = False
        for chat_id in self.adapter.conditions:
            self.adapter.set_condition(chat_id, open=False)

    def open(self, chat_id: str | None, folder: str | None) -> None:
        """Open the app, selecting a chat only when supported."""
        self.calls.append(("open", chat_id, folder))
        was_running = self.adapter.app_running
        self.adapter.app_running = True
        if not was_running:
            self.adapter.visible = deepcopy(self.adapter.chats)
        if chat_id is not None and self.adapter.facts.opens_at_chat:
            self.adapter.locator.resolve(chat_id)
            self.adapter.set_condition(chat_id, open=True)

    def release(self, chat_id: str) -> None:
        """Release one idle chat when supported."""
        self.calls.append(("release", chat_id))
        if not self.adapter.facts.can_release_chat:
            raise NotAvailable()
        condition = self.adapter.state.condition(chat_id)
        if not condition.exists:
            raise KeyError(chat_id)
        if condition.replying:
            raise ChatReplying()
        self.adapter.set_condition(chat_id, open=False)
