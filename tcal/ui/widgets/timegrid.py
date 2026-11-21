from textual.app import RenderResult

from tcal.ui.widgets.base import CalendarView


class DayView(CalendarView):
    """Time grid for one day (package: timegrid).

    Time axis from ``config.view.day_start`` to ``day_end`` (scroll reveals the
    rest of the day), ``rows_per_hour`` zoom (0 = fit height, +/- to zoom),
    all-day strip on top, overlapping events side by side, now-line, slot cursor.
    Data: ``self.tcal.occurrences(*state.period())``; colors from
    ``self.tcal.calendar_color(id)``.
    """

    def render(self) -> RenderResult:
        occs = self.tcal.occurrences(*self.tcal.state.period())
        return f"DayView placeholder: {len(occs)} occurrences"


class WeekView(CalendarView):
    """Time grid for the week of ``state.day`` (package: timegrid).

    Same as DayView with one column per day of ``state.period()``; h/l move the
    cursor between days (crossing into the adjacent week).
    """

    def render(self) -> RenderResult:
        occs = self.tcal.occurrences(*self.tcal.state.period())
        return f"WeekView placeholder: {len(occs)} occurrences"
