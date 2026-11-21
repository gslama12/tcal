from rich.style import Style
from rich.text import Text
from textual import events
from textual.app import RenderResult

from tcal.model import Calendar
from tcal.ui.keys import binding
from tcal.ui.widgets.base import TcalWidget

OTHER = "Other calendars"


class CalendarList(TcalWidget, can_focus=True):
    """ "My calendars": one row per calendar, a checkbox in its color and its name;
    subscribed feeds follow under an "Other calendars" heading (like Google), drawn
    as a rule with the title where the border title stands.

    j/k move the cursor, space/enter or a click toggles the calendar's
    visibility via ``app.toggle_calendar`` (hidden ones are in
    ``state.hidden_calendars``). A feed the last sync could not fetch gets a ⚠.
    """

    BORDER_TITLE = "My calendars"
    BINDINGS = [
        binding("cursor_down", action="move(1)"),
        binding("cursor_up", action="move(-1)"),
        binding("toggle_calendar", action="toggle_visible"),
        binding("open", action="toggle_visible"),
    ]

    cursor = 0  # index into ``ordered()``

    def ordered(self) -> list[Calendar]:
        calendars = self.tcal.calendars()
        return [c for c in calendars if not c.subscribed] + [c for c in calendars if c.subscribed]

    def lines(self) -> list[Calendar | str]:
        """The rendered rows: calendars and headings (a blank line, then "Other calendars")."""
        calendars = self.ordered()
        others = [c for c in calendars if c.subscribed]
        if not others:
            return list(calendars)
        return [*calendars[: -len(others)], "", OTHER, *others]

    def render(self) -> RenderResult:
        hidden = self.tcal.state.hidden_calendars
        p = self.tcal.palette
        rows = []
        calendars = iter(enumerate(self.ordered()))
        for line in self.lines():
            if isinstance(line, str):  # a blank, or the heading styled like the border title
                rule = "─" * max(0, self.content_size.width - len(line) - 2) if line else ""
                title = Style(color=p.foreground1)
                rows.append(
                    Text.assemble((f" {line} " if line else "", title), (rule, p.background3))
                )
                continue
            i, cal = next(calendars)
            shown = cal.id not in hidden
            row = Text()
            row.append("■ " if shown else "□ ", style=Style(color=cal.color, bold=True))
            row.append(cal.name, style=Style(color=p.foreground3 if shown else p.foreground1))
            if cal.subscribed and cal.name in self.tcal.sync_status.failed_feeds:
                row.append(" ⚠", style=Style(color=p.yellow))
            if self.has_focus and i == self.cursor:
                row.pad_right(self.content_size.width - len(row))
                row.stylize(Style(bgcolor=p.background3))
            rows.append(row)
        return Text("\n", no_wrap=True, overflow="ellipsis").join(rows)

    def on_click(self, event: events.Click) -> None:
        offset = event.get_content_offset(self)
        lines = self.lines()
        if offset is None or offset.y >= len(lines):
            return
        if isinstance(cal := lines[offset.y], Calendar):
            self.cursor = self.ordered().index(cal)
            self.action_toggle_visible()

    def action_move(self, n: int) -> None:
        self.cursor = max(0, min(self.cursor + n, len(self.tcal.calendars()) - 1))
        self.refresh()

    def action_toggle_visible(self) -> None:
        calendars = self.ordered()
        if calendars:
            self.tcal.toggle_calendar(calendars[min(self.cursor, len(calendars) - 1)].id)

    def on_focus(self) -> None:
        self.refresh()

    def on_blur(self) -> None:
        self.refresh()
