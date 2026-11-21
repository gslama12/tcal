from dataclasses import dataclass
from datetime import date, timedelta

from rich.style import Style
from rich.text import Text
from textual import events
from textual.app import RenderResult

from tcal.model import Occurrence
from tcal.ui.calgrid import by_day, month_weeks, occurrence_days, weekday_names
from tcal.ui.keys import EVENT_BINDINGS
from tcal.ui.messages import EventSelected
from tcal.ui.timelayout import is_bar, layout_bars
from tcal.ui.widgets.base import join_lines
from tcal.ui.widgets.day_cursor import DayCursorView

Chip = Occurrence | int | None  # an event, the count for "+N more", or an empty lane line
Cells = list[list[Chip]]  # chip lines per day of a week


@dataclass(frozen=True)
class Grid:
    """Geometry of the month grid for a content size.

    Line 0 is the weekday header; week ``w`` then takes ``heights[w]`` lines
    from ``tops[w]``: a separator (only if ``rule``; dropped when the height is
    tight), the day number and chip lines. The rows share the full height.
    """

    weeks: list[list[date]]
    xs: list[int]  # x offset of each column
    widths: list[int]
    tops: list[int]
    heights: list[int]
    rule: bool

    def slots(self, week: int) -> int:
        return max(0, self.heights[week] - self.rule - 1)

    @classmethod
    def build(cls, weeks: list[list[date]], width: int, height: int) -> "Grid":
        inner = max(7, width - 6)  # six "│" separators
        widths = [inner // 7 + (i >= 7 - inner % 7) for i in range(7)]  # spare cols at the end
        xs = [sum(widths[:i]) + i for i in range(7)]
        base, extra = divmod(max(len(weeks), height - 1), len(weeks))
        heights = [base + (w < extra) for w in range(len(weeks))]
        tops = [1 + sum(heights[:w]) for w in range(len(weeks))]
        return cls(weeks, xs, widths, tops, heights, rule=base >= 4)

    def at(self, x: int, y: int) -> tuple[int, int, int] | None:
        """(week, column, cell line) under content offset (x, y); cell line 0 is
        the day number, 1.. the chips and -1 the separator."""
        if y < 1 or y >= self.tops[-1] + self.heights[-1]:
            return None
        week = max(w for w in range(len(self.weeks)) if self.tops[w] <= y)
        column = max(i for i in range(7) if self.xs[i] <= x or i == 0)
        return week, column, y - self.tops[week] - self.rule


def layout_week(week: list[date], occurrences: list[Occurrence], slots: int) -> Cells:
    """Chip lines per day of ``week``.

    All-day / multi-day events keep one lane across the week (so they draw as
    one bar), timed events follow below the day's bars; if they overflow the
    last line is "+N more".
    """
    bars = layout_bars(occurrences, week)
    timed = by_day([occ for occ in occurrences if not is_bar(occ)])
    cells: Cells = []
    for i, day in enumerate(week):
        lanes = {bar.lane: bar.occ for bar in bars if bar.first <= i < bar.last}
        lines: list[Chip] = [lanes.get(k) for k in range(max(lanes, default=-1) + 1)]
        lines += timed.get(day, [])
        if len(lines) > slots:
            keep = max(0, slots - 1)
            hidden = sum(1 for chip in lines[keep:] if chip is not None)
            lines = [*lines[:keep], hidden][:slots]
        cells.append(lines)
    return cells


class MonthView(DayCursorView):
    """Grid of the weeks of ``state.day``'s month with event chips per day.

    h/j/k/l move the selected day, n/p select the shown events (``selected``),
    enter opens the selected event (``EventSelected``) or else the day in the
    Day view; a click on the day number or "+N more" opens the day, on an event
    selects and opens it.
    """

    BINDINGS = EVENT_BINDINGS

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self._picked: Occurrence | None = None

    def grid(self) -> Grid:
        day, week_start = self.tcal.state.day, self.tcal.state.week_start
        weeks = month_weeks(day.year, day.month, week_start)
        return Grid.build(weeks, self.content_size.width, self.content_size.height)

    def week_cells(self, grid: Grid) -> list[Cells]:
        start, end = grid.weeks[0][0], grid.weeks[-1][-1] + timedelta(days=1)
        occurrences = self.tcal.occurrences(start, end)
        return [layout_week(week, occurrences, grid.slots(w)) for w, week in enumerate(grid.weeks)]

    def _stops(self) -> list[tuple[Occurrence, date]]:
        """Events shown in this month's days in n/p order, each with its first such day.

        Days of the adjacent months are skipped: selecting one would switch the month.
        """
        grid, month = self.grid(), self.tcal.state.day.month
        stops: list[tuple[Occurrence, date]] = []
        for week, cells in zip(grid.weeks, self.week_cells(grid), strict=True):
            for day, lines in zip(week, cells, strict=True):
                for chip in lines if day.month == month else []:
                    if isinstance(chip, Occurrence) and all(chip != occ for occ, _ in stops):
                        stops.append((chip, day))
        return stops

    @property
    def selected(self) -> Occurrence | None:
        """The event picked with n/p or a click, while it is shown on the selected day."""
        picked = self._picked
        if picked is None or self.tcal.state.day not in occurrence_days(picked):
            return None
        return picked if any(occ == picked for occ, _ in self._stops()) else None

    def _pick(self, occ: Occurrence, day: date) -> None:
        self._picked = occ
        self.tcal.select_date(day)
        self.refresh()

    def action_cycle(self, step: int) -> None:
        stops = self._stops()
        if not stops:
            return
        occs = [occ for occ, _ in stops]
        current = self.selected
        index = occs.index(current) + step if current in occs else (0 if step > 0 else -1)
        self._pick(*stops[index % len(stops)])

    def move(self, days: int) -> None:
        self._picked = None
        super().move(days)

    def action_open(self) -> None:
        if occ := self.selected:
            self.post_message(EventSelected(occ))
        else:
            super().action_open()

    # ----- drawing --------------------------------------------------------

    def render(self) -> RenderResult:
        grid, state, p = self.grid(), self.tcal.state, self.tcal.palette
        rule = Style(color=p.background3)
        header = Text()
        for i, name in enumerate(weekday_names(state.week_start)):
            if i:
                header.append(" ")
            header.append(name.center(grid.widths[i]), style=Style(color=p.foreground1, bold=True))
        lines = [header]
        selected = self.selected
        for w, (week, cells) in enumerate(zip(grid.weeks, self.week_cells(grid), strict=True)):
            if grid.rule:
                lines.append(Text("┼".join("─" * width for width in grid.widths), style=rule))
            lines.append(self._numbers(week, grid))
            for line in range(grid.slots(w)):
                lines.append(self._chip_line(week, cells, line, grid, selected))
        return join_lines(lines)

    def _base(self, day: date) -> Style:
        return self.cursor_style() if day == self.tcal.state.day else Style()

    def _numbers(self, week: list[date], grid: Grid) -> Text:
        state, p = self.tcal.state, self.tcal.palette
        text = Text()
        for i, day in enumerate(week):
            if i:
                text.append("│", style=Style(color=p.background3))
            cell = Text(style=self._base(day))
            number = f"{day:%b} {day.day}" if day.day == 1 else str(day.day)
            if day == date.today():
                style = Style(color=p.background1, bgcolor=p.primary, bold=True)
                number = f" {number} "
            elif day.month != state.day.month:
                style = Style(color=p.foreground1, dim=True)
            else:
                style = Style(color=p.foreground3, bold=day == state.day)
            cell.append(" ")
            cell.append(number, style=style)
            cell.truncate(grid.widths[i], pad=True)
            text.append_text(cell)
        return text

    def _chip_line(
        self,
        week: list[date],
        cells: Cells,
        line: int,
        grid: Grid,
        selected: Occurrence | None,
    ) -> Text:
        """Chip line ``line`` of a week; a bar runs over the days (and borders) it spans."""
        p = self.tcal.palette
        chips = [lines[line] if line < len(lines) else None for lines in cells]
        text, i = Text(), 0
        while i < 7:
            if i:
                text.append("│", style=Style(color=p.background3))
            chip, last = chips[i], i
            if isinstance(chip, Occurrence) and is_bar(chip):
                while last < 6 and chips[last + 1] == chip:
                    last += 1
            width = grid.xs[last] + grid.widths[last] - grid.xs[i]
            text.append_text(self._chip(chip, week[i], week[last], width, chip == selected))
            i = last + 1
        return text

    def _chip(self, chip: Chip, day: date, last: date, width: int, selected: bool) -> Text:
        """``chip`` drawn ``width`` wide for ``day`` (a bar: for ``day`` .. ``last``)."""
        p = self.tcal.palette
        text = Text(style=self._base(day), no_wrap=True, overflow="crop")
        if isinstance(chip, int):
            more = f" +{chip} more"
            text.append(more if len(more) <= width else f" +{chip}", style=Style(bold=True))
        elif chip is not None:
            color = self.tcal.calendar_color(chip.calendar_id)
            if is_bar(chip):
                days = occurrence_days(chip)
                before = "◂" if days[0] < day else " "
                label = f"{before}{chip.summary}".ljust(width)
                if days[-1] > last:
                    label = label[: width - 1] + "▸"
                style = Style(color=p.background1, bgcolor=color, bold=True, reverse=selected)
                text.append(label, style=style)
            else:
                time = f"{chip.start:%-H:%M} " if chip.start.date() == day else ""
                text.append(f" {time}", style=Style(color=color, bold=True, reverse=selected))
                text.append(chip.summary, style=Style(color=color, reverse=selected))
        text.truncate(width, pad=True)
        return text

    def on_click(self, event: events.Click) -> None:
        offset = event.get_content_offset(self)
        grid = self.grid()
        hit = grid.at(offset.x, offset.y) if offset else None
        if hit is None:
            return
        week, column, line = hit
        day = grid.weeks[week][column]
        self._picked = None
        self.tcal.select_date(day)
        lines = self.week_cells(grid)[week][column]
        chip = lines[line - 1] if 1 <= line <= len(lines) else None
        if line == 0 or isinstance(chip, int):
            self.action_open()
        elif isinstance(chip, Occurrence):
            self._pick(chip, day)
            self.post_message(EventSelected(chip))
