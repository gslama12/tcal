"""The event prompt's language: one line of text <-> an event.

``parse("Lunch with Anna tomorrow 12:30-13:30 @Cafe Central #Personal", today, names)``
-> ``QuickAdd(summary="Lunch with Anna", start=..12:30, end=..13:30, all_day=False,
location="Cafe Central", calendar="Personal")``. ``to_text(event, today)`` writes such a
line for an event (``parse`` reads it back); ``apply`` puts a parsed line into an event.

Rules (case-insensitive; the pieces may come in any order):
- ``"..."`` is taken literally (quotes around the whole title or location are dropped);
  ``// notes``: everything after it (at a word start) is the notes.
- ``#cal``: a calendar's full name (it may have spaces) or the first one in ``calendars``
  whose name starts with ``cal``.
- ``for 2h`` / ``for 90m`` / ``for 1h30`` / ``for 1.5h``: the duration, also without "for"
  (a bare ``7h`` or more is a time unless another time is given).
- times: a range ``12:30-13:30`` / ``12-13`` / ``9-11am``, or one time ``12:30`` / ``9am`` /
  ``18h`` / ``14.30`` / ``noon`` / ``midnight`` (optionally after ``at`` / ``from``); an end
  before the start is on the next day. Right after a date or repeat a bare hour is a time
  (``tomorrow 9``); ``12.11`` is a date unless a date is given elsewhere. Or ``all day``.
- repeats: ``daily`` / ``weekly`` / ``monthly`` / ``yearly``, ``every day|week|month|year``,
  ``every 2 weeks`` (also ``every other week``; ``on mon, wed``), ``every weekday`` /
  ``weekdays`` (Mon–Fri) and ``every <weekday>`` (also a list: ``every mon and wed``, ``every
  tue, thu``); the first one is on or after the date. A repeat word that starts the line is
  part of the title ("Weekly review fri"). Ends: ``until 24.12.`` / ``until dec`` (through
  that month), ``10 times``. ``no repeat``: none.
- a date in any of goto's forms (``fri``, ``next fri``, ``in 2 days``, ``24.12.``, ``dec 24``,
  ``+2w``, ``tonight``), optionally after ``on``. A range ``dec 3 - dec 5`` / ``dec 3-5`` /
  ``1.12.-3.12.`` / ``mon-fri`` spans several days (with a time: from the first day to the last).
- `` @``: everything after it (at a word start) (once the pieces above are taken out) is the location.

What the line leaves out comes from ``draft`` (a new event's slot, an edited event): the date,
the time of day and duration, notes, and a repeat rule the prompt has no words for. Without a
``draft``: today, all day (a duration is then ignored).
"""

import re
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from itertools import product

from tcal.dates import WEEKDAYS, add_months, date_text, month_number, parse_date
from tcal.model import Calendar, Event
from tcal.repeat import end_phrase, repeat_phrase, until_part, without_end
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
_MINUTES = r"(\d{1,4})\s*(?:m|mins?|minutes?)"
_LENGTH = rf"(?:(\d{{1,3}})([.,]\d)?\s*(?:h|hrs?|hours?)(\d{{2}})?(?:\s*{_MINUTES})?|{_MINUTES})"
_DURATION = re.compile(rf"\bfor\s+{_LENGTH}(?![\w-])", re.IGNORECASE)
_BARE_DURATION = re.compile(rf"(?<!\bat )(?<![\w.:,/-]){_LENGTH}(?![\w.:-])", re.IGNORECASE)
_MAX_BARE_HOURS = 6  # a bare "18h" is a time
_ALL_DAY = re.compile(r"\ball[ -]?day\b", re.IGNORECASE)
_DASH = re.compile(r"\s*[-–]\s*")
_DOT_TIME = re.compile(r"(?:\bat\s+)?(?<![\d.:/-])(\d{1,2})\.(\d{2})(?![\d.:/-])", re.IGNORECASE)
_NAMED_TIME = re.compile(r"(?:\bat\s+)?\b(noon|midday|midnight)\b", re.IGNORECASE)
_NAMED_TIMES = {"noon": time(12), "midday": time(12), "midnight": time(0)}
_MARK = "\1"  # stands for a removed date or repeat: a bare hour may follow it
_BARE_HOUR = re.compile(rf"{_MARK}\s+(?:at\s+)?(\d{{1,2}})(?![\d.:/-])\b", re.IGNORECASE)
_LOCATION = re.compile(r"(?:^|\s)@")
_CALENDAR = re.compile(r"(?<!\S)#(\S+)")
_DAY_NAME = "|".join(
    sorted({d[:n] for d in WEEKDAYS for n in range(3, len(d) + 1)}, key=len, reverse=True)
)
_DAY_LIST = rf"(?:{_DAY_NAME})s?(?:(?:\s*[,&]\s*|\s+and\s+)(?:{_DAY_NAME})s?)*"
_REPEAT = re.compile(
    rf"\b(?:every\s+({_DAY_LIST})"
    rf"|every\s+(?:(\d{{1,3}}|other)\s+)?(?:(day|month|year)s?|weeks?(?:\s+on\s+({_DAY_LIST}))?)"
    r"|(daily|weekly|monthly|yearly)|(?:(?:every|on)\s+)?weekdays|every\s+weekday)\b",
    re.IGNORECASE,
)
_NO_REPEAT = re.compile(r"\bno\s+repeat\b", re.IGNORECASE)
_TIMES = re.compile(r"(?:\bfor\s+)?(?<![\d.:/-])\b([1-9]\d{0,3})\s+times\b", re.IGNORECASE)
_UNTIL = re.compile(r"\b(?:until|till?)\s+", re.IGNORECASE)
_UNTIL_MONTH = re.compile(r"([a-z]+)\.?(?:\s+(\d{4}))?", re.IGNORECASE)
_LIST_SEP = re.compile(r"\s*[,&]\s*|\s+and\s+", re.IGNORECASE)
# "dec 3-5" / "3-5 dec": a day range, not hours
_MONTH_DAYS = re.compile(r"\b([a-z]{3,})\.?\s+(\d{1,2})\s*[-–]\s*(\d{1,2})(?![\d.:])\b", re.I)
_DAYS_MONTH = re.compile(r"(?<![\d.:])\b(\d{1,2})\s*[-–]\s*(\d{1,2})\s+([a-z]{3,})\b", re.I)
_FREQS = {"day": "DAILY", "month": "MONTHLY", "year": "YEARLY"}
_MON_FRI = frozenset(range(5))


_QUOTED = re.compile(r'(?<![^\s@])"((?:\\.|[^"\\])+)"(?!\S)')
_NOTES = re.compile(r"(?<!\S)//")
_LITERALS = [chr(c) for c in range(0xFDD0, 0xFDF0)]  # noncharacters: stand for quoted strings
_LITERAL_LOCATION = re.compile(r"(?:^|\s)@([\ufdd0-\ufdef])")
# What looks like a time, date or repeat but wasn't taken as one.
_LEFTOVER = re.compile(
    r"(?<!\S)(?:\d{1,2}:\d{2}\S*|\d{1,2}\.\d{1,2}\.\S*|\d{4}-\d{1,2}-\d{1,2}|until\s+\S+)"
    r"|(?<=\S )every\s+\S+",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class QuickAdd:
    summary: str
    start: datetime
    end: datetime
    all_day: bool
    location: str
    calendar: str | None  # a name from ``calendars``; None: no ``#`` given
    rrule: str | None = None  # e.g. "FREQ=WEEKLY;BYDAY=MO"
    notes: str | None = None  # None: no ``//`` given
    has_date: bool = False  # the line says so (else the draft's)
    has_time: bool = False
    has_repeat: bool = False
    warnings: tuple[str, ...] = ()  # bits that weren't understood
    error: str = ""  # why it can't be saved


def _mask(text: str) -> tuple[str, dict[str, str], str | None]:
    """``text`` without its notes and with one character per quoted string, the quoted
    strings by that character, and the notes."""
    literals: dict[str, str] = {}
    parts, pos = [], 0
    while (m := _QUOTED.search(text, pos)) and len(literals) < len(_LITERALS):
        if _NOTES.search(text, pos, m.start()):
            break
        literals[mark := _LITERALS[len(literals)]] = m[0]
        parts += [text[pos : m.start()], mark]
        pos = m.end()
    tail, *notes = _NOTES.split(text[pos:], maxsplit=1)
    return "".join([*parts, tail]), literals, notes[0].strip() if notes else None


def _unmask(text: str, literals: dict[str, str]) -> str:
    if text in literals:
        return re.sub(r"\\(.)", r"\1", literals[text][1:-1])
    return "".join(literals.get(c, c) for c in text)


def _quote(text: str) -> str:
    return '"' + re.sub(r'(["\\])', r"\\\1", text) + '"'


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


def _byday(days: frozenset[int], interval: str = "") -> str:
    return f"FREQ=WEEKLY{interval};BYDAY=" + ",".join(WEEKDAYS[d][:2].upper() for d in sorted(days))


def _weekdays(text: str) -> frozenset[int]:
    """The weekdays (0 = Mon) of a list like "monday and wed"."""
    names = [w.lower().removesuffix("s") for w in _LIST_SEP.split(text)]
    return frozenset(i for i, d in enumerate(WEEKDAYS) for w in names if d.startswith(w))


def _repeat(m: re.Match[str]) -> tuple[str, frozenset[int] | None]:
    """The RRULE of a repeat phrase and the weekdays its first day must be on."""
    listed, count, unit, on, adverb = m.groups()
    if listed:  # "every mon", "every monday and wednesday"
        return _byday(days := _weekdays(listed)), days
    if adverb:
        return f"FREQ={adverb.upper()}", None
    if "weekday" in m[0].lower():
        return _byday(_MON_FRI), _MON_FRI
    n = 2 if count and count.lower() == "other" else max(int(count or 1), 1)
    interval = f";INTERVAL={n}" if n > 1 else ""
    if on:  # "every 2 weeks on mon, wed"
        return _byday(days := _weekdays(on), interval), days
    return f"FREQ={_FREQS[unit.lower()] if unit else 'WEEKLY'}{interval}", None


def _take_repeat(text: str) -> tuple[tuple[str, frozenset[int] | None] | None, str]:
    """The first repeat phrase that doesn't start the title ("Weekly review" is a name)."""
    for m in _REPEAT.finditer(text):
        if _clean(text[: m.start()]):
            return _repeat(m), f"{text[: m.start()]} {_MARK} {text[m.end() :]}"
    return None, text


def _until_day(text: str, start: date) -> date | None:
    """The last day of a series "until ``text``", on or after ``start`` if no year is given."""
    if (day := parse_date(text, start)) is None:
        m = _UNTIL_MONTH.fullmatch(text)
        first = parse_date(f"1 {m[1]} {m[2] or start.year}", start) if m else None
        if first is None:
            return None
        day = add_months(first, 1) - timedelta(days=1)
    if day < start and not re.search(r"\d{4}", text):
        return _next_year(day)
    return day


def _take_end(text: str, today: date) -> tuple[str, str]:
    """A series' end taken out of ``text``: "COUNT=n", or the words after "until", or ""."""
    m, rest = _take(_TIMES, text)
    if m:
        return f"COUNT={int(m[1])}", rest
    for m in _UNTIL.finditer(text):
        words = text[m.end() :].split()
        for size in range(min(4, len(words)), 0, -1):
            if _until_day(until := " ".join(words[:size]), today) is not None:
                return until, f"{text[: m.start()]} {_GAP} {' '.join(words[size:])}"
    return "", text


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


def _take_calendar(text: str, calendars: list[str]) -> tuple[str | None, str, str]:
    """The calendar named after the first ``#``, the ``#`` text if there is none such, and
    the rest of ``text``."""
    m = _CALENDAR.search(text)
    if m is None:
        return None, "", text
    tag = text[m.start(1) :].lower()
    full = [c for c in calendars if re.match(rf"{re.escape(c.lower())}(?!\S)", tag)]
    prefixed = [c for c in calendars if c.lower().startswith(m[1].lower())]
    name = max(full, key=len) if full else next(iter(prefixed), None)
    end = m.start(1) + len(name) if name in full and name else m.end()
    return name, "" if name else m[1], f"{text[: m.start()]} {_GAP} {text[end:]}"


def _length(m: re.Match[str]) -> timedelta:
    hours, tenths, minutes, more, only = m.groups()
    fraction = float(f"0.{tenths[1:]}") * 60 if tenths else 0
    return timedelta(
        hours=int(hours or 0),
        minutes=fraction + int(minutes or 0) + int(more or 0) + int(only or 0),
    )


def _take_duration(text: str) -> tuple[timedelta | None, str]:
    """ "for 2h", "2h", "90 min" taken out of ``text`` ("18h" only if it has another time)."""
    m, rest = _take(_DURATION, text)
    if m and (length := _length(m)):
        return length, rest
    matches = sorted(_BARE_DURATION.finditer(text), key=lambda m: int(m[1] or 0))
    for m in matches:
        rest = f"{text[: m.start()]} {_GAP} {text[m.end() :]}"
        if (length := _length(m)) and (
            int(m[1] or 0) <= _MAX_BARE_HOURS or _take_time(rest)[1] is not None
        ):
            return length, rest
    return None, text


def _days_of(event: Event) -> tuple[date, date]:
    """The first and last day of ``event`` as written (local): the same day if it ends
    within a day, at an earlier time."""
    start, end = event.start.astimezone(local_zone()), event.end.astimezone(local_zone())
    if event.all_day:
        return start.date(), max((end - timedelta(days=1)).date(), start.date())
    overnight = end.date() == start.date() + timedelta(days=1) and end.time() <= start.time()
    return start.date(), start.date() if overnight else end.date()


def parse(text: str, today: date, calendars: list[str], draft: Event | None = None) -> QuickAdd:
    """Parse a prompt line; see the module docstring for the rules."""
    masked, literals, notes = _mask(text)
    calendar, unknown, rest = _take_calendar(_day_ranges(masked), calendars)
    warnings: list[str] = []
    error = f"No calendar “{unknown}”" if unknown else ""

    no_repeat, rest = _take(_NO_REPEAT, rest)
    repeat, rest = _take_repeat(rest)
    rule, weekdays = repeat or (None, None)
    if not repeat and not no_repeat and draft and draft.rrule and not repeat_phrase(draft.rrule):
        rule = without_end(draft.rrule)  # no words for it: kept
    series_end = ""
    if rule:
        series_end, rest = _take_end(rest, today)
    all_day, rest = _take(_ALL_DAY, rest)

    times: tuple[time, time | None] | None = None
    m, cut = _take(_RANGE, rest)
    if m and (span := _range(m)):
        times, rest = span, cut
    duration, rest = _take_duration(rest)
    if times is None:
        rest, start = _take_time(rest)
        times = None if start is None else (start, None)
    days, rest = _take_date(rest, today)
    if times is None:  # "tomorrow 9", "tomorrow 12.11"
        rest, start = _take_time(rest, after_date=True)
        times = None if start is None else (start, None)
    has_time = times is not None or all_day is not None

    day, last = days or (_days_of(draft) if draft else (today, today))
    offset = _first_on(day, weekdays) - day  # "every mon" from a Wednesday: next Monday
    day, last = day + offset, last + offset

    timed_draft = draft if draft and not draft.all_day else None
    default = timed_draft.end - timed_draft.start if timed_draft else DEFAULT_DURATION
    if all_day:
        if times or duration:
            warnings.append("All day: the time is ignored")
        times = None
    elif times is None and timed_draft and (not days or day == last):
        local = timed_draft.start.astimezone(local_zone())
        times = local.time(), None
        last = day
        has_time = duration is not None
    elif times is None and duration:
        warnings.append("All day: a duration needs a start time")

    if times is None:
        start_dt, end_dt = local_midnight(day), local_midnight(last + timedelta(days=1))
    else:
        start_dt = datetime.combine(day, times[0], local_zone())
        if times[1] is None:
            if not days:
                last = day
            if duration is None:  # the draft's, unless the days span more
                duration = default if last == day else DEFAULT_DURATION
            end_dt = datetime.combine(last, times[0], local_zone()) + duration
        else:
            end_dt = datetime.combine(last, times[1], local_zone())
            if end_dt <= start_dt:
                end_dt += timedelta(days=1)

    if rule and series_end and not series_end.startswith("COUNT="):
        until = _until_day(series_end, day)
        series_end = until_part(until, times is None) if until and until >= day else ""
        if not series_end:
            error = error or "The series can't end before it starts"

    rest = _clean(rest)
    warnings += [f"“{m[0]}” not understood (kept as text)" for m in _LEFTOVER.finditer(rest)]
    if literal := _LITERAL_LOCATION.search(rest):
        summary = f"{rest[: literal.start()]} {rest[literal.end() :]}".strip()
        location = literal[1]
    else:
        summary, *after = _LOCATION.split(rest, maxsplit=1)
        location = after[0] if after else ""
    return QuickAdd(
        _unmask(summary.strip(), literals),
        start_dt,
        end_dt,
        times is None,
        _unmask(location.strip(), literals),
        calendar,
        f"{rule};{series_end}" if rule and series_end else rule,
        notes,
        has_date=days is not None,
        has_time=has_time,
        has_repeat=bool(repeat or no_repeat),
        warnings=tuple(warnings),
        error=error,
    )


def _flat(text: str) -> str:
    """``text`` on one line, as the prompt shows it."""
    return ", ".join(line.strip() for line in text.splitlines() if line.strip())


def to_text(event: Event, today: date, calendar: str = "") -> str:
    """``event`` as a prompt line that ``parse`` reads back (title and location are quoted if
    they'd be misread). Left out: notes of several lines, a repeat rule without words for it
    (not its end); ``parse`` keeps both with ``event`` as its draft."""
    first, last = _days_of(event)
    start, end = event.start.astimezone(local_zone()), event.end.astimezone(local_zone())
    when = [date_text(first, today)]
    if last > first:
        when.append(f"- {date_text(last, today)}")
    if event.all_day:
        when.append("all day")
    else:
        when.append(f"{start:%H:%M}" + (f"-{end:%H:%M}" if end > start else ""))
    if event.rrule:
        when += [repeat_phrase(event.rrule) or "", end_phrase(event.rrule, first)]
    if calendar:
        when.append(f"#{calendar}")
    title, location = _flat(event.summary), _flat(event.location)
    notes = event.description.strip()
    tail = [f"// {notes}"] if notes and "\n" not in notes else []
    line = ""
    for quote_title, quote_location in product((False, True), repeat=2):
        place = _quote(location) if quote_location else location
        pieces = [_quote(title) if quote_title and title else title, *when]
        line = " ".join(p for p in [*pieces, f"@{place}" if place else "", *tail] if p)
        q = parse(line, today, [calendar] if calendar else [], event)
        if (q.summary, q.location, q.warnings) == (title, location, ()) and (
            (q.start, q.end, q.error) == (start, end, "")
        ):
            break
    return line


def title_end(text: str, event: Event) -> int:
    """Where the title ends in ``to_text``'s line for ``event`` (inside its quotes)."""
    title = _flat(event.summary)
    quoted = None if text.startswith(title) else _QUOTED.match(text)
    return quoted.end() - 1 if quoted else len(title)


def apply(event: Event, q: QuickAdd, shown: QuickAdd, calendars: list[Calendar]) -> Event:
    """``event`` with ``q`` put into it. What ``q`` has in common with ``shown`` (the line the
    prompt was opened with) keeps the event's own values: time zones, line breaks, an exact
    repeat rule. An instance of a series keeps its calendar and has no repeat rule."""
    calendar_id, rrule = event.calendar_id, event.rrule
    if event.recurrence_id is None:
        if q.calendar not in (None, shown.calendar):
            calendar_id = next(c.id for c in calendars if c.name == q.calendar)
        if q.rrule != shown.rrule:
            rrule = q.rrule
    same_kind = q.all_day == shown.all_day
    return replace(
        event,
        summary=event.summary if q.summary == shown.summary else q.summary,
        calendar_id=calendar_id,
        start=event.start if same_kind and q.start == shown.start else q.start,
        end=event.end if same_kind and q.end == shown.end else q.end,
        all_day=q.all_day,
        location=event.location if q.location == shown.location else q.location,
        description=event.description if q.notes == shown.notes else q.notes or "",
        rrule=rrule,
    )
