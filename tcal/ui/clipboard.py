"""Pure event transforms for editing: copies (yank/paste/duplicate), moves,
resizes and single instances of a series."""

import re
from dataclasses import replace
from datetime import date, datetime, timedelta
from uuid import uuid4

from tcal.model import Event, Occurrence
from tcal.tz import local_midnight, local_zone

STEP = timedelta(minutes=15)  # the grid a resized start/end snaps to; the minimum duration


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


WEEKDAY_CODES = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")
_BYDAY = re.compile(r"(?<![A-Z])BYDAY=([^;]*)", re.IGNORECASE)


def quarter_step(moment: datetime, step: int) -> timedelta:
    """From ``moment`` to the next (``step`` 1) / previous (-1) quarter hour."""
    past = timedelta(
        minutes=moment.minute % 15, seconds=moment.second, microseconds=moment.microsecond
    )
    return STEP - past if step > 0 else -(past or STEP)


def shifted(event: Event, start_by: timedelta, end_by: timedelta) -> Event | None:
    """``event`` with its start and end shifted (wall-clock; equal deltas: a move). A
    series' deleted instances move along with the start and its BYDAY weekdays shift by
    the days the start moves (MO,FR -> TU,SA).
    None if that can't be done: BYDAY with an ordinal ("2MO", "-1FR")."""
    start = event.start + start_by
    rrule = event.rrule
    if rrule and (days := (start.date() - event.start.date()).days % 7):
        m = _BYDAY.search(rrule)
        codes = m[1].upper().split(",") if m else []
        if any(c not in WEEKDAY_CODES for c in codes):
            return None
        if m:
            moved = [WEEKDAY_CODES[(WEEKDAY_CODES.index(c) + days) % 7] for c in codes]
            rrule = f"{rrule[: m.start(1)]}{','.join(moved)}{rrule[m.end(1) :]}"
    return replace(
        event,
        start=start,
        end=event.end + end_by,
        rrule=rrule,
        exdates=tuple(x + start_by for x in event.exdates),
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
