"""Event editing flows behind TcalApp's keys: the event form (new, quick add,
edit "this/all events"), the yank/paste/duplicate clipboard (one event, or the
tab-marked ones as a batch) and moving events.

``Editor(app)`` only opens screens and calls the app's data seam
(``save_event`` / ``source``), so undo and syncing work as for any other edit.
"""

from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

from textual.keys import format_key

from tcal.model import Calendar, Event, Occurrence
from tcal.quickadd import QuickAdd
from tcal.tz import local_midnight
from tcal.ui.clipboard import copy_at, instance_of, shifted
from tcal.ui.screens.event_detail import EditScope, MoveScope, Scope, is_recurring, short_when
from tcal.ui.screens.event_form import EventForm
from tcal.ui.screens.quick_add import Mode, QuickAddScreen
from tcal.ui.widgets.timegrid import TimeGrid

if TYPE_CHECKING:
    from tcal.ui.app import TcalApp


class Editor:
    def __init__(self, app: "TcalApp") -> None:
        self.app = app
        self.yanked: list[Occurrence] = []  # the yank key's copy, by start

    # ----- event form -----------------------------------------------------

    def new_event(self, start: date | datetime) -> None:
        """Open the form for a new event at a time slot (1 h) or on a day (all-day)."""
        if isinstance(start, datetime):
            begin, end, all_day = start, start + timedelta(hours=1), False
        else:
            begin, end, all_day = local_midnight(start), local_midnight(start + timedelta(1)), True
        if not (writable := self._writable()):
            return
        draft = Event(f"{uuid4()}@tcal", self._default(writable).id, "", begin, end, all_day)
        self.app.push_screen(EventForm(draft, writable, new=True), self.form_done)

    def quick_add(self) -> None:
        """One-line quick add: enter saves the parsed event, tab opens it in the form."""
        if not (writable := self._writable()):
            return
        default = self._default(writable)

        def done(result: tuple[Mode, QuickAdd] | None) -> None:
            if result is None:
                return
            mode, q = result
            calendar = next((c for c in writable if c.name == q.calendar), default)
            event = Event(
                f"{uuid4()}@tcal",
                calendar.id,
                q.summary,
                q.start,
                q.end,
                q.all_day,
                q.location,
                rrule=q.rrule,
            )
            if mode == "save":
                self.form_done(event, "Added")
            else:
                form = EventForm(event, writable, new=True, edited=True)
                self.app.push_screen(form, self.form_done)

        readonly = [c.name for c in self.app.calendars() if c.readonly]
        names = [c.name for c in writable]
        self.app.push_screen(QuickAddScreen(date.today(), names, default.name, readonly), done)

    def edit_event(self, event: Event) -> None:
        """Open the form for an existing event (a master edits the whole series)."""
        if self.app.check_writable(event.calendar_id):
            form = EventForm(event, self._writable(warn=False), new=False)
            self.app.push_screen(form, self.form_done)

    def edit_occurrence(self, occurrence: Occurrence) -> None:
        """Edit ``occurrence``; for a series ask "this event" (an override with a
        RECURRENCE-ID) or "all events" (the master)."""
        if not self.app.check_writable(occurrence.calendar_id):
            return
        if not is_recurring(occurrence):
            self.edit_event(occurrence.event)
            return

        def done(scope: Scope | None) -> None:
            if scope == "occurrence":
                self.edit_event(instance_of(occurrence))
            elif scope == "series":
                self.edit_event(self._series(occurrence))

        self.app.push_screen(EditScope(occurrence), done)

    def form_done(self, event: Event | None, verb: str = "Saved") -> None:
        """Save a new/edited event and toast "<verb> “X” · u undo"; a hidden calendar
        it lands in is shown again. The event is selected (unless all events of a
        series were edited)."""
        if event is None:
            return
        if event.calendar_id in self.app.state.hidden_calendars:
            self.app.toggle_calendar(event.calendar_id)
        series_edit = bool(event.rrule and self.app.source.rows(event.uid))
        saved = self.app.save_event(event)
        if not series_edit:  # (that would jump to the series' first event)
            self.select_event(saved.uid, saved.start)
        self.app.notify(f"{verb} “{event.summary}” · {self.app.undo_hint}")

    # ----- clipboard & moving ---------------------------------------------

    def yank(self, occ: Occurrence) -> None:
        self.yanked = [occ]
        self.app.notify(f"Copied “{occ.summary}” · {self._paste_hint}")

    def yank_all(self, occs: list[Occurrence]) -> None:
        """Copy several events (the marked ones, by start) for a batch paste."""
        if len(occs) == 1:
            self.yank(occs[0])
        elif occs:
            self.yanked = occs
            self.app.notify(f"Copied {len(occs)} events · {self._paste_hint}")

    @property
    def _paste_hint(self) -> str:
        return f"{format_key(self.app.config.keys['paste'][0])} paste"

    def paste(self) -> None:
        """A copy of the yanked event at the time grid's cursor slot, else on the selected
        day; several: ``paste_all`` on the selected day."""
        if not self.yanked:
            self.app.notify("Nothing copied")
        elif len(self.yanked) > 1:
            self.paste_all(self.app.state.day)
        else:
            focused = self.app.focused
            at = focused.cursor_time if isinstance(focused, TimeGrid) else self.app.state.day
            self.save_copy(self.yanked[0], at, "Pasted")

    def paste_all(self, day: date) -> None:
        """Copies of all yanked events, as Apple Calendar does: the earliest lands on
        ``day``, the others keep their day offsets from it, times and durations. One
        undo step; the first copy is selected."""
        app = self.app
        offset = day - self.yanked[0].start.date()
        copies = []
        for occ in self.yanked:
            if not (calendar := self._copy_calendar(occ)):
                return
            copies.append(copy_at(occ, occ.start.date() + offset, calendar.id))
        n = len(copies)
        saved = app.save_events(copies, f"Removed {n} pasted events")
        self.select_event(saved[0].uid, saved[0].start)
        app.notify(f"Pasted {n} events to {day:%a} {day.day} · {app.undo_hint}")

    def duplicate(self, occ: Occurrence) -> None:
        """A copy of ``occ`` on the next day."""
        self.save_copy(occ, occ.start + timedelta(days=1), "Duplicated")

    def save_copy(self, occ: Occurrence, at: date | datetime, verb: str) -> None:
        """Save a copy of ``occ`` at ``at`` (its own calendar, or the first writable),
        select it and toast "<verb> “X” to Sun 22" (+ " · Work" if the calendar differs)."""
        app = self.app
        if not (target := self._copy_calendar(occ)):
            return
        copy = app.save_event(copy_at(occ, at, target.id))
        self.select_event(copy.uid, copy.start)
        day = copy.start.date()
        where = "" if target.id == occ.calendar_id else f" · {target.name}"
        app.notify(f"{verb} “{copy.summary}” to {day:%a} {day.day}{where} · {app.undo_hint}")

    def move(self, occ: Occurrence, delta: timedelta) -> None:
        """Shift ``occ`` by ``delta``. For a series ask "this event" / "all events", as
        for editing; the answer holds while the same occurrence is moved on (no other
        change in between). An override just moves."""
        if not self.app.check_writable(occ.calendar_id):
            return
        history = self.app.history

        def done(scope: Scope | None) -> None:
            if scope is None:
                return
            if scope == "series":
                event = self._series(occ)
            else:
                event = instance_of(occ) if is_recurring(occ) else occ.event
            if (moved := shifted(event, delta)) is None:
                self.app.notify("Change the days of this series in the form", severity="warning")
                return
            what = f"all “{occ.summary}” events" if scope == "series" else f"“{occ.summary}”"
            back = short_when(occ.start, occ.all_day)
            self.app.save_event(moved, f"Undid move of {what} (back to {back})", occ.start)
            self.select_event(occ.event.uid, occ.start + delta)
            history.move_run = ((occ.event.uid, occ.start + delta), scope)

        if not is_recurring(occ) or occ.event.recurrence_id is not None:
            done("occurrence")
        elif history.move_run is not None and history.move_run[0] == occ.key:
            done(history.move_run[1])
        else:
            self.app.push_screen(MoveScope(occ), done)

    # ----- helpers --------------------------------------------------------

    def _writable(self, warn: bool = True) -> list[Calendar]:
        """The writable calendars; none: warn "No writable calendar" (or
        ``app.unsynced_hint()`` while nothing has been synced)."""
        app = self.app
        writable = [c for c in app.calendars() if not c.readonly]
        if not writable and warn:
            if hint := app.unsynced_hint():
                app.notify(hint, severity="warning")
            else:
                app.notify("No writable calendar", severity="warning")
        return writable

    def _copy_calendar(self, occ: Occurrence) -> Calendar | None:
        """Where a copy of ``occ`` goes: its calendar, or if that is read-only the first
        writable one (None: there is none, warned)."""
        calendar = self.app.calendar(occ.calendar_id)
        if calendar and not calendar.readonly:
            return calendar
        writable = self._writable()
        return writable[0] if writable else None

    def _default(self, writable: list[Calendar]) -> Calendar:
        """For new events: the first shown calendar of ``writable`` (else the first)."""
        hidden = self.app.state.hidden_calendars
        return next((c for c in writable if c.id not in hidden), writable[0])

    def _series(self, occ: Occurrence) -> Event:
        """The master of ``occ``'s series."""
        return self.app.source.get_event(occ.event.uid) or occ.event

    def select_event(self, uid: str, start: datetime) -> None:
        """Go to the day of event ``uid``'s occurrence at ``start`` and select it in the view."""
        day = start.date()
        self.app.select_date(day)
        occs = self.app.occurrences(day, day + timedelta(1))
        occ = next((o for o in occs if o.event.uid == uid and o.start == start), None)
        if occ is not None:
            self.app.select_in_view(occ)
