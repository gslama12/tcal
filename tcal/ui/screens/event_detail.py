"""Event detail modal (enter/click on an event) and the delete confirmation.

``EventDetail(occ)``: e = edit (``app.edit_occurrence``), x = delete, y = yank,
D = duplicate, the cursor up/down keys scroll, esc/q = close; it follows a sync's changes to the event
(closes if it's gone). A read-only calendar's event hints only "y copy  esc close";
e/x give a notice and keep the detail open.
``confirm_delete(app, occ)`` is the one delete flow, also used by the ``x`` key
in the views: read-only calendars only get a notice; a recurring event asks
"this event" vs "all events". ``scope_prompt(verb, occ)`` asks the same before editing,
moving or resizing one instance of a series.
"""

from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Literal, cast
from zoneinfo import ZoneInfo

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.keys import format_key
from textual.screen import ModalScreen
from textual.widgets import Static

from tcal import ics, tz
from tcal.model import Occurrence
from tcal.tz import local_zone
from tcal.ui.calgrid import WEEKDAY_NAMES
from tcal.ui.keys import binding
from tcal.ui.screens.prompt import Prompt

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


def short_when(start: datetime, all_day: bool) -> str:
    """'Mon 23 11:15' (local time), all-day: 'Mon 23'."""
    local = start.astimezone(tz.local_zone())
    return f"{local:%a %-d}" if all_day else f"{local:%a %-d %H:%M}"


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

    app.push_screen(delete_prompt(occ), done)


def scope_prompt(verb: str, occ: Occurrence) -> Prompt[Scope]:
    """Asks whether to ``verb`` "this event" (the instance ``occ``) or "all events"."""
    day = f"{occ.start.astimezone(tz.local_zone()):%a %-d %b}"
    return Prompt[Scope](
        f"{verb} “{occ.summary}” on {day}?",
        {"o": ("this event", "occurrence"), "s": ("all events", "series")},
    )


def delete_prompt(occ: Occurrence) -> Prompt[Scope]:
    if is_recurring(occ):
        return scope_prompt("Delete", occ)
    return Prompt[Scope](f"Delete “{occ.summary}”?", {"y": ("yes", "series")}, ("n", "no"))


class EventDetail(ModalScreen[None]):
    """Read-only view of one occurrence: title and hints stay put, the rest scrolls
    (the configured cursor up/down keys)."""

    BINDINGS = [
        binding("edit_event", "Edit", action="edit"),
        binding("delete_event", "Delete", action="delete"),
        binding("yank", "Yank", action="yank"),
        binding("duplicate", "Duplicate", action="duplicate"),
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
                ("notes", occ.event.description),
            ):
                if value:
                    yield Static(value, id=widget_id)
            self.hints = (
                "y copy  esc close"
                if calendar and calendar.readonly
                else "e edit  x delete  y copy  esc close"
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
            keys = self.tcal.config.keys
            down, up = (format_key(keys[a][0]) for a in ("cursor_down", "cursor_up"))
            hints = f"{self.hints}  {down}/{up} scroll"
            self.query_one("#hints", Static).update(
                Text(hints, style=self.tcal.palette.foreground1)
            )

    def action_scroll_body(self, lines: int) -> None:
        self.query_one("#dialog", VerticalScroll).scroll_relative(y=lines, animate=False)

    def action_edit(self) -> None:
        if self.tcal.check_writable(self.occ.calendar_id):
            self.dismiss()
            self.tcal.edit_occurrence(self.occ)

    def action_yank(self) -> None:
        self.tcal.editor.yank(self.occ)

    def action_duplicate(self) -> None:
        self.dismiss()  # the copy is selected in the view behind
        self.tcal.editor.duplicate(self.occ)

    def action_delete(self) -> None:
        if self.tcal.check_writable(self.occ.calendar_id):
            self.dismiss()
            confirm_delete(self.tcal, self.occ)
