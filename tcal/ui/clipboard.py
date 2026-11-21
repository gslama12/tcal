"""Pure event transforms for editing: copies (yank/paste/duplicate), moves
(ctrl+h/j/k/l) and single instances of a series."""

from dataclasses import replace
from datetime import date, datetime, timedelta
from uuid import uuid4

from tcal.model import Event, Occurrence
from tcal.tz import local_midnight, local_zone


def copy_at(occ: Occurrence, at: date | datetime, calendar_id: str) -> Event:
    """A new one-off event like ``occ``, keeping its duration, starting at ``at``:
    a slot (timed events start there; all-day ones on its day) or a day (timed
    events keep their time of day)."""
    if occ.all_day:
        day = at.date() if isinstance(at, datetime) else at
        days = max(1, (occ.end.date() - occ.start.date()).days)
        start, end = local_midnight(day), local_midnight(day + timedelta(days))
    else:
        start = (
            at if isinstance(at, datetime) else datetime.combine(at, occ.start.time(), local_zone())
        )
        end = start + (occ.end - occ.start)
    return replace(
        occ.event,
        uid=f"{uuid4()}@tcal",
        calendar_id=calendar_id,
        start=start,
        end=end,
        rrule=None,
        recurrence_id=None,
        exdates=(),
        etag=None,
        href=None,
        raw=None,
    )


def shifted(event: Event, delta: timedelta) -> Event:
    """``event`` moved by ``delta`` (wall-clock); a series' deleted instances move along."""
    return replace(
        event,
        start=event.start + delta,
        end=event.end + delta,
        exdates=tuple(x + delta for x in event.exdates),
    )


def instance_of(occ: Occurrence) -> Event:
    """The event to edit for just ``occ``: its override, or a new one for the
    master's instance (RECURRENCE-ID = the instance's start, no RRULE/EXDATEs)."""
    event = occ.event
    if event.recurrence_id is not None:
        return event
    zone = event.start.tzinfo
    start, end = occ.start.astimezone(zone), occ.end.astimezone(zone)
    return replace(event, start=start, end=end, recurrence_id=start, rrule=None, exdates=())
