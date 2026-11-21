"""Day and Week views: a Google-Calendar-like time grid.

Layout (content area of the widget)::

    axis │ Mon 16 │ Tue 17 │ ...      header: weekday + date, today highlighted
         │ ▆▆ Conference ▆▆▆ │       all-day strip: all-day / multi-day bars
    ─────┼────────┼────────┼──       separator
    09:00│ Standup│        │         time grid: rows_per_hour rows per hour,
         │        │ ██████ │         events as colored blocks, now-line, cursor

The pure helpers (``TimeScale``, ``fit_rows_per_hour``, ``pack_columns``,
``pack_lanes``, ``layout_blocks``, ``layout_bars``) do the geometry; ``TimeGrid``
keeps the cursor / scroll / zoom and draws with the line API from a cached frame.
Cursor and scroll position are stored in minutes so they survive zooming.
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from functools import lru_cache

from rich.cells import cell_len
from rich.segment import Segment
from rich.style import Style
from textual import events
from textual.strip import Strip

from tcal.model import Occurrence
from tcal.ui.keys import binding
from tcal.ui.messages import EventSelected, NewEventRequested
from tcal.ui.state import AppState, ViewMode
from tcal.ui.widgets.base import CalendarView

ZOOMS = (1, 2, 3, 4, 6, 8)  # rows per hour
AXIS = 6  # width of the time axis: "HH:MM "
MAX_LANES = 3  # all-day strip rows shown at most
MINUTES = 24 * 60
SCROLL_ROWS = 2  # rows per mouse-wheel step


def now() -> datetime:
    """Current local time (patched in tests)."""
    return datetime.now().astimezone()


# ----- geometry (pure) ------------------------------------------------------


@dataclass(frozen=True)
class TimeScale:
    """Mapping between minutes after midnight and grid rows."""

    rows_per_hour: int

    @property
    def total_rows(self) -> int:
        return 24 * self.rows_per_hour

    def row_of(self, minute: int) -> int:
        """The row containing ``minute``."""
        return minute * self.rows_per_hour // 60

    def row_end(self, minute: int) -> int:
        """The first row at or after ``minute`` (exclusive end of a span)."""
        return -(-minute * self.rows_per_hour // 60)

    def minute_of(self, row: int) -> int:
        """Start minute of ``row`` (rounded up so that ``row_of`` round-trips)."""
        return -(-row * 60 // self.rows_per_hour)


def fit_rows_per_hour(height: int, start: int, end: int) -> int:
    """Largest zoom that shows the minutes [start, end) in ``height`` rows."""
    fitting = [z for z in ZOOMS if TimeScale(z).row_end(end) - TimeScale(z).row_of(start) <= height]
    return fitting[-1] if fitting else ZOOMS[0]


def _greedy(spans: Sequence[tuple[int, int]], order: Sequence[int]) -> dict[int, int]:
    """Assign each span (in ``order``) the first lane that is free at its start."""
    lane_ends: list[int] = []
    lanes: dict[int, int] = {}
    for i in order:
        start, end = spans[i]
        lane = next((k for k, e in enumerate(lane_ends) if e <= start), len(lane_ends))
        if lane == len(lane_ends):
            lane_ends.append(end)
        else:
            lane_ends[lane] = end
        lanes[i] = lane
    return lanes


def _order(spans: Sequence[tuple[int, int]]) -> list[int]:
    return sorted(range(len(spans)), key=lambda i: (spans[i][0], -spans[i][1]))


def pack_lanes(spans: Sequence[tuple[int, int]]) -> list[int]:
    """Lane per [start, end) span so that spans in one lane never overlap."""
    lanes = _greedy(spans, _order(spans))
    return [lanes[i] for i in range(len(spans))]


def pack_columns(spans: Sequence[tuple[int, int]]) -> list[tuple[int, int]]:
    """``(column, columns)`` per [start, end) span for side-by-side layout.

    Spans are grouped into clusters of transitively overlapping spans; each
    cluster is packed greedily and all its spans share the cluster's width.
    """
    result: list[tuple[int, int]] = [(0, 1)] * len(spans)
    clusters: list[list[int]] = []
    cluster_end = 0
    for i in _order(spans):
        start, end = spans[i]
        if not clusters or start >= cluster_end:
            clusters.append([])
            cluster_end = end
        clusters[-1].append(i)
        cluster_end = max(cluster_end, end)
    for cluster in clusters:
        lanes = _greedy(spans, cluster)
        width = max(lanes.values()) + 1
        for i, lane in lanes.items():
            result[i] = (lane, width)
    return result


def is_bar(occ: Occurrence) -> bool:
    """All-day and >= 24 h events go to the all-day strip, not the grid."""
    return occ.all_day or occ.end - occ.start >= timedelta(days=1)


def _minute_in(day: date, moment: datetime) -> int:
    """Wall-clock minute of ``moment`` relative to ``day``, clamped to [0, 1440]."""
    if moment.date() < day:
        return 0
    if moment.date() > day:
        return MINUTES
    return moment.hour * 60 + moment.minute


@dataclass(frozen=True)
class Block:
    """A timed occurrence drawn in day column ``day``, rows [top, bottom)."""

    occ: Occurrence
    day: int
    top: int
    bottom: int
    col: int
    cols: int


@dataclass(frozen=True)
class Bar:
    """An all-day / multi-day occurrence over day columns [first, last) in ``lane``."""

    occ: Occurrence
    first: int
    last: int
    lane: int


def layout_blocks(
    occs: Sequence[Occurrence], days: Sequence[date], scale: TimeScale
) -> list[Block]:
    """Grid blocks of the timed occurrences, clipped per day and packed into columns.

    An event shorter than a row still gets one row; events crossing midnight
    get one block per day.
    """
    blocks: list[Block] = []
    for i, day in enumerate(days):
        spans: list[tuple[Occurrence, int, int]] = []
        for occ in occs:
            if is_bar(occ):
                continue
            start, end = _minute_in(day, occ.start), _minute_in(day, occ.end)
            if start < end or (start == end and occ.start.date() == day and start < MINUTES):
                top = scale.row_of(start)
                spans.append((occ, top, max(top + 1, scale.row_end(end))))
        packed = pack_columns([(top, bottom) for _, top, bottom in spans])
        blocks += [
            Block(occ, i, top, bottom, col, cols)
            for (occ, top, bottom), (col, cols) in zip(spans, packed, strict=True)
        ]
    return blocks


def layout_bars(occs: Sequence[Occurrence], days: Sequence[date]) -> list[Bar]:
    """Strip bars of the all-day / multi-day occurrences, packed into lanes."""
    first_day = days[0]
    spans: list[tuple[Occurrence, int, int]] = []
    for occ in occs:
        if not is_bar(occ):
            continue
        end = occ.end.date() if occ.end.time() == time() else occ.end.date() + timedelta(days=1)
        first = max(0, (occ.start.date() - first_day).days)
        last = min(len(days), (end - first_day).days)
        if first < last:
            spans.append((occ, first, last))
    lanes = pack_lanes([(first, last) for _, first, last in spans])
    return [Bar(occ, f, la, lane) for (occ, f, la), lane in zip(spans, lanes, strict=True)]


# ----- drawing --------------------------------------------------------------


@lru_cache(maxsize=256)
def _style(fg: str, bg: str, bold: bool = False, reverse: bool = False) -> Style:
    return Style(color=fg, bgcolor=bg, bold=bold, reverse=reverse)


def _readable(hex_color: str, dark: str, light: str) -> str:
    """``dark`` or ``light`` text, whichever reads better on ``hex_color``."""
    r, g, b = (int(hex_color.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4))
    return dark if (0.299 * r + 0.587 * g + 0.114 * b) / 255 > 0.6 else light


class _Canvas:
    """A width x height grid of cells (char + style), converted to Strips."""

    def __init__(self, width: int, height: int, style: Style) -> None:
        self.width = width
        self.chars = [[" "] * width for _ in range(height)]
        self.styles = [[style] * width for _ in range(height)]

    def fill(self, y: int, x0: int, x1: int, style: Style, char: str = " ") -> None:
        x0, x1 = max(0, x0), min(self.width, x1)
        self.chars[y][x0:x1] = [char] * (x1 - x0)
        self.styles[y][x0:x1] = [style] * (x1 - x0)

    def text(self, y: int, x0: int, x1: int, text: str, style: Style | None = None) -> None:
        """Write ``text`` into [x0, x1), clipped; wide chars take two cells."""
        x, x1 = x0, min(self.width, x1)
        for ch in text:
            w = cell_len(ch)
            if w == 0:
                continue
            if x + w > x1:
                break
            self.chars[y][x : x + w] = [ch] + [""] * (w - 1)
            if style is not None:
                self.styles[y][x : x + w] = [style] * w
            x += w

    def strips(self) -> list[Strip]:
        strips = []
        for chars, styles in zip(self.chars, self.styles, strict=True):
            segments: list[Segment] = []
            run_start = 0
            for x in range(1, self.width + 1):
                if x == self.width or styles[x] != styles[run_start]:
                    segments.append(Segment("".join(chars[run_start:x]), styles[run_start]))
                    run_start = x
            strips.append(Strip(segments, self.width))
        return strips


# ----- widget ---------------------------------------------------------------


class TimeGrid(CalendarView):
    """Shared core of DayView / WeekView (``days()`` picks the columns).

    Keys: j/k move the slot cursor, h/l the day, n/p cycle events, enter opens
    the selected event (``EventSelected``) or requests a new one on an empty
    slot (``NewEventRequested``), +/- zoom. Mouse: click selects a slot / opens
    an event, the wheel scrolls.
    """

    BINDINGS = [
        binding("next_event", "Next event"),
        binding("prev_event", "Previous event"),
        binding("new_event", "New event"),
    ]

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self._zoom: int | None = None  # set by the user's zoom keys
        self._cursor_min = 0  # cursor slot, minutes after midnight
        self._top_min = 0  # first visible grid row, as minutes
        self._picked: Occurrence | None = None  # chosen by n/p or click
        self._data: tuple[list[date], list[Occurrence], list[Bar]] | None = None
        self._blocks: tuple[int, list[Block]] | None = None  # (rows_per_hour, blocks)
        self._lines: list[Strip] | None = None

    def days(self) -> list[date]:
        """The dates of the columns, for the current state."""
        raise NotImplementedError

    # ----- lifecycle ------------------------------------------------------

    def on_mount(self) -> None:
        view = self.tcal.config.view
        current = now()
        minute = current.hour * 60 + current.minute
        today = current.date() == self.tcal.state.day
        self._cursor_min = (
            minute if today and view.day_start <= minute < view.day_end else view.day_start
        )
        self._top_min = view.day_start
        super().on_mount()
        self.set_interval(60, self._redraw)

    def on_state(self, state: AppState) -> None:
        self._data = None
        self._blocks = None
        if self._picked is not None and self._picked not in self._occurrences():
            self._picked = None
        self._redraw()

    def on_resize(self) -> None:
        self._redraw()

    def _redraw(self) -> None:
        self._lines = None
        self.refresh()

    # ----- data -----------------------------------------------------------

    def _load(self) -> tuple[list[date], list[Occurrence], list[Bar]]:
        if self._data is None:
            days = self.days()
            occs = self.tcal.occurrences(days[0], days[-1] + timedelta(days=1))
            self._data = days, occs, layout_bars(occs, days)
        return self._data

    def _occurrences(self) -> list[Occurrence]:
        return self._load()[1]

    def _bars(self) -> list[Bar]:
        return self._load()[2]

    def _block_list(self) -> list[Block]:
        rph = self.rows_per_hour
        if self._blocks is None or self._blocks[0] != rph:
            days, occs, _ = self._load()
            self._blocks = rph, layout_blocks(occs, days, self.scale)
        return self._blocks[1]

    # ----- geometry -------------------------------------------------------

    @property
    def rows_per_hour(self) -> int:
        """Current zoom: the user's, else the config's, else fit to the height."""
        view = self.tcal.config.view
        if self._zoom:
            return self._zoom
        if view.rows_per_hour:
            return view.rows_per_hour
        return fit_rows_per_hour(self._grid_height(), view.day_start, view.day_end)

    @property
    def scale(self) -> TimeScale:
        return TimeScale(self.rows_per_hour)

    def _strip_rows(self) -> int:
        lanes = max((bar.lane + 1 for bar in self._bars()), default=0)
        return max(1, min(lanes, MAX_LANES))

    def _header_height(self) -> int:
        return 2 + self._strip_rows()  # day header + strip + separator

    def _grid_height(self) -> int:
        return max(1, self.size.height - self._header_height())

    def _top_row(self) -> int:
        scale = self.scale
        limit = max(0, scale.total_rows - self._grid_height())
        return min(max(0, scale.row_of(self._top_min)), limit)

    def _cursor_row(self) -> int:
        return self.scale.row_of(self._cursor_min)

    def _columns(self) -> list[int]:
        """x of each day column's divider, plus the right edge."""
        n, avail = len(self._load()[0]), max(0, self.size.width - AXIS)
        return [AXIS + avail * i // n for i in range(n + 1)]

    def _sub_columns(self, block: Block, xs: list[int]) -> tuple[int, int]:
        x0, x1 = xs[block.day] + 1, xs[block.day + 1]
        inner = x1 - x0
        left, right = (
            x0 + inner * block.col // block.cols,
            x0 + inner * (block.col + 1) // block.cols,
        )
        if block.col < block.cols - 1 and right - left > 2:
            right -= 1  # gap between side-by-side events
        return left, right

    # ----- cursor & selection --------------------------------------------

    @property
    def cursor_time(self) -> datetime:
        """Start of the cursor slot (local, aware)."""
        minute = self.scale.minute_of(self._cursor_row())
        return datetime.combine(self.tcal.state.day, time(minute // 60, minute % 60), now().tzinfo)

    @property
    def selected(self) -> Occurrence | None:
        """The picked event if still under the cursor, else the event at the cursor slot."""
        days = self._load()[0]
        day, row = days.index(self.tcal.state.day), self._cursor_row()
        at_cursor = sorted(
            (b for b in self._block_list() if b.day == day and b.top <= row < b.bottom),
            key=lambda b: b.col,
        )
        picked = self._picked
        if picked is not None and (
            any(bar.occ == picked for bar in self._bars())
            or any(b.occ == picked for b in at_cursor)
        ):
            return picked
        return at_cursor[0].occ if at_cursor else None

    def _move_cursor(self, minute: int) -> None:
        self._cursor_min = minute
        self._picked = None
        self._ensure_visible()
        self._redraw()

    def _ensure_visible(self) -> None:
        scale, row, top, height = (
            self.scale,
            self._cursor_row(),
            self._top_row(),
            self._grid_height(),
        )
        if row < top:
            self._top_min = scale.minute_of(row)
        elif row >= top + height:
            self._top_min = scale.minute_of(row - height + 1)

    def _scroll(self, rows: int) -> None:
        top = max(0, min(self._top_row() + rows, self.scale.total_rows - self._grid_height()))
        self._top_min = self.scale.minute_of(top)
        self._redraw()

    def _pick(self, occ: Occurrence) -> None:
        """Select ``occ``: move to its day and (timed events) its start slot."""
        days = self._load()[0]
        day = min(max(occ.start.date(), days[0]), days[-1])
        self._picked = occ
        if not is_bar(occ) and occ.start.date() == day:
            self._cursor_min = occ.start.hour * 60 + occ.start.minute
        self._ensure_visible()
        if day != self.tcal.state.day:
            self.tcal.select_date(day)  # redraws via on_state, keeps the pick
        self._redraw()

    def _stops(self) -> list[Occurrence]:
        """Events in view in n/p order: by day, all-day bars first, then by start."""
        days = self._load()[0]

        def key(occ: Occurrence) -> tuple[date, bool, datetime]:
            return max(occ.start.date(), days[0]), not is_bar(occ), occ.start

        return sorted(self._occurrences(), key=key)

    def _cycle(self, step: int) -> None:
        stops = self._stops()
        if not stops:
            return
        current = self.selected
        index = stops.index(current) + step if current in stops else (0 if step > 0 else -1)
        self._pick(stops[index % len(stops)])

    # ----- actions --------------------------------------------------------

    def action_cursor_down(self) -> None:
        row = min(self._cursor_row() + 1, self.scale.total_rows - 1)
        self._move_cursor(self.scale.minute_of(row))

    def action_cursor_up(self) -> None:
        self._move_cursor(self.scale.minute_of(max(self._cursor_row() - 1, 0)))

    def action_cursor_left(self) -> None:
        self._picked = None
        self.tcal.select_date(self.tcal.state.day - timedelta(days=1))

    def action_cursor_right(self) -> None:
        self._picked = None
        self.tcal.select_date(self.tcal.state.day + timedelta(days=1))

    def action_next_event(self) -> None:
        self._cycle(1)

    def action_prev_event(self) -> None:
        self._cycle(-1)

    def action_open(self) -> None:
        occ = self.selected
        self.post_message(EventSelected(occ) if occ else NewEventRequested(self.cursor_time))

    def action_new_event(self) -> None:
        self.post_message(NewEventRequested(self.cursor_time))

    def action_zoom_in(self) -> None:
        self._set_zoom([z for z in ZOOMS if z > self.rows_per_hour][:1])

    def action_zoom_out(self) -> None:
        self._set_zoom([z for z in ZOOMS if z < self.rows_per_hour][-1:])

    def _set_zoom(self, choice: list[int]) -> None:
        if choice:
            self._zoom = choice[0]
            self._ensure_visible()
            self._redraw()

    # ----- mouse ----------------------------------------------------------

    def on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        event.stop()
        self._scroll(SCROLL_ROWS)

    def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        event.stop()
        self._scroll(-SCROLL_ROWS)

    def on_click(self, event: events.Click) -> None:
        offset = event.get_content_offset(self)
        if offset is None:
            return
        x, y = offset
        xs = self._columns()
        days = self._load()[0]
        column = next((i for i in range(len(days)) if xs[i] <= x < xs[i + 1]), None)
        if column is None:
            return
        event.stop()
        header = self._header_height()
        if y == 0:
            self._picked = None
            self.tcal.select_date(days[column])
        elif y < header - 1:
            bar = next(
                (b for b in self._bars() if b.lane == y - 1 and b.first <= column < b.last), None
            )
            if bar is None:
                self.tcal.select_date(days[column])
            else:
                self._open(bar.occ)
        elif y >= header:
            row = self._top_row() + y - header
            if row >= self.scale.total_rows:
                return
            block = next(
                (
                    b
                    for b in self._block_list()
                    if b.day == column
                    and b.top <= row < b.bottom
                    and self._sub_columns(b, xs)[0] <= x < self._sub_columns(b, xs)[1]
                ),
                None,
            )
            self._cursor_min = self.scale.minute_of(row)
            self._picked = None
            if days[column] != self.tcal.state.day:
                self.tcal.select_date(days[column])
            if block is not None:
                self._open(block.occ)
            self._redraw()

    def _open(self, occ: Occurrence) -> None:
        self._pick(occ)
        self.post_message(EventSelected(occ))

    # ----- rendering ------------------------------------------------------

    def render_line(self, y: int) -> Strip:
        if self._lines is None or len(self._lines) != self.size.height:
            self._lines = self._render_frame()
        return self._lines[y] if y < len(self._lines) else Strip.blank(self.size.width)

    def _render_frame(self) -> list[Strip]:
        width, height = self.size
        if width <= AXIS or height <= self._header_height():
            return [Strip.blank(width)] * height
        p = self.tcal.palette
        canvas = _Canvas(width, height, _style(p.foreground1, p.background1))
        xs = self._columns()
        self._draw_header(canvas, xs)
        self._draw_strip(canvas, xs)
        self._draw_grid(canvas, xs)
        return canvas.strips()

    def _draw_header(self, canvas: _Canvas, xs: list[int]) -> None:
        p = self.tcal.palette
        today, selected = now().date(), self.tcal.state.day
        for i, day in enumerate(self._load()[0]):
            x0, x1 = xs[i] + 1, xs[i + 1]
            labels = [f"{day:%A}, {day.day} {day:%B}", f"{day:%a} {day.day}", str(day.day)]
            label = next((lab for lab in labels if len(lab) + 2 <= x1 - x0), labels[-1])
            label = f" {label} "
            if day == today:
                style = _style(p.background1, p.primary, bold=True)
            elif day == selected:
                style = _style(p.foreground3, p.background3, bold=True)
            else:
                style = _style(p.foreground2, p.background1)
            start = x0 + max(0, (x1 - x0 - len(label)) // 2)
            canvas.text(0, start, x1, label, style)

    def _draw_strip(self, canvas: _Canvas, xs: list[int]) -> None:
        p = self.tcal.palette
        rows, divider = self._strip_rows(), _style(p.background3, p.background1)
        for y in range(1, rows + 1):
            for x in xs[:-1]:
                canvas.fill(y, x, x + 1, divider, "│")
        selected, bars = self.selected, self._bars()
        hidden = sum(1 for bar in bars if bar.lane >= rows)
        if hidden:
            canvas.text(rows, 0, AXIS, f"+{hidden}", _style(p.foreground1, p.background1))
        days = self._load()[0]
        n = len(days)
        for bar in bars:
            if bar.lane >= rows:
                continue
            color = self.tcal.calendar_color(bar.occ.calendar_id)
            fg = _readable(color, p.background1, p.foreground3)
            style = _style(fg, color, bold=True, reverse=bar.occ == selected)
            y, x0, x1 = 1 + bar.lane, xs[bar.first] + 1, xs[bar.last]
            canvas.fill(y, x0, x1, style)
            before = "◂" if bar.occ.start.date() < days[0] else " "
            after = bar.last == n and bar.occ.end > _midnight(days[-1] + timedelta(days=1))
            canvas.text(y, x0, x1, f"{before}{_clean(bar.occ.summary)}")
            if after:
                canvas.text(y, x1 - 1, x1, "▸")
        sep = 1 + rows
        canvas.fill(sep, 0, canvas.width, divider, "─")
        for x in xs[:-1]:
            canvas.fill(sep, x, x + 1, divider, "┼")

    def _draw_grid(self, canvas: _Canvas, xs: list[int]) -> None:
        p = self.tcal.palette
        scale, header, top = self.scale, self._header_height(), self._top_row()
        days = self._load()[0]
        bottom = min(scale.total_rows, top + len(canvas.chars) - header)
        divider = _style(p.background3, p.background1)
        line = _style(p.background3, p.background1)
        label = _style(p.foreground1, p.background1)
        cursor = _style(p.foreground1, p.background3)
        cursor_label = _style(p.primary, p.background1, bold=True)
        sel_col, cursor_row = days.index(self.tcal.state.day), self._cursor_row()
        current = now()
        now_col = days.index(current.date()) if current.date() in days else None
        now_min = current.hour * 60 + current.minute

        for row in range(top, bottom):
            y = header + row - top
            minute = scale.minute_of(row)
            hour_start = minute % 60 == 0
            if row == cursor_row:
                canvas.text(y, 0, AXIS, f"{minute // 60:02d}:{minute % 60:02d}", cursor_label)
            elif hour_start:
                canvas.text(y, 0, AXIS, f"{minute // 60:02d}:00", label)
            for i, x in enumerate(xs[:-1]):
                canvas.fill(y, x, x + 1, divider, "│")
                if hour_start and scale.rows_per_hour >= 2:
                    canvas.fill(y, x + 1, xs[i + 1], line, "╌")
            if row == cursor_row:
                canvas.fill(y, xs[sel_col] + 1, xs[sel_col + 1], cursor)
            if now_col is not None and row == scale.row_of(now_min):
                red = Style(color=p.red, bold=True)
                x0, x1 = xs[now_col] + 1, xs[now_col + 1]
                for x in range(x0, x1):
                    canvas.chars[y][x] = "●" if x == x0 else "━"
                    canvas.styles[y][x] = canvas.styles[y][x] + red
                canvas.text(y, 0, AXIS, f"{current:%H:%M}", _style(p.red, p.background1, bold=True))

        selected = self.selected
        for block in self._block_list():
            self._draw_block(canvas, xs, block, top, bottom, header, block.occ == selected)

    def _draw_block(
        self,
        canvas: _Canvas,
        xs: list[int],
        block: Block,
        top: int,
        bottom: int,
        header: int,
        selected: bool,
    ) -> None:
        first, last = max(block.top, top), min(block.bottom, bottom)
        if first >= last:
            return
        p, occ = self.tcal.palette, block.occ
        color = self.tcal.calendar_color(occ.calendar_id)
        fg = _readable(color, p.background1, p.foreground3)
        style = _style(fg, color, reverse=selected)
        x0, x1 = self._sub_columns(block, xs)
        pad = " " if x1 - x0 >= 6 else ""
        title, span = _clean(occ.summary), f"{occ.start:%H:%M}–{occ.end:%H:%M}"
        if block.bottom - block.top == 1:
            texts = [f"{occ.start:%H:%M} {title}" if x1 - x0 >= 12 else title]
        else:
            texts = [title, span] + ([_clean(occ.event.location)] if occ.event.location else [])
        for row in range(first, last):
            y = header + row - top
            canvas.fill(y, x0, x1, style)
            index = row - first
            if index < len(texts):
                bold = _style(fg, color, bold=True, reverse=selected) if index == 0 else None
                canvas.text(y, x0, x1, pad + texts[index], bold)


def _midnight(day: date) -> datetime:
    return datetime.combine(day, time(), now().tzinfo)


def _clean(text: str) -> str:
    return " ".join(text.split())


class DayView(TimeGrid):
    """Time grid for ``state.day``."""

    def days(self) -> list[date]:
        return [self.tcal.state.day]


class WeekView(TimeGrid):
    """Time grid for the week of ``state.day`` (starting at config ``week_start``)."""

    def days(self) -> list[date]:
        start, _ = replace(self.tcal.state, view=ViewMode.WEEK).period()
        return [start + timedelta(days=i) for i in range(7)]
