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
- times: a range ``12:30-13:30`` / ``12-13`` / ``9-11am`` / ``1pm-3`` / ``9.30-11``, or one time
  ``12:30`` / ``9am`` / ``1:30p`` / ``18h`` / ``14.30`` / ``noon`` / ``midnight`` (optionally
  after ``at`` / ``from``); an end before the start is on the next day. Right after a date or
  repeat also a bare hour ``9``, ``1330`` or ``9a`` (``tomorrow 9``); a number after ``at`` and
  ``1p`` only where the title ends (``1p`` also starting the line, ``at 9a`` anywhere).
  ``12.11`` is a date unless a date is given elsewhere. Or ``all day``.
- repeats: ``daily`` / ``weekly`` / ``monthly`` / ``yearly``, ``every day|week|month|year``,
  ``every 2 weeks`` (also ``every other week``; ``on mon, wed``), ``every weekday`` /
  ``weekdays`` (Mon–Fri) and ``every <weekday>`` (also a list: ``every mon and wed``, ``every
  tue, thu``, ``every mo, we``); the first one is on or after the date. A repeat word that
  starts the line is part of the title ("Weekly review fri"). Ends: ``until 24.12.`` /
  ``until dec`` (through that month), ``10 times``. ``no repeat``: none.
- a date in any of goto's forms (``fri``, ``next fri``, ``in 2 days``, ``24.12.``, ``dec 24``,
  ``+2w``, ``in 3d``, ``1.1.27``, ``tonight``, ``tmr``), optionally after ``on``. A range
  ``dec 3 - dec 5`` / ``dec 3-5`` / ``1.12.-3.12.`` / ``mon-fri`` spans several days (with a
  time: from the first day to the last).
- short dates that are words, names or fractions too (``tom``, ``tod``, ``mo`` .. ``su``,
  ``24/12``) count only if the line has no other date, a title remains without them and they
  are in a date position: after ``on``; before a time; or where the title ends (before the end
  of the line, a repeat, ``#`` or ``@``) or goes on with "with". ``we`` must be before a time or
  repeat or after ``on``; a slash date may also start the line. A short word is no date after
  one that takes a name ("with Tom", "call Tom", "Anna, Tom"; ``_BEFORE_NAME``), and in the
  location only before a time; a slash date never is one there ("Main St 14/3").
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
_MARK = "\1"  # stands for a removed date or repeat: a bare hour may follow it
_TIME_GAP = "\2"  # stands for a removed time
_GAPS = (_GAP, _MARK, _TIME_GAP)

_SUFFIX = r"(\s*(?:am|pm|h)|[ap])"  # no space before "a" / "p": "10-11 a walk"
_TIME = rf"(\d{{1,2}})(?:([:.])(\d{{2}}))?{_SUFFIX}?"
_RANGE = re.compile(
    rf"(?:\b(?:from|at)\s+)?(?<![\d.:/-]){_TIME}\s*[-–]\s*{_TIME}(?![\d.:/-])\b",
    re.IGNORECASE,
)
_SINGLE = re.compile(
    rf"(?:\bat\s+)?(?<![\d.:/-])(\d{{1,2}})"
    rf"(?::(\d{{2}}){_SUFFIX}?|\.(\d{{2}}){_SUFFIX}|\s*(am|pm|h))(?![\d.:/-])\b",
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
# "9", "9a" or "1330" after a date or "at", or "1p"
_SHORT_TIME = re.compile(
    rf"(?:({_MARK})\s+)?(?:\b(at)\s+)?(?<!\S)(?:(\d{{1,2}})([ap])?|(\d{{2}})(\d{{2}}))(?![\w.:/-])",
    re.IGNORECASE,
)
_LOCATION = re.compile(r"(?:^|\s)@")
_CALENDAR = re.compile(r"(?<!\S)#(\S+)")
_DAY_NAME = "|".join(
    sorted({d[:n] for d in WEEKDAYS for n in range(2, len(d) + 1)}, key=len, reverse=True)
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
# Dates that are something else too: they need a date position.
_SHORT_DATE = re.compile(r"tom|tod|mo|tu|th|fr|sa|su|(?:(?:next|last) )?we|\d+/[\d/]+", re.I)
_IN_3D = re.compile(r"in \d+D")  # "a movie in 3D"
_BEFORE_NAME = re.compile(  # "lunch with Tom", "Anna, Tom": a name follows
    r"@|@?(?:with|and|or|for|to|from|by|of|about|without|vs|the|an?|my|uncle|aunt|mr|dr"
    r"|call|phone|ring|meet|see|visit|ask|tell|text|e?mail|help|remind"
    r"|mit|und|oder|für|von|vom|zu|zum|bei|an|über|ohne|der|die|das|den|dem|ein|onkel|tante)"
    r"|.*[,&+]",
    re.IGNORECASE,
)
_HOUR = r"(?:[01]?\d|2[0-3])"
_HOUR_NEXT = re.compile(
    rf"(?:at (?:{_HOUR}[ap]?|\d{{4}})|{_HOUR}(?:[ap]|\.[0-5]\d)|({_HOUR}|\d{{4}}))(?!\S)",
    re.IGNORECASE,
)
_FREQS = {"day": "DAILY", "month": "MONTHLY", "year": "YEARLY"}
_MON_FRI = frozenset(range(5))


_QUOTED = re.compile(r'(?<![^\s@])"((?:\\.|[^"\\])+)"(?!\S)')
_NOTES = re.compile(r"(?<!\S)//")
_LITERALS = [chr(c) for c in range(0xFDD0, 0xFDF0)]  # noncharacters: stand for quoted strings
_LITERAL_LOCATION = re.compile(r"(?:^|\s)@([\ufdd0-\ufdef])")
# What looks like a time, date or repeat but wasn't taken as one.
_LEFTOVER = re.compile(
    r"(?<!\S)(?:\d{1,2}:\d{2}\S*|\d{1,2}\.\d{1,2}\.\S*|\d{4}-\d{1,2}-\d{1,2}"
    r"|\d{1,2}/\d{1,2}/\d{2,4}|until\s+\S+)"
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


def _half(suffix: str | None) -> str:
    """The half of the day a time's suffix stands for: "a", "p" or "" (none, "h")."""
    letter = (suffix or "").strip().lower()[:1]
    return letter if letter in ("a", "p") else ""


def _hour(h: str, m: str | None, suffix: str | None) -> time | None:
    hour, minute = int(h), int(m or 0)
    if half := _half(suffix):
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if half == "p" else 0)
    if hour > 23 or minute > 59:
        return None
    return time(hour, minute)


def _range(m: re.Match[str]) -> tuple[time, time] | None:
    h1, dot1, m1, s1, h2, dot2, m2, s2 = m.groups()
    dotted = [minute for dot, minute in ((dot1, m1), (dot2, m2)) if dot == "."]
    if dotted and not s1 and not s2 and all(1 <= int(minute) <= 12 for minute in dotted):
        return None  # dates: "1.12-3.12"
    start, end = _hour(h1, m1, s1), _hour(h2, m2, s2)
    if start is None or end is None:
        return None
    if not s1 and _half(s2):  # "9-11am": the start shares the suffix, not in "11-1pm"
        shared = _hour(h1, m1, s2)
        if shared is not None and shared <= end:
            start = shared
    elif _half(s1) and not s2 and 1 <= int(h2) <= 12:  # "1pm-3", "11am-1": the next 3, 1 o'clock
        early = time(int(h2) % 12, end.minute)
        late = early.replace(hour=early.hour + 12)
        end = late if early <= start < late else early
    return start, end


def _cut(text: str, m: re.Match[str], mark: str = _GAP) -> str:
    """``text`` with ``mark`` for the match ``m``."""
    return f"{text[: m.start()]} {mark} {text[m.end() :]}"


def _take(pattern: re.Pattern[str], text: str) -> tuple[re.Match[str] | None, str]:
    """The first match of ``pattern`` in ``text`` and ``text`` with it cut out."""
    m = pattern.search(text)
    return (None, text) if m is None else (m, _cut(text, m))


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
            return _repeat(m), _cut(text, m, _MARK)
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


def _title(text: str) -> str:
    """What is left of ``text`` before the location."""
    return _LOCATION.split(_clean(text), maxsplit=1)[0].strip()


def _ends_title(words: list[str]) -> bool:
    """``words`` start with a removed piece or the location, or there are none."""
    return not words or words[0] in _GAPS or words[0].startswith("@")


def _in_date_position(words: list[str], i: int, end: int, has_time: bool) -> bool:
    """Whether the short date ``words[i:end]`` is where a date is expected (see the module
    docstring)."""
    run, previous = " ".join(words[i:end]).lower(), words[i - 1].lower() if i else ""
    if previous == "on":
        return True
    after = words[end:]
    starts_line = not _clean(" ".join(words[:i]))
    in_location = any(w.startswith("@") for w in words[:i])
    hour = None if has_time else _HOUR_NEXT.match(" ".join(after[:2]))
    before_time = after[:1] in ([_TIME_GAP], [_MARK])
    if hour:  # "tom at 9 lunch", "tom 9 lunch"; not "give Tom 3 books"
        bare = hour[1] is not None
        before_time = not bare or (starts_line and run != "we") or _ends_title(after[1:])
    goes_on = after[:1] in (["with"], ["mit"]) and not starts_line
    ends = not in_location and (_ends_title(after) or goes_on)
    if "/" in run:
        return not in_location and (starts_line or before_time or ends)
    if _BEFORE_NAME.fullmatch(previous):
        return False
    return before_time or (ends and not run.endswith("we"))


def _take_date(text: str, today: date, has_time: bool) -> tuple[tuple[date, date] | None, str]:
    """The longest run of words (≤ 9) that is a date or a date range, and the rest. Short dates
    (``_SHORT_DATE``) come after the others, what may be a time (``12.11``) last."""
    words = text.split()
    found: list[tuple[int, int, int, tuple[date, date], str]] = []
    for size in range(min(9, len(words)), 0, -1):
        for i in range(len(words) - size + 1):
            run, end = " ".join(words[i : i + size]), i + size
            if any(w in _GAPS for w in words[i:end]) or _IN_3D.fullmatch(run):
                continue
            if (days := _dates(run, today)) is None:
                continue
            first = i - 1 if i and words[i - 1].lower() == "on" else i
            rest = " ".join(words[:first] + [_MARK] + words[end:])
            rank = 0
            if _SHORT_DATE.fullmatch(run):
                if not _title(rest) or not _in_date_position(words, i, end, has_time):
                    continue
                rank = 1
            elif (m := _DOT_TIME.fullmatch(run)) and _hour(m[1], m[2], None):
                rank = 2
            found.append((rank, -size, i, days, rest))
    if not found:
        return None, text
    *_, days, rest = min(found)
    return days, rest


def _clean(text: str) -> str:
    return " ".join(w for w in text.split() if w not in _GAPS)


def _short_time(text: str) -> tuple[str, time | None]:
    """A time like ``9``, ``1330`` or ``1p`` in a time position taken out of ``text``."""
    for m in _SHORT_TIME.finditer(text):
        mark, at, hour, half, hh, mm = m.groups()
        ends = _ends_title(text[m.end() :].split())
        starts_line = not _clean(text[: m.start()])
        shortly = _half(half) == "p" and (ends or starts_line)  # "1p", but not "Room 5a"
        placed = bool(half) or ends if at else shortly  # "at 9a", "at 13"
        start = _hour(hour or hh, mm, half)
        if (mark or placed) and start is not None:
            return _cut(text, m, _TIME_GAP), start
    return text, None


def _take_time(text: str, after_date: bool = False) -> tuple[str, time | None]:
    """One time of day taken out of ``text``. ``after_date`` (dates are taken out): also a
    short one in a time position, and any ``H.MM`` (else only one that can't be a date,
    ``14.30``)."""
    for m in _SINGLE.finditer(text):
        start = _hour(m[1], m[2] or m[4], m[3] or m[5] or m[6])
        if start is not None:
            return _cut(text, m, _TIME_GAP), start
    for m in _DOT_TIME.finditer(text):
        start = _hour(m[1], m[2], None)
        if start is not None and (after_date or not 1 <= int(m[2]) <= 12):
            return _cut(text, m, _TIME_GAP), start
    if named := _NAMED_TIME.search(text):
        return _cut(text, named, _TIME_GAP), _NAMED_TIMES[named[1].lower()]
    return _short_time(text) if after_date else (text, None)


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
        rest = _cut(text, m)
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
    for m in _RANGE.finditer(rest):
        if span := _range(m):
            times, rest = span, _cut(rest, m, _TIME_GAP)
            break
    duration, rest = _take_duration(rest)
    if times is None:
        rest, start = _take_time(rest)
        times = None if start is None else (start, None)
    days, rest = _take_date(rest, today, times is not None)
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
