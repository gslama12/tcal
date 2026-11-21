from dataclasses import dataclass
from datetime import date

from rich.style import Style
from rich.text import Text
from textual import events
from textual.app import RenderResult

from tcal.ui.calgrid import by_day
from tcal.ui.state import add_months
from tcal.ui.widgets.day_cursor import DayCursorView
from tcal.ui.widgets.minimonth import HEIGHT, WIDTH, day_at, mini_month

BLOCK_HEIGHT = HEIGHT + 1  # month title + mini month


@dataclass(frozen=True)
class Layout:
    """Where the 12 month blocks go: ``cols`` x ``rows`` blocks, top left at (x0, y0).

    If not all rows fit the height, the page of rows holding the selected month
    is shown (y0 is then negative for the rows above it).
    """

    cols: int
    x0: int
    y0: int
    hgap: int
    vgap: int

    @classmethod
    def build(cls, width: int, height: int, month: int) -> "Layout":
        """The layout for a content size, with month index ``month`` (0..11) visible."""
        cols = next((c for c in (4, 3, 2) if c * WIDTH + (c - 1) * 2 <= width), 1)
        hgap = 3 if cols * WIDTH + (cols - 1) * 3 <= width else 2
        rows = -(-12 // cols)
        vgap = 1 if rows * BLOCK_HEIGHT + rows - 1 <= height else 0
        x0 = max(0, (width - cols * WIDTH - (cols - 1) * hgap) // 2)
        y0 = (height - rows * BLOCK_HEIGHT - (rows - 1) * vgap) // 2
        if y0 < 0:
            fit = max(1, height // BLOCK_HEIGHT)
            y0 = -min(month // cols // fit * fit, rows - fit) * BLOCK_HEIGHT
        return cls(cols, x0, y0, hgap, vgap)

    def origin(self, index: int) -> tuple[int, int]:
        """Top left of month block ``index`` (0 = January)."""
        row, col = divmod(index, self.cols)
        return self.x0 + col * (WIDTH + self.hgap), self.y0 + row * (BLOCK_HEIGHT + self.vgap)

    def at(self, x: int, y: int) -> tuple[int, int, int] | None:
        """(month index, x, y within its block) under content offset (x, y)."""
        for index in range(12):
            bx, by = self.origin(index)
            if bx <= x < bx + WIDTH and by <= y < by + BLOCK_HEIGHT:
                return index, x - bx, y - by
        return None


class YearView(DayCursorView):
    """The 12 months of ``state.day``'s year (4x3, 3x4, ... depending on the width).

    Today accented, days with events underlined, the selected day highlighted;
    h/j/k/l move it, enter opens the Day view. Clicking a day selects it
    (clicking the selected day opens it), clicking a month name opens the Month view.
    """

    def render(self) -> RenderResult:
        state, p = self.tcal.state, self.tcal.palette
        width, height = self.content_size
        layout = Layout.build(width, height, state.day.month - 1)
        event_days = by_day(self.tcal.occurrences(*state.period())).keys()
        canvas = [Text() for _ in range(height)]
        for index in range(12):
            month = date(state.day.year, index + 1, 1)
            color = p.primary if month.month == date.today().month else p.foreground3
            title = Text(f" {month:%B}", style=Style(color=color, bold=True))
            block = [title] + mini_month(
                month,
                week_start=state.week_start,
                palette=p,
                today=date.today(),
                selected=state.day,
                event_days=event_days,
                adjacent=False,
            )
            x, y = layout.origin(index)
            for i, line in enumerate(block):
                if 0 <= y + i < height:
                    row = canvas[y + i]
                    row.pad_right(x - len(row))
                    row.append_text(line)
        return Text("\n", no_wrap=True, overflow="crop").join(canvas)

    def on_click(self, event: events.Click) -> None:
        offset = event.get_content_offset(self)
        state = self.tcal.state
        hit = (
            Layout.build(*self.content_size, state.day.month - 1).at(offset.x, offset.y)
            if offset
            else None
        )
        if hit is None:
            return
        index, x, y = hit
        month = date(state.day.year, index + 1, 1)
        if y == 0:
            self.tcal.select_date(add_months(state.day, index + 1 - state.day.month))
            self.tcal.action_set_view("month")
        elif (day := day_at(month, state.week_start, x, y - 1)) and day.month == month.month:
            if day == state.day:
                self.action_open()
            else:
                self.tcal.select_date(day)
