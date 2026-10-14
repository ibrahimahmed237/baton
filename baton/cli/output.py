"""Results and errors as the shared objects of docs/plan/CONTRACT.md.

Every function returns plain dicts and lists ready for `json.dumps`. Words for
the user come from the note catalogue only; this module never writes a sentence
of its own.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Iterable, Mapping, Sequence

from ..domain.conditions import SideCondition
from ..domain.errors import BatonError
from ..domain.link import LedgerTurn
from ..domain.model import Message
from ..notes.catalogue import CATALOGUE
from ..ports.tool import ChatRef, Usage
from ..services.status import SideStatus
from .tools import LABELS, label

logger = logging.getLogger(__name__)

# What the user is told about a crash or a refusal that has no note of its own.
UNEXPECTED = "error.unexpected"

# The same rough estimate services.status uses to size what a message carries.
CHARS_PER_TOKEN = 4

# Note ids whose {tool} is a tool call's name, not a coding app (CONTRACT.md, F2).
_NOT_APP_LABELS = ("mapping.",)


# Notes

def note(note_id: str, values: Mapping[str, Any] | None = None, *, lenient: bool = False) -> dict[str, Any]:
    """Render a catalogue note; values naming a coding app are replaced by its display label.

    Raises KeyError for an unknown id or a missing value, unless `lenient`, which
    fills a missing value with nothing.
    """
    values = app_labels(note_id, values or {})
    definition = CATALOGUE[note_id]
    if not lenient:
        return definition.to_dict(values)
    blanks = {name: "" for name in definition.fields if name not in values}
    return {**definition.to_dict({**blanks, **values}), "values": dict(values)}


def app_labels(note_id: str, values: Mapping[str, Any]) -> dict[str, Any]:
    """Replace tool ids in `tool`, `other_tool`, `first_tool` ... by the display label."""
    if note_id.startswith(_NOT_APP_LABELS):
        return dict(values)
    return {key: LABELS.get(value, value) if _names_a_tool(key, value) else value
            for key, value in values.items()}


def _names_a_tool(key: str, value: Any) -> bool:
    return (key == "tool" or key.endswith("_tool")) and isinstance(value, str)


def note_list(items: Iterable[tuple[str, Mapping[str, Any]] | str]) -> list[dict[str, Any]]:
    """Render a list of note ids, or (id, values) pairs."""
    result = []
    for item in items:
        note_id, values = (item, None) if isinstance(item, str) else item
        result.append(note(note_id, values))
    return result


# Shared objects

def chat(tool: str, chat_id: str, name: str, folder: str, updated_at: str,
         linked: bool = False, link_id: int | None = None) -> dict[str, Any]:
    """Chat: one chat in one tool. A missing chat is built from its last known name."""
    return {"tool": tool, "tool_label": label(tool), "id": chat_id, "name": name, "folder": folder,
            "updated_at": updated_at, "linked": linked, "link_id": link_id}


def chat_from_ref(tool: str, ref: ChatRef, linked: bool = False, link_id: int | None = None) -> dict[str, Any]:
    """Chat for a chat a locator found."""
    return chat(tool, ref.id, ref.name, ref.folder, ref.updated_at, linked, link_id)


def side_condition(value: SideCondition) -> dict[str, Any]:
    """Side.condition, with the additive CP1 fields."""
    return {"exists": value.exists, "open": value.open, "replying": value.replying,
            "hooks_ready": value.hooks_ready, "app_running": value.app_running,
            "app_started_at": value.app_started_at, "format_known": value.format_known,
            **({"format_new_version": True} if getattr(value, "format_new_version", False) else {})}


def message(value: Message) -> dict[str, Any]:
    """One entry of Turn.messages. A tool name is given for tool calls and results only."""
    result = {"kind": value.kind, "text": value.text}
    if value.tool:
        result["tool"] = value.tool
    return result


def turn(value: LedgerTurn, messages: Sequence[Message] | None = None) -> dict[str, Any]:
    """Turn: one turn of a linked conversation. `messages` only when the caller asked for them."""
    result: dict[str, Any] = {
        "id": value.id, "seq": value.seq, "origin": value.origin, "first_line": value.first_line,
        "started_at": value.started_at, "ended_at": value.ended_at or None,
        "tokens": value.size // CHARS_PER_TOKEN, "pinned": value.pinned, "states": dict(value.states)}
    if messages is not None:
        result["messages"] = [message(item) for item in messages]
    return result


def side_usage(value: Usage) -> dict[str, Any]:
    """Side.usage: tokens in use, the size if known, the percent, and the limit if one was hit."""
    from ..services.usage import SideUsage, context_use, limit_state
    return SideUsage('', context_use(value), limit_state(value, ''), ()).as_contract()



def since_you_left(turns: int, files: int, commands: int, since: str) -> dict[str, Any]:
    """Side.since_you_left."""
    return {"turns": turns, "files": files, "commands": commands, "since": since}


def next_message(status: SideStatus) -> dict[str, int]:
    """Side.next_message: what the next message in that chat would carry."""
    return {"turns": status.attached_on_next_message, "tokens": status.attached_tokens}


def side(status: SideStatus, *, chat_info: Mapping[str, Any], condition: SideCondition,
         usage: Mapping[str, Any], since: Mapping[str, Any] | None = None,
         notes: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
    """Side: where one side of a link stands."""
    return {
        "tool": status.side, "tool_label": label(status.side), "chat": dict(chat_info),
        "condition": side_condition(condition),
        "total": status.total, "agent_has": status.agent_has, "chat_shows": status.chat_shows,
        "added": status.added, "attached": status.attached, "waiting": status.waiting,
        "kept_elsewhere": status.kept_elsewhere, "skipped": status.skipped,
        "synced_up_to": turn(status.synced_up_to) if status.synced_up_to else None,
        "waiting_reason": status.waiting_reason or None,
        "next_message": next_message(status), "usage": dict(usage),
        "since_you_left": dict(since) if since else None,
        "notes": [dict(item) for item in notes]}


def step(tool: str, action: str, turn_ids: Iterable[int], *, reason: str = "",
         needs: Iterable[str] = (), notes: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
    """Step: what a plan does to one side."""
    return {"tool": tool, "tool_label": label(tool), "action": action, "turns": list(turn_ids),
            "reason": reason, "needs": list(needs), "notes": [dict(item) for item in notes]}


def plan(plan_id: str, link_id: int | None, steps: Sequence[Mapping[str, Any]], *,
         decision_needed: bool = False, notes: Sequence[Mapping[str, Any]] = (),
         applied: bool = False, **extra: Any) -> dict[str, Any]:
    """Plan: what an action would do. `extra` adds a command's own fields (removes, brief ...)."""
    return {"plan_id": plan_id, "applied": applied, "link_id": link_id,
            "steps": [dict(item) for item in steps], "decision_needed": decision_needed,
            "notes": [dict(item) for item in notes], **extra}


# Errors

def snake_case(name: str) -> str:
    """ChatChanged -> chat_changed."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def error(failure: BatonError, values: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The error object for an expected refusal: its kind and the note that explains it.

    A refusal with no catalogue note gets the plain `error.unexpected` note; what
    the exception said goes to the log, never to the user.
    """
    shown = {**getattr(failure, "values", {}), **(values or {})}
    if getattr(failure, "side", None):
        shown.setdefault("tool", failure.side)
    if hasattr(failure, 'at') and failure.note_id == 'keep.too_late':
        shown.update(other_tool=failure.side, at=failure.at)
    try:
        explained = note(failure.note_id, shown, lenient=True)
    except KeyError:
        logger.warning("no note for %s (%r): %s", type(failure).__name__, failure.note_id, failure)
        explained = note(UNEXPECTED)
    return {"error": {"kind": snake_case(type(failure).__name__), "note": explained}}


def internal_error(failure: BaseException) -> dict[str, Any]:
    """The error object for a crash: the plain note only. The details are logged by the caller."""
    return {"error": {"kind": "internal", "note": note(UNEXPECTED)}}


def usage_error(note_id: str, values: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The error object for a command line that could not be understood."""
    explained = note(note_id if note_id in CATALOGUE else "cli.usage", values)
    return {"error": {"kind": "usage", "message": explained["text"], "note": explained}}


# C2 read projections: domain objects enter here; only catalogue text leaves.
def read_chat(item):
    """Serialize a locator reference and its observed link ownership."""
    link = item['link']
    return chat_from_ref(item['tool'], item['ref'], bool(link), link.id if link else None)


def link_summary(fresh):
    """Serialize a link headline including outstanding visibility instructions."""
    link, state = fresh['link'], fresh['status']
    from ..services.status import link_headline
    return {'link_id': link.id,
            'sides': {s: chat_from_ref(s, fresh['refs'][s], True, link.id) for s in link.sides},
            'mode': link.mode, 'paused': link.paused, 'headline': note(*link_headline(state, fresh['missing'])),
            'in_sync': state.in_sync and not fresh['missing'], 'decision_needed': state.decision_needed,
            'needs_attention': bool(fresh['missing'] or state.paused or state.decision_needed or not state.in_sync
                                    or any(s.needs for s in state.sides.values()))}


def read_status(fresh, with_messages=False):
    """Serialize canonical public status and explicit reached receipts."""
    link, state = fresh['link'], fresh['status']
    sides = {}
    for tool in link.sides:
        sides[tool] = side(state.side(tool), chat_info=chat_from_ref(tool, fresh['refs'][tool], True, link.id),
                           condition=fresh['conditions'][tool], usage=fresh['usage'][tool],
                           since=fresh['digests'][tool], notes=note_list(fresh['side_notes'][tool]))
        if tool in fresh['coverage']:
            sides[tool]['summary_coverage'] = fresh['coverage'][tool]
    turns = [turn(row, fresh['canonical_messages'].get(row.id, ()) if with_messages else None)
             for row in fresh['turns']]
    boundaries = {}
    for tool, value in state.sides.items():
        if value.synced_up_to:
            boundaries.setdefault(value.synced_up_to.id, []).append(tool)
    receipts = []
    for ident, tools in boundaries.items():
        row = next(t for t in fresh['turns'] if t.id == ident)
        if len(tools) == len(link.sides) and all(row.states[t] in ('shown', 'written_here') for t in tools):
            receipts.append(note('screen.received_both', {'seq': row.seq}))
        else:
            receipts.extend(note('screen.received_one' if row.states[t] in ('shown', 'written_here') else
                                 'screen.received_hidden_tool', {'tool': t, 'seq': row.seq}) for t in tools)
    return {'link_id': link.id, 'mode': link.mode, 'paused': link.paused,
            'in_sync': state.in_sync and not fresh['missing'], 'decision_needed': state.decision_needed,
            'sides': sides, 'turns': turns, 'notes': [link_summary(fresh)['headline'],
              note('status.checked', {'at': fresh['checked_at']}), *receipts]}


def read_setup(items):
    """Render setup facts, findings and mode labels from the catalogue."""
    result = []
    for item in items:
        row = {**item, 'tool_label': label(item['tool']),
               'findings': [{**f, 'note': note(*f['note'])} for f in item['findings']]}
        if (item.get('version') and item['version'] not in item['facts'].get('checked_versions', ())
                and any(f['id'] == 'format' and f['ok'] for f in item['findings'])):
            row['format_new_version'] = True
            row['findings'].append({'id': 'new_version', 'ok': True,
                                    'note': note('format.new_version', {'tool': item['tool'], 'version': item['version']})})
        row['link_modes'] = [{**mode, 'label': note(*mode['label']), 'tag': None,
                              'reason': note(*mode['reason']) if mode['reason'] else None}
                             for mode in item['link_modes']]
        result.append(row)
    return {'tools': result, 'notes': note_list(('dialog.link', 'dialog.target', 'dialog.target_chat',
             'dialog.new_chat', 'dialog.retained_side', 'dialog.ways', 'dialog.what_will_happen', 'dialog.actions'))}


def read_merge(value):
    """Serialize merge rows and string preset labels without private messages."""
    from ..domain.model import PROMPT, REPLY, TOOL_CALL, TOOL_RESULT, TOOL_TEXT
    rows = []
    for row in value['unsynced']:
        actual = value['messages'][row.id]
        public = [m for m in (actual.prompt, *actual.messages) if m.kind in (PROMPT, REPLY, TOOL_CALL, TOOL_RESULT, TOOL_TEXT)]
        rows.append(turn(row, public))
    presets = []
    for preset in value['presets']:
        ident = preset['id']
        title = note('merge.preset_time' if ident == 'by_time' else 'merge.preset_keep' if ident == 'dont_reorder'
                     else 'merge.preset_first', {'tool': ident.removesuffix('_first')})
        presets.append({**preset, 'label': title['text'], 'label_note': title})
    return {**{k: v for k, v in value.items() if k not in ('last_shared', 'unsynced', 'messages', 'presets')},
            'last_shared': turn(value['last_shared']) if value['last_shared'] else None,
            'unsynced': rows, 'presets': presets, 'notes': note_list(value.get('notes', ())) if 'notes' in value else note_list(('merge.decision_needed',)) if value.get('decision_needed') else []}


_HISTORY = {'linked': 'history.linked', 'add': 'history.added', 'added': 'history.added',
            'delivered': 'history.added', 'synced': 'history.added', 'place': 'history.added',
            'attached': 'history.attached', 'create': 'history.created', 'created': 'history.created',
            'twin_created': 'history.created', 'merge': 'history.merged', 'undo': 'history.undone',
            'restore': 'history.restored', 'paused': 'history.paused', 'resumed': 'history.resumed',
            'unlinked': 'history.removed', 'removed': 'history.removed', 'link_removed': 'history.removed',
            'moved': 'history.moved', 'link_moved': 'history.moved',
            'brief': 'history.brief', 'aligned': 'history.aligned',
            'attach_pending': 'history.attach_pending', 'not_confirmed': 'history.not_confirmed',
            'undo_shown': 'history.undo_shown'}


def read_history(items):
    """Label completed actions and bookkeeping without changing their records or eligibility."""
    events = []
    for item in items:
        event = item['event']
        ident = _HISTORY.get(event.kind, 'history.recorded')
        if event.kind in ('aligned', 'attach_pending', 'not_confirmed') and len(event.turn_ids) == 1:
            ident += '_one'
        rendered = note(ident, {'tool': event.side, 'n': len(event.turn_ids)})
        events.append({'id': event.id, 'at': event.at, 'kind': event.kind, 'tool': event.side or None,
                       'turns': list(event.turn_ids), 'text': rendered['text'],
                       'can_undo': item['can_undo'], 'can_restore': item['can_restore'],
                       'label': rendered, 'undo_label': note('history.undo_action'),
                       'restore_label': note('history.restore_action'), 'tool_label': label(event.side) if event.side else None})
    return {'events': events, 'notes': [] if events else note_list(('history.empty',))}


def read_settings(values, defaults):
    """Serialize current values and labels for the authoritative defaults."""
    notes = []
    for key, value in defaults.items():
        data = {'key': key, 'tool': 'claude'} if key == 'add_to_idle_claude' else {'key': key}
        notes.append(note('settings.' + key, data))
        if isinstance(value, bool):
            default = note('settings.on' if value else 'settings.off')['text']
        elif key == 'theme':
            default = note('screen.theme.' + value)['text']
        elif key in ('merge', 'add_to_idle_claude'):
            default = note('settings.' + value)['text']
        else:
            default = str(value)
        notes.append(note('settings.default', {'key': key, 'value': default}))
    notes.extend(note_list(('settings.appearance', 'settings.sync', 'settings.chats', 'settings.reset', 'settings.on',
              'settings.off', 'settings.on_button', 'settings.automatic', 'settings.ask', 'settings.by_time',
              'screen.theme.system', 'screen.theme.light', 'screen.theme.graphite', 'settings.glass_help',
              'settings.apply', 'settings.saved', 'settings.error', 'settings.invalid', 'settings.loading')))
    return {'settings': values, 'notes': notes}


def merge_plan(value, service):
    """Serialize the merge fingerprint, never the underlying delivery fingerprint."""
    notes = note_list(value.notes)
    steps = []
    for item in value.delivery.steps:
        extra = []
        if 'app_closed' in item.needs:
            notice = note('write.app_must_close', {'tool': item.side, 'n': len(item.turn_ids), 'button_ids': []})
            extra.append(notice)
        steps.append(step(item.side, item.action, item.turn_ids, needs=item.needs, reason=item.reason, notes=extra))
    unavailable = any(s.action == 'hold' or 'app_closed' in s.needs for s in value.delivery.steps)
    confirmation = note('plan.unavailable' if unavailable else 'plan.confirm_split' if value.split
                        else 'plan.confirm_keep' if value.keep else 'plan.confirm_merge', {'tool': value.keep})
    return plan(value.plan_id, value.delivery.link_id, steps, notes=notes, confirmation=confirmation,
                order=list(value.order), preset=value.preset, keep=value.keep, split=value.split,
                mismatch_note=note('write.chat_changed'))


def undo_plan(value):
    """Render per-side undo notes, removals and headings from the service boundary."""
    notes, groups = [], []
    rows = {r['id']: LedgerTurn(**r) for r in value.record['turns']}
    side_notes = value.detail.get('notes_by_side', {})
    for side in dict.fromkeys(s.side for s in value.steps):
        removed = [r for r in value.removes if r['side'] == side]
        end = value.ends_at.get(side)
        values = {'tool': side, 'n': len(removed), 'days': 30,
                  'first_line': (end.get('first_line') or end.get('prompt', {}).get('text', '').split('\n')[0]) if end else '',
                  'at': (end.get('started_at') or end.get('prompt', {}).get('at', '')) if end else ''}
        for ident in side_notes.get(side, value.notes):
            data = dict(values)
            if ident == 'undo.only_here':
                data['n'] = sum(r['only_here'] for r in removed)
            rendered = note(ident, data, lenient=True)
            if rendered not in notes:
                notes.append(rendered)
        for category, ident in (('added', 'undo.group_added'), ('written', 'undo.group_written')):
            members = [r for r in removed if (r['turn']['origin'] == side) == (category == 'written')]
            if members:
                groups.append({'tool': side, 'category': category, 'heading': note(ident, {'tool': side}),
                               'removes': [{'turn': turn(LedgerTurn(**r['turn'])), 'only_here': r['only_here'], 'tool': side}
                                           for r in members]})
    for ident in value.notes:
        if ident == 'undo.merge' and not any(n['id'] == ident for n in notes):
            notes.append(note(ident))
    if value.operation == 'undo' and any(s.action == 'move_link' for s in value.steps):
        notes.append(note('plan.confirm_undo'))
    end_id = next((s.turn_ids[-1] for s in value.steps if s.turn_ids), None)
    return plan(value.plan_id, value.link_id,
                [step(s.side, s.action, s.turn_ids, needs=s.needs) for s in value.steps], notes=notes,
                removes=[{'turn': turn(LedgerTurn(**r['turn'])), 'only_here': r['only_here'], 'tool': r['side']}
                         for r in value.removes], removal_groups=groups,
                ends_at=turn(rows[end_id]) if end_id in rows and value.ends_at else None)


def action_receipt(value, result):
    """Add service result fields without interpreting a write outcome."""
    for key in ('link_id', 'chat_id', 'event_id', 'needs', 'rollback_error', 'pending_entry',
                'opened', 'waiting', 'completed_links', 'reopen_error'):
        if hasattr(result, key):
            item = getattr(result, key)
            value[key] = list(item) if key in ('needs', 'completed_links') else item
    lifecycle_notes = []
    receipt = result
    while receipt is not None:
        lifecycle_notes.extend(note_list(getattr(receipt, 'notes', ())))
        if getattr(receipt, 'reopen_error', ''):
            value['opened'] = False
            value['reopen_error'] = receipt.reopen_error
        receipt = getattr(receipt, 'write_result', None)
    value['notes'] = [*value.get('notes', ()), *[n for n in lifecycle_notes if n not in value.get('notes', ())]]
    if getattr(result, 'error', ''):
        value['error'] = {'kind': snake_case(result.error),
                          'note': lifecycle_notes[0] if lifecycle_notes else note('error.unexpected')}
    return value


def unlink_action_plan(value):
    """Render removal notes solely from the immutable metadata plan."""
    refs = [value.observations[s].get('ref', {}) for s in (value.source, value.target)]
    record = next(r for r in value.records if r['link']['id'] == value.old_link_id)
    notes = []
    for side in record['link']['chats']:
        waiting = sum(t['states'].get(side) in ('waiting', 'attach_pending') for t in record['turns'])
        notes.append(note('link.remove', {'name': refs[0].get('name', ''),
                         'other_name': refs[1].get('name', ''), 'tool': side, 'n': waiting}))
    return plan(value.plan_id, value.old_link_id, [], notes=notes,
                confirmation=note('plan.confirm_unlink'))


def sync_action_plan(value, status):
    """Serialize chosen delivery steps and the status service's explanations."""
    notes = read_status(status)['notes']
    notes.append(note('plan.confirm_sync'))
    steps = []
    for item in value.steps:
        rendered = note_list(status['side_notes'][item.side])
        for need in item.needs:
            if need in ('reopen_chat_to_see', 'relaunch_to_see') and not any(n['id'] == need for n in rendered):
                rendered.append(note(need, {'tool': item.side, 'n': len(item.turn_ids)}))
        steps.append(step(item.side, item.action, item.turn_ids, reason=item.reason,
                          needs=item.needs, notes=rendered))
        for entry in rendered:
            if entry not in notes:
                notes.append(entry)
    return plan(value.plan_id, value.link_id, steps, notes=notes,
                decision_needed=value.decision_needed,
                confirmation=note('plan.unavailable' if value.decision_needed else 'plan.confirm_sync'))


def background_brief_plan(value):
    """Keep E10's exact staged approval and review text."""
    return plan(value.plan_id, value.link_id,
                [step(s.side, s.action, s.turn_ids, needs=s.needs) for s in value.steps],
                notes=note_list(value.notes), stage=value.stage, brief=value.as_contract(),
                confirmation=note(*value.confirmation))


def background_status(value):
    """Pending/running states and completed immutable results share a poll envelope."""
    value = dict(value)
    if value.get('result', {}).get('error') and 'note' not in value['result']['error']:
        failure = value['result']['error']
        value['result'] = {**value['result'], 'error': {**failure,
            'kind': snake_case(failure['kind']), 'note': note('background.failed')}}
    return {**value, 'applied': False,
            'notes': [*value.get('notes', ()), note('background.' + value['state'])]}


def background_relaunch_plan(value, ident=None):
    """Name every chat written and every app lifecycle operation."""
    steps = []
    for delivery in value.deliveries:
        for item in delivery.steps:
            data = step(item.side, item.action, item.turn_ids, needs=item.needs)
            chat_id = delivery.snapshots[item.side]['chat_id']
            ref = value.chats[chat_id]['ref']
            data['chat'] = chat(item.side, chat_id, ref['name'], ref['folder'], ref['updated_at'])
            steps.append(data)
    lifecycle = [step(s.side, s.action, s.turn_ids) for s in value.steps
                 if s.action in ('close', 'wait_until_still', 'reopen')]
    return plan(ident or value.plan_id, value.link_id, [*lifecycle[:2], *steps, *lifecycle[2:]]
                if value.running else [*steps, *lifecycle],
                decision_needed=value.decision_needed, notes=note_list(value.notes),
                replying=[chat_from_ref(value.tool, ref) for ref in value.replying],
                expires_at=value.expires_at, when_idle=value.when_idle)


def link_action_plan(value, service):
    """Render the service-owned link/copy policy."""
    notes = note_list(service.notes(value))
    created = value.action in ('create', 'full_copy')
    return plan(value.plan_id, value.old_link_id,
                [step(value.target, 'create' if created else 'attach' if value.mode == 'attached_history' else 'add',
                      value.turn_ids, needs=value.needs, notes=notes)], notes=notes,
                confirmation=note('plan.unavailable' if not service.confirmation_available(value) else
                                  'plan.confirm_link' if value.and_link else 'plan.confirm_copy'))


def rename_action_plan(value, service):
    """Render the immutable rename actions and notes."""
    return plan(value.plan_id, value.link_id,
                [step(s.side, s.action, (), needs=s.needs) for s in service.action_steps(value)],
                notes=note_list(service.action_notes(value)) or [note('cli.rename_summary')],
                confirmation=note('plan.confirm_rename'))


def continue_action_plan(value, status):
    """Render sync and opening together before either is performed."""
    result = sync_action_plan(value.delivery, status)
    result.update(plan_id=value.plan_id, opened=False,
                  confirmation=note('plan.confirm_continue', {'tool': value.destination}))
    result['notes'].append(note(*value.opening['note']))
    return result


def open_action_result(value):
    """The contract's chat/folder receipt and preselected note."""
    return {'opened': value['opened'], 'note': note(*value['note'])}


def display_open_note(value, stream=None):
    """Flush the pre-action note on stderr; stdout retains its single receipt."""
    import sys
    stream = stream if stream is not None else sys.stderr
    stream.write(note(*value['note'])['text'] + "\n")
    stream.flush()
