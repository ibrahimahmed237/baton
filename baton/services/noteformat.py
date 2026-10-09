"""Small helpers shared by services that hand notes to the command line.

A service never writes a sentence: it returns a `NoteRef` (a catalogue id and
its values) and the caller renders it. Values that name a coding app use the
keys `tool` or `*_tool`, so the caller can swap the id for its display label.
Counts and times are formatted here because a template can only substitute.
"""
from __future__ import annotations

from datetime import date, datetime, timezone, tzinfo
from typing import Any, Callable, Mapping, NamedTuple

from ..notes.catalogue import get

# Tool id -> the name the user reads. Wiring supplies it; services never hold names.
Label = Callable[[str], str]


class NoteRef(NamedTuple):
    """A catalogue note id with the values that fill it."""
    id: str
    values: Mapping[str, Any]


def count(number: int) -> str:
    """Write a count with thousands separators: 164000 becomes 164,000."""
    return f"{number:,}"


def short_count(number: int) -> str:
    """Write a large count roughly, as in "about 310k tokens"."""
    return f"{round(number / 1000)}k" if number >= 1000 else str(number)


def parse_time(value: str | None) -> datetime | None:
    """Read an ISO 8601 time that carries a zone; anything else is not a usable time."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else None


def clock_time(value: str, tz: tzinfo = timezone.utc, today: date | None = None) -> str:
    """Write a time of day, with the date when it is not `today`; unreadable input is returned as it is."""
    parsed = parse_time(value)
    if parsed is None:
        return value
    local = parsed.astimezone(tz)
    if today is not None and local.date() != today:
        return f"{local:%Y-%m-%d %H:%M}"
    return f"{local:%H:%M}"


def day_of(now: str, tz: tzinfo = timezone.utc) -> date | None:
    """The calendar day of `now` in the user's zone, or None when `now` is unreadable."""
    parsed = parse_time(now)
    return parsed.astimezone(tz).date() if parsed else None


def plural(one_id: str, other_id: str, number: int) -> str:
    """Render "1 file" or "6 files" from the two catalogue entries."""
    return get(one_id if number == 1 else other_id).render({"n": number}).template
