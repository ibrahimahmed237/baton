"""Confirmed linking and copying without changing either existing chat."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from difflib import SequenceMatcher
from hashlib import sha256
import json
from itertools import combinations
from typing import Mapping

from ..domain.capabilities import Visibility, WriteWindow
from ..domain.errors import AlreadyLinked, ChatChanged, NotAvailable
from ..domain.link import ADDED, SHOWN, WAITING, WRITTEN_HERE, KEPT_BACK, SKIPPED
from ..domain.model import Message, Turn
from ..ports.clock import Clock
from ..ports.store import RecordStore
from ..ports.tool import ToolAdapter
from ..notes.catalogue import get
from .journal import Guard, Journal
from .mapping import content_key, for_created_chat, title

from .observations import canonical_sources

@dataclass(frozen=True)
class LinkPlan:
    """A fingerprinted link action with complete observations and creation payload."""
    plan_id: str
    action: str
    source: str
    target: str
    mode: str
    observations: dict
    records: list
    turns: tuple = ()
    name: str = ''
    folder: str = ''
    needs: tuple[str, ...] = ()
    old_link_id: int | None = None
    and_link: bool = True
    turn_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class LinkResult:
    """A completed metadata change or an explicit failed creation outcome."""
    plan_id: str
    applied: bool
    chat_id: str = ''
    link_id: int | None = None
    needs: tuple[str, ...] = ()
    error: str = ''
    rollback_error: str = ''
    pending_entry: int | None = None


def _fingerprint(data: dict) -> str:
    return 'p_' + sha256(json.dumps(data,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


class Linker:
    """Preview, confirm and atomically record link changes and new copies."""
    def __init__(self, store: RecordStore, adapters: Mapping[str, ToolAdapter], clock: Clock):
        self.store, self.adapters, self.clock = store, adapters, clock
        self.guard = Guard(store)
        self.journal = Journal(store,adapters,clock)
        self.recovery = self.journal.recover()

    def _records(self) -> list:
        return [{'link':asdict(link),'turns':[asdict(t) for t in self.store.turns(link.id)]}
                for link in self.store.links()]

    def _observe(self, side: str, chat_id: str | None, allow_missing: bool = False,
                 metadata_only: bool = False) -> dict:
        adapter = self.adapters[side]
        facts = {k:getattr(v,'value',v) for k,v in asdict(adapter.facts).items()}
        base = {'facts':facts,'format':asdict(adapter.state.format_version()),'running':adapter.app.running()}
        if chat_id is None:
            return base
        try:
            ref = adapter.locator.resolve(chat_id)
        except KeyError:
            if not allow_missing:
                raise
            condition = asdict(adapter.state.condition(chat_id))
            condition['exists'] = False
            return dict(base,missing_chat_id=chat_id,condition=condition,metadata_only=metadata_only)
        observed = dict(base,ref=asdict(ref),condition=asdict(adapter.state.condition(ref.id)))
        if metadata_only:
            return dict(observed,metadata_only=True)
        return dict(observed,turns=[asdict(t) for t in adapter.reader.read(ref.id)])

    def _free(self, side: str, chat: str, replacing: int | None = None) -> None:
        linked = self.store.link_for(side,chat)
        if linked is not None and linked.id != replacing:
            raise AlreadyLinked(side,linked)

    def _plan(self, record_snapshot: dict | None = None, **values) -> LinkPlan:
        values['records'] = self._records()
        if record_snapshot is not None:
            current = next((r for r in values['records'] if r['link']['id'] == record_snapshot['link']['id']),None)
            if current != record_snapshot:
                raise ChatChanged()
            # The payload's exact record snapshot, rather than a newer read, is confirmed.
            values['records'] = [record_snapshot if r['link']['id']==record_snapshot['link']['id'] else r
                                 for r in values['records']]
        plan = LinkPlan('',**deepcopy(values))
        data = asdict(plan)
        data.pop('plan_id')
        return replace(plan,plan_id=_fingerprint(data))

    def plan_link(self, from_side: str, from_chat: str, to_tool: str,
                  to_chat: str | None = None, mode: str = 'full_copy',
                  title_tag: bool = True) -> LinkPlan:
        """Preview an existing-pair link or a newly created full-history twin."""
        return self._link_plan(from_side,from_chat,to_tool,to_chat,mode,title_tag)

    def _link_plan(self, source: str, chat: str, target: str, target_chat: str | None,
                   mode: str, title_tag: bool, old_link_id: int | None = None,
                   and_link: bool = True) -> LinkPlan:
        if source == target or source not in self.adapters or target not in self.adapters:
            raise NotAvailable()
        if mode not in ('full_copy','attached_history'):
            raise NotAvailable()
        if target_chat is None and mode == 'attached_history':
            raise NotAvailable()
        try:
            observations = {source:self._observe(source,chat),target:self._observe(target,target_chat)}
        except KeyError:
            raise NotAvailable() from None
        source_ref = observations[source]['ref']
        if and_link:
            self._free(source,source_ref['id'],old_link_id)
            if target_chat is not None:
                self._free(target,observations[target]['ref']['id'],old_link_id)
        source_condition = observations[source]['condition']
        if not source_condition['exists'] or source_condition['replying']:
            raise NotAvailable()
        created = target_chat is None
        needs = ()
        payload = ()
        if created:
            facts = self.adapters[target].facts
            needs = ('app_closed',) if facts.write_window == WriteWindow.APP_CLOSED else ()
            if facts.new_chat_visible == Visibility.AFTER_RELAUNCH:
                needs += ('relaunch_to_see',)
            payload = tuple(for_created_chat(self._turns(observations[source]['turns']),facts))
        elif not observations[target]['condition']['exists']:
            raise NotAvailable()
        return self._plan(action='create' if created else 'link',source=source,target=target,mode=mode,
                          observations=observations,turns=payload,
                          name=title(source_ref['name'],source,title_tag) if created else '',
                          folder=source_ref['folder'] if created else '',needs=needs,
                          old_link_id=old_link_id,and_link=and_link)

    def already_linked_note(self, error: AlreadyLinked) -> dict:
        """Name the existing partner and expose the catalogue's change-link actions."""
        other = error.link.others(error.side)[0]
        values = {'name':self.adapters[error.side].locator.name(error.link.chat(error.side)),
                  'other_name':self.adapters[other].locator.name(error.link.chat(other)),
                  'tool':other}
        return get(error.note_id).to_dict(values)

    def plan_copy(self, from_side: str, from_chat: str, to_tool: str,
                  and_link: bool = False, title_tag: bool = True) -> LinkPlan:
        """Preview a complete new copy, optionally linked to its source."""
        plan = self._link_plan(from_side,from_chat,to_tool,None,'full_copy',title_tag,and_link=and_link)
        linked = self.store.link_for(from_side,plan.observations[from_side]['ref']['id'])
        if linked is not None and not and_link:
            observations,payload,_,record_snapshot = self._conversation(linked.id,from_side)
            data = asdict(plan)
            data.pop('plan_id')
            data['observations'].update(observations)
            data['turns'] = tuple(for_created_chat(payload,self.adapters[to_tool].facts))
            data['records'] = self._records()
            return self._plan(record_snapshot=record_snapshot,**data)
        return plan

    @staticmethod
    def _turns(values) -> list[Turn]:
        return [Turn(Message(**t['prompt']),tuple(Message(**m) for m in t['messages'])) for t in values]

    def _conversation(self, link_id: int, side: str):
        link = self.store.get_link(link_id)
        try:
            observations = {s:self._observe(s,c) for s,c in link.chats.items()}
        except KeyError:
            raise NotAvailable() from None
        if any(o['condition']['replying'] or not o['condition']['exists'] for o in observations.values()):
            raise NotAvailable()
        all_recorded = self.store.turns(link_id)
        for origin,observed in observations.items():
            known = set(self.store.local_ids(link_id,origin).values())
            known.update(t.origin_id for t in all_recorded if t.origin == origin)
            if any(t['prompt']['id'] not in known for t in observed['turns']):
                # Refresh records new completed turns; read-only previews must not omit them.
                raise ChatChanged()
        recorded = [t for t in all_recorded if t.states[side] not in (KEPT_BACK,SKIPPED)]
        originals = {s:{t.id:t for t in self._turns(o['turns'])} for s,o in observations.items()}
        try:
            resolved = canonical_sources(self.store, link_id, {s: list(v.values()) for s, v in originals.items()})
            payload = [resolved[t.id] for t in recorded]
        except KeyError:
            raise ChatChanged() from None
        from .applier import Applier
        payload = [Applier._local_turn(turn,link_id,record.id) for turn,record in zip(payload,recorded)]
        record_snapshot = {'link':asdict(link),'turns':[asdict(t) for t in all_recorded]}
        return observations,payload,tuple(t.id for t in recorded),record_snapshot

    def plan_full_copy(self, link_id: int, side: str, title_tag: bool = True) -> LinkPlan:
        """Preview a full visible twin from both origins, moving the existing link."""
        link = self.store.get_link(link_id)
        if link.removed_at or side not in link.sides:
            raise NotAvailable()
        observations,payload,turn_ids,record_snapshot = self._conversation(link_id,side)
        facts = self.adapters[side].facts
        needs = ('app_closed',) if facts.write_window == WriteWindow.APP_CLOSED else ()
        if facts.new_chat_visible == Visibility.AFTER_RELAUNCH:
            needs += ('relaunch_to_see',)
        mapped = tuple(for_created_chat(payload,facts))
        other = link.others(side)[0]
        ref = observations[side]['ref']
        return self._plan(record_snapshot=record_snapshot,action='full_copy',source=other,target=side,mode='full_copy',
                          observations=observations,turns=mapped,name=title(ref['name'],other,title_tag),
                          folder=ref['folder'],needs=needs,old_link_id=link_id,
                          turn_ids=turn_ids)

    def plan_relink(self, link_id: int, to_tool: str, to_chat: str | None = None,
                    mode: str = 'full_copy', from_side: str | None = None,
                    title_tag: bool = True) -> LinkPlan:
        """Preview replacing one partner while keeping both old chats intact."""
        link = self.store.get_link(link_id)
        if link.removed_at:
            raise NotAvailable()
        if from_side is None:
            remaining = [side for side in link.sides if side != to_tool]
            if len(remaining) != 1:
                raise NotAvailable()
            from_side = remaining[0]
        if from_side not in link.sides or from_side == to_tool:
            raise NotAvailable()
        return self._link_plan(from_side,link.chat(from_side),to_tool,to_chat,mode,title_tag,link_id)

    def plan_unlink(self, link_id: int) -> LinkPlan:
        """Preview removal of a live link while leaving its chats intact."""
        link = self.store.get_link(link_id)
        if link.removed_at:
            raise NotAvailable()
        observations = {s:self._observe(s,c,allow_missing=True,metadata_only=True) for s,c in link.chats.items()}
        return self._plan(action='unlink',source=link.sides[0],target=link.sides[1],mode=link.mode,
                          observations=observations,old_link_id=link_id)

    def _validate(self, plan: LinkPlan) -> None:
        data = asdict(plan)
        data.pop('plan_id')
        if _fingerprint(data) != plan.plan_id or self._records() != plan.records:
            raise ChatChanged()
        if self.store.journal_entries(pending=True):
            raise NotAvailable()
        self._check_observations(plan)

    def _check_observations(self, plan: LinkPlan) -> None:
        for side,observed in plan.observations.items():
            try:
                missing = observed.get('missing_chat_id')
                current = self._observe(side,missing or observed.get('ref',{}).get('id'),
                                        allow_missing=plan.action == 'unlink',
                                        metadata_only=bool(observed.get('metadata_only')))
            except KeyError:
                raise ChatChanged() from None
            if current != observed:
                raise ChatChanged()

    @staticmethod
    def _rows(source: str, target: str, source_turns, target_turns,
              shared_state: str = SHOWN) -> list[dict]:
        # Ordered matching keeps duplicate occurrences distinct and both local orders intact.
        matcher = SequenceMatcher(None,[content_key(t) for t in source_turns],
                                  [content_key(t) for t in target_turns],autojunk=False)
        rows = []
        a = b = 0
        def row(side,turn,other_id=None):
            local = {side:turn.id}
            states = {side:WRITTEN_HERE,(target if side == source else source):WAITING}
            if other_id is not None:
                local[target] = other_id
                states[target] = shared_state
            rows.append({'origin':side,'turn':turn,'local_ids':local,'states':states})
        for block in matcher.get_matching_blocks():
            for turn in source_turns[a:block.a]: row(source,turn)
            for turn in target_turns[b:block.b]: row(target,turn)
            for offset in range(block.size):
                row(source,source_turns[block.a+offset],target_turns[block.b+offset].id)
            a,b = block.a+block.size,block.b+block.size
        return rows

    def apply(self, plan: LinkPlan, plan_id: str | None = None) -> LinkResult:
        """Apply only a still-current preview, rolling back an uncommitted creation."""
        self._validate(plan)
        if plan_id is not None and plan_id != plan.plan_id:
            raise ChatChanged()
        if plan.action == 'unlink':
            self.store.remove_link(plan.old_link_id,self.clock.now())
            return LinkResult(plan.plan_id,True,link_id=plan.old_link_id)
        source_turns = self._turns(plan.observations[plan.source]['turns'])
        source_chat = plan.observations[plan.source]['ref']['id']
        entry = None
        try:
            if plan.action in ('create','full_copy'):
                adapter = self.adapters[plan.target]
                self.guard.check_write(adapter,None,action='create')
                entry = self.journal.begin(plan.old_link_id if plan.action == 'full_copy' else None,plan.target,None,'create')
                result = adapter.writer.create(plan.turns,plan.name,plan.folder)
                actual = adapter.reader.read(result.chat_id)
                if (result.receipt.tool,result.receipt.chat_id,result.receipt.kind) != (plan.target,result.chat_id,'create'):
                    raise ChatChanged()
                if ([content_key(t) for t in actual] != [content_key(t) for t in plan.turns] or
                        tuple(t.id for t in actual) != result.local_ids or
                        len(set(result.local_ids)) != len(result.local_ids)):
                    raise ChatChanged()
                self._check_observations(plan)
                if self._records() != plan.records:
                    raise ChatChanged()
                target_chat,target_turns = result.chat_id,actual
                state = SHOWN if adapter.facts.new_chat_visible == Visibility.AT_ONCE else ADDED
                receipt = asdict(result.receipt)
            else:
                target_chat = plan.observations[plan.target]['ref']['id']
                target_turns = self._turns(plan.observations[plan.target]['turns'])
                state,receipt = SHOWN,None
            rows = self._rows(plan.source,plan.target,source_turns,target_turns,state)
            if plan.action == 'full_copy':
                link = self.store.complete_link_copy(plan.old_link_id,plan.target,target_chat,
                                                     plan.turn_ids,result.local_ids,state,
                                                     self.clock.now(),entry,receipt)
                link_id = link.id
            elif plan.and_link:
                link = self.store.complete_link({plan.source:source_chat,plan.target:target_chat},
                                                 plan.mode,rows,self.clock.now(),entry,receipt,plan.old_link_id)
                link_id = link.id
            else:
                self.store.complete_copy(entry,receipt,self.clock.now())
                link_id = None
            return LinkResult(plan.plan_id,True,target_chat,link_id,plan.needs)
        except Exception as error:
            rollback_error,pending = '',None
            if entry is not None:
                self.journal.fail(entry,error)
                try:
                    self.journal.take_back(entry)
                except Exception as rollback:
                    rollback_error,pending = type(rollback).__name__,entry
            return LinkResult(plan.plan_id,False,error=type(error).__name__,
                              rollback_error=rollback_error,pending_entry=pending)

    def copy_status(self, tool: str, chat_id: str) -> dict:
        """Keep a deferred copy visibility instruction until a later app start."""
        adapter = self.adapters[tool]
        ref = adapter.locator.resolve(chat_id)
        info = self.store.copy_info(tool,chat_id) or self.store.copy_info(tool,ref.id)
        if info is None:
            raise NotAvailable()
        shown = bool(info['shown']) or adapter.facts.new_chat_visible == Visibility.AT_ONCE
        if not shown:
            try:
                started = datetime.fromisoformat(adapter.state.condition(ref.id).app_started_at)
                delivered = datetime.fromisoformat(info['delivered_at'])
                shown = bool(started.tzinfo and delivered.tzinfo) and started > delivered
            except (ValueError,TypeError):
                pass
        if shown:
            self.store.mark_copy_shown(tool,info['chat_id'],self.clock.now())
        return {'chat':ref,'shown':shown,'needs':() if shown else ('relaunch_to_see',)}

    def suggestions(self) -> list[dict]:
        """Suggest unlinked pairs by ordered public-content matches, never counts alone."""
        result = []
        for (a,first),(b,second) in combinations(self.adapters.items(),2):
            for left in first.locator.chats():
                if self.store.link_for(a,left.id): continue
                one = [content_key(t) for t in first.reader.read(left.id)]
                for right in second.locator.chats():
                    if self.store.link_for(b,right.id): continue
                    two = [content_key(t) for t in second.reader.read(right.id)]
                    matched = sum(block.size for block in SequenceMatcher(None,one,two,autojunk=False).get_matching_blocks())
                    if matched:
                        result.append({'a':(a,left),'b':(b,right),'matched_turns':matched})
        return result
