"""Base classes for tcal widgets: typed app access and the state-change hook."""

from collections.abc import Iterable
from typing import TYPE_CHECKING, cast

from rich.cells import cell_len
from rich.style import Style
from rich.text import Text
from textual.widget import Widget

from tcal.ui.keys import VIEW_BINDINGS, binding
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


class SidebarWidget(TcalWidget, can_focus=True):
    """A focusable sidebar pane: the cancel key (esc) returns focus to the main view
    (on a narrow terminal the sidebar then hides again)."""

    BINDINGS = [binding("cancel", action="leave")]

    def action_leave(self) -> None:
        self.tcal.focus_view()


class CalendarView(TcalWidget, can_focus=True):
    """Base of the main-panel views (Day/Week/Month/Year/Schedule).

    Declares the configurable cursor/zoom/open bindings (``VIEW_BINDINGS``);
    subclasses implement the matching ``action_cursor_left/down/up/right``,
    ``action_open`` and, where it makes sense, ``action_zoom_in/out``. Moving
    the cursor across days calls ``self.tcal.select_date(day)``.
    """

    BINDINGS = VIEW_BINDINGS

    def cursor_style(self) -> Style:
        """Background of the selected day / event row (brighter while focused)."""
        p = self.tcal.palette
        return Style(bgcolor=p.background3 if self.has_focus else p.background2)


def join_lines(lines: Iterable[Text]) -> Text:
    """Rendered lines as one Text, cropped (not wrapped) to the widget width."""
    return Text("\n", no_wrap=True, overflow="crop").join(lines)


def fit(text: str, width: int) -> str:
    """``text`` cut to ``width`` cells, ending with ``…`` when cut."""
    if cell_len(text) <= width:
        return text
    out = ""
    for ch in text:
        if cell_len(out + ch) >= width:
            break
        out += ch
    return out.rstrip() + "…" if width > 0 else ""
