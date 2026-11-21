"""Quick add: parse one line like Google Calendar's quick add into an event draft.

``parse("Lunch with Anna tomorrow 12:30-13:30 @Cafe Central #Personal", today, names)``
-> ``QuickAdd(summary="Lunch with Anna", start=..12:30, end=..13:30, all_day=False,
location="Cafe Central", calendar="Personal")``.

Rules (case-insensitive; the pieces may come in any order):
- ``#cal``: the first calendar in ``calendars`` whose name starts with ``cal``.
- ``for 2h`` / ``for 90m`` / ``for 1h30``: the duration (default 1 h).
- times: a range ``12:30-13:30`` / ``12-13`` / ``9-11am``, or one time ``12:30`` / ``9am`` /
  ``18h`` (optionally after ``at`` / ``from``); an end before the start is on the next day.
- a date in any of goto's forms (``fri``, ``next fri``, ``in 2 days``, ``24.12.``, ``dec 24``,
  ``+2w``), optionally after ``on``; default: ``today``. A range ``dec 3 - dec 5`` /
  ``1.12.-3.12.`` spans several days (with a time: from the first day to the last).
- no time: an all-day event (the duration is ignored).
- `` @``: everything after it (at a word start) (once the pieces above are taken out) is the location.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from tcal.dates import parse_date
from tcal.tz import local_midnight, local_zone

DEFAULT_DURATION = timedelta(hours=1)
_GAP = "\0"  # stands for a removed piece, so a date is never read across it

_TIME = r"(\d{1,2})(?::(\d{2}))?\s*(am|pm|h)?"
_RANGE = re.compile(
    rf"(?:\bfrom\s+)?(?<![\d.:/-]){_TIME}\s*[-–]\s*{_TIME}(?![\d.:/-])\b",
    re.IGNORECASE,
)
_SINGLE = re.compile(
    r"(?:\bat\s+)?(?<![\d.:/-])(\d{1,2})(?:(?::(\d{2}))\s*(am|pm)?|\s*(am|pm|h))(?![\d.:/-])\b",
    re.IGNORECASE,
)
_MINUTES = r"(\d+)\s*(?:m|mins?|minutes?)"
_DURATION = re.compile(
    rf"\bfor\s+(?:(\d+)\s*(?:h|hrs?|hours?)(\d{{2}})?(?:\s*{_MINUTES})?|{_MINUTES})\b",
    re.IGNORECASE,
)
_DASH = re.compile(r"\s*[-–]\s*")
_LOCATION = re.compile(r"(?:^|\s)@")
_CALENDAR = re.compile(r"#(\S+)")


@dataclass(frozen=True)
class QuickAdd:
    summary: str
    start: datetime
    end: datetime
    all_day: bool
    location: str
    calendar: str | None  # a name from ``calendars``; None: no ``#`` given
    unknown_calendar: str = ""  # the ``#`` text that matched no calendar


def _hour(h: str, m: str | None, suffix: str | None) -> time | None:
    hour, minute = int(h), int(m or 0)
    suffix = (suffix or "").lower()
    if suffix in ("am", "pm"):
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if suffix == "pm" else 0)
    if hour > 23 or minute > 59:
        return None
    return time(hour, minute)


def _range(m: re.Match[str]) -> tuple[time, time] | None:
    h1, m1, s1, h2, m2, s2 = m.groups()
    end = _hour(h2, m2, s2)
    start = None
    if not s1 and s2 and s2.lower() in ("am", "pm"):  # "9-11am": the start shares the suffix
        start = _hour(h1, m1, s2)
        if start is not None and end is not None and start > end:  # "11-1pm"
            start = None
    start = start or _hour(h1, m1, s1)
    return (start, end) if start is not None and end is not None else None


def _take(pattern: re.Pattern[str], text: str) -> tuple[re.Match[str] | None, str]:
    """The first match of ``pattern`` in ``text`` and ``text`` with it cut out."""
    m = pattern.search(text)
    if m is None:
        return None, text
    return m, f"{text[: m.start()]} {_GAP} {text[m.end() :]}"


def _dates(text: str, today: date) -> tuple[date, date] | None:
    """``text`` as one date (first == last) or a range "<date> - <date>"."""
    if (day := parse_date(text, today)) is not None:
        return day, day
    for dash in _DASH.finditer(text):
        first, last = parse_date(text[: dash.start()], today), parse_date(text[dash.end() :], today)
        if first is not None and last is not None:
            if last < first:  # "dec 30 - jan 2": the end is in the next year
                last = _next_year(last)
            if last is not None and last >= first:
                return first, last
    return None


def _next_year(day: date) -> date | None:
    try:
        return day.replace(year=day.year + 1)
    except ValueError:  # 29 Feb
        return None


def _take_date(text: str, today: date) -> tuple[tuple[date, date] | None, str]:
    """The longest run of words (≤ 9) that is a date or a date range, and the rest."""
    words = text.split()
    for size in range(min(9, len(words)), 0, -1):
        for i in range(len(words) - size + 1):
            run = words[i : i + size]
            if _GAP in run or (days := _dates(" ".join(run), today)) is None:
                continue
            if i and words[i - 1].lower() == "on":
                i, size = i - 1, size + 1
            return days, " ".join(words[:i] + [_GAP] + words[i + size :])
    return None, text


def _clean(text: str) -> str:
    return " ".join(w for w in text.split() if w != _GAP)


def parse(text: str, today: date, calendars: list[str]) -> QuickAdd:
    """Parse a quick-add line; see the module docstring for the rules."""
    calendar, unknown = None, ""
    tag, rest = _take(_CALENDAR, text)
    if tag:
        query = tag[1].lower()
        calendar = next((c for c in calendars if c.lower().startswith(query)), None)
        unknown = "" if calendar else tag[1]

    duration = DEFAULT_DURATION
    m, rest = _take(_DURATION, rest)
    if m:
        minutes = int(m[2] or 0) + int(m[3] or 0) + int(m[4] or 0)
        duration = timedelta(hours=int(m[1] or 0), minutes=minutes) or DEFAULT_DURATION

    times: tuple[time, time | None] | None = None
    m, rest = _take(_RANGE, rest)
    if m and (span := _range(m)):
        times = span
    else:
        before = rest
        m, rest = _take(_SINGLE, rest)
        start = _hour(m[1], m[2], m[3] or m[4]) if m else None
        if start is not None:
            times = (start, None)
        else:
            rest = before

    days, rest = _take_date(rest, today)
    day, last = days or (today, today)
    summary, *location = _LOCATION.split(_clean(rest), maxsplit=1)

    if times is None:
        start_dt, end_dt = local_midnight(day), local_midnight(last + timedelta(days=1))
    else:
        start_dt = datetime.combine(day, times[0], local_zone())
        if times[1] is None:
            end_dt = datetime.combine(last, times[0], local_zone()) + duration
        else:
            end_dt = datetime.combine(last, times[1], local_zone())
            if end_dt <= start_dt:
                end_dt += timedelta(days=1)
    return QuickAdd(
        summary.strip(),
        start_dt,
        end_dt,
        times is None,
        location[0].strip() if location else "",
        calendar,
        unknown,
    )
