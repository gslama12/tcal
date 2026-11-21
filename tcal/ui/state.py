"""App state: what is selected and shown. Immutable; the app replaces it.

``TcalApp.state`` is a reactive holding an AppState. Widgets react with
``self.watch(self.app, "state", callback)``; the callback also fires after a
data refresh (sync) with an unchanged state, so it is the one redraw signal.
"""

from calendar import monthrange
from dataclasses import dataclass, replace
from datetime import date, timedelta
from enum import StrEnum


class ViewMode(StrEnum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    YEAR = "year"


@dataclass(frozen=True)
class AppState:
    day: date  # the selected day (cursor); every view keeps it in its range
    view: ViewMode
    week_start: int = 0  # 0 = Monday .. 6 = Sunday
    hidden_calendars: frozenset[str] = frozenset()

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
                return start, _add_months(start, 1)
            case ViewMode.YEAR:
                return date(d.year, 1, 1), date(d.year + 1, 1, 1)

    def shifted(self, n: int) -> "AppState":
        """Move the selected date by ``n`` periods (prev/next)."""
        match self.view:
            case ViewMode.DAY:
                new = self.day + timedelta(days=n)
            case ViewMode.WEEK:
                new = self.day + timedelta(weeks=n)
            case ViewMode.MONTH:
                new = _add_months(self.day, n)
            case ViewMode.YEAR:
                new = _add_months(self.day, 12 * n)
        return replace(self, day=new)

    def title(self) -> str:
        """Human title of the current period, e.g. 'November 2026'."""
        start, end = self.period()
        last = end - timedelta(days=1)
        match self.view:
            case ViewMode.DAY:
                return f"{start:%A, %-d %B %Y}"
            case ViewMode.WEEK:
                if start.year != last.year:
                    return f"{start:%-d %b %Y} – {last:%-d %b %Y}"
                if start.month != last.month:
                    return f"{start:%-d %b} – {last:%-d %b %Y}"
                return f"{start:%-d} – {last:%-d %B %Y}"
            case ViewMode.MONTH:
                return f"{start:%B %Y}"
            case ViewMode.YEAR:
                return str(start.year)


def _add_months(d: date, n: int) -> date:
    """``d`` moved by ``n`` months, clamping the day (31 Jan + 1 -> 28/29 Feb)."""
    month0 = d.month - 1 + n
    year, month = d.year + month0 // 12, month0 % 12 + 1
    return date(year, month, min(d.day, monthrange(year, month)[1]))
