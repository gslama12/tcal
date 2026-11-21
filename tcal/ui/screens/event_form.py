"""EventForm: modal to create or edit an event.

``EventForm(draft, calendars)`` shows ``draft`` (a new event or an existing one)
and dismisses with the edited ``Event`` (ctrl+s) or ``None`` (esc; asks
"Discard changes?" when a field was changed). It does not
save: the caller passes the result to ``app.save_event``. ``calendars`` are the
writable calendars to choose from.

Fields left as shown keep the event's own values (time zone, a custom RRULE).
Changing the start shifts the end so the duration stays the same. An event with
``recurrence_id`` is one instance of a series: repeat and calendar are fixed;
a master with an RRULE edits all events (the dates shown are the first one's).
A series can end on a date (UNTIL) or after a number of times (COUNT).
Dates accept goto's forms (``fri``, ``tomorrow``, ``24.12.``, ISO). An error on
save is shown below its field, which is marked; it clears when a field changes.
If a sync changed or deleted the event while the form was open, saving asks
``ServerChanged`` first (overwrite / discard / back to the form).

"""

import re
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING, cast

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Button, Checkbox, Input, Label, Select, Static, TextArea

from tcal import dates
from tcal.model import Calendar, Event
from tcal.tz import local_midnight, local_zone
from tcal.ui.keys import binding
from tcal.ui.screens.event_detail import describe_rrule, until_date

if TYPE_CHECKING:
    from tcal.ui.app import TcalApp

REPEATS: dict[str, str | None] = {  # choice -> RRULE
    "none": None,
    "daily": "FREQ=DAILY",
    "weekdays": "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR",
    "weekly": "FREQ=WEEKLY",
    "monthly": "FREQ=MONTHLY",
    "yearly": "FREQ=YEARLY",
}
REPEAT_LABELS = {
    "none": "Does not repeat",
    "daily": "Every day",
    "weekdays": "Every weekday",
    "weekly": "Every week",
    "monthly": "Every month",
    "yearly": "Every year",
}
ENDS = {"never": "Never", "on": "On date", "after": "After"}  # a series' end: none/UNTIL/COUNT
DEFAULT_START, DEFAULT_END = time(9), time(10)
CUSTOM = "custom"  # an RRULE the form can't express; kept unless changed


class FormError(ValueError):
    """Invalid form input; the message is shown below the widget ``field`` (an id)."""

    def __init__(self, message: str, field: str) -> None:
        super().__init__(message)
        self.field = field


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
    ends: str  # a key of ENDS
    ends_value: str  # "on": a date, "after": a number of times


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
        ends=split_end(event.rrule)[1],
        ends_value=split_end(event.rrule)[2],
    )


def repeat_of(rrule: str | None) -> str:
    """The REPEATS choice of ``rrule`` (its end aside), CUSTOM if none matches."""
    if not rrule:
        return "none"
    rule = split_end(rrule)[0].upper()
    return next((r for r, known in REPEATS.items() if known == rule), CUSTOM)


def split_end(rrule: str | None) -> tuple[str, str, str]:
    """``rrule`` without COUNT/UNTIL, the ENDS choice and its value as shown."""
    parts = [p for p in (rrule or "").split(";") if p]
    rest = ";".join(p for p in parts if p.split("=")[0].upper() not in ("COUNT", "UNTIL"))
    for part in parts:
        key, _, value = part.partition("=")
        if key.upper() == "COUNT":
            return rest, "after", value
        if key.upper() == "UNTIL":
            return rest, "on", until_date(value).isoformat()
    return rest, "never", ""


def end_rule(values: FormValues, start: datetime, all_day: bool, today: date | None) -> str:
    """The RRULE suffix for the form's "Ends" fields ('' = never)."""
    text = values.ends_value.strip()
    if values.ends == "after":
        if not text.isdigit() or int(text) < 1:
            raise FormError(f"Not a number of times: {text!r}", "ends_value")
        return f";COUNT={int(text)}"
    if values.ends == "on":
        day = parse_date(text, "ends_value", today)
        if day < start.astimezone(local_zone()).date():
            raise FormError("The series can't end before it starts", "ends_value")
        if all_day:
            return f";UNTIL={day:%Y%m%d}"
        last = local_midnight(day + timedelta(days=1)) - timedelta(seconds=1)
        return f";UNTIL={last.astimezone(UTC):%Y%m%dT%H%M%SZ}"
    return ""


def parse_date(text: str, field: str = "start_date", today: date | None = None) -> date:
    """A date in any form goto understands (relative to ``today``)."""
    day = dates.parse_date(text, today or date.today())
    if day is None:
        raise FormError(f"Not a date: {text!r} (e.g. 2026-12-24, fri, 24.12.)", field)
    return day


def parse_time(text: str, field: str = "start_time") -> time:
    """'9', '930', '9:30', '09:30' -> time."""
    match = re.fullmatch(r"(\d{1,2}):?(\d{2})?", text.strip())
    try:
        if match is None:
            raise ValueError
        return time(int(match[1]), int(match[2] or 0))
    except ValueError:
        raise FormError(f"Not a time: {text!r} (use HH:MM)", field) from None


def build_event(
    event: Event, shown: FormValues, values: FormValues, today: date | None = None
) -> Event:
    """``event`` with the form ``values`` applied (``shown`` = the values it was
    opened with); raises FormError on invalid input."""
    title = values.title.strip()
    if not title:
        raise FormError("Title is required", "title")
    start_day = parse_date(values.start_date, "start_date", today)
    end_day = parse_date(values.end_date, "end_date", today)
    if values.all_day:
        start, end = local_midnight(start_day), local_midnight(end_day + timedelta(days=1))
    else:
        zone = local_zone()
        start = datetime.combine(start_day, parse_time(values.start_time, "start_time"), zone)
        end = datetime.combine(end_day, parse_time(values.end_time, "end_time"), zone)
    if end <= start:
        raise FormError("End must be after start", "end_date" if values.all_day else "end_time")
    if values.all_day == shown.all_day:  # unchanged times keep their own zone
        if _start_fields(values) == _start_fields(shown):
            start = event.start
        if _end_fields(values) == _end_fields(shown):
            end = event.end
    rrule = event.rrule
    if _repeat_fields(values) != _repeat_fields(shown):
        base = split_end(rrule)[0] if values.repeat == CUSTOM else REPEATS[values.repeat]
        rrule = base and base + end_rule(values, start, values.all_day, today)
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


def _repeat_fields(v: FormValues) -> tuple[str, str, str]:
    return v.repeat, v.ends, v.ends_value.strip()


def _content(rows: list[Event]) -> list[Event]:
    """``rows`` without what our own push changes (etag, href; ``raw`` isn't compared)."""
    return [replace(r, etag=None, href=None) for r in rows]


class AllDay(Checkbox):
    """A checkbox whose box is empty when off (styled in styles.tcss) and ✓ when on."""

    BUTTON_INNER = "✓"


class ConfirmDiscard(ModalScreen[bool]):
    """Asks "Discard changes?": y = True, n/esc = False."""

    BINDINGS = [
        Binding("y", "dismiss(True)", show=False),
        Binding("n,escape", "dismiss(False)", show=False),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static("Discard changes?", classes="question")
            with Horizontal(id="buttons"):
                yield Button("Discard (y)", id="y", variant="error")
                yield Button("Keep editing (n)", id="n")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "y")


class ServerChanged(ModalScreen[bool | None]):
    """At save, the event changed (or was deleted) on the server since the form opened:
    o = overwrite with the form's version (True), d = discard it (False), esc = back."""

    BINDINGS = [
        Binding("o", "dismiss(True)", show=False),
        Binding("d", "dismiss(False)", show=False),
        Binding("escape", "dismiss(None)", show=False),
    ]

    def __init__(self, summary: str, deleted: bool) -> None:
        super().__init__()
        self.summary = summary
        self.deleted = deleted

    def compose(self) -> ComposeResult:
        what = "was deleted" if self.deleted else "changed"
        with Vertical(id="dialog"):
            yield Static(f"“{self.summary}” {what} on the server.", classes="question")
            with Horizontal(id="buttons"):
                yield Button("Save again (o)" if self.deleted else "Overwrite (o)", id="o")
                yield Button("Discard mine (d)", id="d", variant="error")
                yield Button("Back (esc)", id="back")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss({"o": True, "d": False}.get(event.button.id or ""))


class EventForm(ModalScreen[Event | None]):
    BINDINGS = [binding("save", "Save", priority=True), binding("cancel", "Cancel")]

    def __init__(
        self, event: Event, calendars: list[Calendar], new: bool, edited: bool = False
    ) -> None:
        """``edited``: the prefilled values are already the user's input (quick add), so
        cancel asks "Discard changes?" even when no field was changed."""
        super().__init__()
        self.event = event
        self.calendars = calendars
        self.new = new
        self.edited = edited
        self.shown = values_of(event)
        if all(c.id != event.calendar_id for c in calendars):
            self.shown = replace(self.shown, calendar_id=calendars[0].id)
        self._start: datetime | None = datetime.combine(
            parse_date(self.shown.start_date), parse_time(self.shown.start_time)
        )  # last valid start shown, to shift the end with

    def compose(self) -> ComposeResult:
        v = self.shown
        repeats = list(REPEAT_LABELS.items())
        if v.repeat == CUSTOM:
            repeats.append((CUSTOM, describe_rrule(split_end(self.event.rrule)[0])))
        instance = self.event.recurrence_id is not None  # one instance of a series
        series = not self.new and bool(self.event.rrule)
        # The fields scroll on short terminals; the title (border) and the hint stay put.
        with VerticalScroll(id="form", can_focus=False) as form:
            form.border_title = "New event" if self.new else "Edit event"
            if instance or series:
                form.border_title = "Edit this event" if instance else "Edit all events"
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
                yield Input(v.start_date, placeholder="date", id="start_date")
                yield Input(v.start_time, placeholder="HH:MM", id="start_time", classes="time")
            with Horizontal(classes="row"):
                yield Label("To", classes="label")
                yield Input(v.end_date, placeholder="date", id="end_date")
                yield Input(v.end_time, placeholder="HH:MM", id="end_time", classes="time")
            if series:
                yield Static("Dates are the first event's; changes apply to all events.", id="note")
            yield AllDay("All day", v.all_day, id="all_day")
            yield Select(
                [(label, r) for r, label in repeats],
                value=v.repeat,
                allow_blank=False,
                disabled=instance,
                id="repeat",
            )
            with Horizontal(classes="row", id="ends_row"):
                yield Label("Ends", classes="label")
                yield Select(
                    [(label, e) for e, label in ENDS.items()],
                    value=v.ends,
                    allow_blank=False,
                    id="ends",
                )
                yield Input(v.ends_value, id="ends_value")
            yield Input(v.location, placeholder="Location", id="location")
            yield TextArea(v.notes, placeholder="Notes", id="notes")
            yield Static(id="error")
            yield Static("ctrl+s save · esc cancel · tab next field", id="hint")

    @property
    def _rows(self) -> list[Event]:
        """The cache's rows of the event now (``TcalApp.source``)."""
        return cast("TcalApp", self.app).source.rows(self.event.uid)

    def on_mount(self) -> None:
        self._opened = _content(self._rows)  # to notice a sync's changes at save time
        self._show_times(self.shown.all_day)
        self._show_ends()
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
            ends=str(self.query_one("#ends", Select).value),
            ends_value=text("ends_value"),
        )

    def action_save(self) -> None:
        try:
            event = build_event(self.event, self.shown, self.values())
        except FormError as error:
            self._show_error(error)
            return
        now = self._rows
        if self.new or _content(now) == self._opened:
            self.dismiss(event)
            return

        def done(overwrite: bool | None) -> None:
            if overwrite:  # on top of the server's version (or created again)
                href, etag = (now[0].href, now[0].etag) if now else (None, None)
                self.dismiss(replace(event, href=href, etag=etag))
            elif overwrite is False:
                self.dismiss(None)

        self.app.push_screen(ServerChanged(event.summary, deleted=not now), done)

    def action_cancel(self) -> None:
        if not self.edited and self.values() == self.shown:
            self.dismiss(None)
            return

        def done(discard: bool | None) -> None:
            if discard:
                self.dismiss(None)

        self.app.push_screen(ConfirmDiscard(), done)

    def _show_error(self, error: FormError) -> None:
        """Show ``error`` below its field's row and mark and focus the field."""
        form, field = self.query_one("#form"), self.query_one(f"#{error.field}")
        row = next(w for w in [field, *field.ancestors] if w.parent is form)
        message = self.query_one("#error", Static)
        message.update(str(error))
        form.move_child(message, after=cast(Widget, row))
        field.add_class("-invalid")
        field.focus()

    @on(Input.Changed)
    @on(TextArea.Changed)
    @on(Select.Changed)
    @on(Checkbox.Changed)
    def _clear_error(self) -> None:
        self.query_one("#error", Static).update("")
        self.query(".-invalid").remove_class("-invalid")

    @on(Checkbox.Changed, "#all_day")
    def _all_day_changed(self, message: Checkbox.Changed) -> None:
        self._show_times(message.value)

    @on(Select.Changed, "#repeat, #ends")
    def _show_ends(self) -> None:
        """The "Ends" row only for a series; its value field only for a date or count."""
        repeat, ends = self.query_one("#repeat", Select), self.query_one("#ends", Select)
        self.query_one("#ends_row").display = repeat.value != "none"
        value = self.query_one("#ends_value", Input)
        value.display = ends.value != "never"
        value.placeholder = "date" if ends.value == "on" else "times"

    @on(Input.Changed, "#start_date, #start_time")
    def _start_changed(self) -> None:
        """Move the end along with the start (keeping the duration)."""
        new = self._shown_time("start")
        if new is None or self._start is None:
            self._start = new or self._start
            return
        end = self._shown_time("end")
        if end is None:
            return
        end += new - self._start
        self._start = new
        self.query_one("#end_date", Input).value = end.date().isoformat()
        self.query_one("#end_time", Input).value = f"{end:%H:%M}"

    def _shown_time(self, side: str) -> datetime | None:
        """The ``start``/``end`` date and time fields as a naive datetime, None if invalid."""
        try:
            return datetime.combine(
                parse_date(self.query_one(f"#{side}_date", Input).value),
                parse_time(self.query_one(f"#{side}_time", Input).value),
            )
        except FormError:
            return None

    def _show_times(self, all_day: bool) -> None:
        for widget in self.query(".time"):
            widget.display = not all_day
