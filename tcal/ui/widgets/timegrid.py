"""Day and Week views: a Google-Calendar-like time grid.

Layout (content area of the widget)::

    axis │ Mon 16 │ Tue 17 │ ...      header: weekday + date, today highlighted
         │ ▆▆ Conference ▆▆▆ │       all-day strip: all-day / multi-day bars
    ─────┼────────┼────────┼──       separator
    09:00│ Standup│        │         time grid: rows_per_hour rows per hour,
         │        │ ██████ │         events as colored blocks, now-line, cursor

The pure helpers (``TimeScale``, ``pack_columns``,
``pack_lanes``, ``layout_blocks``, ``layout_bars``, ``fit_scale``) do the geometry; ``TimeGrid``
keeps the cursor / scroll / zoom and draws with the line API from a cached frame.
Cursor and scroll position are stored in minutes so they survive zooming.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from fractions import Fraction
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
MIN_EVENT_WIDTH = 4  # narrowest side-by-side event (+ 1-col gap); else the cluster collapses
HEADER_FORMATS = ("%A, {day} %B", "%A {day}", "%a {day}", "{day}")  # widest first


def now() -> datetime:
    """Current local time (patched in tests)."""
    return datetime.now().astimezone()


# ----- geometry (pure) ------------------------------------------------------


@dataclass(frozen=True)
class TimeScale:
    """Mapping between minutes after midnight and grid rows.

    Row ``r`` starts at minute ``offset + r * 60 / rows_per_hour``. A minute belongs to
    the row whose start is nearest (ties: the earlier row), so event edges, hour labels
    and the cursor all round the same way. Zoom levels are whole rows per hour aligned
    to midnight; a fitted scale may be fractional, with ``offset`` (within half a row
    of 0) aligning a row start to ``day_start``.
    """

    rows_per_hour: Fraction | int
    offset: Fraction | int = 0

    @classmethod
    def aligned(cls, rows_per_hour: Fraction, minute: int) -> "TimeScale":
        """The scale whose rows start exactly at ``minute``."""
        per_row = 60 / rows_per_hour
        return cls(rows_per_hour, minute - math.ceil(minute / per_row - Fraction(1, 2)) * per_row)

    @property
    def even(self) -> bool:
        """Whole rows per hour aligned to midnight (a zoom level)."""
        return self.offset == 0 and Fraction(self.rows_per_hour).denominator == 1

    @property
    def per_row(self) -> Fraction:
        return Fraction(60) / self.rows_per_hour

    @property
    def total_rows(self) -> int:
        return math.ceil((MINUTES - self.offset) / self.per_row)

    def row_of(self, minute: int) -> int:
        """The row whose start is nearest ``minute``."""
        return math.ceil((minute - self.offset) / self.per_row - Fraction(1, 2))

    def minute_of(self, row: int) -> int:
        """Start minute of ``row`` as shown to the user (``row_of`` round-trips).

        Zoom levels use the exact row start; uneven rows snap to the roundest of
        :00 / :30 / :15 / :05 among the minutes that belong to the row.
        """
        per_row = self.per_row
        start = self.offset + row * per_row
        if self.even:
            return max(0, math.ceil(start))
        lo = max(start - per_row / 2, Fraction(-1))
        hi = min(start + per_row / 2, Fraction(MINUTES - 1))
        for step in (60, 30, 15, 5, 1):
            first, last = math.floor(lo / step) + 1, math.floor(hi / step)
            if first <= last:
                return min(range(first * step, last * step + 1, step), key=lambda m: abs(m - start))
        return max(0, math.ceil(start))  # unreachable: rows are > 1 minute


def fit_scale(height: int, start: int, end: int) -> TimeScale:
    """The scale that shows the minutes [start, end) in exactly ``height`` rows.

    Outside the zoom range the nearest zoom level is used instead (scroll / extra
    hours above ``start``).
    """
    rows_per_hour = Fraction(height * 60, end - start)
    if rows_per_hour < ZOOMS[0]:
        return TimeScale(ZOOMS[0])
    if rows_per_hour > ZOOMS[-1]:
        return TimeScale(ZOOMS[-1])
    return TimeScale.aligned(rows_per_hour, start)


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


def pack_columns(spans: Sequence[tuple[int, int]]) -> list[tuple[int, int, int]]:
    """``(column, span, columns)`` per [start, end) span for side-by-side layout.

    Google-style: spans are grouped into clusters of transitively overlapping spans
    (touching is no overlap); each cluster is packed greedily into ``columns``
    columns, and a span widens over the columns to its right (``span``) until one
    holds a span it overlaps.
    """
    result: list[tuple[int, int, int]] = [(0, 1, 1)] * len(spans)
    for cluster in _clusters(spans):
        lanes = _greedy(spans, cluster)
        width = max(lanes.values()) + 1
        for i, lane in lanes.items():
            start, end = spans[i]
            right = min(
                (
                    lanes[j]
                    for j in cluster
                    if lanes[j] > lane and spans[j][0] < end and start < spans[j][1]
                ),
                default=width,
            )
            result[i] = (lane, right - lane, width)
    return result


def _clusters(spans: Sequence[tuple[int, int]]) -> list[list[int]]:
    """Indices of transitively overlapping spans, in start order."""
    clusters: list[list[int]] = []
    cluster_end = 0
    for i in _order(spans):
        start, end = spans[i]
        if not clusters or start >= cluster_end:
            clusters.append([])
            cluster_end = end
        clusters[-1].append(i)
        cluster_end = max(cluster_end, end)
    return clusters


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
    span: int = 1  # columns it covers from ``col``
    group: tuple[Occurrence, ...] = ()  # a collapsed cluster: its events (``occ`` first)

    @property
    def occs(self) -> tuple[Occurrence, ...]:
        """The occurrences drawn in this block."""
        return self.group or (self.occ,)


@dataclass(frozen=True)
class Bar:
    """An all-day / multi-day occurrence over day columns [first, last) in ``lane``."""

    occ: Occurrence
    first: int
    last: int
    lane: int


def layout_blocks(
    occs: Sequence[Occurrence],
    days: Sequence[date],
    scale: TimeScale,
    max_cols: int | None = None,
) -> list[Block]:
    """Grid blocks of the timed occurrences, clipped per day and packed into columns.

    An event shorter than a row still gets one row; events crossing midnight
    get one block per day. A cluster needing more than ``max_cols`` columns
    becomes one block over the whole column (``group`` = its events).
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
                spans.append((occ, top, max(top + 1, scale.row_of(end))))
        rows = [(top, bottom) for _, top, bottom in spans]
        packed = pack_columns(rows)
        for cluster in _clusters(rows):
            if max_cols is not None and packed[cluster[0]][2] > max_cols:
                top, bottom = rows[cluster[0]][0], max(rows[j][1] for j in cluster)
                group = tuple(sorted((spans[j][0] for j in cluster), key=_by_start))
                blocks.append(Block(group[0], i, top, bottom, 0, 1, group=group))
                continue
            for j in cluster:
                (occ, top, bottom), (col, span, cols) = spans[j], packed[j]
                blocks.append(Block(occ, i, top, bottom, col, cols, span))
    return blocks


def _by_start(occ: Occurrence) -> tuple[datetime, datetime]:
    return occ.start, occ.end


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


def _readable(hex_color: str, *colors: str) -> str:
    """The darkest or lightest of ``colors``, whichever reads better on ``hex_color``
    (order-independent, so light themes work too)."""
    dark, *_, light = sorted(colors, key=_luma)
    return dark if _luma(hex_color) > 0.6 else light


def _luma(hex_color: str) -> float:
    r, g, b = (int(hex_color.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4))
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255


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
        self._zoom: int | None = None  # rows per hour; None = fit day_start..day_end
        self._cursor_min = 0  # cursor slot, minutes after midnight
        self._top_min = 0  # first visible grid row, as minutes
        self._picked: Occurrence | None = None  # chosen by n/p or click
        self._data: tuple[list[date], list[Occurrence], list[Bar]] | None = None
        self._blocks: tuple[TimeScale, int, list[Block]] | None = None
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
        self._zoom = view.rows_per_hour or None
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
        scale, max_cols = self.scale, self._max_cols()
        if self._blocks is None or self._blocks[:2] != (scale, max_cols):
            days, occs, _ = self._load()
            self._blocks = scale, max_cols, layout_blocks(occs, days, scale, max_cols)
        return self._blocks[2]

    # ----- geometry -------------------------------------------------------

    @property
    def scale(self) -> TimeScale:
        """Current zoom: a zoom level, or day_start..day_end fitted to the grid."""
        return TimeScale(self._zoom) if self._zoom else self._fit()

    def _fit(self) -> TimeScale:
        view = self.tcal.config.view
        return fit_scale(self._grid_height(), view.day_start, view.day_end)

    @property
    def rows_per_hour(self) -> Fraction | int:
        return self.scale.rows_per_hour

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

    def _max_cols(self) -> int:
        """Side-by-side events that fit the narrowest day column (1-col gaps)."""
        xs = self._columns()
        inner = min(b - a - 1 for a, b in zip(xs, xs[1:], strict=False))
        return max(1, (inner + 1) // (MIN_EVENT_WIDTH + 1))

    def _sub_columns(self, block: Block, xs: list[int]) -> tuple[int, int]:
        x0, x1 = xs[block.day] + 1, xs[block.day + 1]
        inner, end = x1 - x0 + 1, block.col + block.span
        left = x0 + inner * block.col // block.cols
        right = x0 + inner * end // block.cols - 1  # 1-col gap (the last one is the divider)
        return left, min(right, x1)

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
            or any(picked in b.occs for b in at_cursor)
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

    def select(self, occ: Occurrence) -> None:
        """Select ``occ`` (it must be in view), as n/p would."""
        self._pick(occ)

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

    def _ladder(self) -> list[tuple[Fraction | int, int | None]]:
        """Zoom stops ``(rows_per_hour, zoom)``: the levels plus the fit (zoom None).

        Levels whose day is shorter than the grid (empty rows below 24:00) are left out.
        """
        height = self._grid_height()
        stops: dict[Fraction | int, int | None] = {z: z for z in ZOOMS if 24 * z >= height}
        stops[self._fit().rows_per_hour] = None
        return sorted(stops.items())

    def action_zoom_in(self) -> None:
        self._set_zoom([z for rph, z in self._ladder() if rph > self.rows_per_hour][:1])

    def action_zoom_out(self) -> None:
        self._set_zoom([z for rph, z in self._ladder() if rph < self.rows_per_hour][-1:])

    def _set_zoom(self, choice: list[int | None]) -> None:
        if choice:
            self._cursor_min = self.scale.minute_of(self._cursor_row())  # keep the shown time
            self._zoom = choice[0]
            if self._zoom is None:
                self._top_min = self.tcal.config.view.day_start
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
        days = self._load()[0]
        narrowest = min(b - a - 1 for a, b in zip(xs, xs[1:], strict=False))
        fmt = next(
            (f for f in HEADER_FORMATS if max(len(_header(f, d)) for d in days) + 2 <= narrowest),
            HEADER_FORMATS[-1],
        )
        for i, day in enumerate(days):
            x0, x1 = xs[i] + 1, xs[i + 1]
            label = f" {_header(fmt, day)} "
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
            style = _style(fg, color, bold=True)
            y, x0, x1 = 1 + bar.lane, xs[bar.first] + 1, xs[bar.last]
            canvas.fill(y, x0, x1, style)
            before = "◂" if bar.occ.start.date() < days[0] else " "
            if bar.occ == selected:  # accent bar, as for selected blocks
                before = "▌" if before == " " else before
            after = bar.last == n and bar.occ.end > _midnight(days[-1] + timedelta(days=1))
            canvas.text(y, x0, x1, f"{before}{_clean(bar.occ.summary)}")
            if bar.occ == selected:
                canvas.text(y, x0, x0 + 1, before, _style(p.foreground3, color, bold=True))
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
        cursor = _style(p.background1, p.primary)
        cursor_label = _style(p.primary, p.background1, bold=True)
        hour_rows = {scale.row_of(hour * 60): hour for hour in range(24)}
        sel_col, cursor_row = days.index(self.tcal.state.day), self._cursor_row()
        current = now()
        now_col = days.index(current.date()) if current.date() in days else None
        now_min = current.hour * 60 + current.minute

        for row in range(top, bottom):
            y = header + row - top
            hour_start = row in hour_rows
            if row == cursor_row:
                minute = scale.minute_of(row)
                canvas.text(y, 0, AXIS, f"{minute // 60:02d}:{minute % 60:02d}", cursor_label)
            elif hour_start:
                canvas.text(y, 0, AXIS, f"{hour_rows[row]:02d}:00", label)
            for i, x in enumerate(xs[:-1]):
                canvas.fill(y, x, x + 1, divider, "│")
                if hour_start and scale.rows_per_hour >= 2:
                    canvas.fill(y, x + 1, xs[i + 1], line, "╌")
            if row == cursor_row:
                canvas.fill(y, xs[sel_col] + 1, xs[sel_col + 1], cursor)
            if now_col is not None and row == scale.row_of(now_min):
                # ● replaces the column's divider (never covered); events drawn later cover
                # the line, so it never hides their text. The hour label stays.
                red = Style(color=p.red, bold=True)
                for x in range(xs[now_col], xs[now_col + 1]):
                    canvas.chars[y][x] = "●" if x == xs[now_col] else "─"
                    canvas.styles[y][x] = canvas.styles[y][x] + red

        selected = self.selected
        for block in self._block_list():
            self._draw_block(canvas, xs, block, top, bottom, header, selected)
        self._draw_hidden(canvas, xs, top, bottom, header)

    def _draw_hidden(
        self, canvas: _Canvas, xs: list[int], top: int, bottom: int, header: int
    ) -> None:
        """``▲ N earlier`` / ``▼ N later`` per column for events scrolled out of view."""
        p = self.tcal.palette
        style = _style(p.foreground2, p.background2)
        for i in range(len(xs) - 1):
            blocks = [b for b in self._block_list() if b.day == i]
            x0, x1 = xs[i] + 1, xs[i + 1]
            for y, arrow, word, count in (
                (header, "▲", "earlier", sum(len(b.occs) for b in blocks if b.bottom <= top)),
                (
                    header + bottom - top - 1,
                    "▼",
                    "later",
                    sum(len(b.occs) for b in blocks if b.top >= bottom),
                ),
            ):
                if count:
                    label = next(
                        (
                            t
                            for t in (f" {arrow} {count} {word} ", f"{arrow}{count}", arrow)
                            if len(t) <= x1 - x0
                        ),
                        "",
                    )
                    canvas.text(y, x1 - len(label), x1, label, style)

    def _draw_block(
        self,
        canvas: _Canvas,
        xs: list[int],
        block: Block,
        top: int,
        bottom: int,
        header: int,
        selected_occ: Occurrence | None,
    ) -> None:
        first, last = max(block.top, top), min(block.bottom, bottom)
        if first >= last:
            return
        p, selected = self.tcal.palette, selected_occ in block.occs
        occ = selected_occ if selected and selected_occ is not None else block.occ
        color = self.tcal.calendar_color(occ.calendar_id)
        fg = _readable(color, p.background1, p.foreground3)
        style = _style(fg, color, bold=selected)
        x0, x1 = self._sub_columns(block, xs)
        pad = " " if x1 - x0 >= 6 or selected else ""
        title, span = _clean(occ.summary), f"{occ.start:%H:%M}–{occ.end:%H:%M}"
        if block.group:
            n = len(block.group)
            count = next((t for t in (f"{n} events", f"{n} ev") if len(pad + t) <= x1 - x0), f"{n}")
            texts = [count] + ([title, span] if selected else [])
        elif block.bottom - block.top == 1:
            texts = [f"{occ.start:%H:%M} {title}" if x1 - x0 >= 12 else title]
        else:
            texts = [title, span] + ([_clean(occ.event.location)] if occ.event.location else [])
        for row in range(first, last):
            y = header + row - top
            canvas.fill(y, x0, x1, style)
            index = row - first
            if index < len(texts):
                bold = _style(fg, color, bold=True) if index == 0 else None
                canvas.text(y, x0, x1, pad + texts[index], bold)
            if selected:  # Google-like: keep the colour, add a bright accent bar + bold text
                canvas.text(y, x0, x0 + 1, "▌", _style(p.foreground3, color, bold=True))


def _header(fmt: str, day: date) -> str:
    return day.strftime(fmt).replace("{day}", str(day.day))


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
