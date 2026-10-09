"""Build and fingerprint immutable confirmations from observed chats and records."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256
import json
from typing import Collection, Mapping, Sequence

from ..domain.errors import ChatChanged, NotAvailable
from ..domain.model import Turn
from ..ports.store import RecordStore
from ..ports.tool import ToolAdapter
from .mapping import for_target
from .planner import plan_sync
from .observations import condition, initial_history_sides, local_turn

from .delivery_plan import ApplyStep, PreparedPlan


class PreviewBuilder:
    """Observe and confirm without writing chats or mutating links."""
    def __init__(self, store: RecordStore, adapters: Mapping[str, ToolAdapter]):
        self.store, self.adapters = store, adapters

    def _condition(self, side, chat):
        return condition(self.adapters, side, chat)

    def _initial_history_sides(self, link, observed):
        return initial_history_sides(self.store, link, observed)

    _local_turn = staticmethod(local_turn)

    def _record(self, link_id: int | None) -> dict:
        if link_id is None:
            return {}
        return {'link': asdict(self.store.get_link(link_id)),
                'turns': [asdict(t) for t in self.store.turns(link_id)],
                'history': [asdict(e) for e in self.store.history(link_id)]}


    def _snapshot(self, side: str, chat_id: str) -> dict:
        adapter = self.adapters[side]
        ref = adapter.locator.resolve(chat_id)
        return {'chat_id': ref.id, 'ref': asdict(ref),
                'turns': [asdict(t) for t in adapter.reader.read(ref.id)],
                'condition': asdict(self._condition(side, ref.id)),
                'facts': {k: getattr(v, 'value', v) for k,v in asdict(adapter.facts).items()}}


    def prepare(self, link_id: int | None, steps: Sequence[ApplyStep],
                chats: Mapping[str, str], decision_needed: bool = False) -> PreparedPlan:
        """Fingerprint complete planned actions, chat contents and current records."""
        snapshots = {side: self._snapshot(side, chat) for side, chat in chats.items()}
        record = self._record(link_id)
        if link_id is not None and any(record['link']['chats'].get(side) != snapshot['chat_id']
                                       for side, snapshot in snapshots.items()):
            raise ChatChanged()
        steps = tuple(deepcopy(list(steps)))
        data = {'link_id': link_id, 'steps': [asdict(s) for s in steps],
                'snapshots': snapshots, 'record': record, 'decision_needed': decision_needed}
        plan_id = 'p_' + sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        return PreparedPlan(plan_id, link_id, steps, snapshots, record, decision_needed)


    def preview(self, link_id: int, add_when_idle: Collection[str] = ()) -> PreparedPlan:
        """Build delivery actions from freshly observed whole turns and facts."""
        link = self.store.get_link(link_id)
        if link.removed_at:
            raise NotAvailable()
        for side, chat in link.chats.items():
            try:
                canonical = self.adapters[side].locator.resolve(chat).id
            except KeyError:
                continue
            if canonical != chat:
                # Refresh records moved chats; a preview must not silently mutate a link.
                raise ChatChanged()
        conditions = {s: self._condition(s, c) for s, c in link.chats.items()}
        facts = {s: self.adapters[s].facts for s in link.sides}
        observed = {s: self.adapters[s].reader.read(c) for s,c in link.chats.items()}
        plan = plan_sync(link, self.store.turns(link_id), conditions,
                         add_when_idle=add_when_idle, facts=facts,
                         initial_history_sides=self._initial_history_sides(link, observed),
                         history=self.store.history(link_id))
        source = {s: {t.id: t for t in values} for s, values in observed.items()}
        steps = []
        for step in plan.steps.values():
            turns = []
            for recorded in step.turns:
                try:
                    original = source[recorded.origin][recorded.origin_id]
                except KeyError:
                    raise ChatChanged() from None
                if (conditions[recorded.origin].replying and observed[recorded.origin]
                        and original.id == observed[recorded.origin][-1].id):
                    raise NotAvailable()
                mapped = for_target(original, facts[step.side])
                turns.append(self._local_turn(mapped, link_id, recorded.id))
            steps.append(ApplyStep(step.side, step.action, tuple(t.id for t in step.turns),
                                   tuple(turns), step.reason, step.needs, alternatives=step.alternatives))
        prepared = self.prepare(link_id, steps, link.chats, plan.decision_needed)
        for side in link.sides:
            # A changed read during preview must not confirm an older mapped payload.
            snapshot = prepared.snapshots[side]
            current_facts = {k: getattr(v, 'value', v) for k,v in asdict(facts[side]).items()}
            if (snapshot['turns'] != [asdict(t) for t in observed[side]] or
                    snapshot['condition'] != asdict(conditions[side]) or
                    snapshot['facts'] != current_facts):
                raise ChatChanged()
        return prepared
