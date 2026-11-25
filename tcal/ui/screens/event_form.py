"""EventForm: modal to edit an event (new ones are typed: ``event_prompt``).

``EventForm(event, calendars, today)`` dismisses with the edited ``Event`` (enter, in the
notes ``[keys] save``) or ``None`` (``[keys] cancel``, asking "Discard changes?" if a field
was changed; or saved unchanged). It does not save: the caller passes the result to
``app.save_event``. ``calendars`` are the writable calendars to choose from. The fields'
texts are read and written by ``tcal.ui.formvalues``.

Keys: tab / shift+tab and the cursor up/down keys go between the fields, cursor left/right
change a choice, space opens its list (which takes the cursor keys too) or ticks "All day".
Letters bound to the cursor are just typed in the text fields.

Changing the start shifts the end so the duration stays the same. An event with
``recurrence_id`` is one instance of a series: repeat and calendar are fixed;
a master with an RRULE edits all events (the dates shown are the first one's).
An error on save is shown below its field, which is marked; it clears when a field changes.
If a sync changed or deleted the event while the form was open, saving asks first
(overwrite / discard / back to the form).
"""

from dataclasses import replace
from datetime import date, datetime
from typing import TYPE_CHECKING, cast

from textual import events, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.keys import format_key
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Checkbox, Input, Label, OptionList, Select, Static, TextArea

from tcal.model import Calendar, Event
from tcal.repeat import describe_rrule, without_end
from tcal.ui.formvalues import (
    CUSTOM,
    FormError,
    FormValues,
    build_event,
    parse_date,
    parse_time,
    show_date,
    values_of,
)
from tcal.ui.keys import binding
from tcal.ui.screens.prompt import Prompt

if TYPE_CHECKING:
    from tcal.ui.app import TcalApp

REPEAT_LABELS = {
    "none": "Does not repeat",
    "daily": "Every day",
    "weekdays": "Every weekday",
    "weekly": "Every week",
    "monthly": "Every month",
    "yearly": "Every year",
}
ENDS_LABELS = {"never": "Never", "on": "On date", "after": "After"}


def _content(rows: list[Event]) -> list[Event]:
    """``rows`` without what our own push changes (etag, href; ``raw`` isn't compared)."""
    return [replace(r, etag=None, href=None) for r in rows]


def discard_prompt() -> Prompt[bool]:
    return Prompt[bool]("Discard changes?", {"y": ("discard", True)}, ("n", "keep editing"))


def server_changed_prompt(summary: str, now: str | None) -> Prompt[bool]:
    """At save, the event changed on the server since the form opened: overwrite it with
    the form's version (True), discard that (False) or go back. ``summary``: the event's
    title when the form opened; ``now``: its title on the server (None: deleted)."""
    if now is None:
        question = f"“{summary}” was deleted on the server."
    elif now != summary:
        question = f"“{summary}” was changed on the server (now “{now}”)."
    else:
        question = f"“{summary}” was changed on the server."
    overwrite = "save again" if now is None else "overwrite"
    return Prompt(question, {"o": (overwrite, True), "d": ("discard mine", False)}, ("esc", "back"))


class Fields(VerticalScroll, inherit_bindings=False):
    """The form's box: up/down go between the fields, which scroll on short terminals."""

    can_focus = False
    BINDINGS = [
        binding("cursor_down", action="app.focus_next"),
        binding("cursor_up", action="app.focus_previous"),
    ]


class AllDay(Checkbox, inherit_bindings=False):
    """A checkbox whose box is empty when off (styled in styles.tcss) and ✓ when on."""

    BUTTON_INNER = "✓"
    BINDINGS = [Binding("space", "toggle_button", show=False)]


class Choice(Select[str], inherit_bindings=False):
    """A Select for the cursor keys: left/right change it, up/down move in its open list."""

    BINDINGS = [
        Binding("space", "show_overlay", show=False),
        binding("cursor_left", action="change(-1)"),
        binding("cursor_right", action="change(1)"),
        binding("cursor_down", action="move(1)"),
        binding("cursor_up", action="move(-1)"),
    ]

    def __init__(self, labels: dict[str, str], value: str, id: str, disabled: bool = False) -> None:
        super().__init__(
            [(label, key) for key, label in labels.items()],
            value=value,
            allow_blank=False,
            type_to_search=False,
            id=id,
            disabled=disabled,
        )
        self.keys = list(labels)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool:
        """The list takes up/down only when open (else they go between the fields)."""
        return self.expanded if action == "move" else True

    def action_change(self, step: int) -> None:
        if not self.expanded:
            index = self.keys.index(str(self.value)) + step
            self.value = self.keys[index % len(self.keys)]

    def action_move(self, step: int) -> None:
        options = self.query_one(OptionList)
        if step > 0:
            options.action_cursor_down()
        else:
            options.action_cursor_up()


class EventForm(ModalScreen[Event | None]):
    BINDINGS = [
        binding("save", "Save", priority=True),
        binding("cancel", "Cancel"),
        Binding("enter", "save", show=False),
    ]

    def __init__(self, event: Event, calendars: list[Calendar], today: date) -> None:
        """``today``: what dates are relative to."""
        super().__init__()
        self.event = event
        self.calendars = calendars
        self.today = today
        self.shown = values_of(event)
        self._start: datetime | None = None  # last valid start shown, to shift the end with

    @property
    def tcal(self) -> "TcalApp":
        return cast("TcalApp", self.app)

    def compose(self) -> ComposeResult:
        v = self.shown
        repeats = dict(REPEAT_LABELS)
        if v.repeat == CUSTOM:
            repeats[CUSTOM] = describe_rrule(without_end(self.event.rrule or ""))
        instance = self.event.recurrence_id is not None  # one instance of a series
        series = bool(self.event.rrule)
        with Fields(id="form") as form:
            form.border_title = "Edit event"
            if instance or series:
                form.border_title = "Edit this event" if instance else "Edit all events"
            # (no select-all on focus: typing after `e` appends, as in vim's `A`)
            yield Input(v.title, placeholder="Title", id="title", select_on_focus=False)
            names = {c.id: c.name for c in self.calendars}
            yield Choice(names, v.calendar_id, "calendar", disabled=instance)
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
            yield Choice(repeats, v.repeat, "repeat", disabled=instance)
            with Horizontal(classes="row", id="ends_row"):
                yield Label("Ends", classes="label")
                yield Choice(ENDS_LABELS, v.ends, "ends")
                yield Input(v.ends_value, id="ends_value")
                yield Label("times", id="ends_unit")
            yield Input(v.location, placeholder="Location", id="location")
            yield TextArea(v.notes, placeholder="Notes", id="notes")
            yield Static(id="error", markup=False)

    @property
    def _event_rows(self) -> list[Event]:
        """The cache's rows of the event now."""
        return self.tcal.source.rows(self.event.uid)

    def on_mount(self) -> None:
        self._opened = _content(self._event_rows)  # to notice a sync's changes at save time
        self._start = self._shown_time("start")
        self._show_times(self.shown.all_day)
        self._show_ends()
        self.query_one("#title").focus()

    def values(self) -> FormValues:
        def text(id: str) -> str:
            return self.query_one(f"#{id}", Input).value

        def choice(id: str) -> str:
            return str(self.query_one(f"#{id}", Choice).value)

        return FormValues(
            title=text("title"),
            calendar_id=choice("calendar"),
            start_date=text("start_date"),
            start_time=text("start_time"),
            end_date=text("end_date"),
            end_time=text("end_time"),
            all_day=self.query_one(AllDay).value,
            location=text("location"),
            notes=self.query_one(TextArea).text,
            repeat=choice("repeat"),
            ends=choice("ends"),
            ends_value=text("ends_value"),
        )

    # ----- keys -----------------------------------------------------------

    def on_descendant_focus(self, focus: events.DescendantFocus) -> None:
        """Show the focused field's keys at the bottom."""

        def key(action: str) -> str:
            return format_key(self.tcal.config.keys[action][0])

        hints = ["enter save"]
        if isinstance(focus.widget, OptionList):  # an open list
            hints = [f"{key('cursor_down')}/{key('cursor_up')} move", "enter choose", "esc back"]
        else:
            if isinstance(focus.widget, Choice):
                change = f"{key('cursor_left')}/{key('cursor_right')} change"
                hints = [change, "space list", *hints]
            elif isinstance(focus.widget, AllDay):
                hints = ["space toggle", *hints]
            elif isinstance(focus.widget, TextArea):  # enter is a new line
                hints = [f"{key('save')} save"]
            hints += ["tab next", f"{key('cancel')} cancel"]
        self.query_one("#form").border_subtitle = " · ".join(hints)

    def on_input_submitted(self) -> None:
        self.action_save()

    def action_save(self) -> None:
        values = self.values()
        if values == self.shown:
            self.dismiss(None)
            return
        try:
            event = build_event(self.event, self.shown, values, self.today)
        except FormError as error:
            self._show_error(error)
            return
        now = self._event_rows
        if _content(now) == self._opened:
            self.dismiss(event)
            return

        def done(overwrite: bool | None) -> None:
            if overwrite:  # on top of the server's version (or created again)
                href, etag = (now[0].href, now[0].etag) if now else (None, None)
                self.dismiss(replace(event, href=href, etag=etag))
            elif overwrite is False:
                self.dismiss(None)

        title = next((r for r in now if r.recurrence_id is None), now[0]).summary if now else None
        self.app.push_screen(server_changed_prompt(self.event.summary, title), done)

    def action_cancel(self) -> None:
        if self.values() == self.shown:
            self.dismiss(None)
            return

        def done(discard: bool | None) -> None:
            if discard:
                self.dismiss(None)

        self.app.push_screen(discard_prompt(), done)

    # ----- errors ---------------------------------------------------------

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

    # ----- fields that depend on others -----------------------------------

    @on(Checkbox.Changed, "#all_day")
    def _all_day_changed(self, message: Checkbox.Changed) -> None:
        self._show_times(message.value)

    @on(Select.Changed, "#repeat, #ends")
    def _show_ends(self) -> None:
        """The "Ends" row only for a series; its value field only for a date or count."""
        repeat, ends = self.query_one("#repeat", Choice), self.query_one("#ends", Choice)
        self.query_one("#ends_row").display = repeat.value != "none"
        value = self.query_one("#ends_value", Input)
        value.display = ends.value != "never"
        value.placeholder = "date" if ends.value == "on" else "number"
        self.query_one("#ends_unit").display = ends.value == "after"

    @on(Input.Changed, "#start_date, #start_time")
    def _start_changed(self) -> None:
        """Move the end along with the start (keeping the duration)."""
        new, end = self._shown_time("start"), self._shown_time("end")
        if new is None or self._start is None or end is None:
            self._start = new or self._start
            return
        end += new - self._start
        self._start = new
        self.query_one("#end_date", Input).value = show_date(end.date())
        self.query_one("#end_time", Input).value = f"{end:%H:%M}"

    def _shown_time(self, side: str) -> datetime | None:
        """The ``start``/``end`` date and time fields as a naive datetime, None if invalid."""
        date_text, time_text = (
            self.query_one(f"#{side}_{part}", Input).value for part in ("date", "time")
        )
        try:
            return datetime.combine(
                parse_date(date_text, f"{side}_date", self.today),
                parse_time(time_text, f"{side}_time"),
            )
        except FormError:
            return None

    def _show_times(self, all_day: bool) -> None:
        for widget in self.query(".time"):
            widget.display = not all_day
