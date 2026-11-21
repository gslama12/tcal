from dataclasses import dataclass
from datetime import date, timedelta

from rich.style import Style
from rich.text import Text
from textual import events
from textual.app import RenderResult

from tcal.model import Occurrence
from tcal.ui.calgrid import by_day, month_weeks, weekday_names
from tcal.ui.messages import EventSelected
from tcal.ui.widgets.day_cursor import DayCursorView

Chip = Occurrence | int  # an event, or the count for "+N more"


@dataclass(frozen=True)
class Grid:
    """Geometry of the month grid for a content size.

    Line 0 is the weekday header; each week then takes ``block`` lines: a
    separator (only if ``rule``; dropped when the height is tight), the day
    number and ``slots`` chip lines.
    """

    weeks: list[list[date]]
    xs: list[int]  # x offset of each column
    widths: list[int]
    block: int
    rule: bool

    @property
    def slots(self) -> int:
        return self.block - self.rule - 1

    @classmethod
    def build(cls, weeks: list[list[date]], width: int, height: int) -> "Grid":
        inner = max(7, width - 6)  # six "│" separators
        widths = [inner // 7 + (i < inner % 7) for i in range(7)]
        xs = [sum(widths[:i]) + i for i in range(7)]
        block = max(1, (height - 1) // len(weeks))
        return cls(weeks, xs, widths, block, rule=block >= 4)

    def at(self, x: int, y: int) -> tuple[date, int] | None:
        """(day, cell line) under content offset (x, y); cell line 0 is the day
        number, 1.. the chips and -1 the separator."""
        week, line = divmod(y - 1, self.block)
        if y < 1 or week >= len(self.weeks):
            return None
        column = max(i for i in range(7) if self.xs[i] <= x or i == 0)
        return self.weeks[week][column], line - self.rule


def chips(occurrences: list[Occurrence], slots: int) -> list[Chip]:
    """What fits in ``slots`` chip lines: events, the last line "+N more" if they overflow."""
    shown: list[Chip] = list(occurrences)
    if len(shown) > slots:
        keep = max(0, slots - 1)
        shown = [*shown[:keep], len(shown) - keep][:slots]
    return shown


class MonthView(DayCursorView):
    """Grid of the weeks of ``state.day``'s month with event chips per day.

    h/j/k/l move the selected day, enter (or a click on the day number or on
    "+N more") opens it in the Day view, a click on an event posts
    ``EventSelected``. The cell height follows the widget height.
    """

    def grid(self) -> Grid:
        day, week_start = self.tcal.state.day, self.tcal.state.week_start
        weeks = month_weeks(day.year, day.month, week_start)
        return Grid.build(weeks, self.content_size.width, self.content_size.height)

    def day_chips(self, grid: Grid) -> dict[date, list[Chip]]:
        start, end = grid.weeks[0][0], grid.weeks[-1][-1] + timedelta(days=1)
        days = by_day(self.tcal.occurrences(start, end))
        return {day: chips(occs, grid.slots) for day, occs in days.items()}

    def render(self) -> RenderResult:
        grid, state, p = self.grid(), self.tcal.state, self.tcal.palette
        day_chips = self.day_chips(grid)
        rule = Style(color=p.background3)
        header = Text()
        for i, name in enumerate(weekday_names(state.week_start)):
            if i:
                header.append(" ")
            header.append(name.center(grid.widths[i]), style=Style(color=p.foreground1, bold=True))
        lines = [header]
        for week in grid.weeks:
            if grid.rule:
                lines.append(Text("┼".join("─" * w for w in grid.widths), style=rule))
            for line in range(grid.slots + 1):
                text = Text()
                for i, day in enumerate(week):
                    if i:
                        text.append("│", style=rule)
                    text.append_text(self.cell_line(day, line, grid.widths[i], day_chips))
                lines.append(text)
        return Text("\n", no_wrap=True, overflow="crop").join(lines)

    def cell_line(
        self, day: date, line: int, width: int, day_chips: dict[date, list[Chip]]
    ) -> Text:
        """Line ``line`` of the cell for ``day``: 0 = day number, then the chips."""
        state, p = self.tcal.state, self.tcal.palette
        selected = day == state.day
        base = Style(bgcolor=p.background3 if self.has_focus else p.background2) if selected else ""
        text = Text(style=base, no_wrap=True, overflow="crop")
        if line == 0:
            number = f"{day:%b} {day.day}" if day.day == 1 else str(day.day)
            if day == date.today():
                style = Style(color=p.background1, bgcolor=p.primary, bold=True)
            elif day.month != state.day.month:
                style = Style(color=p.foreground1, dim=True)
            else:
                style = Style(color=p.foreground3, bold=selected)
            text.append(" ")
            text.append(f" {number} " if day == date.today() else number, style=style)
        elif line - 1 < len(cell := day_chips.get(day, [])):
            chip = cell[line - 1]
            if isinstance(chip, int):
                more = f" +{chip} more"
                text.append(more if len(more) <= width else f" +{chip}", style=Style(bold=True))
            elif chip.all_day:
                color = self.tcal.calendar_color(chip.calendar_id)
                label = f" {chip.summary}".ljust(width)
                text.append(label, style=Style(color=p.background1, bgcolor=color))
            else:
                color = self.tcal.calendar_color(chip.calendar_id)
                time = f"{chip.start:%-H:%M} " if chip.start.date() == day else ""
                text.append(f" {time}", style=Style(color=color, bold=True))
                text.append(chip.summary, style=Style(color=color))
        text.truncate(width, pad=True)
        return text

    def on_click(self, event: events.Click) -> None:
        offset = event.get_content_offset(self)
        grid = self.grid()
        hit = grid.at(offset.x, offset.y) if offset else None
        if hit is None:
            return
        day, line = hit
        self.tcal.select_date(day)
        cell = self.day_chips(grid).get(day, [])
        chip = cell[line - 1] if 1 <= line <= len(cell) else None
        if line == 0 or isinstance(chip, int):
            self.action_open()
        elif chip is not None:
            self.post_message(EventSelected(chip))
