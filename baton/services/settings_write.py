"""Parse and validate contract settings before saving any override."""
import json
from math import isfinite

from ..domain.errors import BatonError
from .noteformat import NoteRef


class InvalidSetting(BatonError):
    """A key or value is outside the settings contract."""
    note_id = 'settings.invalid_value'


class SettingSaveFailed(BatonError):
    """The store could not persist a validated choice."""
    note_id = 'settings.error'


class SettingsWrite:
    """Share the read service's defaults, choices and bounds."""
    def __init__(self, reader):
        self.reader = reader

    def set(self, key, value):
        if key not in self.reader.defaults:
            raise InvalidSetting()
        default = self.reader.defaults[key]
        if isinstance(default, (bool, int, float)):
            try:
                value = json.loads(value) if isinstance(value, str) else value
            except (ValueError, TypeError):
                raise InvalidSetting() from None
            if isinstance(default, bool):
                valid = isinstance(value, bool)
            else:
                valid = isinstance(value, (int, float)) and not isinstance(value, bool) and (isinstance(value, int) or isfinite(value))
                if key in self.reader.bounds and self.reader.bounds[key][1] is None:
                    valid = valid and value == int(value)
            if not valid:
                raise InvalidSetting()
        elif not isinstance(value, str):
            raise InvalidSetting()
        if key in self.reader.choices and value not in self.reader.choices[key]:
            raise InvalidSetting()
        lower, upper = self.reader.bounds.get(key, (None, None))
        if lower is not None and value < lower or upper is not None and value > upper:
            raise InvalidSetting()
        try:
            self.reader.store.save_setting(key, value)
        except Exception:
            raise SettingSaveFailed() from None
        return self.reader.get(), (NoteRef('settings.saved', {}),)
