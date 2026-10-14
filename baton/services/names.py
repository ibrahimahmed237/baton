"""Follow native names and explicitly confirm reversible name changes."""
from dataclasses import asdict, dataclass
from copy import deepcopy

from ..domain.capabilities import WriteWindow
from ..domain.errors import AppMustBeClosed, ChatChanged, ChatReplying, NotAvailable, UnknownFormat, LinkPaused
from ..ports.clock import Clock
from ..ports.store import RecordStore
from .delivery_plan import ApplyStep
from .journal import Journal
from .noteformat import NoteRef
from .preview import PreviewBuilder


class PausedAction(LinkPaused):
    """A paused link must be resumed before this mutation."""
    note_id = 'action.paused'


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

    def _active(self, link_id):
        link = self.store.get_link(link_id)
        if link.removed_at:
            raise NotAvailable()
        if link.paused:
            raise PausedAction()

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
        self._active(link_id)
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
        self._active(plan.link_id)
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
                self._active(plan.link_id)
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

    def plan_action(self, link_id, name, tools=None):
        """Bind the rename and required close/write/reopen operations to one approval."""
        from hashlib import sha256
        import json
        from .relaunch import Relaunch
        renamed = self.plan_rename(link_id, name, tools)
        lifecycle = Relaunch(self.store, self.adapters, self.clock)
        relaunches = []
        for step in renamed.steps:
            if 'app_closed' in step.needs and self.adapters[step.side].app.running():
                single = self.preview.prepare(link_id, [step], self.store.get_link(link_id).chats)
                relaunches.append(lifecycle.plan_relaunch(step.side, rename=single))
        ident = 'p_' + sha256(json.dumps([renamed.plan_id, [p.plan_id for p in relaunches]]).encode()).hexdigest()
        return RenameAction(ident, link_id, renamed, tuple(relaunches))

    def action_steps(self, plan):
        """Expose every lifecycle step selected by this service."""
        lifecycle = {p.tool: p for p in plan.relaunches}
        return tuple(item for step in plan.rename.steps
                     for item in (lifecycle[step.side].steps if step.side in lifecycle else (step,)))

    def action_notes(self, plan):
        """Explain names and any app closure before confirmation."""
        return self.notes(plan.rename) + tuple(n for p in plan.relaunches for n in p.notes)

    def apply_action(self, plan):
        """Apply the reviewed names with service-owned lifecycle orchestration."""
        from .relaunch import Relaunch
        self._active(plan.link_id)
        names = {s.name for s in plan.rename.steps}
        if len(names) > 1:
            raise NotAvailable()
        name = next(iter(names), '')
        if plan.rename.steps:
            fresh = self.plan_action(plan.link_id, name, [s.side for s in plan.rename.steps])
            if fresh != plan:
                raise ChatChanged()
        elif self.preview.prepare(plan.link_id, (), self.store.get_link(plan.link_id).chats) != plan.rename:
            raise ChatChanged()
        if not plan.relaunches:
            result = self.apply(plan.rename)
            return RenameResult(plan.plan_id, result.applied, result.link_id, result.renamed, result.notes)
        notes = list(self.action_notes(plan))
        renamed = []
        lifecycle = Relaunch(self.store, self.adapters, self.clock)
        for step in plan.rename.steps:
            self._active(plan.link_id)
            if self.preview._snapshot(step.side, plan.rename.snapshots[step.side]['chat_id']) != plan.rename.snapshots[step.side]:
                raise ChatChanged()
            single = self.preview.prepare(plan.link_id, [step], self.store.get_link(plan.link_id).chats)
            if any(p.tool == step.side for p in plan.relaunches):
                result = lifecycle.apply(lifecycle.plan_relaunch(step.side, rename=single))
                notes.extend(result.notes)
                if not result.applied:
                    if renamed:
                        notes.append(NoteRef('rename.partial', {}))
                    return RenameResult(plan.plan_id, False, plan.link_id, tuple(renamed), tuple(notes))
            else:
                self.apply(single)
            renamed.append(step.side)
        return RenameResult(plan.plan_id, True, plan.link_id, tuple(renamed), tuple(notes))


@dataclass(frozen=True)
class RenameAction:
    """One approval for the exact rename and any required app lifecycle."""
    plan_id: str
    link_id: int
    rename: object
    relaunches: tuple
