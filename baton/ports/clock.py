"""UTC clocks for the engine and its tests."""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol


class Clock(Protocol):
    """Supply the current ISO 8601 UTC time."""
    def now(self) -> str:
        """Return the current time."""
        ...


class SystemClock:
    """Read the system's UTC time."""
    def now(self) -> str:
        """Return the current time in UTC."""
        return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class FixedClock:
    """Return a settable time for deterministic tests."""
    value: str

    def now(self) -> str:
        """Return the configured time."""
        return self.value
