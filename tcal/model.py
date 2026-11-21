"""Core data types, shared by providers, the store and the UI.

Time convention: timed events carry timezone-aware datetimes. All-day events
have ``all_day=True`` and start/end at local midnight (aware), with ``end``
exclusive, as in iCalendar (a one-day event on the 5th ends on the 6th).
"""

from dataclasses import dataclass, field
from datetime import datetime

SUBSCRIPTION_PREFIX = "subscription:"  # id of a read-only feed's calendar: prefix + feed URL


@dataclass
class Calendar:
    id: str
    name: str
    color: str  # "#RRGGBB"
    visible: bool = True
    readonly: bool = False

    @property
    def subscribed(self) -> bool:
        """A subscribed iCalendar feed ("Other calendars"), not one of the account's."""
        return self.id.startswith(SUBSCRIPTION_PREFIX)


@dataclass
class Event:
    uid: str
    calendar_id: str
    summary: str
    start: datetime
    end: datetime  # exclusive
    all_day: bool = False
    location: str = ""
    description: str = ""
    rrule: str | None = None  # RRULE value, e.g. "FREQ=WEEKLY;BYDAY=MO"
    recurrence_id: datetime | None = None  # set on an overridden instance of a series
    exdates: tuple[datetime, ...] = ()  # starts of deleted instances of a series
    etag: str | None = None
    href: str | None = None  # server URL of the resource; None until pushed
    # iCalendar text of the whole resource as last seen (see tcal/ics.py); edits are
    # written into it so properties tcal doesn't model (alarms, attendees) survive.
    raw: str | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class Occurrence:
    """One concrete instance of an event, as drawn by the views.

    ``start``/``end`` are in local time (aware); for a non-recurring event they
    equal the event's own.
    """

    event: Event
    start: datetime
    end: datetime

    @property
    def key(self) -> tuple[str, datetime]:
        """Identity across reloads (a sync changes the etag and raw text): uid + start."""
        return self.event.uid, self.start

    @property
    def all_day(self) -> bool:
        return self.event.all_day

    @property
    def summary(self) -> str:
        return self.event.summary

    @property
    def calendar_id(self) -> str:
        return self.event.calendar_id
