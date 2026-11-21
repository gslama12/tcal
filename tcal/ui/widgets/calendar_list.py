from rich.text import Text
from textual.app import RenderResult

from tcal.ui.widgets.base import TcalWidget


class CalendarList(TcalWidget, can_focus=True):
    """Toggleable list of calendars below the minical (package: views).

    One row per ``self.tcal.calendars()``: a checkbox in the calendar's color
    and its name. j/k (cursor_down/up) move, enter/space or a click toggles via
    ``self.tcal.toggle_calendar(cal.id)``; hidden ones are in
    ``state.hidden_calendars``.
    """

    def render(self) -> RenderResult:
        hidden = self.tcal.state.hidden_calendars
        text = Text()
        for cal in self.tcal.calendars():
            text.append("■ " if cal.id not in hidden else "□ ", style=cal.color)
            text.append(f"{cal.name}\n")
        return text
