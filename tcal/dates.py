"""Pure date helpers: month arithmetic and ``parse_date`` for dates typed by the user
(goto, the event form and quick add)."""

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

_RELATIVE = re.compile(r"([+-]\d+)\s*([dwmy])")
_NEXT_LAST = re.compile(r"(next|last)\s+(week|month|year)")
_NEXT_WEEKDAY = re.compile(r"(next|last)\s+([a-z]+)")
_IN = re.compile(r"in\s+(\d+)\s+(day|week|month|year)s?")
_ISO = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")
_DOTTED = re.compile(r"(\d{1,2})\.(\d{1,2})\.?(\d{4})?")
_DAY_MONTH = re.compile(r"(\d{1,2})\s+([a-z]+)\.?(?:\s+(\d{4}))?")
_MONTH_DAY = re.compile(r"([a-z]+)\.?\s+(\d{1,2})(?:,?\s+(\d{4}))?")


def _prefix_index(word: str, names: tuple[str, ...]) -> int | None:
    """Index of the name ``word`` abbreviates ("fri", "friday", "dec", "december")."""
    if len(word) < 3:
        return None
    return next((i for i, name in enumerate(names) if name.startswith(word)), None)


def _month(word: str) -> int | None:
    """The month number ``word`` abbreviates (1 = January)."""
    index = _prefix_index(word, MONTHS)
    return None if index is None else index + 1


def _make(year: int, month: int | None, day: int) -> date | None:
    if month is None:
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_date(text: str, today: date) -> date | None:
    """Parse a date typed by the user, relative to ``today``; None if not understood.

    Accepts: today, tomorrow, yesterday; a weekday (mon .. sunday: the next one
    after today); next/last <weekday> (that day in the next/previous week);
    +3d / -1w / +2m / +1y; in 3 days|weeks|months|years (= +3d ...);
    next/last week|month|year (= ±1w/m/y); 2026-12-24; 24.12. / 24.12.2026;
    dec 24 / 24 dec (optionally with a year). Dates without a year are in
    today's year.
    """
    s = text.strip().lower()
    if s in ("today", "now"):
        return today
    if s == "tomorrow":
        return today + timedelta(days=1)
    if s == "yesterday":
        return today - timedelta(days=1)
    if (weekday := _prefix_index(s, WEEKDAYS)) is not None:
        return today + timedelta(days=(weekday - today.weekday() - 1) % 7 + 1)
    if m := _NEXT_LAST.fullmatch(s):
        s = f"{'+' if m[1] == 'next' else '-'}1{m[2][0]}"
    elif (m := _NEXT_WEEKDAY.fullmatch(s)) and (
        weekday := _prefix_index(m[2], WEEKDAYS)
    ) is not None:
        monday = today - timedelta(days=today.weekday())
        return monday + timedelta(weeks=1 if m[1] == "next" else -1, days=weekday)
    if m := _IN.fullmatch(s):
        s = f"+{m[1]}{m[2][0]}"
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
        return _make(int(m[3] or today.year), int(m[2]), int(m[1]))
    if m := _DAY_MONTH.fullmatch(s):
        return _make(int(m[3] or today.year), _month(m[2]), int(m[1]))
    if m := _MONTH_DAY.fullmatch(s):
        return _make(int(m[3] or today.year), _month(m[1]), int(m[2]))
    return None


def add_months(d: date, n: int) -> date:
    """``d`` moved by ``n`` months, clamping the day (31 Jan + 1 -> 28/29 Feb)."""
    month0 = d.month - 1 + n
    year, month = d.year + month0 // 12, month0 % 12 + 1
    return date(year, month, min(d.day, monthrange(year, month)[1]))
