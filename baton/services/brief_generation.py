"""Brief generation, candidate readiness and immutable artifacts."""
from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime, timedelta
from hashlib import sha256
import logging

from ..domain.errors import ChatChanged, NotAvailable
from ..domain.link import Link
from ..domain.model import Message, PROMPT, Turn
from ..notes.catalogue import get
from .mapping import content_key, for_target, title
from .noteformat import NoteRef
from .observations import decode_turns, local_turn

logger = logging.getLogger("baton.services.brief")

from .brief_types import BriefPlan, BriefResult, OFFLINE, _NOT_FOR_THIS_TOOL, _fingerprint, estimate_tokens

class BriefGeneration:
    """Build and generate immutable brief artifacts after consent."""
    def _eligible(self, request, *, generation=False):
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
            elif not (adapter.runner.available().ok if generation else
                      adapter.runner.ready().ok if hasattr(adapter.runner, "ready") else
                      getattr(getattr(adapter.runner, "finding", None), "ok", True)):
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

    def _check_pause(self, request):
        for link_id in (request.get('link_id'), request.get('replace_link_id')):
            if link_id is not None:
                link = self.store.get_link(link_id)
                if link.paused or link.removed_at:
                    raise NotAvailable()

    def _preview_request(self, request):
        self._check_pause(request)
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
        ident = 'p_' + self._new_id()
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
        opening = Turn(Message('baton_brief_' + self._new_id(), PROMPT, text, self.clock.now()))
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
        ident = 'p_' + self._new_id()
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
            self._check_pause(request)
            self._validate_request(request)
            notes = [NoteRef(**value) for value in payload['notes']]
            for side in payload['candidates']:
                self._check_pause(request)
                prompt, cached, key, prefix, privacy = self._prompt(request, side)
                estimate = next(e for e in payload['estimates'] if e['writer'] == side)
                cost_prompt = prompt if cached is None else self._full_prompt(request, side)
                if (_fingerprint({'prompt': cost_prompt, 'cached_summary': cached}) != estimate['input_fingerprint']
                        or estimate_tokens(cost_prompt) != estimate['tokens']):
                    raise ChatChanged()
                if side not in self._eligible(request, generation=True)[0]:
                    notes.extend(note for note in self._eligible(request, generation=True)[1] if note.values.get('tool') == side)
                    continue
                if cached is not None:
                    if side != request['to'] and request['writer'] is None:
                        notes.append(NoteRef('brief.written_by', {'tool': side}))
                    return self._artifact(request, side, cached, notes, payload['estimates'])
                folder = (request['snapshots'].get(side, {}).get('ref') or request['source_ref'])['folder']
                self._check_pause(request)
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
        self._check_pause(artifact['request'])
        self._validate_request(artifact['request'])
        return self._create(ident, artifact)

