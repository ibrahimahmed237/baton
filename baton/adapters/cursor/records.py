"""Display bubbles and transcript messages, with no executable agent state."""
from copy import deepcopy
from dataclasses import asdict
import json
import re

from ...domain.errors import UnknownFormat
from ...notes.catalogue import get
from ...domain.model import Message, Turn, PROMPT, REPLY, TOOL_CALL, TOOL_RESULT, TOOL_TEXT


def prompt_text(text):
    match = re.search(r'<user_query>\s*(.*?)\s*</user_query>', text, re.S)
    if match:
        return match.group(1)
    return re.sub(r'^\s*\[\d{4}-\d\d-\d\d[^\]]*\]\s*', '', text)


def display_messages(bubbles):
    messages = []
    for bubble in bubbles:
        if bubble.get('isInserted') or bubble.get('inserted'):
            continue
        if 'batonMessage' in bubble:
            messages.append(Message(**bubble['batonMessage']))
            continue
        text = bubble.get('text', '')
        if text.lstrip().startswith('<baton-catch-up>'):
            continue
        kind = PROMPT if bubble['type'] == 1 else REPLY
        tool = bubble.get('toolCall')
        if isinstance(tool, dict):
            messages.append(Message(bubble['bubbleId'], TOOL_CALL, at=bubble.get('createdAt', ''),
                                    tool=tool.get('name', ''), tool_input=tool.get('arguments'),
                                    call_id=tool.get('id', '')))
        elif bubble.get('toolResult'):
            messages.append(Message(bubble['bubbleId'], TOOL_RESULT, text,
                                    bubble.get('createdAt', ''), call_id=bubble['toolResult'].get('id', '')))
        elif text:
            messages.append(Message(bubble['bubbleId'], kind, prompt_text(text) if kind == PROMPT else text,
                                    bubble.get('createdAt', '')))
    return messages


def transcript_messages(raw, native, written_ids=()):
    """Overlay exported text onto original bubbles, keeping display order."""
    replacements, offset = {}, 0
    for line in raw.splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get('type') == 'turn_ended':
            continue
        payload = record.get('message', record)
        role = payload.get('role', record.get('role'))
        content = payload.get('content', '')
        blocks = [{'type': 'text', 'text': content}] if isinstance(content, str) else content
        if role not in ('user', 'assistant', 'tool') or not isinstance(blocks, list):
            continue
        for block in blocks:
            if not isinstance(block, dict) or block.get('inserted') or block.get('isInserted'):
                continue
            typ = block.get('type')
            kind = {'tool_use': TOOL_CALL, 'tool_call': TOOL_CALL,
                    'tool_result': TOOL_RESULT}.get(typ, PROMPT if role == 'user' else REPLY)
            text = block.get('text', block.get('content', ''))
            if not isinstance(text, str):
                text = json.dumps(text)
            if kind == PROMPT:
                text = prompt_text(text)
            if text.lstrip().startswith('<baton-catch-up>'):
                continue
            match = next((i for i in range(offset, len(native))
                          if native[i].kind == kind and native[i].id not in written_ids), None)
            if match is None:
                continue
            source = native[match]
            replacements[source.id] = Message(source.id, kind, text, source.at,
                block.get('name', source.tool), block.get('input', block.get('arguments', source.tool_input)),
                block.get('tool_use_id', block.get('call_id', source.call_id)), source.is_error)
            offset = match + 1
    return [replacements.get(message.id, message) for message in native]


def turns_from_messages(messages):
    result, prompt, replies = [], None, []
    for message in messages:
        if message.kind == PROMPT:
            if prompt is not None:
                result.append(Turn(prompt, tuple(replies)))
            prompt, replies = message, []
        elif prompt is not None:
            replies.append(message)
    if prompt is not None:
        result.append(Turn(prompt, tuple(replies)))
    return result


# Only native presentation fields cross the template boundary.
BUBBLE_FIELDS = ('bubbleId', 'type', 'text', 'createdAt', 'richText')
HEAD_FIELDS = ('bubbleId', 'type', 'createdAt', 'grouping')
GROUPING_FIELDS = ('hasText', 'textPreview')
CHAT_FIELDS = ('_v', 'contextTokenLimit', 'contextWindowSize')
HEADER_FIELDS = ('workspaceId', 'version')


def selected(value, fields):
    return {key: deepcopy(value[key]) for key in fields if key in value}


def rich_text(text):
    leaf = {'detail': 0, 'format': 0, 'mode': 'normal', 'style': '',
            'text': text, 'type': 'text', 'version': 1}
    paragraph = {'children': [leaf], 'direction': 'ltr', 'format': '',
                 'indent': 0, 'type': 'paragraph', 'version': 1}
    return json.dumps({'root': {**paragraph, 'children': [paragraph], 'type': 'root'}})


def tool_text(message, calls):
    if message.kind == TOOL_CALL:
        return get('mapping.tool_call').render({
            'n': calls[message.id], 'tool': message.tool,
            'input': json.dumps(message.tool_input, sort_keys=True, ensure_ascii=False),
            'text': message.text}).template
    return get('mapping.tool_result').render({
        'n': calls.get(message.call_id, 0), 'text': message.text,
        'is_error': json.dumps(message.is_error)}).template


def turn_records(turns, templates):
    bubbles, heads = {}, []
    for turn in turns:
        calls = {m.id: i for i, m in enumerate(
            (m for m in turn.messages if m.kind == TOOL_CALL), start=1)}
        for message in turn.messages:
            if message.kind == TOOL_CALL and message.call_id:
                calls[message.call_id] = calls[message.id]
        for message in turn.messages:
            if message.kind == TOOL_RESULT and message.call_id and message.call_id not in calls:
                calls[message.call_id] = max(calls.values(), default=0) + 1
        for message in (turn.prompt, *turn.messages):
            role = 1 if message.kind == PROMPT else 2
            if role not in templates:
                raise UnknownFormat()
            source, head = templates[role]
            text = tool_text(message, calls) if message.kind in (TOOL_CALL, TOOL_RESULT) else message.text
            bubble = selected(source, BUBBLE_FIELDS)
            bubble.update(bubbleId=message.id, type=role, text=text, createdAt=message.at,
                          batonMessage=asdict(message))
            if 'richText' in bubble:
                bubble['richText'] = rich_text(text)
            new_head = selected(head, HEAD_FIELDS)
            new_head.update(bubbleId=message.id, type=role, createdAt=message.at,
                            grouping={**selected(head.get('grouping', {}), GROUPING_FIELDS),
                                      'hasText': True, 'textPreview': text[:80]})
            bubbles[message.id] = bubble
            heads.append(new_head)
    return bubbles, heads
