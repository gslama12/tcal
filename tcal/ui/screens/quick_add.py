"""Quick add (``A``): one line parsed by ``tcal.quickadd.parse``, previewed as you type.

Dismisses with ``("save", parsed)`` (enter) or ``("form", parsed)`` (tab: open the full
form prefilled; fixed, like enter); ``[keys] cancel`` cancels. The caller turns the
result into an ``Event``.
"""

from datetime import date, timedelta
from typing import Literal

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from tcal.quickadd import QuickAdd, parse
from tcal.ui.keys import binding
from tcal.ui.screens.event_detail import describe_rrule

Mode = Literal["save", "form"]


def describe(q: QuickAdd, default_calendar: str) -> str:
    """One-line summary of ``q``: "“Lunch” · Thu 19 Nov 12:30–13:30 · every week · @Cafe ·
    Personal"."""
    if q.all_day:
        last = q.end - timedelta(days=1)
        when = f"{q.start:%a %-d %b}" + (f" – {last:%a %-d %b}" if last > q.start else "")
        when += " · all day"
    else:
        end = f"{q.end:%H:%M}" if q.end.date() == q.start.date() else f"{q.end:%a %-d %b %H:%M}"
        when = f"{q.start:%a %-d %b %H:%M}–{end}"
    parts = [f"“{q.summary}”" if q.summary else "(no title)", when]
    if q.rrule:
        repeat = describe_rrule(q.rrule)
        parts.append(repeat[0].lower() + repeat[1:])
    if q.location:
        parts.append(f"@{q.location}")
    parts.append(q.calendar or default_calendar)
    return " · ".join(parts)


class QuickAddScreen(ModalScreen[tuple[Mode, QuickAdd]]):
    """Prompt + live preview; enter saves, tab opens the event form, esc cancels."""

    BINDINGS = [
        binding("cancel", "Cancel", action="dismiss"),
        Binding("tab", "open_form", "Full form", priority=True),
    ]

    def __init__(
        self, today: date, calendars: list[str], default: str, readonly: list[str]
    ) -> None:
        """``calendars``: the writable names (``#`` matches these first), ``default``: the
        one used without ``#``; ``readonly``: names ``#`` reports as read-only."""
        super().__init__()
        self.today = today
        self.calendars = calendars
        self.default = default
        self.readonly = readonly

    def compose(self) -> ComposeResult:
        with Vertical():
            prompt = Input(placeholder="Lunch with Anna tomorrow 12:30-13:30 @Cafe #Personal")
            prompt.border_title = "Quick add"
            yield prompt
            yield Static(id="preview")

    def on_mount(self) -> None:
        keys = {
            b.binding.id: self.app.get_key_display(b.binding) for b in self.active_bindings.values()
        }
        hint = f"enter save · tab full form · {keys.get('cancel', '')} cancel"
        self.query_one(Input).border_subtitle = hint
        self._preview()

    def parsed(self) -> QuickAdd:
        return parse(self.query_one(Input).value, self.today, self.calendars + self.readonly)

    def error(self, q: QuickAdd) -> str:
        """Why ``q`` can't be saved ("" if it can)."""
        if q.unknown_calendar:
            return f"No calendar “{q.unknown_calendar}”"
        if q.calendar in self.readonly and q.calendar not in self.calendars:
            return f"{q.calendar} is read-only"
        return ""

    def _preview(self) -> QuickAdd:
        q = self.parsed()
        error = self.error(q)
        preview = self.query_one("#preview", Static)
        preview.set_class(bool(error), "-error")
        preview.update(error or describe(q, self.default))
        return q

    def on_input_changed(self) -> None:
        self._preview()

    def on_input_submitted(self) -> None:
        q = self._preview()
        if not q.summary:
            self.query_one("#preview", Static).set_class(True, "-error").update("Type a title")
        elif not self.error(q):
            self.dismiss(("save", q))

    def action_open_form(self) -> None:
        if not self.error(q := self._preview()):
            self.dismiss(("form", q))
