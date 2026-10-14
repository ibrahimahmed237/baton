"""Cursor beforeSubmitPrompt and stop payload identities."""
from . import HookCall, identity


def parse(payload):
    return HookCall(identity(payload.get('conversation_id')),
                    identity(payload.get('generation_id')))


def nothing(prompt):
    return '{"continue": true}' if prompt else '{}'
