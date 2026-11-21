from textual.app import RenderResult

from tcal.ui.widgets.base import CalendarView


class MonthView(CalendarView):
    """6x7 grid of the month of ``state.day`` (package: views).

    Each cell lists event chips in calendar color, "+N more" when it overflows.
    h/j/k/l move the selected day; enter opens the day (``set_view(DAY)``).
    Data: ``self.tcal.occurrences(grid_start, grid_end)``.
    """

    def render(self) -> RenderResult:
        occs = self.tcal.occurrences(*self.tcal.state.period())
        return f"MonthView placeholder: {len(occs)} occurrences"
