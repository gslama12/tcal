"""TcalApp: the Google-Calendar-like shell, the app state and the data seam.

Layout::

    ┌ sidebar ─┐┌ main ───────────────────────────┐
    │ MiniCal  ││ ViewSwitcher (tabs + title)     │
    │          ││ ContentSwitcher: Day/Week/      │
    │ Calendar ││   Month/YearView (id = mode)    │
    │ List     ││                                 │
    └──────────┘└─────────────────────────────────┘
     StatusBar

Public API for widgets/screens: ``state``, ``config``, ``palette``,
``calendars()``, ``calendar_color()``, ``occurrences()``, ``select_date()``,
``set_view()``, ``toggle_calendar()``, ``refresh_data()``.
"""

from dataclasses import replace
from datetime import date

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import ContentSwitcher

from tcal.config import Config, ConfigError, load_config
from tcal.model import Calendar, Occurrence
from tcal.source import EventSource
from tcal.ui.keys import binding, keymap
from tcal.ui.state import AppState, ViewMode
from tcal.ui.theme import PALETTES, make_theme
from tcal.ui.widgets.calendar_list import CalendarList
from tcal.ui.widgets.minical import MiniCal
from tcal.ui.widgets.month_view import MonthView
from tcal.ui.widgets.statusbar import StatusBar
from tcal.ui.widgets.timegrid import DayView, WeekView
from tcal.ui.widgets.view_switcher import ViewSwitcher
from tcal.ui.widgets.year_view import YearView


class TcalApp(App[None]):
    CSS_PATH = "styles.tcss"
    TITLE = "tcal"

    BINDINGS = [
        binding("prev_period", "Previous"),
        binding("next_period", "Next"),
        binding("today", "Today"),
        binding("view_day", "Day", action="set_view('day')"),
        binding("view_week", "Week", action="set_view('week')"),
        binding("view_month", "Month", action="set_view('month')"),
        binding("view_year", "Year", action="set_view('year')"),
        binding("new_event", "New event"),
        binding("edit_event", "Edit event"),
        binding("delete_event", "Delete event"),
        binding("goto_date", "Go to date"),
        binding("search", "Search"),
        binding("sync", "Sync"),
        binding("focus_calendars", "Calendars"),
        binding("focus_next", "Next pane"),
        binding("help", "Help"),
        binding("quit", "Quit"),
    ]

    # The one redraw signal: replaced on navigation, re-assigned on data refresh.
    state: reactive[AppState] = reactive(
        AppState(date.today(), ViewMode.WEEK), always_update=True, init=False
    )

    def __init__(
        self, source: EventSource, config: Config | None = None, today: date | None = None
    ) -> None:
        super().__init__()
        self.source = source
        self.config = config or load_config()
        name = self.config.theme.name
        if name not in PALETTES:
            raise ConfigError(f"unknown theme {name!r}; one of {', '.join(PALETTES)}")
        self.palette = PALETTES[name]
        self.register_theme(make_theme(name))
        self.theme = f"tcal-{name}"
        self._calendars = source.calendars()
        self.set_reactive(
            TcalApp.state,
            AppState(
                day=today or date.today(),
                view=ViewMode(self.config.view.default_view),
                week_start=self.config.view.week_start,
                hidden_calendars=frozenset(c.id for c in self._calendars if not c.visible),
            ),
        )

    # ----- data seam ------------------------------------------------------

    def calendars(self) -> list[Calendar]:
        return self._calendars

    def calendar_color(self, calendar_id: str) -> str:
        for cal in self._calendars:
            if cal.id == calendar_id:
                return cal.color
        return self.palette.foreground1

    def occurrences(self, start: date, end: date) -> list[Occurrence]:
        """Occurrences of visible calendars in the days [start, end), sorted by start."""
        hidden = self.state.hidden_calendars
        return [o for o in self.source.occurrences(start, end) if o.calendar_id not in hidden]

    def refresh_data(self) -> None:
        """Re-read calendars from the source and redraw everything (e.g. after sync)."""
        self._calendars = self.source.calendars()
        self.state = self.state

    # ----- state changes --------------------------------------------------

    def select_date(self, day: date) -> None:
        self.state = replace(self.state, day=day)

    def set_view(self, mode: ViewMode | str) -> None:
        self.state = replace(self.state, view=ViewMode(mode))

    def toggle_calendar(self, calendar_id: str) -> None:
        self.state = replace(
            self.state, hidden_calendars=self.state.hidden_calendars ^ {calendar_id}
        )

    def watch_state(self, state: AppState) -> None:
        self.query_one("#views", ContentSwitcher).current = state.view.value

    # ----- layout ---------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Horizontal(id="body"):
            with Vertical(id="sidebar"):
                yield MiniCal()
                yield CalendarList()
            with Vertical(id="main"):
                yield ViewSwitcher()
                with ContentSwitcher(id="views", initial=self.state.view.value):
                    yield DayView(id=ViewMode.DAY.value)
                    yield WeekView(id=ViewMode.WEEK.value)
                    yield MonthView(id=ViewMode.MONTH.value)
                    yield YearView(id=ViewMode.YEAR.value)
        yield StatusBar()

    def on_mount(self) -> None:
        self.set_keymap(keymap(self.config))
        self.query_one(f"#{self.state.view.value}").focus()

    # ----- actions --------------------------------------------------------

    def action_prev_period(self) -> None:
        self.state = self.state.shifted(-1)

    def action_next_period(self) -> None:
        self.state = self.state.shifted(1)

    def action_today(self) -> None:
        self.select_date(date.today())

    def action_set_view(self, mode: str) -> None:
        self.set_view(mode)
        self.query_one(f"#{mode}").focus()

    def action_focus_calendars(self) -> None:
        self.query_one(CalendarList).focus()

    # Filled in by the crud / backend packages.
    def action_new_event(self) -> None:
        self.notify("New event: not implemented yet")

    def action_edit_event(self) -> None:
        self.notify("Edit event: not implemented yet")

    def action_delete_event(self) -> None:
        self.notify("Delete event: not implemented yet")

    def action_goto_date(self) -> None:
        self.notify("Go to date: not implemented yet")

    def action_search(self) -> None:
        self.notify("Search: not implemented yet")

    def action_sync(self) -> None:
        self.notify("Sync: not implemented yet")

    def action_help(self) -> None:
        self.notify("Help: not implemented yet")
