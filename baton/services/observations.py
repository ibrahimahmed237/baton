"""Shared chat observations and stable delivery identities."""
from __future__ import annotations
from dataclasses import replace
from typing import Mapping, Sequence
from ..domain.conditions import SideCondition
from ..domain.model import Turn
from ..ports.store import RecordStore
from ..ports.tool import ToolAdapter

def condition(adapters: Mapping[str, ToolAdapter], side: str, chat: str) -> SideCondition:
    """Combine current chat state with the adapter's checked-format evidence."""
    adapter = adapters[side]
    condition = adapter.state.condition(chat)
    return replace(condition, format_known=condition.format_known and adapter.state.format_version().known)


def initial_history_sides(store: RecordStore, link, observed: Mapping[str, Sequence[Turn]]) -> tuple[str, ...]:
    """Identify empty attached-history sides that have never received delivery."""
    if link.mode != 'attached_history':
        return ()
    delivered = {e.side for e in store.history(link.id)
                 if e.kind in ('attached', 'add', 'create', 'place', 'shown', 'added', 'delivered')}
    return tuple(s for s in link.sides if not observed.get(s) and s not in delivered)


def local_turn(turn: Turn, link_id: int, turn_id: int) -> Turn:
    """Assign stable delivery message identities while preserving turn content."""
    ids = {message.id: f'baton_{link_id}_{turn_id}_{index}'
           for index, message in enumerate((turn.prompt, *turn.messages))}
    return Turn(replace(turn.prompt, id=ids[turn.prompt.id]), tuple(
        replace(m, id=ids[m.id], call_id=ids.get(m.call_id, m.call_id)) for m in turn.messages))


def decode_turns(values) -> list[Turn]:
    """Rebuild turns from the serialized content stored in preview snapshots."""
    from ..domain.model import Message
    return [Turn(Message(**t['prompt']), tuple(Message(**m) for m in t['messages'])) for t in values]


def canonical_sources(store: RecordStore, link_id: int,
                      observed: Mapping[str, Sequence[Turn]]) -> dict[int, Turn]:
    """Resolve original content from active chats or saved pre-undo observations."""
    rows = store.turns(link_id)
    live = {s: {t.id: t for t in values} for s, values in observed.items()}
    archived = {}
    for event in store.history(link_id):
        if event.kind != 'undo':
            continue
        before = event.detail.get('before', {})
        chats = event.detail.get('before_chats', {})
        saved = {s: {t.id: t for t in decode_turns(value['turns'])}
                 for s, value in chats.items() if ':' not in s}
        for row in before.get('turns', ()):
            source = saved.get(row['origin'], {}).get(row['origin_id'])
            if source is not None:
                archived.setdefault(row['id'], source)
    return {row.id: live.get(row.origin, {}).get(row.origin_id) or archived[row.id]
            for row in rows if row.origin_id in live.get(row.origin, {}) or row.id in archived}
