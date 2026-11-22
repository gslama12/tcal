from datetime import date, timedelta

from rich.style import Style
from rich.text import Text
from textual import events
from textual.app import RenderResult

from tcal.dates import add_months
from tcal.ui.calgrid import by_day, grid_start
from tcal.ui.keys import binding
from tcal.ui.state import AppState, ViewMode
from tcal.ui.widgets.base import SidebarWidget
from tcal.ui.widgets.minimonth import WEEKS, WIDTH, day_at, mini_month

PREV_X, NEXT_X = WIDTH - 3, WIDTH - 1  # the "‹ ›" arrows in the header line


class MiniCal(SidebarWidget):
    """Small month calendar at the top of the sidebar.

    Shows the month of its own ``cursor`` (follows ``state.day``): today accented,
    the cursor highlighted, days with events bright (others dimmed), the shown
    week as a band. Focused (``focus_minical``, M), the cursor keys (h/j/k/l) move
    the cursor, the period keys (H/L) by a month and enter jumps the main view to
    it (and focuses it, like clicking a day); clicking ‹ › browses months; esc returns to the main view.
    """

    BINDINGS = [
        binding("cursor_left", action="move(-1)"),
        binding("cursor_right", action="move(1)"),
        binding("cursor_up", action="move(-7)"),
        binding("cursor_down", action="move(7)"),
        binding("prev_period", action="month(-1)"),
        binding("next_period", action="month(1)"),
        binding("open", action="jump"),
    ]

    cursor = date.min  # set from the state on mount

    def on_state(self, state: AppState) -> None:
        self.cursor = state.day
        self.refresh()

    def render(self) -> RenderResult:
        state = self.tcal.state
        month = self.cursor.replace(day=1)
        start = grid_start(month.year, month.month, state.week_start)
        occs = self.tcal.occurrences(start, start + timedelta(weeks=WEEKS))
        week = state.period() if state.view is ViewMode.WEEK else (start, start)
        p = self.tcal.palette
        title = Text(f"{month:%B %Y}", style=Style(bold=True))
        title.align("left", PREV_X)
        title.append("‹ ›", style=Style(color=p.primary, bold=True))
        lines = mini_month(
            month,
            week_start=state.week_start,
            palette=p,
            today=date.today(),
            selected=self.cursor,
            event_days=by_day(occs).keys(),
            marked={week[0] + timedelta(days=i) for i in range((week[1] - week[0]).days)},
        )
        return Text("\n").join([title, *lines])

    def on_click(self, event: events.Click) -> None:
        offset = event.get_content_offset(self)
        if offset is None:
            return
        if offset.y == 0:
            if offset.x == PREV_X:
                self.action_month(-1)
            elif offset.x == NEXT_X:
                self.action_month(1)
            return
        day = day_at(self.cursor.replace(day=1), self.tcal.state.week_start, offset.x, offset.y - 1)
        if day is not None:
            self.tcal.select_date(day)
            self.tcal.focus_view()

    def action_move(self, days: int) -> None:
        self.cursor += timedelta(days=days)
        self.refresh()

    def action_month(self, n: int) -> None:
        self.cursor = add_months(self.cursor, n)
        self.refresh()

    def action_jump(self) -> None:
        self.tcal.select_date(self.cursor)
        self.tcal.focus_view()
