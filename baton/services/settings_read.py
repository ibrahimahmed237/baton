"""Resolve configuration without constructing any write/recovery service."""
from __future__ import annotations

from math import isfinite
from typing import Mapping

from ..ports.store import RecordStore


class SettingsRead:
    """Only expose known, valid settings; wiring supplies the contract defaults."""

    def __init__(self, store: RecordStore, defaults: Mapping, *, choices: Mapping | None = None,
                 bounds: Mapping | None = None):
        self.store = store
        self.defaults = dict(defaults)
        self.choices = choices or {}
        self.bounds = bounds or {}

    def get(self) -> dict:
        """Return validated saved overrides over the supplied public defaults."""
        result = dict(self.defaults)
        for key, value in self.store.settings_values().items():
            if key not in result:
                continue
            default = self.defaults[key]
            if isinstance(default, bool):
                valid = isinstance(value, bool)
            elif isinstance(default, (int, float)):
                valid = (isinstance(value, (int, float)) and not isinstance(value, bool)
                         and (isinstance(value, int) or isfinite(value)))
            else:
                valid = type(value) is type(default)
            if not valid:
                continue
            if key in self.choices and value not in self.choices[key]:
                continue
            if key in self.bounds:
                lower, upper = self.bounds[key]
                if (lower is not None and value < lower or
                        upper is not None and value > upper):
                    continue
            result[key] = value
        return result
