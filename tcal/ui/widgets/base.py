"""Base classes for tcal widgets: typed app access and the state-change hook."""

from typing import TYPE_CHECKING, cast

from textual.widget import Widget

from tcal.ui.keys import VIEW_BINDINGS
from tcal.ui.state import AppState

if TYPE_CHECKING:
    from tcal.ui.app import TcalApp


class TcalWidget(Widget):
    """A widget that redraws on app state changes.

    Override ``on_state``; it runs once on mount and after every state change
    or data refresh. Read data via ``self.tcal.occurrences(...)`` /
    ``self.tcal.calendars()`` and change state via the TcalApp methods.
    """

    @property
    def tcal(self) -> "TcalApp":
        return cast("TcalApp", self.app)

    def on_mount(self) -> None:
        self.watch(self.app, "state", self.on_state)

    def on_state(self, state: AppState) -> None:
        self.refresh()


class CalendarView(TcalWidget, can_focus=True):
    """Base of the main-panel views (Day/Week/Month/Year).

    Declares the configurable cursor/zoom/open bindings (``VIEW_BINDINGS``);
    subclasses implement the matching ``action_cursor_left/down/up/right``,
    ``action_open`` and, where it makes sense, ``action_zoom_in/out``. Moving
    the cursor across days calls ``self.tcal.select_date(day)``.
    """

    BINDINGS = VIEW_BINDINGS
