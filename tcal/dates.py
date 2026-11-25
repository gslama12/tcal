"""Pure date helpers: month arithmetic and ``parse_date`` for dates typed by the user
(goto and the event prompt)."""

import re
from calendar import monthrange
from datetime import date, timedelta

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
MONTHS = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)

YEARS = range(1900, 2200)  # what a typed date may be in

_RELATIVE = re.compile(r"([+-]\d+)\s*([dwmy])")
_NEXT_LAST = re.compile(r"(next|last)\s+(week|month|year)")
_NEXT_WEEKDAY = re.compile(r"(next|last)\s+([a-z]+)")
_IN = re.compile(r"in\s+(\d+)(?:\s+(day|week|month|year)s?|\s*([dwy]))")  # "in 3m" may be minutes
_ISO = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")
_DOTTED = re.compile(r"(\d{1,2})\.(\d{1,2})(?:\.?|\.?\s*(\d{4})|\.(\d{2}))")
_DAY_MONTH = re.compile(r"(\d{1,2})\s+([a-z]+)\.?(?:\s+(\d{4}))?")
_MONTH_DAY = re.compile(r"([a-z]+)\.?\s+(\d{1,2})(?:,?\s+(\d{4}))?")
_MONTH_YEAR = re.compile(r"([a-z]+)\.?(?:\s+(\d{4}))?")
_YEAR = re.compile(r"\d{4}")
_SLASHED = re.compile(r"(\d{1,2})/(\d{1,2})(?:/(\d{4}|\d{2}))?")


# "wed 18 nov", "wed 18.11.": the weekday is ignored ("fri 10.10" may be a time, see quickadd)
_AFTER_WEEKDAY = re.compile(
    r"([a-z]+),?\s+(\d{4}-\d.*|\d{1,2}\.\d{1,2}\.(?:\d{4}|\d{2})?|\d{1,2}/\d.*|\d{1,2}\s+[a-z].*"
    r"|[a-z]+\.?\s+\d.*)"
)


def _prefix_index(word: str, names: tuple[str, ...], shortest: int) -> int | None:
    """Index of the name ``word`` abbreviates ("fri", "friday", "dec", "december")."""
    if len(word) < shortest:
        return None
    return next((i for i, name in enumerate(names) if name.startswith(word)), None)


def _weekday(word: str) -> int | None:
    """The weekday (0 = Monday) ``word`` abbreviates ("fr", "fri")."""
    return _prefix_index(word, WEEKDAYS, 2)


def month_number(word: str) -> int | None:
    """The month number ``word`` abbreviates (1 = January)."""
    index = _prefix_index(word, MONTHS, 3)
    return None if index is None else index + 1


def _year(text: str | None, today: date) -> int:
    """A typed year ("2027", "27"), today's if there is none."""
    if not text:
        return today.year
    return int(text) + (2000 if len(text) == 2 else 0)


def _make(year: int, month: int | None, day: int) -> date | None:
    if month is None:
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_date(text: str, today: date) -> date | None:
    """Parse a date typed by the user, relative to ``today``; None if not understood.

    Accepts: today (tod, now, tonight), tomorrow (tom, tmr, tmrw), yesterday (yest); a weekday
    (mo, mon .. sunday: the next one after today); next/last <weekday> (that day in the
    next/previous week); +3d / -1w / +2m / +1y; in 3 days|weeks|months|years (= +3d ...; also
    in 3d|3w|3y); next/last week|month|year (= ±1w/m/y); 2026-12-24; 24.12. / 24.12.2026 /
    24.12.26; 24/12 / 24/12/26 (day/month, only if the day can't be a month; not "24/7");
    dec 24 / 24 dec (optionally with a year), also after a weekday (wed 18 nov). Dates
    without a year are in today's year. None also outside ``YEARS``.
    """
    try:
        day = _parse_date(text, today)
    except (ValueError, OverflowError):  # e.g. "+99999y"
        return None
    return day if day is not None and day.year in YEARS else None


def _parse_date(text: str, today: date) -> date | None:
    s = text.strip().lower()
    if s in ("today", "tod", "now", "tonight"):
        return today
    if s in ("tomorrow", "tom", "tmr", "tmrw"):
        return today + timedelta(days=1)
    if s in ("yesterday", "yest"):
        return today - timedelta(days=1)
    if (weekday := _weekday(s)) is not None:
        return today + timedelta(days=(weekday - today.weekday() - 1) % 7 + 1)
    if m := _NEXT_LAST.fullmatch(s):
        s = f"{'+' if m[1] == 'next' else '-'}1{m[2][0]}"
    elif (m := _NEXT_WEEKDAY.fullmatch(s)) and (weekday := _weekday(m[2])) is not None:
        monday = today - timedelta(days=today.weekday())
        return monday + timedelta(weeks=1 if m[1] == "next" else -1, days=weekday)
    if m := _IN.fullmatch(s):
        s = f"+{m[1]}{(m[2] or m[3])[0]}"
    if m := _RELATIVE.fullmatch(s):
        n, unit = int(m[1]), m[2]
        if unit == "d":
            return today + timedelta(days=n)
        if unit == "w":
            return today + timedelta(weeks=n)
        return add_months(today, n * (12 if unit == "y" else 1))
    if m := _ISO.fullmatch(s):
        return _make(int(m[1]), int(m[2]), int(m[3]))
    if m := _DOTTED.fullmatch(s):
        return _make(_year(m[3] or m[4], today), int(m[2]), int(m[1]))
    if (m := _SLASHED.fullmatch(s)) and int(m[1]) > 12 and s != "24/7":
        return _make(_year(m[3], today), int(m[2]), int(m[1]))
    if m := _DAY_MONTH.fullmatch(s):
        return _make(int(m[3] or today.year), month_number(m[2]), int(m[1]))
    if m := _MONTH_DAY.fullmatch(s):
        return _make(int(m[3] or today.year), month_number(m[1]), int(m[2]))
    if (m := _AFTER_WEEKDAY.fullmatch(s)) and _weekday(m[1]) is not None:
        return parse_date(m[2], today)
    return None


def parse_jump(text: str, today: date) -> date | None:
    """``parse_date`` plus the forms only goto takes (in the event prompt they would eat title
    words like "may" or "2027"): a month ``dec`` / ``jan 2027`` (its first day, in today's
    year without one), a year ``2027`` (1 Jan) and ``12/24`` / ``12/24/2026`` (month/day,
    or day/month when the first number can't be a month)."""
    if (day := parse_date(text, today)) is not None:
        return day
    s = text.strip().lower()
    if m := _MONTH_YEAR.fullmatch(s):
        return _make(int(m[2] or today.year), month_number(m[1]), 1)
    if _YEAR.fullmatch(s):
        return _make(int(s), 1, 1)
    if m := _SLASHED.fullmatch(s):
        year, a, b = _year(m[3], today), int(m[1]), int(m[2])
        return _make(year, a, b) if a <= 12 else _make(year, b, a)
    return None


def add_months(d: date, n: int) -> date:
    """``d`` moved by ``n`` months, clamping the day (31 Jan + 1 -> 28/29 Feb)."""
    month0 = d.month - 1 + n
    year, month = d.year + month0 // 12, month0 % 12 + 1
    return date(year, month, min(d.day, monthrange(year, month)[1]))
