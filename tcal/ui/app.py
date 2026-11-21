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
``delete_event()``, ``undo()``, ``request_sync()``, ``show_occurrence()``, ``sync_status``,
``new_event()``, ``edit_event()``, ``edit_occurrence()`` (open the event form),
``check_writable()``, ``focus_view()``.

The sidebar hides itself below ``SIDEBAR_MIN_WIDTH`` columns; the toggle key
overrides that until the terminal crosses the threshold again.
"""

from collections.abc import Callable
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from uuid import uuid4

from textual import events
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.keys import format_key
from textual.reactive import reactive
from textual.widgets import ContentSwitcher
from textual.worker import Worker, WorkerState

from tcal.config import Config, ConfigError, load_config
from tcal.model import Calendar, Event, Occurrence
from tcal.source import EventSource
from tcal.sync import SyncSummary
from tcal.tz import local_midnight, local_zone
from tcal.ui.keys import binding, keymap
from tcal.ui.messages import EventSelected, NewEventRequested
from tcal.ui.screens.event_detail import (
    EditScope,
    EventDetail,
    Scope,
    confirm_delete,
    is_recurring,
)
from tcal.ui.screens.event_form import EventForm
from tcal.ui.screens.goto import GotoScreen
from tcal.ui.screens.help import HelpScreen
from tcal.ui.screens.search import SearchScreen
from tcal.ui.state import AppState, ViewMode, add_months
from tcal.ui.sync_status import SyncStatus
from tcal.ui.theme import PALETTES, make_theme
from tcal.ui.widgets.calendar_list import CalendarList
from tcal.ui.widgets.minical import MiniCal
from tcal.ui.widgets.month_view import MonthView
from tcal.ui.widgets.statusbar import StatusBar
from tcal.ui.widgets.timegrid import DayView, TimeGrid, WeekView
from tcal.ui.widgets.view_switcher import ViewSwitcher
from tcal.ui.widgets.year_view import YearView

SIDEBAR_MIN_WIDTH = 120  # terminal columns below which the sidebar starts hidden
OCC_CACHE_SIZE = 32  # date ranges whose occurrences are kept until the next data refresh


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
        binding("undo", "Undo"),
        binding("goto_date", "Go to date"),
        binding("search", "Search"),
        binding("sync", "Sync"),
        binding("focus_calendars", "Calendars"),
        binding("focus_next", "Next pane"),
        binding("toggle_sidebar", "Sidebar"),
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
        self.sync_status = SyncStatus()  # shown in the status bar
        self._wide: bool | None = None  # terminal >= SIDEBAR_MIN_WIDTH, None before layout
        self._undo: list[Event] = []  # rows of the last deleted event
        self.config = config or load_config()
        name = self.config.theme.name
        if name not in PALETTES:
            raise ConfigError(f"unknown theme {name!r}; one of {', '.join(PALETTES)}")
        self.palette = PALETTES[name]
        self.register_theme(make_theme(name))
        self.theme = f"tcal-{name}"
        self._calendars = source.calendars()
        self._occ_cache: dict[tuple[date, date], list[Occurrence]] = {}
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
        return [o for o in self._occurrences(start, end) if o.calendar_id not in hidden]

    def _occurrences(self, start: date, end: date) -> list[Occurrence]:
        """The source's occurrences, cached per range until ``refresh_data``
        (every widget redraw asks again; most ask for the same few ranges)."""
        key = (start, end)
        if key not in self._occ_cache:
            if len(self._occ_cache) >= OCC_CACHE_SIZE:
                self._occ_cache.clear()
            self._occ_cache[key] = self.source.occurrences(start, end)
        return self._occ_cache[key]

    def refresh_data(self) -> None:
        """Re-read calendars from the source and redraw everything (e.g. after sync)."""
        self._calendars = self.source.calendars()
        self._occ_cache.clear()
        self.state = self.state

    def save_event(self, event: Event) -> Event:
        """Create/update an event in the cache, redraw, and push it in the background."""
        saved = self.source.save_event(event)
        self.refresh_data()
        self.request_sync()
        return saved

    def delete_event(self, uid: str, occurrence: datetime | None = None) -> None:
        """Delete an event, or one instance of a series: pass the instance's
        original start (``occ.event.recurrence_id or occ.start``). The undo key restores it."""
        self._undo = self.source.delete_event(uid, occurrence)
        self.refresh_data()
        self.request_sync()
        if self._undo:
            undo = format_key(self.config.keys["undo"][0])
            self.notify(f"Deleted “{self._undo[0].summary}” · {undo} undo")

    def undo(self) -> None:
        """Restore the last deleted event (once)."""
        if not self._undo:
            self.notify("Nothing to undo")
            return
        self.source.restore(self._undo)
        self.notify(f"Restored “{self._undo[0].summary}”")
        self._undo = []
        self.refresh_data()
        self.request_sync()

    # ----- event form ---------------------------------------------------

    def new_event(self, start: date | datetime) -> None:
        """Open the form for a new event at a time slot (1 h) or on a day (all-day)."""
        if isinstance(start, datetime):
            begin, end, all_day = start, start + timedelta(hours=1), False
        else:
            begin, end, all_day = local_midnight(start), local_midnight(start + timedelta(1)), True
        writable = self._writable()
        if not writable:
            self.notify("No writable calendar", severity="warning")
            return
        draft = Event(f"{uuid4()}@tcal", writable[0].id, "", begin, end, all_day)
        self.push_screen(EventForm(draft, writable, new=True), self._form_done)

    def edit_event(self, event: Event) -> None:
        """Open the form for an existing event (a master edits the whole series)."""
        if self.check_writable(event.calendar_id):
            self.push_screen(EventForm(event, self._writable(), new=False), self._form_done)

    def edit_occurrence(self, occurrence: Occurrence) -> None:
        """Edit ``occurrence``; for a series ask "this event" (an override with a
        RECURRENCE-ID) or "all events" (the master)."""
        if not self.check_writable(occurrence.calendar_id):
            return
        if not is_recurring(occurrence):
            self.edit_event(occurrence.event)
            return

        def done(scope: Scope | None) -> None:
            if scope == "occurrence":
                self.edit_event(instance_of(occurrence))
            elif scope == "series":
                self.edit_event(self.source.get_event(occurrence.event.uid) or occurrence.event)

        self.push_screen(EditScope(occurrence), done)

    def check_writable(self, calendar_id: str) -> bool:
        """True if events in ``calendar_id`` can be edited; else show "<name> is read-only"."""
        calendar = next((c for c in self._calendars if c.id == calendar_id), None)
        if calendar is None or not calendar.readonly:
            return True
        self.notify(f"{calendar.name} is read-only", severity="warning")
        return False

    def _writable(self) -> list[Calendar]:
        return [c for c in self._calendars if not c.readonly]

    def _form_done(self, event: Event | None) -> None:
        if event is not None:
            self.save_event(event)

    # ----- sync -----------------------------------------------------------

    def request_sync(self) -> None:
        """Start a background sync unless one is running (or syncing is off)."""
        if self._sync is None or any(w.group == "sync" and w.is_running for w in self.workers):
            return
        self.sync_status = self.sync_status.started()
        self.refresh_data()
        self.run_worker(self._sync, group="sync", thread=True, exit_on_error=False)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        worker = event.worker
        if worker.group != "sync" or event.state not in (WorkerState.SUCCESS, WorkerState.ERROR):
            return
        if event.state is WorkerState.SUCCESS:
            self.sync_status = self.sync_status.succeeded(datetime.now())
        else:
            self.sync_status = self.sync_status.failed(worker.error)
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

    def focus_view(self) -> None:
        """Focus the main view of the current mode."""
        self.query_one(f"#{self.state.view.value}").focus()

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
        self.focus_view()
        if self._sync is not None:
            self.request_sync()
            self.set_interval(self.config.sync.interval, self.request_sync)

    def on_resize(self, event: events.Resize) -> None:
        wide = event.size.width >= SIDEBAR_MIN_WIDTH
        if wide != self._wide:
            self._wide = wide
            self._show_sidebar(wide)

    def _show_sidebar(self, show: bool) -> None:
        sidebar = self.query_one("#sidebar")
        sidebar.display = show
        if not show and self.focused is not None and sidebar in self.focused.ancestors:
            self.focus_view()

    # ----- actions --------------------------------------------------------

    def action_toggle_sidebar(self) -> None:
        self._show_sidebar(not self.query_one("#sidebar").display)

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
        self._show_sidebar(True)
        self.query_one(CalendarList).focus()

    def action_new_event(self) -> None:
        """A timed event at the next round hour on the selected day (day/week views
        post their own ``NewEventRequested`` for the selected slot)."""
        hour = min(datetime.now().hour + 1, 23)
        self.new_event(datetime.combine(self.state.day, time(hour), local_zone()))

    def selected_occurrence(self) -> Occurrence | None:
        """The event selected in the focused day/week/month view, if any."""
        focused = self.focused
        return focused.selected if isinstance(focused, TimeGrid | MonthView) else None

    def action_edit_event(self) -> None:
        """Edit the event selected in the focused day/week/month view."""
        if occ := self.selected_occurrence():
            self.edit_occurrence(occ)
        else:
            self.notify("No event selected")

    def action_delete_event(self) -> None:
        if occ := self.selected_occurrence():
            confirm_delete(self, occ)
        else:
            self.notify("No event selected")

    def action_undo(self) -> None:
        self.undo()

    def action_goto_date(self) -> None:
        def jump(day: date | None) -> None:
            if day is not None:
                self.select_date(day)

        self.push_screen(GotoScreen(date.today()), jump)

    def action_search(self) -> None:
        """Search the cached sync window; picking a result opens its day selected."""
        today, window = date.today(), self.config.sync
        occs = self.occurrences(
            add_months(today, -window.past_months), add_months(today, window.future_months)
        )
        screen = SearchScreen(occs, datetime.now().astimezone(), self.calendar_color)
        self.push_screen(screen, self.show_occurrence)

    def show_occurrence(self, occ: Occurrence | None) -> None:
        """Switch to the day view on ``occ``'s day with ``occ`` selected."""
        if occ is None:
            return
        self.set_view(ViewMode.DAY)
        self.select_date(occ.start.date())
        view = self.query_one(DayView)
        view.focus()
        view.select(occ)

    def action_sync(self) -> None:
        if self._sync is None:
            self.notify("Syncing is off (no account)")
        self.request_sync()

    def action_help(self) -> None:
        self.push_screen(HelpScreen(self.config.keys))

    def on_event_selected(self, message: EventSelected) -> None:
        self.push_screen(EventDetail(message.occurrence))

    def on_new_event_requested(self, message: NewEventRequested) -> None:
        self.new_event(message.start)


def instance_of(occ: Occurrence) -> Event:
    """The event to edit for just ``occ``: its override, or a new one for the
    master's instance (RECURRENCE-ID = the instance's start, no RRULE/EXDATEs)."""
    event = occ.event
    if event.recurrence_id is not None:
        return event
    zone = event.start.tzinfo
    start, end = occ.start.astimezone(zone), occ.end.astimezone(zone)
    return replace(event, start=start, end=end, recurrence_id=start, rrule=None, exdates=())
