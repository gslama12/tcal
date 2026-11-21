from textual.app import RenderResult

from tcal.ui.widgets.base import CalendarView


class YearView(CalendarView):
    """12 mini-months of ``state.day``'s year (package: views).

    Days with events highlighted, selected day marked; h/j/k/l move by day/week,
    enter opens the day (``set_view(DAY)``).
    """

    def render(self) -> RenderResult:
        occs = self.tcal.occurrences(*self.tcal.state.period())
        return f"YearView placeholder: {len(occs)} occurrences"
