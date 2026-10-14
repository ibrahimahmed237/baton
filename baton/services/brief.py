"""A brief: a summary that opens a new chat instead of sending a long history (DESIGN 6).

Covers working-across W4, W14, W15 and the size offer (M12). A brief never goes
into an existing chat, so the plan is always a `create`. Who writes the summary
is decided here: the destination tool, else the other tool, else Baton itself
from the turns (the offline brief). Whoever writes it, every pinned turn comes
in full, and a turn kept back from a tool never reaches that tool's agent.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone, tzinfo
from hashlib import sha256
import logging
import json
from uuid import uuid4
from typing import Any, Mapping, Sequence

from ..domain.errors import ChatChanged, NotAvailable, OrderNotAllowed
from ..domain.link import ADDED, SHOWN, KEPT_BACK, SKIPPED, LedgerTurn, Link
from ..domain.model import REPLY, TOOL_TEXT, Message, PROMPT, Turn
from ..notes.catalogue import get
from ..ports.clock import Clock
from ..ports.store import RecordStore
from ..ports.tool import ToolAdapter, WriteReceipt
from . import planner
from .mapping import content_key, for_created_chat, for_target, title
from .noteformat import Label, NoteRef, clock_time, day_of, short_count
from .observations import canonical_sources
from .transcripts import TranscriptStore
from .usage import UsageService
from .journal import Guard, Journal
from .preview import PreviewBuilder
from .delivery_plan import ApplyStep
from .observations import decode_turns, local_turn, verified_source

logger = logging.getLogger("baton.services.brief")

from .brief_types import (BriefPlan, BriefResult, OFFLINE, DEFAULT_RECENT_TURNS,
                          DEFAULT_THRESHOLD_TOKENS, Pair, _NOT_FOR_THIS_TOOL,
                          _fingerprint, estimate_tokens, _CHARS_PER_TOKEN)

from .brief_generation import BriefGeneration
from .brief_creation import BriefCreation

class BriefService(BriefGeneration, BriefCreation):
    """Plan briefs and the offer to write one."""

    def __init__(self, store: RecordStore, adapters: Mapping[str, ToolAdapter], clock: Clock,
                 transcripts: TranscriptStore, label: Label, tz: tzinfo = timezone.utc):
        self.store, self.adapters, self.clock = store, adapters, clock
        self.transcripts, self.label, self.tz = transcripts, label, tz
        self.recovery = Journal(store, adapters, clock).recover()
        self.usage = UsageService({tool: adapter.reader for tool, adapter in adapters.items()}, clock, tz)

    def _new_id(self):
        """Retain the public facade's injectable identity source."""
        return uuid4().hex

    # The offer

    def offer(self, link_id: int, to: str, threshold: int = DEFAULT_THRESHOLD_TOKENS,
              *, merged_copy: bool = False) -> NoteRef | None:
        """Offer a brief when sending the whole history to `to` would be about `threshold` tokens or more."""
        link = self._link(link_id, to)
        tokens = sum(row.size for row in self.store.turns(link.id)
                     if row.states.get(to) not in _NOT_FOR_THIS_TOOL) // _CHARS_PER_TOKEN
        if tokens < threshold:
            return None
        if merged_copy:
            return NoteRef("merge.large_copy", {"tokens": short_count(tokens)})
        return NoteRef("brief.large_chat", {"tokens": short_count(tokens), "tool": to})

    # The plan

    def plan(self, link_id: int, to: str, *, writer: str | None = None,
             recent_turns: int = DEFAULT_RECENT_TURNS, order: Sequence[int] | None = None,
             title_tag: bool = True) -> BriefPlan:
        """Preview without asking an agent; every confirmation is durable and single-use."""
        link = self._link(link_id, to)
        if writer not in (None, OFFLINE) and writer not in link.sides:
            raise NotAvailable()
        if self.store.journal_entries(pending=True):
            raise NotAvailable()
        rows, content = self._conversation(link, order)
        evidence = self.store.turn_evidence(link_id)
        for row in rows:
            verified_source(self.store, link_id, row, content.get(row.id), evidence)
        destination_pairs = self._pairs(rows, content, to)
        if not destination_pairs:
            raise NotAvailable()
        builder = PreviewBuilder(self.store, self.adapters)
        request = {'kind': 'existing', 'link_id': link_id, 'to': to, 'writer': writer,
                   'recent_turns': max(0, int(recent_turns)), 'title_tag': bool(title_tag),
                   'order': list(order) if order is not None else None,
                   'chats': dict(link.chats),
                   'snapshots': {s: builder._snapshot(s, c) for s, c in link.chats.items()},
                   'record': self._record(link_id),
                   'rows': [asdict(row) for row in rows],
                   'content': {str(ident): asdict(turn) for ident, turn in content.items()}}
        # Read again after constructing all dependent inputs: never bind a token
        # to a newer snapshot than the content used for its cost/artifact.
        self._validate_request(request)
        return self._preview_request(request)

    def plan_new(self, source: str, chat_id: str, to: str, *, writer: str | None = None,
                 recent_turns: int = DEFAULT_RECENT_TURNS, title_tag: bool = True,
                 replace_link_id: int | None = None) -> BriefPlan:
        """Bind unlinked/relink source content without making a temporary link."""
        if source == to or source not in self.adapters or to not in self.adapters:
            raise NotAvailable()
        owner = self.store.link_for(source, chat_id)
        if owner and owner.id != replace_link_id:
            from ..domain.errors import AlreadyLinked
            raise AlreadyLinked(source, owner)
        if replace_link_id is not None:
            old = self.store.get_link(replace_link_id)
            if old.removed_at or old.chat(source) != chat_id:
                raise NotAvailable()
            if to in old.sides:
                return self.plan(replace_link_id, to, writer=writer, recent_turns=recent_turns, title_tag=title_tag)
        if writer not in (None, OFFLINE, source, to) or self.store.journal_entries(pending=True):
            raise NotAvailable()
        builder = PreviewBuilder(self.store, self.adapters)
        snapshot = builder._snapshot(source, chat_id)
        if not snapshot['condition']['exists'] or snapshot['condition']['replying']:
            raise NotAvailable()
        turns = decode_turns(snapshot['turns'])
        if not turns:
            raise NotAvailable()
        from ..domain.link import AGENT_HAS, SUMMARIZED, WAITING, WRITTEN_HERE
        source_coverage = None
        previous_record = None
        if owner:
            previous_record = self._record(owner.id)
            previous_rows, previous_content = self._conversation(owner, None)
            evidence = self.store.turn_evidence(owner.id)
            for row in previous_rows:
                verified_source(self.store, owner.id, row, previous_content.get(row.id), evidence)
            local = self.store.local_ids(owner.id, source)
            physical = {turn.id: turn for turn in turns}
            rows, content = [], {}
            for row in previous_rows:
                if row.states[source] not in (*AGENT_HAS, SUMMARIZED):
                    continue
                state = row.states[source]
                native_id = local.get(row.id, row.origin_id if row.origin == source else '')
                actual = physical.get(native_id)
                canonical = previous_content[row.id]
                payload = replace(canonical, prompt=replace(canonical.prompt, id=native_id)) if actual else canonical
                states = {source: state, to: KEPT_BACK if KEPT_BACK in row.states.values() else WAITING}
                converted = replace(row, seq=len(rows)+1, origin=source, origin_id=payload.id, states=states)
                rows.append(converted)
                content[row.id] = payload
            source_coverage = self.store.summary_coverage(owner.id, source)
        else:
            rows = [LedgerTurn(n, n, source, turn.id, turn.started_at, turn.ended_at,
                               turn.prompt.text.strip()[:120], len(turn.prompt.text) + sum(len(m.text) for m in turn.messages),
                               False, {source: WRITTEN_HERE, to: WAITING})
                    for n, turn in enumerate(turns, 1)]
            content = {n: turn for n, turn in enumerate(turns, 1)}
        if not rows:
            raise NotAvailable()
        request = {'kind': 'new_link', 'link_id': None, 'to': to, 'writer': writer,
                   'recent_turns': max(0, int(recent_turns)), 'title_tag': bool(title_tag),
                   'order': None, 'chats': {source: chat_id}, 'source_ref': snapshot['ref'],
                   'snapshots': {source: snapshot}, 'target_observation': self._target_observation(to),
                   'records': [asdict(link) for link in self.store.links()],
                   'replace_link_id': replace_link_id, 'replace_record': previous_record,
                   'source_coverage': source_coverage,
                   'rows': [asdict(row) for row in rows],
                   'content': {str(ident): asdict(turn) for ident, turn in content.items()}}
        self._validate_request(request)
        return self._preview_request(request)

    def _target_observation(self, side):
        adapter = self.adapters[side]
        return {'facts': {k: getattr(v, 'value', v) for k, v in asdict(adapter.facts).items()},
                'format': asdict(adapter.state.format_version()), 'running': adapter.app.running()}

    def _record(self, link_id):
        link = self.store.get_link(link_id)
        return {'link': asdict(link), 'turns': [asdict(t) for t in self.store.turns(link_id)],
                'history': [asdict(e) for e in self.store.history(link_id)],
                'local_ids': {s: self.store.local_ids(link_id, s) for s in link.sides}}

    def _request_content(self, request):
        rows = [LedgerTurn(**value) for value in request['rows']]
        content = {int(ident): decode_turns([value])[0] for ident, value in request['content'].items()}
        return rows, content

    def _validate_request(self, request):
        builder = PreviewBuilder(self.store, self.adapters)
        try:
            for side, snapshot in request['snapshots'].items():
                if _fingerprint(builder._snapshot(side, snapshot['chat_id'])) != _fingerprint(snapshot):
                    raise ChatChanged()
            if request['kind'] == 'existing':
                if _fingerprint(self._record(request['link_id'])) != _fingerprint(request['record']):
                    raise ChatChanged()
                self._conversation(self.store.get_link(request['link_id']), request['order'])
            else:
                if (_fingerprint(self._target_observation(request['to'])) != _fingerprint(request['target_observation']) or
                        [asdict(link) for link in self.store.links()] != request['records']):
                    raise ChatChanged()
                if (request.get('replace_record') and _fingerprint(self._record(request['replace_link_id']))
                        != _fingerprint(request['replace_record'])):
                    raise ChatChanged()
        except KeyError:
            raise ChatChanged() from None

    # The conversation

    def _link(self, link_id: int, to: str) -> Link:
        link = self.store.get_link(link_id)
        if link.removed_at or to not in link.sides:
            raise NotAvailable()
        return link

    def _conversation(self, link: Link, order: Sequence[int] | None):
        rows = self.store.turns(link.id)
        observed = {side: self.adapters[side].reader.read(link.chat(side)) for side in link.sides}
        for side, turns in observed.items():
            known = set(self.store.local_ids(link.id, side).values())
            known.update(row.origin_id for row in rows if row.origin == side)
            coverage = self.store.summary_coverage(link.id, side)
            if coverage:
                known.add(coverage["opening_id"])
            if not {turn.id for turn in turns} <= known:
                raise ChatChanged()  # a turn not recorded yet would be missing from the brief
        content = canonical_sources(self.store, link.id, observed)
        return (self._reordered(rows, order) if order is not None else rows), content

    @staticmethod
    def _reordered(rows: Sequence[LedgerTurn], order: Sequence[int]) -> list[LedgerTurn]:
        by_id = {row.id: row for row in rows}
        if any(ident not in by_id for ident in order):
            raise OrderNotAllowed()
        ordered = [by_id[ident] for ident in order]
        planner.check_order(rows, ordered)
        queue = iter(ordered)
        pending = {row.id for row in planner.unsynced(rows)}
        return [next(queue) if row.id in pending else row for row in rows]

    @staticmethod
    def _pairs(rows: Sequence[LedgerTurn], content: Mapping[int, Turn], tool: str) -> list[Pair]:
        """The turns `tool` may be shown, with their content, in conversation order."""
        pairs = []
        for row in rows:
            if row.states.get(tool) in _NOT_FOR_THIS_TOOL:
                continue
            if row.id not in content:
                raise ChatChanged()
            pairs.append((row, content[row.id]))
        return pairs

    def _offline_summary(self, pairs: Sequence[Pair]) -> str:
        first = get("brief.first_request").render({"text": pairs[0][1].prompt.text}).template
        items = [get("brief.request_item").render({"n": n, "text": row.first_line}).template
                 for n, (row, _) in enumerate(pairs, 1)]
        return "\n\n".join([first, "\n".join([get("brief.requests_heading").template, *items])])

    # The text

    def _compose(self, link: Link, to: str, summary: str, pairs: Sequence[Pair], path: str,
                 recent_turns: int, flat, inline: bool = True) -> tuple[str, list[Pair]]:
        pinned = [pair for pair in pairs if pair[0].pinned]
        recent = [pair for pair in pairs if not pair[0].pinned][-recent_turns:] if recent_turns > 0 else []
        files: list[str] = []
        for row, turn in pairs:
            files.extend(p for p in self.adapters[row.origin].reader.files_changed(turn) if p not in files)
        sections = [get("brief.intro").render({"tool": self.label(link.others(to)[0])}).template, summary]
        for heading, chosen in (("brief.pinned_heading", pinned), ("brief.recent_heading", recent)):
            if chosen and inline:
                sections.append("\n\n".join([get(heading).template,
                                             *(self._turn_text(row, turn, flat) for row, turn in chosen)]))
        if files:
            sections.append("\n".join([get("brief.files_heading").template,
                                       *(get("brief.file_item").render({"path": p}).template for p in files)]))
        sections.append(get("brief.transcript_path").render({"path": path}).template)
        return "\n\n".join(sections), pinned

    def _turn_text(self, row: LedgerTurn, turn: Turn, flat) -> str:
        header = get("brief.turn_header").render({"at": self._time(row.started_at),
                                                  "tool": self.label(row.origin)}).template
        return header + "\n" + self._body(for_target(turn, flat))

    def _markdown(self, pairs: Sequence[Pair], flat) -> str:
        parts = [get("brief.md_title").template]
        for n, (row, turn) in enumerate(pairs, 1):
            parts.append(get("brief.md_turn").render({"n": n, "at": self._time(row.started_at),
                                                      "tool": self.label(row.origin)}).template)
            parts.append(self._body(for_target(turn, flat)))
        return "\n\n".join(parts) + "\n"

    @staticmethod
    def _body(turn: Turn) -> str:
        """The prompt, then each reply and each piece of tool activity, as written."""
        lines = [get("brief.line_user").render({"text": turn.prompt.text}).template]
        for message in turn.messages:
            if message.kind == REPLY:
                lines.append(get("brief.line_reply").render({"text": message.text}).template)
            elif message.kind == TOOL_TEXT:
                lines.append(message.text)
        return "\n".join(lines)

    def _time(self, value: str) -> str:
        return clock_time(value, self.tz, day_of(self.clock.now(), self.tz))
