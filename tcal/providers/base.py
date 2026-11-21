"""The interface every calendar backend implements (iCloud, fake, later others)."""

from datetime import datetime
from typing import Protocol

from tcal.model import Calendar, Event


class ProviderError(Exception):
    """The server refused or failed a request."""


class ConflictError(ProviderError):
    """The server's copy changed since we read it (etag mismatch)."""


class Provider(Protocol):
    def list_calendars(self) -> list[Calendar]: ...

    def fetch_events(self, calendar: Calendar, start: datetime, end: datetime) -> list[Event]:
        """Events of ``calendar`` that may occur in [start, end).

        Recurring series are returned once, as their master event (with ``rrule``),
        plus any overridden instances (with ``recurrence_id``); expansion is the
        caller's job.
        """
        ...

    def create_event(self, event: Event) -> Event:
        """Store a new event; returns it with ``href``/``etag`` filled in."""
        ...

    def update_event(self, event: Event) -> Event:
        """Replace an existing event; returns it with the new ``etag``.

        Raises ConflictError if the server's etag is no longer ``event.etag``.
        """
        ...

    def delete_event(self, event: Event) -> None:
        """Delete the event's resource; ConflictError on an etag mismatch."""
        ...
