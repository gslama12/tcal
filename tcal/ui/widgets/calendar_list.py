from rich.style import Style
from rich.text import Text
from textual import events
from textual.app import RenderResult

from tcal.ui.keys import binding
from tcal.ui.widgets.base import TcalWidget


class CalendarList(TcalWidget, can_focus=True):
    """ "My calendars": one row per calendar, a checkbox in its color and its name.

    j/k move the cursor, space/enter or a click toggles the calendar's
    visibility via ``app.toggle_calendar`` (hidden ones are in
    ``state.hidden_calendars``).
    """

    BORDER_TITLE = "My calendars"
    BINDINGS = [
        binding("cursor_down", action="move(1)"),
        binding("cursor_up", action="move(-1)"),
        binding("toggle_calendar", action="toggle_visible"),
        binding("open", action="toggle_visible"),
    ]

    cursor = 0

    def render(self) -> RenderResult:
        hidden = self.tcal.state.hidden_calendars
        p = self.tcal.palette
        rows = []
        for i, cal in enumerate(self.tcal.calendars()):
            shown = cal.id not in hidden
            row = Text()
            row.append("■ " if shown else "□ ", style=Style(color=cal.color, bold=True))
            row.append(cal.name, style=Style(color=p.foreground3 if shown else p.foreground1))
            if self.has_focus and i == self.cursor:
                row.pad_right(self.content_size.width - len(row))
                row.stylize(Style(bgcolor=p.background3))
            rows.append(row)
        return Text("\n", no_wrap=True, overflow="ellipsis").join(rows)

    def on_click(self, event: events.Click) -> None:
        offset = event.get_content_offset(self)
        if offset is not None and offset.y < len(self.tcal.calendars()):
            self.cursor = offset.y
            self.action_toggle_visible()

    def action_move(self, n: int) -> None:
        self.cursor = max(0, min(self.cursor + n, len(self.tcal.calendars()) - 1))
        self.refresh()

    def action_toggle_visible(self) -> None:
        calendars = self.tcal.calendars()
        if calendars:
            self.tcal.toggle_calendar(calendars[min(self.cursor, len(calendars) - 1)].id)

    def on_focus(self) -> None:
        self.refresh()

    def on_blur(self) -> None:
        self.refresh()
