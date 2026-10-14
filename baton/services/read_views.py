"""Recovery-free projections shared by commands and action-service previews."""
from __future__ import annotations

from dataclasses import asdict, replace
from difflib import SequenceMatcher
from itertools import combinations
from typing import Mapping

from ..domain.errors import BatonError, ChatChanged, ChatHeld, NotAvailable
from ..domain.capabilities import WriteWindow
from ..domain.link import KEPT_BACK, SKIPPED
from ..ports.tool import ChatRef
from . import planner, status
from .digest import DigestBuilder
from .mapping import content_key, for_target
from .noteformat import NoteRef
from .observations import canonical_sources, verified_source
from .refresh import ChatRefresh
from .usage import UsageService


def require_settled(store, *, link_id=None, chats=()):
    """Never interpret a pending native write as a new origin or recover it."""
    for entry in store.journal_entries(pending=True):
        if (link_id is not None and entry['link_id'] == link_id or (entry['tool'], entry['chat_id']) in chats
                or entry['action'] == 'create' and not entry['chat_id'] and any(s == entry['tool'] for s, _ in chats)):
            raise ChatChanged()


def suggestions(store, adapters):
    """Ordered public-content matches between unlinked chats; no writer service."""
    result = []
    for (a, first), (b, second) in combinations(adapters.items(), 2):
        for left in first.locator.chats():
            if store.link_for(a, left.id):
                continue
            require_settled(store, chats=((a, left.id),))
            store.remember_chat(a, left.id, asdict(left))
            left_turns = first.reader.read(left.id)
            if first.state.condition(left.id).replying:
                left_turns = left_turns[:-1]
            one = [content_key(t) for t in left_turns]
            for right in second.locator.chats():
                if store.link_for(b, right.id):
                    continue
                require_settled(store, chats=((b, right.id),))
                store.remember_chat(b, right.id, asdict(right))
                right_turns = second.reader.read(right.id)
                if second.state.condition(right.id).replying:
                    right_turns = right_turns[:-1]
                two = [content_key(t) for t in right_turns]
                matched = sum(block.size for block in SequenceMatcher(None, one, two, autojunk=False).get_matching_blocks())
                if matched:
                    result.append({'a': (a, left), 'b': (b, right), 'matched_turns': matched})
    return result


def merge_projection(link, rows, payload, adapters, *, merge_setting='ask', brief_threshold_tokens=150000):
    """The merge screen's policy, shared with the confirmed merger."""
    pending, order = planner.unsynced(rows), planner.merge_order(rows)
    changed = {}
    for turn in pending:
        for path in adapters[turn.origin].reader.files_changed(payload[turn.id]):
            changed.setdefault(path, []).append(turn)
    same_files = [{'file': path, 'turns': [t.id for t in values]}
                  for path, values in sorted(changed.items()) if len({t.origin for t in values}) > 1]
    presets = [{'id': 'by_time', 'order': [t.id for t in order]}]
    presets += [{'id': side + '_first', 'order': [t.id for t in planner.merge_order(rows, side)]}
                for side in link.sides if any(t.origin == side for t in pending)]
    presets += [{'id': 'dont_reorder', 'order': [t.id for t in order]}]
    tokens = sum(t.size for t in rows if KEPT_BACK not in t.states.values() and SKIPPED not in t.states.values()) // 4
    return {'last_shared': planner.last_shared(rows), 'unsynced': pending,
            'messages': {t.id: payload[t.id] for t in pending}, 'order': [t.id for t in order],
            'presets': presets, 'outcome': planner.outcome(order),
            'overlaps': [[a.id, b.id] for a, b in planner.overlapping(order)],
            'same_files': same_files, 'tokens': tokens, 'offer_brief': tokens >= brief_threshold_tokens,
            'automatic_allowed': merge_setting == 'by_time' and not same_files}


class ReadViews:
    """Read native evidence and committed records without running write recovery."""
    def __init__(self, store, adapters, clock, settings, label, automatic_sides=lambda: ()):
        self.store, self.adapters, self.clock = store, adapters, clock
        self.settings, self.label, self.automatic_sides = settings, label, automatic_sides

    def _link(self, link_id, *, active=True):
        try:
            link = self.store.get_link(link_id)
        except KeyError:
            raise ChatChanged() from None
        if active and link.removed_at:
            raise ChatChanged()
        return link

    @staticmethod
    def _unavailable(tool):
        failure = NotAvailable(tool)
        failure.note_id = 'setup.adapter_unavailable'
        failure.values = {'tool': tool}
        return failure

    def _verified(self, link_id, row, actual, evidence):
        try:
            return verified_source(self.store, link_id, row, actual, evidence)
        except NotAvailable:
            raise ChatChanged() from None

    def chats(self, tool, folder=None):
        """List observed references with current link ownership."""
        if tool not in self.adapters:
            raise self._unavailable(tool)
        refs = self.adapters[tool].locator.chats()
        result = []
        for ref in refs:
            if folder is not None and ref.folder != folder:
                continue
            self.store.remember_chat(tool, ref.id, asdict(ref))
            result.append({'tool': tool, 'ref': ref, 'link': self.store.link_for(tool, ref.id)})
        return result

    def suggestions(self):
        """Match unlinked public histories using the shared ordered matcher."""
        return suggestions(self.store, self.adapters)

    def _reference(self, link, side):
        chat = link.chat(side)
        saved = self.store.known_chat(side, chat)
        if saved is None:
            for event in self.store.history(link.id):
                for group in ('after_chats', 'after', 'before_chats', 'snapshots', 'observations'):
                    snapshot = event.detail.get(group, {}).get(side, {})
                    candidate = snapshot.get('ref')
                    if (isinstance(candidate, dict) and candidate.get('id') == chat and snapshot.get('chat_id', chat) == chat and
                            all(isinstance(candidate.get(k), str) for k in ('id', 'name', 'folder', 'updated_at'))):
                        saved = {k: candidate[k] for k in ('id', 'name', 'folder', 'updated_at')}
                        self.store.remember_chat(side, chat, saved)
                        break
                if saved is None and event.kind == 'brief' and event.detail.get('artifact_id'):
                    try:
                        request = self.store.brief_artifact(event.detail['artifact_id'])['request']
                    except KeyError:
                        request = {}
                    snapshot = request.get('snapshots', {}).get(side, {})
                    candidate = snapshot.get('ref')
                    if (request.get('chats', {}).get(side) == chat and isinstance(candidate, dict)
                            and candidate.get('id') == chat and snapshot.get('chat_id', chat) == chat
                            and all(isinstance(candidate.get(k), str) for k in ('id', 'name', 'folder', 'updated_at'))):
                        saved = {k: candidate[k] for k in ('id', 'name', 'folder', 'updated_at')}
                        self.store.remember_chat(side, chat, saved)
                if saved is not None:
                    break
        return ChatRef(**(saved or {'id': chat, 'name': '', 'folder': '', 'updated_at': ''}))

    def link_summary(self, link_id):
        """Refresh one settled link and retain last observed chat names."""
        link = self._link(link_id)
        require_settled(self.store, link_id=link_id, chats=tuple(link.chats.items()))
        missing = next((side for side in link.sides if side not in self.adapters), None)
        if missing:
            raise self._unavailable(missing)
        automatic = self.automatic_sides()
        fresh = ChatRefresh(self.store, self.adapters, self.clock).refresh(link_id, add_when_idle=automatic)
        fresh['refs'] = {s: self._reference(fresh['link'], s) for s in link.sides}
        return fresh

    def status(self, link_id, messages=False):
        """Combine actual usage, digest, public messages and delivery evidence."""
        fresh = self.link_summary(link_id)
        link = fresh['link']
        readers = {s: a.reader for s, a in self.adapters.items()}
        usage = UsageService(readers, self.clock)
        digest = DigestBuilder(self.store, readers, self.clock, self.label)
        sources = canonical_sources(self.store, link_id, fresh['observed'])
        fresh['canonical_messages'] = {}
        if messages:
            evidence = self.store.turn_evidence(link_id)
            for row in fresh['turns']:
                if row.origin in fresh['missing']:
                    continue
                actual = sources.get(row.id)
                if evidence.get(row.id, {}).get('complete', True):
                    actual = self._verified(link_id, row, actual, evidence)
                if actual:
                    public = for_target(actual, replace(self.adapters[row.origin].facts, replays_tool_calls=True))
                    fresh['canonical_messages'][row.id] = (public.prompt, *public.messages)
        fresh['usage'], fresh['digests'], fresh['side_notes'], fresh['coverage'] = {}, {}, {}, {}
        for side in link.sides:
            state = fresh['status'].side(side)
            values = {'tool': side, 'n': state.waiting}
            notes = [NoteRef('status.summary', {'tool': side, 'agent_has': state.agent_has,
                     'total': state.total, 'chat_shows': state.chat_shows, 'waiting': state.waiting})]
            if side in fresh['missing']:
                notes.append(NoteRef('side.missing', {}))
                notes.append(NoteRef('digest.unavailable', {}))
                fresh['usage'][side] = {'tokens': 0, 'size': None, 'percent': None, 'limit': None}
                fresh['digests'][side] = None
            else:
                used = usage.side(side, link.chat(side), link.others(side)[0])
                fresh['usage'][side] = used.as_contract()
                notes.extend(used.notes)
                news = None
                try:
                    if fresh['missing']:
                        raise ChatChanged()
                    news = digest.for_side(link_id, side)
                except (BatonError, KeyError):
                    notes.append(NoteRef('digest.unavailable', {}))
                fresh['digests'][side] = news.as_contract() if news else None
                if news:
                    notes.append(digest.note(news))
            check = self.adapters[side].state.format_version()
            if not check.known or check.new_version:
                notes.append(NoteRef('format.unknown_version' if not check.known else 'format.new_version',
                                     {'tool': side, 'version': check.version}))
            if state.waiting:
                action, reason, needs, alternatives = status.delivery_choice(
                    link, fresh['conditions'][side], self.adapters[side].facts, state.waiting_reason,
                    side in self.automatic_sides(),
                    side in fresh['initial_history'])
                if action == 'add' and self.adapters[side].facts.write_window == WriteWindow.ANY_TIME:
                    notes.append(NoteRef('write.any_time', values))
                elif action == 'attach':
                    key = 'status.first_message' if reason == 'initial_history' else (
                        'write.chat_open_release' if 'add_now' in alternatives else 'write.chat_open')
                    notes.append(NoteRef(key, values))
                elif action == 'add_after_release':
                    notes.append(NoteRef('write.release', values))
                elif reason == 'hooks_not_ready':
                    notes.append(NoteRef('setup.hooks', values))
                if state.attached_on_next_message:
                    notes.append(NoteRef('status.if_send', {**values, 'n': state.attached_on_next_message, 'tokens': state.attached_tokens}))
            for need in state.needs:
                notes.append(NoteRef(need, {'tool': side, 'n': state.added}))
            if state.attached:
                notes.append(NoteRef('status.attached', {'tool': side, 'n': state.attached}))
            coverage = self.store.summary_coverage(link_id, side)
            if coverage:
                fresh['coverage'][side] = {k: coverage[k] for k in ('artifact_id', 'chat_id', 'through_turn_id', 'turn_ids')}
                notes.append(NoteRef('brief.summary_receipt', {'tool': side}))
            fresh['side_notes'][side] = notes
        return fresh

    def merge_show(self, link_id):
        """Project canonical merge choices without constructing a recovering merger."""
        fresh = self.link_summary(link_id)
        if fresh['missing']:
            raise ChatChanged()
        payload = canonical_sources(self.store, link_id, fresh['observed'])
        evidence = self.store.turn_evidence(link_id)
        for row in fresh['turns']:
            self._verified(link_id, row, payload.get(row.id), evidence)
        settings = self.settings.get()
        result = merge_projection(fresh['link'], fresh['turns'], payload, self.adapters,
                    merge_setting=settings['merge'], brief_threshold_tokens=settings['brief_threshold_tokens'])
        result['decision_needed'] = fresh['status'].decision_needed
        return result

    def history(self, link_id):
        """Eligibility uses the existing immutable E8 preflight and read-only guards."""
        from .undo import UndoPreview
        from .journal import Guard
        link = self._link(link_id, active=False)
        preview, guard = UndoPreview(self.store, self.adapters, self.clock), Guard(self.store)
        events = self.store.history(link_id)
        def eligible(event, operation):
            if self.store.journal_entries(pending=True) or link.removed_at:
                return False
            try:
                plan = preview.restore(link_id, event.id) if operation == 'restore' else preview.plan(link_id, event.id)
                for step in plan.steps:
                    adapter = self.adapters[step.side]
                    chat = link.chat(step.side)
                    if adapter.state.condition(chat).replying:
                        return False
                    if step.action == 'move_link':
                        continue
                    create = step.action == 'create_shorter'
                    try:
                        guard.check_write(adapter, None if create else chat, link_id,
                                          action='create' if create else 'add' if step.action == 'restore' else step.action)
                    except ChatHeld:
                        if 'release_chat' not in step.needs:
                            raise
                        guard.check_release(adapter, chat, link_id)
                return bool(plan.steps)
            except (BatonError, KeyError, ValueError, TypeError):
                return False
        results = []
        undo_kinds = ('add', 'added', 'delivered', 'place', 'attached', 'create', 'merge', 'brief')
        for event in events:
            undone = any(e.kind == 'undo' and e.detail.get('target') == event.id and
                         not any(r.kind == 'restore' and r.detail.get('target') == e.id for r in events)
                         for e in events)
            results.append({'event': event, 'can_undo': event.kind in undo_kinds and not undone and eligible(event, 'undo'),
                            'can_restore': event.kind == 'undo' and eligible(event, 'restore')})
        return results
