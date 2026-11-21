"""Pure date math for month-shaped grids (minical, month view, year view)."""

from calendar import monthrange
from collections import defaultdict
from datetime import date, timedelta

from tcal.model import Occurrence

WEEKDAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def weekday_names(week_start: int) -> list[str]:
    """Short weekday names in display order, e.g. ['Mon', ..., 'Sun']."""
    return [WEEKDAY_NAMES[(week_start + i) % 7] for i in range(7)]


def grid_start(year: int, month: int, week_start: int) -> date:
    """The first day shown in the grid of a month: the week-start day on or before the 1st."""
    first = date(year, month, 1)
    return first - timedelta(days=(first.weekday() - week_start) % 7)


def month_weeks(
    year: int, month: int, week_start: int, weeks: int | None = None
) -> list[list[date]]:
    """Week rows (7 days each) covering the month, padded with the adjacent months' days.

    ``weeks=None`` uses as many rows as needed (4..6); a fixed number (6) keeps
    the height stable as used by the small month calendars.
    """
    start = grid_start(year, month, week_start)
    if weeks is None:
        offset = (date(year, month, 1) - start).days
        weeks = -(-(offset + monthrange(year, month)[1]) // 7)
    return [[start + timedelta(days=7 * w + d) for d in range(7)] for w in range(weeks)]


def occurrence_days(occ: Occurrence) -> list[date]:
    """The local days an occurrence touches (end exclusive; zero-length counts its start day)."""
    first = occ.start.date()
    last = max(first, (occ.end - timedelta(microseconds=1)).date())
    return [first + timedelta(days=i) for i in range((last - first).days + 1)]


def by_day(occurrences: list[Occurrence]) -> dict[date, list[Occurrence]]:
    """Occurrences per day they touch; per day all-day events first, then by start."""
    days: dict[date, list[Occurrence]] = defaultdict(list)
    for occ in occurrences:
        for day in occurrence_days(occ):
            days[day].append(occ)
    for occs in days.values():
        occs.sort(key=lambda o: (not o.all_day, o.start, o.end))
    return dict(days)
