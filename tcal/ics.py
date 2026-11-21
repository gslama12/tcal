"""iCalendar text <-> ``model.Event``, shared by the CalDAV and fake providers.

A CalDAV resource holds one series: the master VEVENT plus overridden
instances (same UID, with RECURRENCE-ID). ``from_ics`` returns all of them,
each keeping the resource text in ``Event.raw``; ``to_ics`` writes one event
back into that text, so properties tcal doesn't model (alarms, attendees, ...)
survive an edit.
"""

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import icalendar

from tcal.model import Event
from tcal.tz import local_midnight, local_zone

PRODID = "-//tcal//tcal//EN"
# The properties tcal owns; everything else in a component is left untouched.
MANAGED = (
    "DTSTAMP",
    "SUMMARY",
    "DTSTART",
    "DTEND",
    "DURATION",
    "LOCATION",
    "DESCRIPTION",
    "RRULE",
    "EXDATE",
    "RECURRENCE-ID",
)


def from_ics(
    text: str, calendar_id: str, href: str | None = None, etag: str | None = None
) -> list[Event]:
    """All VEVENTs of a resource, the master (if any) first."""
    cal = icalendar.Calendar.from_ical(text)
    events = [_event(c, calendar_id, href, etag, text) for c in cal.walk("VEVENT")]
    return sorted(events, key=lambda e: e.recurrence_id is not None)


def to_ics(event: Event) -> str:
    """The resource text with ``event`` written into it (a new resource if no ``raw``)."""
    cal = icalendar.Calendar.from_ical(event.raw) if event.raw else _new_calendar()
    if not any(str(c.get("UID")) == event.uid for c in cal.walk("VEVENT")):
        cal = _new_calendar()  # raw of another event (e.g. a copy with a new uid)
    comp = _find(cal, event.uid, event.recurrence_id)
    if comp is None:
        comp = icalendar.Event()
        comp.add("UID", event.uid)
        cal.add_component(comp)
    for name in MANAGED:
        comp.pop(name, None)

    comp.add("DTSTAMP", datetime.now(UTC))
    comp.add("SUMMARY", event.summary)
    value = _date_value if event.all_day else _time_value
    comp.add("DTSTART", value(event.start, event.start))
    comp.add("DTEND", value(event.end, event.start))
    if event.location:
        comp.add("LOCATION", event.location)
    if event.description:
        comp.add("DESCRIPTION", event.description)
    if event.rrule:
        comp.add("RRULE", icalendar.vRecur.from_ical(event.rrule))
    if event.exdates:
        comp.add("EXDATE", [value(x, event.start) for x in event.exdates])
    if event.recurrence_id:
        comp.add("RECURRENCE-ID", value(event.recurrence_id, event.start))
    cal.add_missing_timezones()
    return cal.to_ical().decode()


@dataclass(frozen=True)
class Extras:
    """Properties tcal shows but does not edit (kept in ``Event.raw``)."""

    organizer: str = ""
    attendees: tuple[tuple[str, str], ...] = ()  # (name or e-mail, PARTSTAT)
    alarms: tuple[timedelta | datetime, ...] = ()  # offset from the start, or an absolute time
    url: str = ""


def extras(event: Event) -> Extras:
    """Organizer, attendees, alarms and URL of ``event`` from its ``raw`` text."""
    if not event.raw:
        return Extras()
    comp = _find(icalendar.Calendar.from_ical(event.raw), event.uid, event.recurrence_id)
    if comp is None:
        return Extras()
    organizer = comp.get("ORGANIZER")
    return Extras(
        organizer=_person(organizer) if organizer is not None else "",
        attendees=tuple(
            (_person(a), str(a.params.get("PARTSTAT", "NEEDS-ACTION")).upper())
            for a in _as_list(comp.get("ATTENDEE"))
        ),
        alarms=tuple(_trigger(alarm, event) for alarm in comp.walk("VALARM") if "TRIGGER" in alarm),
        url=str(comp.get("URL", "")),
    )


def _person(prop: Any) -> str:
    """CN, else the address without ``mailto:``."""
    name = prop.params.get("CN")
    return str(name) if name else str(prop).removeprefix("mailto:").removeprefix("MAILTO:")


def _trigger(alarm: Any, event: Event) -> timedelta | datetime:
    value = alarm["TRIGGER"].dt
    if isinstance(value, timedelta):
        related_end = str(alarm["TRIGGER"].params.get("RELATED", "START")).upper() == "END"
        return value + (event.end - event.start if related_end else timedelta())
    return _as_datetime(value)


def without_instance(event: Event, recurrence_id: datetime) -> Event:
    """``event`` with the override of instance ``recurrence_id`` removed from ``raw``."""
    if not event.raw:
        return event
    cal = icalendar.Calendar.from_ical(event.raw)
    comp = _find(cal, event.uid, recurrence_id)
    if comp is None:
        return event
    cal.subcomponents.remove(comp)
    return replace(event, raw=cal.to_ical().decode())


def _new_calendar() -> icalendar.Calendar:
    cal = icalendar.Calendar()
    cal.add("PRODID", PRODID)
    cal.add("VERSION", "2.0")
    return cal


def _find(
    cal: icalendar.Calendar, uid: str, recurrence_id: datetime | None
) -> icalendar.Component | None:
    comp: Any
    for comp in cal.walk("VEVENT"):
        if str(comp.get("UID")) != uid:
            continue
        if _recurrence_id(comp) == recurrence_id:  # aware datetimes compare as instants
            return comp
    return None


def _event(comp: Any, calendar_id: str, href: str | None, etag: str | None, raw: str) -> Event:
    start_value = comp["DTSTART"].dt
    all_day = not isinstance(start_value, datetime)
    start = _as_datetime(start_value)
    if "DTEND" in comp:
        end = _as_datetime(comp["DTEND"].dt)
    elif "DURATION" in comp:
        end = start + comp["DURATION"].dt
    else:
        end = start
    if end <= start and all_day:
        end = start + timedelta(days=1)  # no DTEND, or DTEND == DTSTART: one day
    end = max(end, start)
    rrule = _first(comp.get("RRULE"))
    return Event(
        uid=str(comp.get("UID", "")),
        calendar_id=calendar_id,
        summary=str(comp.get("SUMMARY", "")),
        start=start,
        end=end,
        all_day=all_day,
        location=str(comp.get("LOCATION", "")),
        description=str(comp.get("DESCRIPTION", "")),
        rrule=rrule.to_ical().decode() if rrule is not None else None,
        recurrence_id=_recurrence_id(comp),
        exdates=tuple(
            _as_datetime(d.dt) for prop in _as_list(comp.get("EXDATE")) for d in prop.dts
        ),
        etag=etag,
        href=href,
        raw=raw,
    )


def _recurrence_id(comp: Any) -> datetime | None:
    return _as_datetime(comp["RECURRENCE-ID"].dt) if "RECURRENCE-ID" in comp else None


def _as_datetime(value: date | datetime) -> datetime:
    """DATE -> local midnight; floating time -> local zone; aware times as they are."""
    if not isinstance(value, datetime):
        return local_midnight(value)
    return value if value.tzinfo else value.replace(tzinfo=local_zone())


def _date_value(value: datetime, _start: datetime) -> date:
    return value.astimezone(local_zone()).date()


def _time_value(value: datetime, start: datetime) -> datetime:
    """``value`` in the zone written for ``start``: its named zone, else local or UTC."""
    zone = start.tzinfo
    if not isinstance(zone, ZoneInfo):
        local = local_zone()
        same = (
            isinstance(local, ZoneInfo) and start.utcoffset() == start.astimezone(local).utcoffset()
        )
        zone = local if same else UTC
    return value.astimezone(zone)


def _first(value: Any) -> Any:
    return value[0] if isinstance(value, list) else value


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]
