"""Reconcile native content, names and explicit visibility evidence."""
from __future__ import annotations
from dataclasses import replace
from typing import Mapping
from ..domain.link import ADDED, SHOWN
from ..ports.clock import Clock
from ..ports.store import RecordStore
from ..ports.tool import ToolAdapter
from .mapping import content_key, for_target
from .observations import canonical_sources, condition, initial_history_sides
from .status import link_status, visible_added_turn_ids


class ChatRefresh:
    """Refresh durable state through the store without inferring screen visibility."""
    def __init__(self, store: RecordStore, adapters: Mapping[str, ToolAdapter], clock: Clock):
        self.store, self.adapters, self.clock = store, adapters, clock

    def refresh(self, link_id: int) -> dict:
        """Reconcile fresh names, content and visibility evidence with turn states."""
        link = self.store.get_link(link_id)
        observed = {}
        names = {}
        missing = []
        for side, chat in link.chats.items():
            adapter = self.adapters[side]
            try:
                ref = adapter.locator.resolve(chat)
            except KeyError:
                missing.append(side)
                continue
            if not adapter.state.condition(ref.id).exists:
                missing.append(side)
                continue
            if ref.id != chat:
                self.store.move_link(link_id, side, ref.id, at=self.clock.now())
            names[side] = ref.name
            observed[side] = adapter.reader.read(ref.id)
        sources = canonical_sources(self.store, link_id, observed)
        for side, values in observed.items():
            local_ids = self.store.local_ids(link_id, side)
            read = {t.id: t for t in values}
            bypassed = []
            for recorded in self.store.turns(link_id):
                if recorded.states.get(side) not in (ADDED, SHOWN):
                    continue
                actual = read.get(local_ids.get(recorded.id))
                source = sources.get(recorded.id)
                if actual is None or source is None or content_key(actual) != content_key(source):
                    bypassed.append(recorded.id)
            self.store.reset_delivery(link_id, side, bypassed, self.clock.now())
            self.store.record_turns(link_id, side, values)
        link = self.store.get_link(link_id)
        conditions = {s: condition(self.adapters,s,c) for s,c in link.chats.items()}
        facts = {s: self.adapters[s].facts for s in link.sides}
        for side in link.sides:
            if side in missing:
                continue
            shown = visible_added_turn_ids(self.store.turns(link_id), side, facts[side],
                                           conditions[side], self.store.history(link_id))
            self.store.mark_shown(link_id, side, shown)
        turns = self.store.turns(link_id)
        return {'link': link, 'status': link_status(link, turns, conditions, facts=facts,
                                                  history=self.store.history(link_id),
                                                  initial_history_sides=initial_history_sides(self.store,link,observed)),
                'names': names, 'turns': turns,
                'messages': {s: [for_target(t, replace(facts[s], replays_tool_calls=True)) for t in values]
                             for s,values in observed.items()}, 'checked_at': self.clock.now(),
                'missing': tuple(missing)}
