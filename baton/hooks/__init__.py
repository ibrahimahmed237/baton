"""Fail-safe native hook boundaries, separate from ordinary CLI responses."""
from dataclasses import dataclass
from importlib import import_module


@dataclass(frozen=True)
class HookCall:
    chat: str
    turn: str = ''
    event: str = 'turn_end'


def protocol(tool):
    return import_module('baton.hooks.' + tool) if tool in (
        'claude', 'codex', 'opencode', 'cursor') else None


def identity(value):
    if value is None:
        return ''
    if not isinstance(value, str):
        raise ValueError('hook_identity')
    return value
