"""Expand events (RRULE, EXDATE, RECURRENCE-ID overrides) into Occurrences.

Series are expanded in the wall-clock time of their own zone, so a weekly
09:00 meeting stays at 09:00 across DST changes; results are in local time.
"""

import re
from collections.abc import Iterable, Iterator
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from functools import lru_cache

from dateutil.rrule import rrule, rruleset, rrulestr

from tcal.model import Event, Occurrence
from tcal.tz import local_midnight, local_zone

_UNTIL = re.compile(r"UNTIL=([0-9TZ]+);?", re.IGNORECASE)


def expand(events: Iterable[Event], start: datetime, end: datetime) -> list[Occurrence]:
    """Occurrences of ``events`` overlapping [start, end), sorted by (start, end).

    ``events`` may hold masters (with ``rrule``) and overridden instances (with
    ``recurrence_id``); an override replaces the master's instance it names.
    """
    events = list(events)
    overridden = {(e.uid, _instant(e.recurrence_id)) for e in events if e.recurrence_id}
    found: list[Occurrence] = []
    for event in events:
        if event.rrule and not event.recurrence_id:
            duration = event.end - event.start
            for s in _starts(event, start - duration, end):
                if (event.uid, _instant(s)) not in overridden:
                    found.append(_occurrence(event, s, s + duration))
        else:
            found.append(_occurrence(event, event.start, event.end))
    hits = [o for o in found if _overlaps(o, start, end)]
    return sorted(hits, key=lambda o: (o.start, o.end))


def _starts(event: Event, lo: datetime, hi: datetime) -> Iterator[datetime]:
    """Instance starts of a series in [lo, hi], in the event's zone."""
    zone = event.start.tzinfo
    rules = _rules(event.rrule or "", event.start, event.exdates)
    for s in rules.between(_wall(lo, zone), _wall(hi, zone), inc=True):
        yield s.replace(tzinfo=zone)


@lru_cache(maxsize=1024)
def _rules(text: str, start: datetime, exdates: tuple[datetime, ...]) -> rruleset:
    """The series' rule set in wall-clock time of ``start``'s zone; cached, and
    with dateutil's cache on, so redraws don't re-parse and re-iterate it."""
    zone = start.tzinfo
    rule_text, until = _split_until(text)
    rule = rrulestr(rule_text, dtstart=_wall(start, zone))
    assert isinstance(rule, rrule)
    if until is not None:
        rule = rule.replace(until=_wall(until, zone) if until.tzinfo else until)
    rules = rruleset(cache=True)
    rules.rrule(rule)
    for exdate in exdates:
        rules.exdate(_wall(exdate, zone))
    return rules


def _wall(dt: datetime, zone: tzinfo | None) -> datetime:
    return dt.astimezone(zone).replace(tzinfo=None)


def _split_until(text: str) -> tuple[str, datetime | None]:
    """The rule without UNTIL, and UNTIL as an aware or naive (wall-clock) datetime.

    dateutil rejects a naive/date UNTIL with an aware start, so we apply it ourselves.
    """
    match = _UNTIL.search(text)
    if not match:
        return text, None
    value = match.group(1).upper()
    rest = (text[: match.start()] + text[match.end() :]).rstrip(";")
    if "T" not in value:  # a DATE: the whole day is included
        return rest, datetime.combine(
            date(int(value[:4]), int(value[4:6]), int(value[6:8])), time.max
        )
    parsed = datetime.strptime(value.rstrip("Z"), "%Y%m%dT%H%M%S")
    return rest, parsed.replace(tzinfo=UTC) if value.endswith("Z") else parsed


def _occurrence(event: Event, start: datetime, end: datetime) -> Occurrence:
    if event.all_day:
        days = (end.date() - start.date()).days
        first = start.date()
        return Occurrence(event, local_midnight(first), local_midnight(first + timedelta(days)))
    zone = local_zone()
    return Occurrence(event, start.astimezone(zone), end.astimezone(zone))


def _overlaps(occ: Occurrence, start: datetime, end: datetime) -> bool:
    if occ.start == occ.end:  # zero-length: a point in time
        return start <= occ.start < end
    return occ.start < end and occ.end > start


def _instant(dt: datetime | None) -> datetime | None:
    return dt.astimezone(UTC) if dt else None
