from dataclasses import dataclass
from datetime import date

from rich.style import Style
from rich.text import Text
from textual import events
from textual.app import RenderResult

from tcal.ui.calgrid import by_day
from tcal.ui.state import add_months
from tcal.ui.widgets.base import join_lines
from tcal.ui.widgets.day_cursor import DayCursorView
from tcal.ui.widgets.minimonth import WEEKS, WIDTH, day_at, mini_month

GRIDS = ((4, 3), (3, 4), (2, 6))  # month columns x rows, preferred first
MIN_HGAP = 2
# (weekday initials shown, min. blank lines between rows), dropped in turn if nothing fits
COMPACT = ((True, 1), (False, 1), (False, 0))


@dataclass(frozen=True)
class Layout:
    """Where the 12 month blocks go: ``cols`` x ``rows`` blocks, top left at (x0, y0).

    Each block is a month title over a ``mini_month`` scaled to ``cell`` columns
    per day and ``row_height`` lines per week (without the weekday initials if
    ``header`` is False, for terminals too small for any grid otherwise).
    """

    cols: int
    rows: int
    cell: int
    row_height: int
    header: bool
    x0: int
    y0: int
    hgap: int
    vgap: int

    @property
    def width(self) -> int:
        return 7 * self.cell - 1

    @property
    def height(self) -> int:
        return 1 + self.header + WEEKS * self.row_height

    @classmethod
    def build(cls, width: int, height: int) -> "Layout":
        """The grid (of ``GRIDS``) with the largest day cells that fits the content size."""
        for header, min_vgap in COMPACT:
            best: Layout | None = None
            for cols, rows in GRIDS:
                cell = (width - (cols - 1) * MIN_HGAP + cols) // (7 * cols)
                lines = (height - (rows - 1) * min_vgap - (1 + header) * rows) // (WEEKS * rows)
                if cell < 3 or lines < 1:
                    continue
                # keep the day cells about as tall as wide (a cell is ~2:1)
                row_height = min(lines, max(1, round(cell / 3)))
                cell = min(cell, 3 * row_height + 1)
                if best is None or cell * row_height > best.cell * best.row_height:
                    best = cls._place(cols, rows, cell, row_height, header, width, height)
            if best is not None:
                return best
        # too small for any grid: the narrowest that fits, cropped below
        cols, rows = next(
            (g for g in GRIDS if g[0] * WIDTH + (g[0] - 1) * MIN_HGAP <= width), GRIDS[-1]
        )
        return cls._place(cols, rows, 3, 1, False, width, height)

    @classmethod
    def _place(
        cls, cols: int, rows: int, cell: int, row_height: int, header: bool, w: int, h: int
    ) -> "Layout":
        """Spread the blocks over the free space (gaps up to 2 cells / 1 week), centred."""
        bw, bh = 7 * cell - 1, 1 + header + WEEKS * row_height
        hgap = max(MIN_HGAP, min(2 * cell, (w - cols * bw) // (cols - 1)))
        vgap = max(0, min(row_height, (h - rows * bh) // (rows - 1)))
        x0 = max(0, (w - cols * bw - (cols - 1) * hgap) // 2)
        y0 = max(0, (h - rows * bh - (rows - 1) * vgap) // 2)
        return cls(cols, rows, cell, row_height, header, x0, y0, hgap, vgap)

    def origin(self, index: int) -> tuple[int, int]:
        """Top left of month block ``index`` (0 = January)."""
        row, col = divmod(index, self.cols)
        return self.x0 + col * (self.width + self.hgap), self.y0 + row * (self.height + self.vgap)

    def at(self, x: int, y: int) -> tuple[int, int, int] | None:
        """(month index, x, y within its block) under content offset (x, y)."""
        for index in range(12):
            bx, by = self.origin(index)
            if bx <= x < bx + self.width and by <= y < by + self.height:
                return index, x - bx, y - by
        return None


class YearView(DayCursorView):
    """The 12 months of ``state.day``'s year (4x3, 3x4 or 2x6, scaled to the size).

    Today accented, days with events bright (others dimmed), the selected day highlighted;
    h/j/k/l move it, enter opens the Day view. Clicking a day selects it
    (clicking the selected day opens it), clicking a month name opens the Month view.
    """

    def render(self) -> RenderResult:
        state, p = self.tcal.state, self.tcal.palette
        width, height = self.content_size
        layout = Layout.build(width, height)
        event_days = by_day(self.tcal.occurrences(*state.period())).keys()
        canvas = [Text() for _ in range(height)]
        for index in range(12):
            month = date(state.day.year, index + 1, 1)
            color = p.primary if month.month == date.today().month else p.foreground3
            title = Text(f" {month:%B}", style=Style(color=color, bold=True))
            lines = mini_month(
                month,
                week_start=state.week_start,
                palette=p,
                today=date.today(),
                selected=state.day,
                event_days=event_days,
                adjacent=False,
                cell=layout.cell,
                row_height=layout.row_height,
            )
            block = [title, *(lines if layout.header else lines[1:])]
            x, y = layout.origin(index)
            for i, line in enumerate(block):
                if 0 <= y + i < height:
                    row = canvas[y + i]
                    row.pad_right(x - len(row))
                    row.append_text(line)
        return join_lines(canvas)

    def on_click(self, event: events.Click) -> None:
        offset = event.get_content_offset(self)
        state = self.tcal.state
        layout = Layout.build(*self.content_size)
        hit = layout.at(offset.x, offset.y) if offset else None
        if hit is None:
            return
        index, x, y = hit
        month = date(state.day.year, index + 1, 1)
        if y == 0:
            self.tcal.select_date(add_months(state.day, index + 1 - state.day.month))
            self.tcal.action_set_view("month")
        elif (
            day := day_at(
                month, state.week_start, x, y - layout.header, layout.cell, layout.row_height
            )
        ) and day.month == month.month:
            if day == state.day:
                self.action_open()
            else:
                self.tcal.select_date(day)
