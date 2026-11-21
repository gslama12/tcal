"""The one data access seam the UI uses: ``EventSource``.

The UI never talks to providers or the store directly; it asks an EventSource
for calendars and for the occurrences in a day range. ``ProviderSource`` reads
straight from a provider and expands recurrence itself; it backs ``--demo`` and
tests until the backend package puts the SQLite store + recurrence.py behind
this protocol.
"""

from datetime import date, datetime, time
from typing import Protocol

from dateutil.rrule import rrulestr

from tcal.model import Calendar, Event, Occurrence
from tcal.providers.base import Provider


class EventSource(Protocol):
    def calendars(self) -> list[Calendar]: ...

    def occurrences(self, start: date, end: date) -> list[Occurrence]:
        """Occurrences overlapping the local days [start, end), sorted by start."""
        ...


def local_midnight(day: date) -> datetime:
    return datetime.combine(day, time(), datetime.now().astimezone().tzinfo)


class ProviderSource:
    def __init__(self, provider: Provider) -> None:
        self.provider = provider

    def calendars(self) -> list[Calendar]:
        return self.provider.list_calendars()

    def occurrences(self, start: date, end: date) -> list[Occurrence]:
        lo, hi = local_midnight(start), local_midnight(end)
        found = [
            occ
            for cal in self.calendars()
            for event in self.provider.fetch_events(cal, lo, hi)
            for occ in _expand(event, lo, hi)
        ]
        return sorted(found, key=lambda o: (o.start, o.end))


def _expand(event: Event, lo: datetime, hi: datetime) -> list[Occurrence]:
    if not event.rrule:
        if event.start < hi and event.end > lo:
            return [Occurrence(event, event.start.astimezone(), event.end.astimezone())]
        return []
    duration = event.end - event.start
    rule = rrulestr(event.rrule, dtstart=event.start)
    return [
        Occurrence(event, s.astimezone(), (s + duration).astimezone())
        for s in rule.between(lo - duration, hi, inc=False)
        if s + duration > lo
    ]
