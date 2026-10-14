"""Claude UserPromptSubmit and Stop payloads measured in SPIKE-M0."""
from . import HookCall, identity


def parse(payload):
    return HookCall(identity(payload.get('session_id')), identity(payload.get('prompt_id')))


def nothing(prompt):
    return ''
