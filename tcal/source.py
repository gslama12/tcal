"""The one data access seam the UI uses: ``EventSource``.

The UI never talks to providers or the store directly; it asks an EventSource
for calendars and occurrences in a day range, and hands it edits.
``StoreSource`` reads the SQLite cache and expands recurrence (PLAN D3: the UI
only reads the cache; ``SyncEngine`` keeps it current in the background).
"""

from datetime import date, datetime
from typing import Protocol

from tcal.model import Calendar, Event, Occurrence
from tcal.recurrence import expand
from tcal.store import Store
from tcal.tz import local_midnight


class EventSource(Protocol):
    def calendars(self) -> list[Calendar]: ...

    def occurrences(self, start: date, end: date) -> list[Occurrence]:
        """Occurrences overlapping the local days [start, end), sorted by start."""
        ...

    def save_event(self, event: Event) -> Event:
        """Create or update (a series is edited as a whole); returns the stored event."""
        ...

    def delete_event(self, uid: str, occurrence: datetime | None = None) -> None:
        """Delete the event, or only the instance whose original start is ``occurrence``."""
        ...

    def pending_count(self) -> int:
        """Number of local edits waiting to be pushed."""
        ...


class StoreSource:
    def __init__(self, store: Store) -> None:
        self.store = store

    def calendars(self) -> list[Calendar]:
        return self.store.calendars()

    def occurrences(self, start: date, end: date) -> list[Occurrence]:
        lo, hi = local_midnight(start), local_midnight(end)
        return expand(self.store.events_between(lo, hi), lo, hi)

    def save_event(self, event: Event) -> Event:
        return self.store.save_event(event)

    def delete_event(self, uid: str, occurrence: datetime | None = None) -> None:
        self.store.delete_event(uid, occurrence)

    def pending_count(self) -> int:
        return self.store.pending_count()
