from datetime import timedelta

from tcal.ui.keys import binding
from tcal.ui.messages import NewEventRequested
from tcal.ui.widgets.base import CalendarView


class DayCursorView(CalendarView):
    """A view whose cursor is the selected day: h/l move a day, j/k a week.

    Enter opens the day in the Day view; 'new event' posts ``NewEventRequested(day)``.
    """

    BINDINGS = [binding("new_event")]

    def move(self, days: int) -> None:
        self.tcal.select_date(self.tcal.state.day + timedelta(days=days))

    def action_cursor_left(self) -> None:
        self.move(-1)

    def action_cursor_right(self) -> None:
        self.move(1)

    def action_cursor_up(self) -> None:
        self.move(-7)

    def action_cursor_down(self) -> None:
        self.move(7)

    def action_open(self) -> None:
        self.tcal.action_set_view("day")

    def action_new_event(self) -> None:
        self.post_message(NewEventRequested(self.tcal.state.day))
