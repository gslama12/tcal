from textual.app import RenderResult

from tcal.ui.widgets.base import TcalWidget


class MiniCal(TcalWidget):
    """Small month calendar at the top of the sidebar (package: views).

    Shows the month of ``state.day``, week rows starting at ``state.week_start``,
    today and the selected day highlighted, days of the current period marked.
    Clicking a day calls ``self.tcal.select_date(day)``. Fixed height (~8 rows).
    """

    def render(self) -> RenderResult:
        return f"{self.tcal.state.day:%B %Y}"
