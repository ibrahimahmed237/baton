"""Codex requires valid JSON for both native hook responses."""
from . import HookCall, identity


def parse(payload):
    return HookCall(identity(payload.get('session_id')), identity(payload.get('turn_id')))


def nothing(prompt):
    return '{}'
