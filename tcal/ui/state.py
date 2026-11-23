"""App state: what is selected and shown. Immutable; the app replaces it.

``TcalApp.state`` is a reactive holding an AppState. Widgets react with
``self.watch(self.app, "state", callback)``; the callback also fires after a
data refresh (sync) with an unchanged state, so it is the one redraw signal.
"""

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Literal

from tcal.dates import add_months


class ViewMode(StrEnum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    YEAR = "year"
    SCHEDULE = "schedule"


Edge = Literal["start", "end"]

SCHEDULE_DAYS = 14  # a schedule "period": H/L page by two weeks


@dataclass(frozen=True)
class Resize:
    """Resize mode: the cursor up/down keys move this edge of event ``uid``."""

    uid: str
    edge: Edge = "end"

    def toggled(self) -> "Resize":
        return replace(self, edge="start" if self.edge == "end" else "end")


@dataclass(frozen=True)
class AppState:
    day: date  # the selected day (cursor); every view keeps it in its range
    view: ViewMode
    week_start: int = 0  # 0 = Monday .. 6 = Sunday
    hidden_calendars: frozenset[str] = frozenset()
    marked: frozenset[tuple[str, datetime]] = frozenset()  # tab-marked ``Occurrence.key``s
    grid: bool = False  # day/week: the cursor keys move a slot cursor, not between events
    resize: Resize | None = None  # day/week: resize mode, and the edge it moves

    def period(self) -> tuple[date, date]:
        """The [start, end) day range of the current view's period."""
        d = self.day
        match self.view:
            case ViewMode.DAY:
                return d, d + timedelta(days=1)
            case ViewMode.WEEK:
                start = d - timedelta(days=(d.weekday() - self.week_start) % 7)
                return start, start + timedelta(days=7)
            case ViewMode.MONTH:
                start = d.replace(day=1)
                return start, add_months(start, 1)
            case ViewMode.YEAR:
                return date(d.year, 1, 1), date(d.year + 1, 1, 1)
            case ViewMode.SCHEDULE:
                return d, d + timedelta(days=SCHEDULE_DAYS)

    def shifted(self, n: int) -> "AppState":
        """Move the selected date by ``n`` periods (prev/next)."""
        match self.view:
            case ViewMode.DAY:
                new = self.day + timedelta(days=n)
            case ViewMode.WEEK:
                new = self.day + timedelta(weeks=n)
            case ViewMode.MONTH:
                new = add_months(self.day, n)
            case ViewMode.YEAR:
                new = add_months(self.day, 12 * n)
            case ViewMode.SCHEDULE:
                new = self.day + timedelta(days=SCHEDULE_DAYS * n)
        return replace(self, day=new)

    def title(self, short: bool = False) -> str:
        """Human title of the current period, e.g. 'November 2026'
        (``short``: abbreviated names, e.g. 'Nov 2026', 'Sat 21 Nov 2026')."""
        start, end = self.period()
        last = end - timedelta(days=1)
        match self.view:
            case ViewMode.DAY:
                return f"{start:%a %-d %b %Y}" if short else f"{start:%A, %-d %B %Y}"
            case ViewMode.WEEK:
                if start.year != last.year:
                    return f"{start:%-d %b %Y} – {last:%-d %b %Y}"
                if start.month != last.month:
                    return f"{start:%-d %b} – {last:%-d %b %Y}"
                return f"{start:%-d} – {last:%-d {'%b' if short else '%B'} %Y}"
            case ViewMode.MONTH | ViewMode.SCHEDULE:
                return f"{start:%b %Y}" if short else f"{start:%B %Y}"
            case ViewMode.YEAR:
                return str(start.year)
