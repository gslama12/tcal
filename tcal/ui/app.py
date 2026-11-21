"""TcalApp: the Google-Calendar-like shell, the app state and the data seam.

Layout::

    ┌ sidebar ─┐┌ main ───────────────────────────┐
    │ MiniCal  ││ ViewSwitcher (tabs + title)     │
    │          ││ ContentSwitcher: Day/Week/      │
    │ Calendar ││   Month/Year/ScheduleView       │
    │ List     ││   (id = mode)                   │
    └──────────┘└─────────────────────────────────┘
     StatusBar

Public API for widgets/screens: ``state``, ``config``, ``palette``,
``calendars()``, ``calendar()``, ``calendar_color()``, ``occurrences()``, ``select_date()``,
``set_view()``, ``toggle_calendar()``, ``refresh_data()``, ``save_event()``,
``delete_event()``, ``undo()``, ``request_sync()``, ``show_occurrence()``, ``sync_status``,
``new_event()``, ``edit_event()``, ``edit_occurrence()`` (open the event form),
``check_writable()``, ``focus_view()``, ``selected_occurrence()``, ``select_in_view()``.

Editing flows (form, quick add, clipboard, moving) live in ``tcal.ui.editing.Editor``
(``app.editor``), the undo stack in ``tcal.ui.undo`` (``app.history``).

The sidebar hides itself below ``SIDEBAR_MIN_WIDTH`` columns (and again when focus
leaves it there); once the user toggles it, that choice wins over resizes.
"""

from collections.abc import Callable
from dataclasses import replace
from datetime import date, datetime, time, timedelta

from textual import events
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.keys import format_key
from textual.reactive import reactive
from textual.widgets import ContentSwitcher
from textual.worker import Worker, WorkerState

from tcal.config import Config, default_data, describe_conflicts, key_conflicts, load_config
from tcal.model import Calendar, Event, Occurrence
from tcal.source import EventSource
from tcal.sync import SyncSummary
from tcal.tz import local_zone
from tcal.ui.editing import Editor
from tcal.ui.keys import binding, keymap
from tcal.ui.messages import EventSelected, NewEventRequested
from tcal.ui.screens.event_detail import EventDetail, confirm_delete, short_when
from tcal.ui.screens.goto import GotoScreen
from tcal.ui.screens.help import HelpScreen
from tcal.ui.screens.search import SearchScreen
from tcal.ui.state import AppState, ViewMode, add_months
from tcal.ui.sync_status import SyncState, SyncStatus
from tcal.ui.theme import PALETTES, make_theme
from tcal.ui.undo import UndoHistory, UndoStep
from tcal.ui.widgets.calendar_list import CalendarList
from tcal.ui.widgets.minical import MiniCal
from tcal.ui.widgets.month_view import MonthView
from tcal.ui.widgets.schedule_view import ScheduleView
from tcal.ui.widgets.statusbar import StatusBar
from tcal.ui.widgets.timegrid import DayView, TimeGrid, WeekView
from tcal.ui.widgets.view_switcher import ViewSwitcher
from tcal.ui.widgets.year_view import YearView

SIDEBAR_MIN_WIDTH = 120  # terminal columns below which the sidebar starts hidden
OCC_CACHE_SIZE = 32  # date ranges whose occurrences are kept until the next data refresh
SELECTING_VIEWS = TimeGrid | MonthView | ScheduleView  # views with a selected event


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
        binding("view_schedule", "Schedule", action="set_view('schedule')"),
        binding("new_event", "New event"),
        binding("quick_add", "Quick add"),
        binding("edit_event", "Edit event"),
        binding("delete_event", "Delete event"),
        binding("undo", "Undo"),
        binding("yank", "Yank"),
        binding("paste", "Paste"),
        binding("duplicate", "Duplicate"),
        binding("move_down", "Later", action="move(15, 0)"),
        binding("move_up", "Earlier", action="move(-15, 0)"),
        binding("move_left", "Day earlier", action="move(0, -1)"),
        binding("move_right", "Day later", action="move(0, 1)"),
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
        self._sync_by_key = False  # the running sync was asked for with the sync key
        self._error_shown = ""  # the sync error last toasted (not again until it changes)
        self._wide: bool | None = None  # terminal >= SIDEBAR_MIN_WIDTH, None before layout
        self._sidebar_pinned = False  # the user toggled the sidebar: resizes leave it alone
        self.history = UndoHistory()
        self.editor = Editor(self)
        self.config = config or load_config()
        name = self.config.theme.name
        self._theme_notice = ""
        if name not in PALETTES:
            fallback = default_data()["theme"]["name"]
            self._theme_notice = (
                f"Unknown theme {name!r}, using {fallback!r}; one of {', '.join(PALETTES)}"
            )
            name = fallback
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

    def calendar(self, calendar_id: str) -> Calendar | None:
        return next((c for c in self._calendars if c.id == calendar_id), None)

    def calendar_color(self, calendar_id: str) -> str:
        calendar = self.calendar(calendar_id)
        return calendar.color if calendar else self.palette.foreground1

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

    def save_event(self, event: Event, undo_message: str = "") -> Event:
        """Create/update an event in the cache, redraw, and push it in the background.
        The undo key takes it back (and toasts ``undo_message``, default: "Undid edit of
        “X”" / "Removed “X”")."""
        before = self.source.rows(event.uid)
        saved = self.source.save_event(event)
        if not undo_message:
            undo_message = (
                f"Undid edit of “{before[0].summary}”" if before else f"Removed “{event.summary}”"
            )
        self.history.push(UndoStep(event.uid, before, undo_message))
        self.refresh_data()
        self.request_sync()
        return saved

    def delete_event(self, uid: str, occurrence: datetime | None = None) -> None:
        """Delete an event, or one instance of a series: pass the instance's
        original start (``occ.event.recurrence_id or occ.start``). The undo key restores it."""
        rows = self.source.delete_event(uid, occurrence)
        self.refresh_data()
        self.request_sync()
        if rows:
            first = next((r for r in rows if r.recurrence_id is None), rows[0])
            if not first.rrule:
                what = f"“{first.summary}”"
            elif occurrence is not None:
                what = f"this “{first.summary}” ({short_when(occurrence, first.all_day)})"
            else:
                what = f"all “{first.summary}” events"
            self.history.push(UndoStep(uid, rows, f"Restored {what}"))
            self.notify(f"Deleted {what} · {self.undo_hint}")

    @property
    def undo_hint(self) -> str:
        return f"{format_key(self.config.keys['undo'][0])} undo"

    @property
    def sync_hint(self) -> str:
        """The sync key, e.g. "r"."""
        return format_key(self.config.keys["sync"][0])

    def undo(self) -> None:
        """Take back the last create, edit, move or delete (up to ``UNDO_DEPTH`` in turn)."""
        step = self.history.pop()
        if step is None:
            self.notify("Nothing to undo")
            return
        if step.rows:
            self.source.restore(step.rows)
        else:
            self.source.delete_event(step.uid)
        self.notify(step.message)
        self.refresh_data()
        self.request_sync()

    # ----- event form (``Editor``) ---------------------------------------

    def new_event(self, start: date | datetime) -> None:
        """Open the form for a new event at a time slot (1 h) or on a day (all-day)."""
        self.editor.new_event(start)

    def edit_event(self, event: Event) -> None:
        """Open the form for an existing event (a master edits the whole series)."""
        self.editor.edit_event(event)

    def edit_occurrence(self, occurrence: Occurrence) -> None:
        """Edit ``occurrence``; a series asks "this event" / "all events" first."""
        self.editor.edit_occurrence(occurrence)

    def check_writable(self, calendar_id: str) -> bool:
        """True if events in ``calendar_id`` can be edited; else show "<name> is read-only"."""
        calendar = self.calendar(calendar_id)
        if calendar is None or not calendar.readonly:
            return True
        self.notify(f"{calendar.name} is read-only", severity="warning")
        return False

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
            result = worker.result
            summary = result if isinstance(result, SyncSummary) else SyncSummary()
            self.sync_status = self.sync_status.succeeded(datetime.now(), tuple(summary.failed))
            if summary.conflicts:
                self.notify(
                    f"{summary.conflicts} local change(s) conflicted with the server"
                    " and were dropped (server version kept)",
                    title="Sync",
                    severity="warning",
                    timeout=10,
                )
            if self._sync_by_key:
                self.notify("Synced", title="Sync")
            self._error_shown = ""
        else:
            self.sync_status = self.sync_status.failed(worker.error)
            self.log.error(f"sync failed: {worker.error!r}")
            self._toast_sync_error()
        self._sync_by_key = False
        self.refresh_data()

    def _toast_sync_error(self) -> None:
        """Toast why the sync failed if the user asked for it, or nothing is cached yet
        (a first run offline); the same error only once in a row."""
        status = self.sync_status
        if not self._sync_by_key and (self._calendars or status.error == self._error_shown):
            return
        self._error_shown = status.error
        what = "Couldn't reach iCloud" if status.state is SyncState.OFFLINE else "Sync failed"
        self.notify(
            f"{what}: {status.error} · {self.sync_hint} retry · `tcal doctor` checks the setup",
            title="Sync",
            severity="warning" if status.state is SyncState.OFFLINE else "error",
            timeout=15,
        )

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
                    yield ScheduleView(id=ViewMode.SCHEDULE.value)
        yield StatusBar()

    def on_mount(self) -> None:
        self.set_keymap(keymap(self.config))
        if self._theme_notice:
            self.notify(self._theme_notice, title="Config", severity="warning", timeout=15)
        conflicts = describe_conflicts(key_conflicts(self.config))
        if conflicts:
            self.notify(
                "\n".join(conflicts) + "\n(see `tcal config check`)",
                title="Conflicting key bindings",
                severity="warning",
                timeout=15,
            )
        self.focus_view()
        if self._sync is not None:
            self.request_sync()
            self.set_interval(self.config.sync.interval, self.request_sync)

    def on_resize(self, event: events.Resize) -> None:
        wide = event.size.width >= SIDEBAR_MIN_WIDTH
        if wide != self._wide:
            self._wide = wide
            if not self._sidebar_pinned:
                self._show_sidebar(wide)

    def on_descendant_blur(self, event: events.DescendantBlur) -> None:
        """Narrow terminal: a sidebar shown just to reach it (``focus_calendars``)
        hides again once focus leaves it."""
        sidebar = self.query_one("#sidebar")
        if self._wide or self._sidebar_pinned or not sidebar.display:
            return
        self.call_after_refresh(self._hide_unfocused_sidebar)

    def _hide_unfocused_sidebar(self) -> None:
        sidebar = self.query_one("#sidebar")
        focused = self.focused
        if self._sidebar_pinned or focused is None or focused.screen is not sidebar.screen:
            return  # a modal on top keeps the sidebar for when it closes
        if sidebar not in focused.ancestors:
            sidebar.display = False

    def _show_sidebar(self, show: bool) -> None:
        sidebar = self.query_one("#sidebar")
        sidebar.display = show
        if not show and self.focused is not None and sidebar in self.focused.ancestors:
            self.focus_view()

    # ----- actions --------------------------------------------------------

    def action_toggle_sidebar(self) -> None:
        self._sidebar_pinned = True
        self._show_sidebar(not self.query_one("#sidebar").display)

    def action_prev_period(self) -> None:
        self.state = self.state.shifted(-1)

    def action_next_period(self) -> None:
        self.state = self.state.shifted(1)

    def action_today(self) -> None:
        self.select_date(date.today())

    def action_set_view(self, mode: str) -> None:
        self.set_view(mode)
        self.focus_view()

    def action_focus_calendars(self) -> None:
        self._show_sidebar(True)
        self.query_one(CalendarList).focus()

    def action_new_event(self) -> None:
        """A timed event at the next round hour on the selected day (day/week views
        post their own ``NewEventRequested`` for the selected slot)."""
        hour = min(datetime.now().hour + 1, 23)
        self.new_event(datetime.combine(self.state.day, time(hour), local_zone()))

    def selected_occurrence(self) -> Occurrence | None:
        """The event selected in the focused day/week/month/schedule view, if any."""
        focused = self.focused
        return focused.selected if isinstance(focused, SELECTING_VIEWS) else None

    def _selected(self) -> Occurrence | None:
        """``selected_occurrence()``; None also toasts "No event selected"."""
        occ = self.selected_occurrence()
        if occ is None:
            self.notify("No event selected")
        return occ

    def select_in_view(self, occ: Occurrence) -> None:
        """Select ``occ`` (on the selected day) in the current view."""
        view = self.query_one(f"#{self.state.view.value}")
        if isinstance(view, SELECTING_VIEWS):
            view.select(occ)

    def action_edit_event(self) -> None:
        """Edit the event selected in the focused day/week/month/schedule view."""
        if occ := self._selected():
            self.edit_occurrence(occ)

    def action_delete_event(self) -> None:
        if occ := self._selected():
            confirm_delete(self, occ)

    def action_undo(self) -> None:
        self.undo()

    def action_quick_add(self) -> None:
        self.editor.quick_add()

    def action_yank(self) -> None:
        if occ := self._selected():
            self.editor.yank(occ)

    def action_paste(self) -> None:
        self.editor.paste()

    def action_duplicate(self) -> None:
        if occ := self._selected():
            self.editor.save_copy(occ, occ.start + timedelta(days=1), "Duplicated")

    def action_move(self, minutes: int, days: int) -> None:
        """Shift the selected event by ``minutes`` (timed events in a time grid) or ``days``."""
        occ = self._selected()
        if occ is None:
            return
        if minutes and (occ.all_day or not isinstance(self.focused, TimeGrid)):
            self.notify("Moving by time works for timed events in the day/week view")
            return
        self.editor.move(occ, timedelta(days=days, minutes=minutes))

    def action_goto_date(self) -> None:
        def jump(day: date | None) -> None:
            if day is not None:
                self.select_date(day)

        self.push_screen(GotoScreen(date.today()), jump)

    def action_search(self) -> None:
        """Search the cached sync window; picking a result shows it (``show_occurrence``)."""
        today, window = date.today(), self.config.sync
        occs = self.occurrences(
            add_months(today, -window.past_months), add_months(today, window.future_months)
        )
        screen = SearchScreen(occs, datetime.now().astimezone(), self.calendar_color)
        self.push_screen(screen, self.show_occurrence)

    def show_occurrence(self, occ: Occurrence | None) -> None:
        """Go to ``occ``'s day in the current view, select it there and open its detail."""
        if occ is None:
            return
        self.select_date(occ.start.date())
        self.focus_view()
        self.select_in_view(occ)
        self.push_screen(EventDetail(occ))

    def action_sync(self) -> None:
        if self._sync is None:
            self.notify("Syncing is off (no account)")
            return
        self._sync_by_key = True
        if self.sync_status.state is SyncState.SYNCING:
            self.notify("Already syncing…", title="Sync")
        self.request_sync()

    def action_help(self) -> None:
        self.push_screen(HelpScreen(self.config.keys))

    def on_event_selected(self, message: EventSelected) -> None:
        self.push_screen(EventDetail(message.occurrence))

    def on_new_event_requested(self, message: NewEventRequested) -> None:
        self.new_event(message.start)
