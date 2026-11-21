"""Event detail modal (enter/click on an event) and the delete confirmation.

``EventDetail(occ)``: e = edit (``app.edit_occurrence``), x = delete, esc/q = close.
``confirm_delete(app, occ)`` is the one delete flow, also used by the ``x`` key
in the views: read-only calendars only get a notice; a recurring event asks
"this occurrence" vs "whole series".
"""

from datetime import date, timedelta
from typing import TYPE_CHECKING, Literal, cast

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from tcal.model import Occurrence
from tcal.ui.keys import binding

if TYPE_CHECKING:
    from tcal.ui.app import TcalApp

DeleteScope = Literal["occurrence", "series"]

FREQS = {"DAILY": "day", "WEEKLY": "week", "MONTHLY": "month", "YEARLY": "year"}
WEEKDAYS = {
    "MO": "Mon",
    "TU": "Tue",
    "WE": "Wed",
    "TH": "Thu",
    "FR": "Fri",
    "SA": "Sat",
    "SU": "Sun",
}


def is_recurring(occ: Occurrence) -> bool:
    return bool(occ.event.rrule or occ.event.recurrence_id)


def time_range(occ: Occurrence) -> str:
    """'Wed 18 Nov 2026, 10:00 – 11:30', all-day: 'Wed 18 Nov 2026 (all day)'."""
    start, end = occ.start, occ.end
    if occ.all_day:
        last = (end - timedelta(days=1)).date()  # end is exclusive
        if last <= start.date():
            return f"{start:%a %-d %b %Y} (all day)"
        return f"{start:%a %-d %b %Y} – {last:%a %-d %b %Y} (all day)"
    if start.date() == end.date():
        return f"{start:%a %-d %b %Y, %H:%M} – {end:%H:%M}"
    return f"{start:%a %-d %b %Y, %H:%M} – {end:%a %-d %b %Y, %H:%M}"


def describe_rrule(rrule: str) -> str:
    """An RRULE in words, e.g. 'Every 2 weeks on Mon, Fri, until 31 Dec 2026'."""
    parts = dict(p.split("=", 1) for p in rrule.upper().split(";") if "=" in p)
    unit = FREQS.get(parts.get("FREQ", ""))
    if unit is None:
        return f"Repeats ({rrule})"
    interval = int(parts.get("INTERVAL", "1"))
    words = f"Every {interval} {unit}s" if interval > 1 else f"Every {unit}"
    if days := parts.get("BYDAY"):
        names = [WEEKDAYS.get(d[-2:], d) for d in days.split(",")]
        if unit == "week" and names == list(WEEKDAYS.values())[:5]:
            names = ["weekdays"]
        words += " on " + ", ".join(names)
    if count := parts.get("COUNT"):
        words += f", {count} times"
    elif until := parts.get("UNTIL"):
        words += f", until {date(int(until[:4]), int(until[4:6]), int(until[6:8])):%-d %b %Y}"
    return words


def recurrence_text(occ: Occurrence) -> str:
    if occ.event.rrule:
        return describe_rrule(occ.event.rrule)
    return "Changed instance of a repeating event" if occ.event.recurrence_id else ""


def confirm_delete(app: "TcalApp", occ: Occurrence) -> None:
    """Ask, then delete ``occ`` (or its series) via ``app.delete_event``."""
    calendar = next((c for c in app.calendars() if c.id == occ.calendar_id), None)
    if calendar is not None and calendar.readonly:
        app.notify(f"{calendar.name} is read-only", severity="warning")
        return

    def done(scope: DeleteScope | None) -> None:
        if scope == "series":
            app.delete_event(occ.event.uid)
        elif scope == "occurrence":
            app.delete_event(occ.event.uid, occ.event.recurrence_id or occ.start)

    app.push_screen(ConfirmDelete(occ), done)


class ConfirmDelete(ModalScreen[DeleteScope | None]):
    """y = delete (o = this occurrence, s = whole series for repeating events), n/esc = cancel."""

    BINDINGS = [
        Binding(key, f"choose('{key}')", show=False) for key in ("y", "o", "s", "n", "escape")
    ]

    def __init__(self, occ: Occurrence) -> None:
        super().__init__()
        self.occ = occ
        self.recurring = is_recurring(occ)

    @property
    def scopes(self) -> list[tuple[str, DeleteScope, str]]:
        """(key, result, button label) per choice."""
        if self.recurring:
            return [("o", "occurrence", "This occurrence (o)"), ("s", "series", "Whole series (s)")]
        return [("y", "series", "Delete (y)")]

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(Text(f"Delete “{self.occ.summary}”?", style="bold"))
            with Horizontal(id="buttons"):
                for key, _, label in self.scopes:
                    yield Button(label, id=key, variant="error")
                yield Button("Cancel (n)", id="n")

    def action_choose(self, key: str) -> None:
        """Dismiss with the choice for ``key``; n/esc/unknown keys cancel."""
        choices = {k: scope for k, scope, _ in self.scopes}
        if key in choices or key in ("n", "escape"):
            self.dismiss(choices.get(key))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.action_choose(event.button.id or "n")


class EventDetail(ModalScreen[None]):
    """Read-only view of one occurrence."""

    BINDINGS = [
        binding("edit_event", "Edit", action="edit"),
        binding("delete_event", "Delete", action="delete"),
        binding("quit", "Close", action="dismiss"),
        Binding("escape", "dismiss", "Close", show=False),
    ]

    def __init__(self, occ: Occurrence) -> None:
        super().__init__()
        self.occ = occ

    @property
    def tcal(self) -> "TcalApp":
        return cast("TcalApp", self.app)

    def compose(self) -> ComposeResult:
        occ, p = self.occ, self.tcal.palette
        calendar = next((c for c in self.tcal.calendars() if c.id == occ.calendar_id), None)
        name = calendar.name if calendar else occ.calendar_id
        if calendar is not None and calendar.readonly:
            name += " (read-only)"
        with Vertical(id="dialog"):
            yield Static(Text(occ.summary or "(no title)", style="bold"), id="title")
            yield Static(
                Text.assemble(("● ", self.tcal.calendar_color(occ.calendar_id)), name),
                id="calendar",
            )
            yield Static(time_range(occ), id="time")
            for widget_id, value in (
                ("recurrence", recurrence_text(occ)),
                ("location", occ.event.location),
                ("notes", occ.event.description),
            ):
                if value:
                    yield Static(value, id=widget_id)
            yield Static(Text("e edit  x delete  esc close", style=p.foreground1), id="hints")

    def action_edit(self) -> None:
        self.dismiss()
        self.tcal.edit_occurrence(self.occ)

    def action_delete(self) -> None:
        self.dismiss()
        confirm_delete(self.tcal, self.occ)
