"""EventPrompt: create or edit an event by typing one line (``tcal.quickadd``).

The card below the line shows the event as it would be saved, updated on every keystroke:
what the line doesn't say is dim (the draft's date and time, the default calendar, …), bits
that weren't understood are named. Enter (or ``[keys] save``) dismisses with the ``Event``,
``[keys] cancel`` with ``None``; tab completes (again: the next) calendar name after ``#``.
It does not save: the caller passes the result to ``app.save_event``.

An edited event is prefilled as text; what the text has in common with the prefilled one
keeps the event's own values (``quickadd.apply``). An event with ``recurrence_id`` is one
instance of a series: repeat and calendar are fixed; a master with an RRULE edits all events
(the dates are the first one's). If a sync changed or deleted the event while the prompt was
open, saving asks first (overwrite / discard / back to the prompt).
"""

import re
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, cast

from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.keys import format_key
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from tcal.model import Calendar, Event
from tcal.quickadd import QuickAdd, apply, parse, title_end, to_text
from tcal.repeat import describe_rrule
from tcal.tz import local_zone
from tcal.ui.keys import binding
from tcal.ui.screens.prompt import Prompt

if TYPE_CHECKING:
    from tcal.ui.app import TcalApp

HINTS = (
    ("Date", "tomorrow · fri · next mon · 24.12. · dec 3-5 · in 2 weeks"),
    ("Time", "12:30-13:30 · 9am · 14:00 2h · all day"),
    ("Repeat", "every week · every mon, wed until dec · daily 10 times"),
    ("More", '@place · #calendar (tab completes) · // notes · "as typed"'),
)
LABEL_WIDTH = 10
_TAG = re.compile(r"(?<!\S)#([^#]*)$")


@dataclass(frozen=True)
class Completion:
    """A calendar name put in by tab: ``value`` with the ``index``-th of ``names``."""

    value: str
    before: str
    names: tuple[str, ...]
    index: int
    after: str


def _rows(rows: list[tuple[Text, Text]]) -> Table:
    table = Table.grid(expand=True)
    table.add_column(width=LABEL_WIDTH, no_wrap=True)
    table.add_column(ratio=1, no_wrap=True, overflow="ellipsis")
    for label, value in rows:
        table.add_row(label, value)
    return table


def when_texts(start: datetime, end: datetime, all_day: bool) -> tuple[str, str]:
    """The date and the time as the card shows them: ("Wed 18 Nov 2026", "10:00 – 11:30")."""
    start, end = start.astimezone(local_zone()), end.astimezone(local_zone())
    last = (end - timedelta(days=1)).date() if all_day else end.date()
    overnight = not all_day and end - start < timedelta(days=1)
    days = f"{start:%a %-d %b %Y}"
    if last > start.date() and not overnight:
        days += f" – {last:%a %-d %b %Y}"
    if all_day:
        return days, "all day"
    next_day = f" ({end:%a})" if overnight and last > start.date() else ""
    return days, f"{start:%H:%M} – {end:%H:%M}{next_day}"


def _content(rows: list[Event]) -> list[Event]:
    """``rows`` without what our own push changes (etag, href; ``raw`` isn't compared)."""
    return [replace(r, etag=None, href=None) for r in rows]


def server_changed_prompt(summary: str, now: str | None) -> Prompt[bool]:
    """At save, the event changed on the server since the prompt opened: overwrite it with
    the typed version (True), discard that (False) or go back. ``summary``: the event's
    title when the prompt opened; ``now``: its title on the server (None: deleted)."""
    if now is None:
        question = f"“{summary}” was deleted on the server."
    elif now != summary:
        question = f"“{summary}” was changed on the server (now “{now}”)."
    else:
        question = f"“{summary}” was changed on the server."
    overwrite = "save again" if now is None else "overwrite"
    return Prompt(question, {"o": (overwrite, True), "d": ("discard mine", False)}, ("esc", "back"))


class EventPrompt(ModalScreen[Event | None]):
    BINDINGS = [
        binding("save", "Save", priority=True),
        binding("cancel", "Cancel", action="dismiss"),
        Binding("tab", "complete", "Complete calendar", priority=True),
    ]

    def __init__(self, event: Event, calendars: list[Calendar], today: date, new: bool) -> None:
        """``event``: the draft (new) or the event to edit; ``today``: what dates are
        relative to."""
        super().__init__()
        self.event = event
        self.today = today
        self.new = new
        self.calendars = sorted(calendars, key=lambda c: c.readonly)  # `#` matches writable first
        self.instance = event.recurrence_id is not None
        self.series = not new and bool(event.rrule)
        name = "" if self.instance else self._calendar(event.calendar_id).name
        self.text = "" if new else to_text(event, today, name)
        self.shown = self._parse(self.text)

    @property
    def tcal(self) -> "TcalApp":
        return cast("TcalApp", self.app)

    def compose(self) -> ComposeResult:
        with Vertical(id="event-prompt"):
            line = Input(
                self.text,
                placeholder="Lunch with Anna tomorrow 12:30-13:30 @Cafe #personal",
                select_on_focus=False,
            )
            line.border_title = "New event" if self.new else "Edit event"
            if self.instance or self.series:
                line.border_title = "Edit this event" if self.instance else "Edit all events"
            keys = self.tcal.config.keys
            line.border_subtitle = f"enter save · {format_key(keys['cancel'][0])} cancel"
            yield line
            with Vertical(id="card"):
                yield Static(id="preview")
                yield Static(id="warning")
                if self.series:
                    yield Static("Dates are the first event's; changes apply to all events.")
            hints = Static(id="hints")
            hints.border_title = "You can type"
            yield hints

    def on_mount(self) -> None:
        self._opened = _content(self._event_rows)  # to notice a sync's changes at save time
        p = self.tcal.palette
        self.query_one("#hints", Static).update(
            _rows([(Text(k, p.secondary), Text(v, p.foreground1)) for k, v in HINTS])
        )
        line = self.query_one(Input)
        line.focus()
        line.cursor_position = title_end(self.text, self.event)  # type on at the title, as vim's A
        self._preview()

    # ----- the event ------------------------------------------------------

    def _calendar(self, calendar_id: str) -> Calendar:
        return next(c for c in self.calendars if c.id == calendar_id)

    @property
    def _event_rows(self) -> list[Event]:
        """The cache's rows of the event now."""
        return self.tcal.source.rows(self.event.uid)

    def _parse(self, text: str) -> QuickAdd:
        return parse(text, self.today, [c.name for c in self.calendars], self.event)

    def _parsed(self) -> QuickAdd:
        return self._parse(self.query_one(Input).value)

    def _error(self, q: QuickAdd, event: Event) -> str:
        """Why ``event``, parsed as ``q``, can't be saved ("" if it can)."""
        if q.error:
            return q.error
        if self.instance and (q.calendar or q.has_repeat):
            what = "calendar" if q.calendar else "repeat"
            return f"One event of a series can't change its {what} (edit all events)"
        calendar = self._calendar(event.calendar_id)
        return f"{calendar.name} is read-only" if calendar.readonly else ""

    # ----- preview --------------------------------------------------------

    def _preview(self) -> None:
        q = self._parsed()
        event = apply(self.event, q, self.shown, self.calendars)
        p = self.tcal.palette
        given, default = p.foreground3, f"{p.foreground1} dim"

        def field(text: str, has: bool, empty: str = "–") -> Text:
            return Text(text or empty, given if text and has else default)

        days, hours = when_texts(event.start, event.end, event.all_day)
        calendar = self._calendar(event.calendar_id)
        notes = " ⏎ ".join(line for line in event.description.splitlines() if line.strip())
        once = "One event of a series" if self.instance else "Does not repeat"
        values = {
            "Title": field(event.summary, True, "(no title)"),
            "When": Text.assemble(field(days, q.has_date), "  ", field(hours, q.has_time)),
            "Calendar": Text.assemble(
                ("● ", calendar.color), field(calendar.name, q.calendar is not None)
            ),
            "Location": field(event.location.replace("\n", ", "), True),
            "Repeats": field(
                describe_rrule(event.rrule) if event.rrule else "", q.has_repeat, once
            ),
            "Notes": field(notes, q.notes is not None),
        }
        values["Title"].stylize("bold")
        self.query_one("#preview", Static).update(
            _rows([(Text(label, p.foreground1), value) for label, value in values.items()])
        )
        error = self._error(q, event)
        self._warn("\n".join([error, *q.warnings] if error else q.warnings))

    def _warn(self, message: str, error: bool = False) -> None:
        warning = self.query_one("#warning", Static)
        warning.display = bool(message)
        warning.set_class(error, "-error")
        warning.update(Text(message))

    def on_input_changed(self) -> None:
        self._preview()

    # ----- keys -----------------------------------------------------------

    def on_input_submitted(self) -> None:
        self.action_save()

    def action_save(self) -> None:
        q = self._parsed()
        event = apply(self.event, q, self.shown, self.calendars)
        if error := self._error(q, event) or ("" if q.summary else "Type a title"):
            self._warn(error, error=True)
            return
        now = self._event_rows
        if self.new or _content(now) == self._opened:
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

    _completion: Completion | None = None

    def action_complete(self) -> None:
        """Complete the calendar name at the cursor; again: the next one that matches."""
        line = self.query_one(Input)
        last = self._completion
        if last is not None and last.value == line.value:
            index = (last.index + 1) % len(last.names)
            before, names, after = last.before, last.names, last.after
        else:
            head = line.value[: line.cursor_position]
            if (tag := _TAG.search(head)) is None:
                return
            found = [c.name for c in self.calendars if not c.readonly]
            names = tuple(n for n in found if n.lower().startswith(tag[1].lower()))
            if not names:
                return
            before, after = head[: tag.start(1)], line.value[line.cursor_position :].lstrip()
            index = 0
        done = f"{before}{names[index]} "
        line.value = done + after
        line.cursor_position = len(done)
        self._completion = Completion(line.value, before, names, index, after)
