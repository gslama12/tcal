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
``set_view()``, ``toggle_calendar()``, ``refresh_data()``, ``save_event()``,
``delete_event()``, ``request_sync()``, ``sync_status``.
"""

from collections.abc import Callable
from dataclasses import replace
from datetime import date, datetime

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import ContentSwitcher
from textual.worker import Worker, WorkerState

from tcal.config import Config, ConfigError, load_config
from tcal.model import Calendar, Event, Occurrence
from tcal.source import EventSource
from tcal.sync import SyncSummary
from tcal.ui.keys import binding, keymap
from tcal.ui.messages import EventSelected, NewEventRequested
from tcal.ui.screens.event_detail import EventDetail, confirm_delete
from tcal.ui.state import AppState, ViewMode
from tcal.ui.theme import PALETTES, make_theme
from tcal.ui.widgets.calendar_list import CalendarList
from tcal.ui.widgets.minical import MiniCal
from tcal.ui.widgets.month_view import MonthView
from tcal.ui.widgets.statusbar import StatusBar
from tcal.ui.widgets.timegrid import DayView, TimeGrid, WeekView
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
        self,
        source: EventSource,
        config: Config | None = None,
        today: date | None = None,
        sync: Callable[[], SyncSummary] | None = None,
    ) -> None:
        """``sync`` runs one sync (in a worker thread): on startup, every
        ``[sync] interval``, on the sync key and after edits. None = no syncing."""
        super().__init__()
        self.source = source
        self._sync = sync
        self.sync_status = ""  # shown in the status bar
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

    def save_event(self, event: Event) -> Event:
        """Create/update an event in the cache, redraw, and push it in the background."""
        saved = self.source.save_event(event)
        self.refresh_data()
        self.request_sync()
        return saved

    def delete_event(self, uid: str, occurrence: datetime | None = None) -> None:
        """Delete an event, or one instance of a series: pass the instance's
        original start (``occ.event.recurrence_id or occ.start``)."""
        self.source.delete_event(uid, occurrence)
        self.refresh_data()
        self.request_sync()

    # ----- sync -----------------------------------------------------------

    def request_sync(self) -> None:
        """Start a background sync unless one is running (or syncing is off)."""
        if self._sync is None or any(w.group == "sync" and w.is_running for w in self.workers):
            return
        self.sync_status = "syncing…"
        self.refresh_data()
        self.run_worker(self._sync, group="sync", thread=True, exit_on_error=False)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        worker = event.worker
        if worker.group != "sync" or event.state not in (WorkerState.SUCCESS, WorkerState.ERROR):
            return
        if event.state is WorkerState.SUCCESS:
            self.sync_status = f"synced {datetime.now():%H:%M}"
        else:
            self.sync_status = f"sync failed: {worker.error}"
            self.log.error(f"sync failed: {worker.error!r}")
        self.refresh_data()

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
        if self._sync is not None:
            self.request_sync()
            self.set_interval(self.config.sync.interval, self.request_sync)

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

    def selected_occurrence(self) -> Occurrence | None:
        """The event under the cursor of the focused day/week view, if any."""
        return self.focused.selected if isinstance(self.focused, TimeGrid) else None

    def action_edit_event(self) -> None:
        if occ := self.selected_occurrence():
            self.edit_occurrence(occ)

    def edit_occurrence(self, occurrence: Occurrence) -> None:
        """Hook for the event form (edit ``occurrence``'s event)."""
        self.notify(f"Edit {occurrence.summary!r}: not implemented yet")

    def action_delete_event(self) -> None:
        if occ := self.selected_occurrence():
            confirm_delete(self, occ)
        else:
            self.notify("No event selected")

    def action_goto_date(self) -> None:
        self.notify("Go to date: not implemented yet")

    def action_search(self) -> None:
        self.notify("Search: not implemented yet")

    def action_sync(self) -> None:
        if self._sync is None:
            self.notify("Syncing is off (no account)")
        self.request_sync()

    def action_help(self) -> None:
        self.notify("Help: not implemented yet")

    def on_event_selected(self, message: EventSelected) -> None:
        self.push_screen(EventDetail(message.occurrence))

    def on_new_event_requested(self, message: NewEventRequested) -> None:
        self.notify(f"New event at {message.start:%a %H:%M}: not implemented yet")
