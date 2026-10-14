"""OpenCode chat.message and event payloads, without native file access."""
from . import HookCall, identity


def parse(payload):
    event = payload.get('event', {})
    properties = event.get('properties', {})
    message = payload.get('message', {})
    chat = payload.get('sessionID') or message.get('sessionID') or properties.get('sessionID') or properties.get('info', {}).get('sessionID')
    status = properties.get('status', {}).get('type')
    name = 'busy' if status == 'busy' else 'idle' if status == 'idle' or event.get('type') == 'session.idle' else 'turn_end'
    return HookCall(identity(chat), identity(payload.get('messageID') or message.get('id')), name)


def nothing(prompt):
    return ''
