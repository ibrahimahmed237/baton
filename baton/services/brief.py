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

logger = logging.getLogger(__name__)

OFFLINE = "offline"
DEFAULT_RECENT_TURNS = 3
DEFAULT_THRESHOLD_TOKENS = 150000  # the brief_threshold_tokens setting
_CHARS_PER_TOKEN = 4
# Turns a tool must not get: kept in the tool they were written in, or skipped in a merge.
_NOT_FOR_THIS_TOOL = (KEPT_BACK, SKIPPED)

Pair = tuple[LedgerTurn, Turn]


@dataclass(frozen=True)
class BriefPlan:
    """A stored approval for generation or immutable native creation."""
    link_id: int | None
    side: str
    action: str
    writer: str
    text: str
    turn: Turn
    name: str
    folder: str
    tokens: int
    pinned: tuple[int, ...]
    pinned_tokens: int
    transcript_path: str
    notes: tuple[NoteRef, ...]
    plan_id: str = ''
    stage: str = 'generate'
    estimated_tokens: int = 0
    candidate_estimates: tuple[dict, ...] = ()
    artifact_id: str = ''
    summary: str = ''
    originals: tuple[Turn, ...] = ()
    needs: tuple[str, ...] = ()
    turn_ids: tuple[int, ...] = ()

    @property
    def steps(self) -> tuple[ApplyStep, ...]:
        """The explicit destination is stable through both approval stages."""
        turns = (self.turn, *self.originals) if self.stage == 'create' else ()
        return (ApplyStep(self.side, 'create', self.turn_ids, turns, needs=self.needs, name=self.name, folder=self.folder),)

    @property
    def confirmation(self):
        """Return the catalogue confirmation belonging to this stored stage."""
        return NoteRef('plan.confirm_brief_generation' if self.stage == 'generate'
                       else 'plan.confirm_brief_creation', {})

    def as_contract(self) -> dict[str, Any]:
        """Expose additive artifact and bounded cost fields for the contract."""
        return {'writer': self.writer, 'tokens': self.tokens, 'pinned': list(self.pinned),
                'estimated_tokens': self.estimated_tokens,
                'candidate_estimates': list(self.candidate_estimates),
                'artifact_id': self.artifact_id, 'text': self.text, 'summary': self.summary, 'pinned_tokens': self.pinned_tokens}


@dataclass(frozen=True)
class BriefResult:
    """Report committed native creation or its recoverable failure."""
    plan_id: str
    applied: bool
    chat_id: str = ''
    link_id: int | None = None
    event_id: int | None = None
    error: str = ''
    rollback_error: str = ''


def _fingerprint(value) -> str:
    normalized = json.loads(json.dumps(value))
    return sha256(json.dumps(normalized, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

def estimate_tokens(text: str) -> int:
    """The same rough size as everywhere else in Baton: four characters a token."""
    return len(text) // _CHARS_PER_TOKEN


class BriefService:
    """Plan briefs and the offer to write one."""

    def __init__(self, store: RecordStore, adapters: Mapping[str, ToolAdapter], clock: Clock,
                 transcripts: TranscriptStore, label: Label, tz: tzinfo = timezone.utc):
        self.store, self.adapters, self.clock = store, adapters, clock
        self.transcripts, self.label, self.tz = transcripts, label, tz
        self.recovery = Journal(store, adapters, clock).recover()
        self.usage = UsageService({tool: adapter.reader for tool, adapter in adapters.items()}, clock, tz)

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

    def _eligible(self, request):
        notes = []
        if request['writer'] == OFFLINE:
            return [], notes
        target = request['to']
        candidates = ([request['writer']] if request['writer'] else
                      [target, *(s for s in request['chats'] if s != target)])
        eligible = []
        for side in candidates:
            adapter = self.adapters[side]
            if adapter.runner is None:
                notes.append(NoteRef('brief.skipped_no_runner', {'tool': side}))
            elif side in request['chats'] and self.usage.limit(side, request['chats'][side]).blocking:
                notes.append(NoteRef('brief.skipped_limit', {'tool': side}))
            elif not adapter.runner.available().ok:
                notes.append(NoteRef('setup.runner', {'tool': side}))
            else:
                eligible.append(side)
        return eligible, notes

    def _safe_pairs(self, request, writer):
        rows, content = self._request_content(request)
        return [(row, turn) for row, turn in self._pairs(rows, content, request['to'])
                if writer == OFFLINE or row.states.get(writer) not in _NOT_FOR_THIS_TOOL]

    def _cache_key(self, request, writer):
        rows, _ = self._request_content(request)
        # Privacy policy is a separate invariant from delivery states. A newly
        # appended safe turn is reusable; changing any earlier exclusion is not.
        privacy = [(row.id, row.states.get(request['to']) in _NOT_FOR_THIS_TOOL,
                    row.states.get(writer) in _NOT_FOR_THIS_TOOL) for row in rows]
        scope = {k: request[k] for k in ('kind', 'chats', 'to')}
        scope['writer'] = writer
        return _fingerprint(scope), privacy

    def _prompt(self, request, writer):
        flat = replace(self.adapters[request['to']].facts, replays_tool_calls=False)
        pairs = self._safe_pairs(request, writer)
        prefix = [{'id': row.id, 'content': content_key(turn)} for row, turn in pairs]
        key, privacy = self._cache_key(request, writer)
        cached = self.store.brief_cache_get(key)
        reused = cached and cached['privacy'] == [list(v) for v in privacy[:len(cached['privacy'])]]
        reused = reused and cached['prefix'] == prefix[:len(cached['prefix'])]
        if reused and len(cached['prefix']) == len(prefix):
            return '', cached['summary'], key, prefix, privacy
        if reused:
            conversation = self._markdown(pairs[len(cached['prefix']):], flat)
            prompt = get('brief.update_prompt').render({'summary': cached['summary'], 'conversation': conversation}).template
        else:
            prompt = get('brief.prompt').render({'conversation': self._markdown(pairs, flat)}).template
        return prompt, None, key, prefix, privacy

    def _full_prompt(self, request, writer):
        flat = replace(self.adapters[request['to']].facts, replays_tool_calls=False)
        return get('brief.prompt').render({'conversation': self._markdown(self._safe_pairs(request, writer), flat)}).template

    def _preview_request(self, request):
        candidates, notes = self._eligible(request)
        estimates = []
        for position, side in enumerate(candidates):
            prompt, reused, *_ = self._prompt(request, side)
            if reused is not None and position == 0:
                return self._artifact(request, side, reused, notes)
            cost_prompt = prompt if reused is None else self._full_prompt(request, side)
            estimates.append({'writer': side, 'tokens': estimate_tokens(cost_prompt),
                              'input_fingerprint': _fingerprint({'prompt': cost_prompt, 'cached_summary': reused})})
        if not candidates:
            if request['writer'] != OFFLINE:
                notes.append(NoteRef('brief.used_offline', {}))
            return self._artifact(request, OFFLINE, self._offline_summary(self._safe_pairs(request, OFFLINE)), notes)
        total = sum(item['tokens'] for item in estimates)
        payload = {'request': request, 'candidates': candidates, 'estimates': estimates,
                   'notes': [note._asdict() for note in notes], 'created_at': self.clock.now()}
        notes = [*notes, *(NoteRef('brief.cost', {'tool': e['writer'], 'writer_id': e['writer'], 'tokens': e['tokens']}) for e in estimates),
                 NoteRef('brief.total_cost', {'tokens': total})]
        ident = 'p_' + uuid4().hex
        self.store.save_brief_plan(ident, 'generate', payload)
        return self._plan_object(ident, 'generate', request, candidates[0], notes,
                                 estimates=estimates, estimated=total)

    def _plan_object(self, ident, stage, request, writer, notes, artifact=None, estimates=(), estimated=0):
        artifact = artifact or {}
        pinned_pairs = [(row, turn) for row, turn in self._safe_pairs(request, OFFLINE) if row.pinned]
        flat = replace(self.adapters[request['to']].facts, replays_tool_calls=False)
        pinned_tokens = sum(estimate_tokens(self._turn_text(row, turn, flat)) for row, turn in pinned_pairs)
        if pinned_pairs:
            notes = [*notes, NoteRef('brief.pinned_size', {'tokens': pinned_tokens})]
        if artifact and not any(note.id == 'brief.summary_receipt' for note in notes):
            notes = [*notes, NoteRef('brief.summary_receipt', {})]
        ref = request['snapshots'][request['to']]['ref'] if request['to'] in request['snapshots'] else request['source_ref']
        source = next(s for s in request['chats'] if s != request['to'])
        opening = decode_turns([artifact['turn']])[0] if artifact else Turn(Message('', PROMPT, ''))
        from ..domain.capabilities import Visibility, WriteWindow
        facts = self.adapters[request['to']].facts
        needs = ('app_closed',) if facts.write_window == WriteWindow.APP_CLOSED else ()
        if facts.new_chat_visible == Visibility.AFTER_RELAUNCH:
            needs += ('relaunch_to_see',)
        return BriefPlan(request.get('link_id'), request['to'], 'create', writer,
                         artifact.get('text', ''), opening,
                         title(ref['name'], self.label(source), request['title_tag']), ref['folder'],
                         artifact.get('tokens', 0), tuple(artifact.get('pinned', [row.id for row, _ in pinned_pairs])),
                         pinned_tokens, artifact.get('transcript_path', ''), tuple(notes),
                         ident, stage, estimated, tuple(estimates), artifact.get('id', ''),
                         artifact.get('summary', ''), tuple(decode_turns(artifact.get('originals', ()))), needs,
                         tuple(artifact.get('covered_ids', [row.id for row, _ in self._safe_pairs(request, OFFLINE)])))

    def _artifact(self, request, writer, summary, notes, estimates=()):
        rows, content = self._request_content(request)
        pairs = self._safe_pairs(request, OFFLINE)
        flat = replace(self.adapters[request['to']].facts, replays_tool_calls=False)
        path = self.transcripts.save(request.get('link_id') or 0, self._markdown(pairs, flat))
        link = Link(request.get('link_id') or 0, request['chats'], 'brief', False, '')
        text, pinned = self._compose(link, request['to'], summary, pairs, path, 0, flat, inline=False)
        recent = [pair for pair in pairs if not pair[0].pinned][-request['recent_turns']:] if request['recent_turns'] else []
        original_ids = {row.id for row, _ in (*pinned, *recent)}
        originals = [(row, turn) for row, turn in pairs if row.id in original_ids]
        opening = Turn(Message('baton_brief_' + uuid4().hex, PROMPT, text, self.clock.now()))
        artifact = {'request': request, 'writer': writer, 'summary': summary, 'text': text,
                    'turn': asdict(opening), 'created_at': self.clock.now(),
                    'transcript_path': path, 'transcript_digest': sha256(self._markdown(pairs, flat).encode()).hexdigest(),
                    'input_fingerprint': _fingerprint(request),
                    'covered_ids': [row.id for row, _ in pairs],
                    'original_ids': [row.id for row, _ in originals],
                    'originals': [asdict(local_turn(for_target(turn, flat), link.id, row.id)) for row, turn in originals],
                    'pinned': [row.id for row, _ in pinned],
                    'pinned_tokens': sum(estimate_tokens(self._turn_text(row, turn, flat)) for row, turn in pinned),
                    'tokens': estimate_tokens(text), 'notes': [note._asdict() for note in notes],
                    'estimates': list(estimates)}
        artifact['id'] = 'a_' + _fingerprint(artifact)
        self.store.save_brief_artifact(artifact['id'], artifact)
        ident = 'p_' + uuid4().hex
        self.store.save_brief_plan(ident, 'create', {'artifact_id': artifact['id'], 'created_at': self.clock.now()})
        return self._plan_object(ident, 'create', request, writer, notes, artifact,
                                 estimates, sum(e['tokens'] for e in estimates))

    def confirm(self, plan: BriefPlan | str, plan_id: str | None = None) -> BriefPlan | BriefResult:
        """Only the stored token/stage decides whether consent generates or writes."""
        ident = plan if isinstance(plan, str) else plan.plan_id
        if plan_id is not None and ident != plan_id:
            raise ChatChanged()
        stored = self.store.brief_plan(ident)
        payload = self.store.consume_brief_plan(ident, stored['stage'])
        created = datetime.fromisoformat(payload['created_at'])
        now = datetime.fromisoformat(self.clock.now())
        if now < created or now - created > timedelta(minutes=10):
            raise ChatChanged()
        if stored['stage'] == 'generate':
            request = payload['request']
            self._validate_request(request)
            notes = [NoteRef(**value) for value in payload['notes']]
            for side in payload['candidates']:
                prompt, cached, key, prefix, privacy = self._prompt(request, side)
                estimate = next(e for e in payload['estimates'] if e['writer'] == side)
                cost_prompt = prompt if cached is None else self._full_prompt(request, side)
                if (_fingerprint({'prompt': cost_prompt, 'cached_summary': cached}) != estimate['input_fingerprint']
                        or estimate_tokens(cost_prompt) != estimate['tokens']):
                    raise ChatChanged()
                if side not in self._eligible(request)[0]:
                    notes.extend(note for note in self._eligible(request)[1] if note.values.get('tool') == side)
                    continue
                if cached is not None:
                    if side != request['to'] and request['writer'] is None:
                        notes.append(NoteRef('brief.written_by', {'tool': side}))
                    return self._artifact(request, side, cached, notes, payload['estimates'])
                folder = (request['snapshots'].get(side, {}).get('ref') or request['source_ref'])['folder']
                try:
                    summary = self.adapters[side].runner.ask(prompt, folder, read_only=True).strip()
                except Exception:
                    logger.exception('brief_generation_failed')
                    summary = ''
                self._validate_request(request)
                if summary:
                    if side != request['to'] and request['writer'] is None:
                        notes.append(NoteRef('brief.written_by', {'tool': side}))
                    self.store.brief_cache_put(key, {'prefix': prefix, 'privacy': privacy, 'summary': summary})
                    return self._artifact(request, side, summary, notes, payload['estimates'])
                notes.append(NoteRef('brief.skipped_failed', {'tool': side}))
            notes.append(NoteRef('brief.used_offline', {}))
            return self._artifact(request, OFFLINE, self._offline_summary(self._safe_pairs(request, OFFLINE)),
                                  notes, payload['estimates'])
        artifact = self.store.brief_artifact(payload['artifact_id'])
        self._validate_request(artifact['request'])
        return self._create(ident, artifact)

    def _create(self, ident, artifact):
        request = artifact['request']
        side, link_id = request['to'], request.get('link_id')
        adapter = self.adapters[side]
        guard, journal = Guard(self.store), Journal(self.store, self.adapters, self.clock)
        entry = None
        entries = []
        try:
            self.transcripts.verify(artifact['transcript_path'], artifact['transcript_digest'])
            guard.check_write(adapter, None, action='create')
            entry = journal.begin(link_id, side, None, 'create')
            entries.append(entry)
            self._validate_request(request)
            self.transcripts.verify(artifact['transcript_path'], artifact['transcript_digest'])
            guard.check_write(adapter, None, action='create')
            turns = for_created_chat(decode_turns([artifact['turn'], *artifact['originals']]), adapter.facts)
            result = adapter.writer.create(turns, self._plan_object(ident, 'create', request, artifact['writer'], [], artifact).name,
                                           self._plan_object(ident, 'create', request, artifact['writer'], [], artifact).folder)
            prepared = self.store.journal_entry(entry)
            if (result.chat_id != prepared['chat_id'] and result.receipt.tool == side
                    and result.receipt.chat_id == result.chat_id and result.receipt.kind == 'create'):
                actual_entry = self.store.journal_begin(link_id, side, result.chat_id, 'create',
                                                        self.clock.now(), asdict(result.receipt))
                entries.append(actual_entry)
                raise ChatChanged()
            if (result.receipt.tool, result.receipt.chat_id, result.receipt.kind) != (side, prepared['chat_id'], 'create'):
                raise ChatChanged()
            actual = adapter.reader.read(result.chat_id)
            if (tuple(turn.id for turn in actual) != result.local_ids
                    or len(set(result.local_ids)) != len(turns)
                    or [content_key(t) for t in actual] != [content_key(t) for t in turns]):
                raise ChatChanged()
            self._validate_request(request)
            from ..domain.capabilities import Visibility
            state = SHOWN if adapter.facts.new_chat_visible == Visibility.AT_ONCE else ADDED
            if request['kind'] == 'existing':
                event = self.store.complete_brief(link_id, side, result.chat_id, artifact['id'], result.local_ids[0],
                                                 artifact['original_ids'], list(result.local_ids[1:]), state,
                                                 entry, asdict(result.receipt), request['record'], self.clock.now(),
                                                 PreviewBuilder(self.store, self.adapters)._snapshot(side, result.chat_id))
            else:
                link_id, event = self.store.complete_brief_link(request, result.chat_id, artifact['id'],
                                        result.local_ids[0], artifact['original_ids'], list(result.local_ids[1:]),
                                        state, entry, asdict(result.receipt), self.clock.now(),
                                        PreviewBuilder(self.store, self.adapters)._snapshot(side, result.chat_id))
            return BriefResult(ident, True, result.chat_id, link_id, event)
        except Exception as error:
            rollback = ''
            if entry is not None:
                # A exception after atomic completion must never remove its
                # committed native chat or downgrade the completed receipt.
                if self.store.journal_entry(entry)['state'] == 'committed':
                    committed_chat = self.store.journal_entry(entry)['chat_id']
                    committed_link = self.store.link_for(side, committed_chat)
                    return BriefResult(ident, True, committed_chat, committed_link.id if committed_link else link_id)
                for pending in reversed(entries):
                    journal.fail(pending, error)
                    try:
                        journal.take_back(pending)
                    except Exception as failure:
                        rollback = type(failure).__name__
            return BriefResult(ident, False, error=type(error).__name__, rollback_error=rollback)

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
