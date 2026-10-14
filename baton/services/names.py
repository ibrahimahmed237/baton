"""Follow native names and explicitly confirm reversible name changes."""
from dataclasses import asdict, dataclass
from copy import deepcopy

from ..domain.capabilities import WriteWindow
from ..domain.errors import AppMustBeClosed, ChatChanged, ChatReplying, NotAvailable, UnknownFormat
from ..ports.clock import Clock
from ..ports.store import RecordStore
from .delivery_plan import ApplyStep
from .journal import Journal
from .noteformat import NoteRef
from .preview import PreviewBuilder


@dataclass(frozen=True)
class RenameResult:
    """The completed name changes and their visibility explanations."""
    plan_id: str
    applied: bool
    link_id: int
    renamed: tuple[str, ...]
    notes: tuple[NoteRef, ...]


class Names:
    """Read current names and confirm explicit journaled renames."""
    def __init__(self, store: RecordStore, adapters, clock: Clock):
        """Use injected store, adapters and timing ports."""
        self.store, self.adapters, self.clock = store, adapters, clock
        self.preview = PreviewBuilder(store, adapters)
        self.journal = Journal(store, adapters, clock)

    def names(self, link_id):
        """Read each linked chat name afresh and remember its reference."""
        link = self.store.get_link(link_id)
        result = {}
        for side, chat in link.chats.items():
            ref = self.adapters[side].locator.resolve(chat)
            self.store.remember_chat(side, ref.id, asdict(ref))
            result[side] = ref.name
        return result

    def plan_rename(self, link_id, name, tools=None):
        """Confirm selected names, current chats and visibility requirements."""
        link = self.store.get_link(link_id)
        if link.removed_at or not name.strip():
            raise NotAvailable()
        chosen = tuple(link.sides if tools is None else tools)
        if not chosen or len(set(chosen)) != len(chosen) or any(s not in link.sides for s in chosen):
            raise NotAvailable()
        steps = []
        for side in chosen:
            adapter = self.adapters[side]
            if adapter.locator.name(link.chat(side)) == name:
                continue
            # Rename's measured rules differ from turn visibility for held chats.
            window = adapter.facts.write_window
            needs = ('app_closed', 'relaunch_to_see') if window in (
                WriteWindow.APP_CLOSED, WriteWindow.CLOSED_OR_RELEASED) else (
                ('relaunch_to_see',) if window == WriteWindow.NOT_HELD else ())
            steps.append(ApplyStep(side, 'rename', needs=needs, name=name))
        return self.preview.prepare(link_id, steps, link.chats)

    def notes(self, plan):
        """Supply the per-side explanation for a rename preview."""
        return tuple(NoteRef('rename.closed' if 'app_closed' in s.needs else
                             'rename.relaunch' if s.needs else 'rename.at_once',
                             {'tool': s.side, 'name': s.name}) for s in plan.steps)

    def apply(self, plan):
        """Execute the approved plan after fresh state and record checks."""
        fresh = self.preview.prepare(plan.link_id, plan.steps,
                                     {s: snap['chat_id'] for s, snap in plan.snapshots.items()})
        if fresh != plan:
            raise ChatChanged()
        if self.store.journal_entries(pending=True):
            raise NotAvailable()
        # Check every side before the first mutation, including rename-only closure rules.
        for step in plan.steps:
            if step.action != 'rename':
                raise NotAvailable()
            adapter = self.adapters[step.side]
            chat = plan.snapshots[step.side]['chat_id']
            state = adapter.state.condition(chat)
            if not adapter.state.format_version().known or not state.format_known:
                raise UnknownFormat()
            if state.replying:
                raise ChatReplying()
            if 'app_closed' in step.needs and adapter.app.running():
                raise AppMustBeClosed()
        completed = []
        working = deepcopy(plan.snapshots)
        record = plan.record
        try:
            for step in plan.steps:
                if self.preview._record(plan.link_id) != record:
                    raise ChatChanged()
                for side, snapshot in working.items():
                    if self.preview._snapshot(side, snapshot['chat_id']) != snapshot:
                        raise ChatChanged()
                adapter = self.adapters[step.side]
                chat = plan.snapshots[step.side]['chat_id']
                before = adapter.reader.read(chat)
                entry = self.journal.begin(plan.link_id, step.side, chat, 'rename')
                completed.append(entry)
                result = adapter.writer.rename(chat, step.name)
                if ((result.chat_id, result.receipt.tool, result.receipt.chat_id, result.receipt.kind) !=
                        (chat, step.side, chat, 'rename') or adapter.locator.name(chat) != step.name or
                        adapter.reader.read(chat) != before or self.preview._record(plan.link_id) != record):
                    raise ChatChanged()
                self.store.complete_rename(entry, asdict(result.receipt), self.clock.now(),
                                           plan.link_id, step.side, plan.snapshots[step.side]['ref']['name'], step.name)
                working[step.side] = self.preview._snapshot(step.side, chat)
                record = self.preview._record(plan.link_id)
        except Exception:
            for entry in reversed(completed):
                self.journal.take_back(entry)
            raise
        self.names(plan.link_id)
        return RenameResult(plan.plan_id, True, plan.link_id,
                            tuple(step.side for step in plan.steps), self.notes(plan))
