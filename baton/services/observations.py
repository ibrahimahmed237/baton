"""Shared chat observations and stable delivery identities."""
from __future__ import annotations
from dataclasses import replace
from typing import Mapping, Sequence
from ..domain.conditions import SideCondition
from ..domain.model import Turn, turn_extends
from ..domain.errors import ChatChanged, NotAvailable
from ..ports.store import RecordStore
from ..ports.tool import ToolAdapter
from .mapping import content_key


def verified_source(store: RecordStore, link_id: int, row, actual: Turn | None,
                    evidence: Mapping[int, dict] | None = None) -> Turn:
    """Require a complete verified origin whose public content still matches."""
    saved = (store.turn_evidence(link_id) if evidence is None else evidence).get(row.id)
    if actual is None:
        raise ChatChanged()
    if saved is None or not saved['verified']:
        raise NotAvailable('unverified_turn_baseline')
    if content_key(saved['turn']) != content_key(actual):
        raise ChatChanged()
    if not saved['complete']:
        raise NotAvailable()
    return actual


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
    """Validate origins, using archives only for removal sanctioned by an undo."""
    rows = store.turns(link_id)
    link = store.get_link(link_id)
    evidence = store.turn_evidence(link_id)
    live = {s: {t.id: t for t in values} for s, values in observed.items()}
    events = store.history(link_id)
    # The latest native undo/restore snapshot decides which absent origins are
    # intentional. An older undo must not conceal deletion after a restore.
    sanctioned = set()
    checked = set()
    for event in events:
        if event.kind not in ('undo', 'restore'):
            continue
        for side, value in event.detail.get('after', {}).items():
            if side in checked or value.get('chat_id') != link.chats.get(side):
                continue
            checked.add(side)
            present = {t.id for t in decode_turns(value['turns'])}
            sanctioned.update(row.id for row in rows
                              if row.origin == side and row.origin_id not in present)
    archived = {}
    for event in events:
        if event.kind != 'undo':
            continue
        before = event.detail.get('before', {})
        chats = event.detail.get('before_chats', {})
        saved = {s: {t.id: t for t in decode_turns(value['turns'])}
                 for s, value in chats.items() if ':' not in s}
        for row in before.get('turns', ()):
            if row['id'] not in sanctioned:
                continue
            source = saved.get(row['origin'], {}).get(row['origin_id'])
            if source is not None:
                archived.setdefault(row['id'], source)
    sources = {}
    for row in rows:
        actual = live.get(row.origin, {}).get(row.origin_id) or archived.get(row.id)
        if actual is None:
            if row.origin in observed:
                raise ChatChanged()
            continue
        saved = evidence.get(row.id)
        if saved and saved['verified']:
            matches = (content_key(saved['turn']) == content_key(actual) if saved['complete']
                       else turn_extends(saved['turn'], actual))
            if not matches:
                raise ChatChanged()
        sources[row.id] = actual
    return sources
