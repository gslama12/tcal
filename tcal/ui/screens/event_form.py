"""EventForm: modal to create or edit an event.

``EventForm(draft, calendars)`` shows ``draft`` (a new event or an existing one)
and dismisses with the edited ``Event`` (ctrl+s) or ``None`` (esc). It does not
save: the caller passes the result to ``app.save_event``. ``calendars`` are the
writable calendars to choose from.

Fields left as shown keep the event's own values (time zone, a custom RRULE).
Changing the start shifts the end so the duration stays the same. An event with
``recurrence_id`` is one instance of a series: repeat and calendar are fixed.
An error shown on save is cleared as soon as a field changes.
"""

import re
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Checkbox, Input, Label, Select, Static, TextArea

from tcal.model import Calendar, Event
from tcal.tz import local_midnight, local_zone
from tcal.ui.keys import binding

REPEATS = ("none", "daily", "weekly", "monthly", "yearly")
DEFAULT_START, DEFAULT_END = time(9), time(10)
CUSTOM = "custom"  # an RRULE the form can't express; kept unless changed


class FormError(ValueError):
    """Invalid form input; the message is shown in the form."""


@dataclass(frozen=True)
class FormValues:
    """The form's fields as text, as shown to the user (local time)."""

    title: str
    calendar_id: str
    start_date: str
    start_time: str
    end_date: str
    end_time: str
    all_day: bool
    location: str
    notes: str
    repeat: str


def values_of(event: Event) -> FormValues:
    start, end = event.start.astimezone(local_zone()), event.end.astimezone(local_zone())
    if event.all_day:  # end shown inclusive; times prefilled for unticking all-day
        end = datetime.combine(end.date() - timedelta(days=1), DEFAULT_END)
        start = datetime.combine(start.date(), DEFAULT_START)
    return FormValues(
        title=event.summary,
        calendar_id=event.calendar_id,
        start_date=start.date().isoformat(),
        start_time=f"{start:%H:%M}",
        end_date=end.date().isoformat(),
        end_time=f"{end:%H:%M}",
        all_day=event.all_day,
        location=event.location,
        notes=event.description,
        repeat=repeat_of(event.rrule),
    )


def repeat_of(rrule: str | None) -> str:
    if not rrule:
        return "none"
    match = re.fullmatch(r"FREQ=([A-Z]+)", rrule)
    freq = match[1].lower() if match else ""
    return freq if freq in REPEATS else CUSTOM


def parse_date(text: str) -> date:
    try:
        return date.fromisoformat(text.strip())
    except ValueError:
        raise FormError(f"Invalid date {text!r} (use YYYY-MM-DD)") from None


def parse_time(text: str) -> time:
    """'9', '930', '9:30', '09:30' -> time."""
    match = re.fullmatch(r"(\d{1,2}):?(\d{2})?", text.strip())
    try:
        if match is None:
            raise ValueError
        return time(int(match[1]), int(match[2] or 0))
    except ValueError:
        raise FormError(f"Invalid time {text!r} (use HH:MM)") from None


def build_event(event: Event, shown: FormValues, values: FormValues) -> Event:
    """``event`` with the form ``values`` applied (``shown`` = the values it was
    opened with); raises FormError on invalid input."""
    title = values.title.strip()
    if not title:
        raise FormError("Title is required")
    start_day, end_day = parse_date(values.start_date), parse_date(values.end_date)
    if values.all_day:
        start, end = local_midnight(start_day), local_midnight(end_day + timedelta(days=1))
    else:
        zone = local_zone()
        start = datetime.combine(start_day, parse_time(values.start_time), zone)
        end = datetime.combine(end_day, parse_time(values.end_time), zone)
    if end <= start:
        raise FormError("End must be after start")
    if values.all_day == shown.all_day:  # unchanged times keep their own zone
        if _start_fields(values) == _start_fields(shown):
            start = event.start
        if _end_fields(values) == _end_fields(shown):
            end = event.end
    rrule = event.rrule
    if values.repeat != shown.repeat:
        rrule = None if values.repeat == "none" else f"FREQ={values.repeat.upper()}"
    return replace(
        event,
        summary=title,
        calendar_id=values.calendar_id,
        start=start,
        end=end,
        all_day=values.all_day,
        location=values.location.strip(),
        description=values.notes.strip(),
        rrule=rrule,
    )


def _start_fields(v: FormValues) -> tuple[str, str]:
    return v.start_date.strip(), v.start_time.strip()


def _end_fields(v: FormValues) -> tuple[str, str]:
    return v.end_date.strip(), v.end_time.strip()


class EventForm(ModalScreen[Event | None]):
    BINDINGS = [binding("save", "Save", priority=True), binding("cancel", "Cancel")]

    def __init__(self, event: Event, calendars: list[Calendar], new: bool) -> None:
        super().__init__()
        self.event = event
        self.calendars = calendars
        self.new = new
        self.shown = values_of(event)
        if all(c.id != event.calendar_id for c in calendars):
            self.shown = replace(self.shown, calendar_id=calendars[0].id)
        self._start: datetime | None = datetime.combine(
            parse_date(self.shown.start_date), parse_time(self.shown.start_time)
        )  # last valid start shown, to shift the end with

    def compose(self) -> ComposeResult:
        v = self.shown
        repeats = REPEATS + (CUSTOM,) if v.repeat == CUSTOM else REPEATS
        instance = self.event.recurrence_id is not None  # one instance of a series
        with Vertical(id="form") as form:
            form.border_title = (
                "New event" if self.new else "Edit this event" if instance else "Edit event"
            )
            yield Input(v.title, placeholder="Title", id="title")
            yield Select(
                [(c.name, c.id) for c in self.calendars],
                value=v.calendar_id,
                allow_blank=False,
                disabled=instance,
                id="calendar",
            )
            with Horizontal(classes="row"):
                yield Label("From", classes="label")
                yield Input(v.start_date, placeholder="YYYY-MM-DD", id="start_date")
                yield Input(v.start_time, placeholder="HH:MM", id="start_time", classes="time")
            with Horizontal(classes="row"):
                yield Label("To", classes="label")
                yield Input(v.end_date, placeholder="YYYY-MM-DD", id="end_date")
                yield Input(v.end_time, placeholder="HH:MM", id="end_time", classes="time")
            yield Checkbox("All day", v.all_day, id="all_day")
            yield Select(
                [(f"Repeat: {r}", r) for r in repeats],
                value=v.repeat,
                allow_blank=False,
                disabled=instance,
                id="repeat",
            )
            yield Input(v.location, placeholder="Location", id="location")
            yield TextArea(v.notes, id="notes")
            yield Static(id="error")
            yield Static("ctrl+s save · esc cancel · tab next field", id="hint")

    def on_mount(self) -> None:
        self._show_times(self.shown.all_day)
        self.query_one("#title").focus()

    def values(self) -> FormValues:
        def text(id: str) -> str:
            return self.query_one(f"#{id}", Input).value

        return FormValues(
            title=text("title"),
            calendar_id=str(self.query_one("#calendar", Select).value),
            start_date=text("start_date"),
            start_time=text("start_time"),
            end_date=text("end_date"),
            end_time=text("end_time"),
            all_day=self.query_one("#all_day", Checkbox).value,
            location=text("location"),
            notes=self.query_one("#notes", TextArea).text,
            repeat=str(self.query_one("#repeat", Select).value),
        )

    def action_save(self) -> None:
        try:
            event = build_event(self.event, self.shown, self.values())
        except FormError as error:
            self.query_one("#error", Static).update(str(error))
            return
        self.dismiss(event)

    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(Input.Changed)
    @on(TextArea.Changed)
    @on(Select.Changed)
    @on(Checkbox.Changed)
    def _clear_error(self) -> None:
        self.query_one("#error", Static).update("")

    @on(Checkbox.Changed, "#all_day")
    def _all_day_changed(self, message: Checkbox.Changed) -> None:
        self._show_times(message.value)

    @on(Input.Changed, "#start_date, #start_time")
    def _start_changed(self) -> None:
        """Move the end along with the start (keeping the duration)."""
        new = self._parsed_start()
        if new is None or self._start is None:
            self._start = new or self._start
            return
        try:
            end = datetime.combine(
                parse_date(self.query_one("#end_date", Input).value),
                parse_time(self.query_one("#end_time", Input).value),
            )
        except FormError:
            return
        end += new - self._start
        self._start = new
        self.query_one("#end_date", Input).value = end.date().isoformat()
        self.query_one("#end_time", Input).value = f"{end:%H:%M}"

    def _parsed_start(self) -> datetime | None:
        try:
            return datetime.combine(
                parse_date(self.query_one("#start_date", Input).value),
                parse_time(self.query_one("#start_time", Input).value),
            )
        except FormError:
            return None

    def _show_times(self, all_day: bool) -> None:
        for widget in self.query(".time"):
            widget.display = not all_day
