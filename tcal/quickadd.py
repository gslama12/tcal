"""Quick add: parse one line like Google Calendar's quick add into an event draft.

``parse("Lunch with Anna tomorrow 12:30-13:30 @Cafe Central #Personal", today, names)``
-> ``QuickAdd(summary="Lunch with Anna", start=..12:30, end=..13:30, all_day=False,
location="Cafe Central", calendar="Personal")``.

Rules (case-insensitive; the pieces may come in any order):
- ``#cal``: the first calendar in ``calendars`` whose name starts with ``cal``.
- ``for 2h`` / ``for 90m`` / ``for 1h30``: the duration (default 1 h).
- times: a range ``12:30-13:30`` / ``12-13`` / ``9-11am``, or one time ``12:30`` / ``9am`` /
  ``18h`` / ``14.30`` / ``noon`` / ``midnight`` (optionally after ``at`` / ``from``); an end
  before the start is on the next day. Right after a date or repeat a bare hour is a time
  (``tomorrow 9``); ``12.11`` is a date unless a date is given elsewhere.
- repeats: ``daily`` / ``weekly`` / ``monthly`` / ``yearly``, ``every day|week|month|year``,
  ``every weekday`` / ``weekdays`` (Mon–Fri) and ``every <weekday>`` (also a list: ``every mon
  and wed``, ``every tue, thu``); the first one is on or after the date. A repeat word that
  starts the line is part of the title ("Weekly review fri").
- a date in any of goto's forms (``fri``, ``next fri``, ``in 2 days``, ``24.12.``, ``dec 24``,
  ``+2w``, ``tonight``), optionally after ``on``; default: ``today``. A range ``dec 3 - dec 5``
  / ``dec 3-5`` / ``1.12.-3.12.`` / ``mon-fri`` spans several days (with a time: from the first
  day to the last).
- no time: an all-day event (the duration is ignored).
- `` @``: everything after it (at a word start) (once the pieces above are taken out) is the location.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from tcal.dates import WEEKDAYS, month_number, parse_date
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
_DOT_TIME = re.compile(r"(?:\bat\s+)?(?<![\d.:/-])(\d{1,2})\.(\d{2})(?![\d.:/-])", re.IGNORECASE)
_NAMED_TIME = re.compile(r"(?:\bat\s+)?\b(noon|midday|midnight)\b", re.IGNORECASE)
_NAMED_TIMES = {"noon": time(12), "midday": time(12), "midnight": time(0)}
_MARK = "\1"  # stands for a removed date or repeat: a bare hour may follow it
_BARE_HOUR = re.compile(rf"{_MARK}\s+(?:at\s+)?(\d{{1,2}})(?![\d.:/-])\b", re.IGNORECASE)
_LOCATION = re.compile(r"(?:^|\s)@")
_CALENDAR = re.compile(r"#(\S+)")
_DAY_NAME = "|".join(
    sorted({d[:n] for d in WEEKDAYS for n in range(3, len(d) + 1)}, key=len, reverse=True)
)
_DAY_LIST = rf"(?:{_DAY_NAME})s?(?:(?:\s*[,&]\s*|\s+and\s+)(?:{_DAY_NAME})s?)*"
_REPEAT = re.compile(
    rf"\b(?:every\s+({_DAY_LIST})|every\s+([a-z]+)|(daily|weekly|monthly|yearly)"
    r"|(?:on\s+)?(weekdays))\b",
    re.IGNORECASE,
)
_LIST_SEP = re.compile(r"\s*[,&]\s*|\s+and\s+", re.IGNORECASE)
# "dec 3-5" / "3-5 dec": a day range, not hours
_MONTH_DAYS = re.compile(r"\b([a-z]{3,})\.?\s+(\d{1,2})\s*[-–]\s*(\d{1,2})(?![\d.:])\b", re.I)
_DAYS_MONTH = re.compile(r"(?<![\d.:])\b(\d{1,2})\s*[-–]\s*(\d{1,2})\s+([a-z]{3,})\b", re.I)
_FREQS = {"day": "DAILY", "week": "WEEKLY", "month": "MONTHLY", "year": "YEARLY"}
_FREQS |= {"daily": "DAILY", "weekly": "WEEKLY", "monthly": "MONTHLY", "yearly": "YEARLY"}
_MON_FRI = frozenset(range(5))


@dataclass(frozen=True)
class QuickAdd:
    summary: str
    start: datetime
    end: datetime
    all_day: bool
    location: str
    calendar: str | None  # a name from ``calendars``; None: no ``#`` given
    unknown_calendar: str = ""  # the ``#`` text that matched no calendar
    rrule: str | None = None  # e.g. "FREQ=WEEKLY;BYDAY=MO"


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


def _take(
    pattern: re.Pattern[str], text: str, mark: str = _GAP
) -> tuple[re.Match[str] | None, str]:
    """The first match of ``pattern`` in ``text`` and ``text`` with it cut out."""
    m = pattern.search(text)
    if m is None:
        return None, text
    return m, f"{text[: m.start()]} {mark} {text[m.end() :]}"


def _byday(days: frozenset[int]) -> str:
    return "FREQ=WEEKLY;BYDAY=" + ",".join(WEEKDAYS[d][:2].upper() for d in sorted(days))


def _repeat(m: re.Match[str]) -> tuple[str, frozenset[int] | None] | None:
    """The RRULE of a repeat phrase and the weekdays (0 = Mon) its first day must be on,
    or None if it isn't one ("every other")."""
    if m[1]:  # "every mon", "every monday and wednesday"
        names = [w.lower().removesuffix("s") for w in _LIST_SEP.split(m[1])]
        days = frozenset(i for i, d in enumerate(WEEKDAYS) for w in names if d.startswith(w))
        return _byday(days), days
    word = (m[2] or m[3] or m[4]).lower()
    if word in _FREQS:
        return f"FREQ={_FREQS[word]}", None
    if word in ("weekday", "weekdays"):
        return _byday(_MON_FRI), _MON_FRI
    return None


def _take_repeat(text: str) -> tuple[tuple[str, frozenset[int] | None] | None, str]:
    """The first repeat phrase that doesn't start the title ("Weekly review" is a name)."""
    for m in _REPEAT.finditer(text):
        if _clean(text[: m.start()]) and (repeat := _repeat(m)):
            return repeat, f"{text[: m.start()]} {_MARK} {text[m.end() :]}"
    return None, text


def _day_ranges(text: str) -> str:
    """ "dec 3-5" -> "dec 3 - dec 5", "3-5 dec" -> "3 dec - 5 dec" (else hours)."""

    def month_days(m: re.Match[str]) -> str:
        return f"{m[1]} {m[2]} - {m[1]} {m[3]}" if month_number(m[1].lower()) else m[0]

    def days_month(m: re.Match[str]) -> str:
        return f"{m[1]} {m[3]} - {m[2]} {m[3]}" if month_number(m[3].lower()) else m[0]

    return _DAYS_MONTH.sub(days_month, _MONTH_DAYS.sub(month_days, text))


def _first_on(day: date, weekdays: frozenset[int] | None) -> date:
    """``day``, or the next day on one of ``weekdays``."""
    while weekdays is not None and day.weekday() not in weekdays:
        day += timedelta(days=1)
    return day


def _dates(text: str, today: date) -> tuple[date, date] | None:
    """``text`` as one date (first == last) or a range "<date> - <date>"."""
    if (day := parse_date(text, today)) is not None:
        return day, day
    for dash in _DASH.finditer(text):
        first, last = parse_date(text[: dash.start()], today), parse_date(text[dash.end() :], today)
        if first is not None and last is not None:
            if last < first:  # "mon-fri" on a Wednesday: the Friday after that Monday
                last = parse_date(text[dash.end() :], first - timedelta(days=1)) or last
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
            if _GAP in run or _MARK in run or (days := _dates(" ".join(run), today)) is None:
                continue
            if i and words[i - 1].lower() == "on":
                i, size = i - 1, size + 1
            return days, " ".join(words[:i] + [_MARK] + words[i + size :])
    return None, text


def _clean(text: str) -> str:
    return " ".join(w for w in text.split() if w not in (_GAP, _MARK))


def _take_time(text: str, after_date: bool = False) -> tuple[str, time | None]:
    """One time of day taken out of ``text``. ``after_date``: also a bare hour right after
    a date or repeat, and any ``H.MM`` (else only one that can't be a date, ``14.30``)."""
    m, rest = _take(_SINGLE, text)
    if m and (start := _hour(m[1], m[2], m[3] or m[4])) is not None:
        return rest, start
    m, rest = _take(_DOT_TIME, text)
    if m and (after_date or int(m[2]) > 12) and (start := _hour(m[1], m[2], None)) is not None:
        return rest, start
    m, rest = _take(_NAMED_TIME, text)
    if m:
        return rest, _NAMED_TIMES[m[1].lower()]
    m, rest = _take(_BARE_HOUR, text, _MARK)
    if after_date and m and (start := _hour(m[1], None, None)) is not None:
        return rest, start
    return text, None


def parse(text: str, today: date, calendars: list[str]) -> QuickAdd:
    """Parse a quick-add line; see the module docstring for the rules."""
    calendar, unknown = None, ""
    tag, rest = _take(_CALENDAR, _day_ranges(text))
    if tag:
        query = tag[1].lower()
        calendar = next((c for c in calendars if c.lower().startswith(query)), None)
        unknown = "" if calendar else tag[1]

    duration = DEFAULT_DURATION
    m, rest = _take(_DURATION, rest)
    if m:
        minutes = int(m[2] or 0) + int(m[3] or 0) + int(m[4] or 0)
        duration = timedelta(hours=int(m[1] or 0), minutes=minutes) or DEFAULT_DURATION

    repeat, rest = _take_repeat(rest)
    rrule, weekdays = repeat or (None, None)

    times: tuple[time, time | None] | None = None
    m, rest = _take(_RANGE, rest)
    if m and (span := _range(m)):
        times = span
    else:
        rest, start = _take_time(rest)
        if start is not None:
            times = (start, None)

    days, rest = _take_date(rest, today)
    if times is None:  # "tomorrow 9", "tomorrow 12.11"
        rest, start = _take_time(rest, after_date=True)
        times = None if start is None else (start, None)
    day, last = days or (today, today)
    offset = _first_on(day, weekdays) - day  # "every mon" from a Wednesday: next Monday
    day, last = day + offset, last + offset
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
        rrule,
    )
