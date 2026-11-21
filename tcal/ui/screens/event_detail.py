"""Event detail modal (enter/click on an event) and the delete confirmation.

``EventDetail(occ)``: e = edit (``app.edit_occurrence``), x = delete, j/k scroll,
esc/q = close; it follows a sync's changes to the event (closes if it's gone) (a read-only calendar's event only hints "esc close"; e/x give a
notice and keep the detail open).
``confirm_delete(app, occ)`` is the one delete flow, also used by the ``x`` key
in the views: read-only calendars only get a notice; a recurring event asks
"this event" vs "all events". ``EditScope`` asks the same before editing
one instance of a series ("this event" vs "all events").
"""

from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Literal, cast
from zoneinfo import ZoneInfo

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from tcal import ics
from tcal.model import Occurrence
from tcal.tz import local_zone
from tcal.ui.calgrid import WEEKDAY_NAMES
from tcal.ui.keys import binding

if TYPE_CHECKING:
    from tcal.ui.app import TcalApp

Scope = Literal["occurrence", "series"]

FREQS = {"DAILY": "day", "WEEKLY": "week", "MONTHLY": "month", "YEARLY": "year"}
WEEKDAYS = dict(zip(("MO", "TU", "WE", "TH", "FR", "SA", "SU"), WEEKDAY_NAMES, strict=True))


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
        words += f", until {until_date(until):%-d %b %Y}"
    return words


def until_date(value: str) -> date:
    """The local day of an RRULE UNTIL (a DATE, a UTC ``…Z`` or a floating date-time)."""
    day = date(int(value[:4]), int(value[4:6]), int(value[6:8]))
    if not value.upper().endswith("Z"):
        return day
    stamp = datetime.strptime(value.upper(), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    return stamp.astimezone(local_zone()).date()


PARTSTATS = {  # PARTSTAT -> reply, in the order the guest summary counts them
    "ACCEPTED": "yes",
    "TENTATIVE": "maybe",
    "DECLINED": "no",
    "NEEDS-ACTION": "awaiting",
    "DELEGATED": "delegated",
}


def zone_text(occ: Occurrence) -> str:
    """The time in the event's own zone, if that differs from local time ('' otherwise)."""
    zone = occ.event.start.tzinfo
    if occ.all_day or not isinstance(zone, ZoneInfo):
        return ""
    there = Occurrence(occ.event, occ.start.astimezone(zone), occ.end.astimezone(zone))
    if there.start.utcoffset() == occ.start.utcoffset():
        return ""
    return f"{zone.key}: {time_range(there)}"


def duration_text(delta: timedelta) -> str:
    """'10 min', '1 h', '1 h 30 min', '2 days', '1 week'."""
    minutes = int(abs(delta).total_seconds()) // 60
    for size, unit in ((7 * 24 * 60, "week"), (24 * 60, "day")):
        if minutes >= size and minutes % size == 0:
            n = minutes // size
            return f"{n} {unit}{'s' if n > 1 else ''}"
    hours, rest = divmod(minutes, 60)
    if not hours:
        return f"{rest} min"
    return f"{hours} h {rest} min" if rest else f"{hours} h"


def alarm_text(alarm: ics.Alarm, occ: Occurrence) -> str:
    """'10 min before', 'At start', '10 min before end', all-day: '1 day before at 09:00',
    absolute: 'At …'."""
    trigger = alarm.trigger
    if isinstance(trigger, datetime):
        return f"At {trigger.astimezone(occ.start.tzinfo):%a %-d %b %Y, %H:%M}"
    if occ.all_day:
        when = (occ.end if alarm.from_end else occ.start) + trigger
        days = (occ.start.date() - when.date()).days
        side = "before" if days > 0 else "after"
        on = "On the day" if days == 0 else f"{abs(days)} day{'s' if abs(days) > 1 else ''} {side}"
        return f"{on} at {when:%H:%M}"
    edge = "end" if alarm.from_end else "start"
    if not trigger:
        return f"At {edge}"
    side = "before" if trigger < timedelta() else "after"
    return f"{duration_text(trigger)} {side}" + (" end" if alarm.from_end else "")


def people_text(extras: ics.Extras) -> str:
    """A Google-style heading ('3 guests · 1 yes, 1 no, 1 awaiting') and one line per
    guest with their reply; the organizer is marked (and listed first if not a guest)."""
    if not extras.attendees and not extras.organizer:
        return ""
    replies = [PARTSTATS.get(status, status.lower()) for _, status in extras.attendees]
    lines = [
        f"{name} · {reply}" + (" · organizer" if name == extras.organizer else "")
        for (name, _), reply in zip(extras.attendees, replies, strict=True)
    ]
    if extras.organizer and all(name != extras.organizer for name, _ in extras.attendees):
        lines.insert(0, f"{extras.organizer} · organizer")
    order = [*PARTSTATS.values(), *sorted(set(replies) - set(PARTSTATS.values()))]
    counts = [f"{replies.count(r)} {r}" for r in order if r in replies]
    heading = f"{len(lines)} guest{'s' if len(lines) > 1 else ''}"
    return "\n".join([" · ".join([heading, ", ".join(counts)]) if counts else heading, *lines])


def recurrence_text(occ: Occurrence) -> str:
    if occ.event.rrule:
        return describe_rrule(occ.event.rrule)
    return "Changed instance of a repeating event" if occ.event.recurrence_id else ""


def confirm_delete(app: "TcalApp", occ: Occurrence) -> None:
    """Ask, then delete ``occ`` (or its series) via ``app.delete_event``."""
    if not app.check_writable(occ.calendar_id):
        return

    def done(scope: Scope | None) -> None:
        if scope == "series":
            app.delete_event(occ.event.uid)
        elif scope == "occurrence":
            app.delete_event(occ.event.uid, occ.event.recurrence_id or occ.start)

    app.push_screen(ConfirmDelete(occ), done)


class ScopeDialog(ModalScreen[Scope | None]):
    """Asks a question about ``occ``; dismisses with the chosen ``Scope``, None on n/esc."""

    BINDINGS = [
        Binding(key, f"choose('{key}')", show=False) for key in ("y", "o", "s", "n", "escape")
    ]

    def __init__(self, occ: Occurrence) -> None:
        super().__init__()
        self.occ = occ
        self.recurring = is_recurring(occ)

    verb = ""

    @property
    def scopes(self) -> list[tuple[str, Scope, str]]:
        """(key, result, button label) per choice."""
        raise NotImplementedError

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(Text(f"{self.verb} “{self.occ.summary}”?", style="bold"))
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


class ConfirmDelete(ScopeDialog):
    """y = delete (o = this event, s = all events for repeating events), n/esc = cancel."""

    verb = "Delete"

    @property
    def scopes(self) -> list[tuple[str, Scope, str]]:
        if self.recurring:
            return [("o", "occurrence", "This event (o)"), ("s", "series", "All events (s)")]
        return [("y", "series", "Delete (y)")]


class EditScope(ScopeDialog):
    """Before editing an instance of a series: o = this event, s = all events, n/esc = cancel."""

    verb = "Edit"

    @property
    def scopes(self) -> list[tuple[str, Scope, str]]:
        return [("o", "occurrence", "This event (o)"), ("s", "series", "All events (s)")]


class MoveScope(EditScope):
    """Before moving an instance of a series (ctrl+h/j/k/l): o = this event, s = all events."""

    verb = "Move"


class EventDetail(ModalScreen[None]):
    """Read-only view of one occurrence: title and hints stay put, the rest scrolls (j/k)."""

    BINDINGS = [
        binding("edit_event", "Edit", action="edit"),
        binding("delete_event", "Delete", action="delete"),
        binding("cursor_down", action="scroll_body(1)"),
        binding("cursor_up", action="scroll_body(-1)"),
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
        calendar = self.tcal.calendar(occ.calendar_id)
        name = calendar.name if calendar else occ.calendar_id
        if calendar is not None and calendar.readonly:
            name += " (read-only)"
        # The dialog scrolls; the title and the hints are docked, so they stay put.
        with VerticalScroll(id="dialog", can_focus=False):
            yield Static(Text(occ.summary or "(no title)", style="bold"), id="title")
            yield Static(
                Text.assemble(("● ", self.tcal.calendar_color(occ.calendar_id)), name),
                id="calendar",
            )
            yield Static(time_range(occ), id="time")
            extras = ics.extras(occ.event)
            for widget_id, value in (
                ("timezone", zone_text(occ)),
                ("recurrence", recurrence_text(occ)),
                ("location", occ.event.location),
                ("url", extras.url),
                ("people", people_text(extras)),
                ("alarms", "\n".join(f"Alert: {alarm_text(a, occ)}" for a in extras.alarms)),
                ("notes", occ.event.description),
            ):
                if value:
                    yield Static(value, id=widget_id)
            self.hints = (
                "esc close" if calendar and calendar.readonly else "e edit  x delete  esc close"
            )
            yield Static(Text(self.hints, style=p.foreground1), id="hints")

    def on_mount(self) -> None:
        self.call_after_refresh(self._show_scroll_hint)
        self.watch(self.app, "state", self._data_changed, init=False)

    def _data_changed(self) -> None:
        """After a sync (any redraw): show the event's new version, or close if it's gone."""
        occ = self.tcal.current_occurrence(self.occ)
        if occ is None:
            gone = self.tcal.source.get_event(self.occ.event.uid) is None
            what = "was deleted" if gone else "was changed"
            self.tcal.notify(f"“{self.occ.summary}” {what} on the server", severity="warning")
            self.dismiss()
        elif occ != self.occ:
            self.occ = occ
            self.refresh(recompose=True)
            self.call_after_refresh(self._show_scroll_hint)

    def _show_scroll_hint(self) -> None:
        if self.query_one("#dialog", VerticalScroll).max_scroll_y:
            hints = f"{self.hints}  j/k scroll"
            self.query_one("#hints", Static).update(
                Text(hints, style=self.tcal.palette.foreground1)
            )

    def action_scroll_body(self, lines: int) -> None:
        self.query_one("#dialog", VerticalScroll).scroll_relative(y=lines, animate=False)

    def action_edit(self) -> None:
        if self.tcal.check_writable(self.occ.calendar_id):
            self.dismiss()
            self.tcal.edit_occurrence(self.occ)

    def action_delete(self) -> None:
        if self.tcal.check_writable(self.occ.calendar_id):
            self.dismiss()
            confirm_delete(self.tcal, self.occ)
