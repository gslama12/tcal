"""Day and Week views: a Google-Calendar-like time grid.

Layout (content area of the widget)::

    axis │ Mon 16 │ Tue 17 │ ...      header: weekday + date, today highlighted
         │ ▆▆ Conference ▆▆▆ │       all-day strip: all-day / multi-day bars
    ─────┼────────┼────────┼──       separator
    09:00│ Standup│        │         time grid: rows_per_hour rows per hour,
         │        │ ██████ │         events as colored blocks, now-line, cursor

The geometry (``TimeScale``, ``layout_blocks``, ``layout_bars``, ...) lives in
``tcal.ui.timelayout`` and the drawing in ``tcal.ui.timepaint``; ``TimeGrid`` keeps
the cursor / scroll / zoom / selection and hands a ``GridFrame`` to ``paint`` (cached
until the next redraw).
Cursor and scroll position are stored in minutes so they survive zooming.
"""

from dataclasses import replace
from datetime import date, datetime, time, timedelta
from fractions import Fraction

from textual import events
from textual.strip import Strip

from tcal.model import Occurrence
from tcal.ui.flash import Flash, Target, overlay, targets
from tcal.ui.keys import EVENT_BINDINGS, binding
from tcal.ui.messages import EventSelected, NewEventRequested
from tcal.ui.state import AppState, ViewMode
from tcal.ui.timelayout import (
    ZOOMS,
    Bar,
    Block,
    TimeScale,
    fit_scale,
    is_bar,
    layout_bars,
    layout_blocks,
    sub_columns,
)
from tcal.ui.timepaint import AXIS, GridFrame, markers, paint
from tcal.ui.widgets.base import CalendarView

MAX_LANES = 3  # all-day strip rows shown at most
SCROLL_ROWS = 2  # rows per mouse-wheel step
SLOT_MINUTES = 15  # shortest cursor step (rows of 7.5 min are stepped two at a time)
HEADER_FORMATS = ("%A, {day} %B", "%A {day}", "%a {day}", "{day}")  # widest first


def now() -> datetime:
    """Current local time (patched in tests)."""
    return datetime.now().astimezone()


class TimeGrid(CalendarView):
    """Shared core of DayView / WeekView (``days()`` picks the columns).

    Keys: j/k move the slot cursor, h/l the day, n/p cycle events (from the cursor),
    enter opens the selected event (``EventSelected``) or requests a new one on an
    empty slot (``NewEventRequested``), +/- zoom. Mouse: click selects a slot / opens
    an event, double-click on an empty slot requests a new one, the wheel scrolls.
    """

    BINDINGS = [*EVENT_BINDINGS, binding("new_event", "New event"), binding("flash", "Flash")]
    header_formats: tuple[str, ...] = HEADER_FORMATS

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self._zoom: int | None = None  # rows per hour; None = fit day_start..day_end
        self._cursor_min = 0  # cursor slot, minutes after midnight
        self._top_min = 0  # first visible grid row, as minutes
        self._picked: Occurrence | None = None  # chosen by n/p or click
        self._data: tuple[list[date], list[Occurrence], list[Bar]] | None = None
        self._blocks: tuple[TimeScale, int, list[Block]] | None = None
        self._lines: list[Strip] | None = None
        self._flash: Flash | None = None  # labels up (f) until a jump or cancel

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
        self._flash = None  # the labels would point at what has moved
        self._data = None
        self._blocks = None
        if self._picked is not None:  # the reloaded copy (or None if it is gone)
            key = self._picked.key
            self._picked = next((o for o in self._occurrences() if o.key == key), None)
        self._redraw()

    def on_show(self) -> None:
        self._show_cursor()

    def on_resize(self) -> None:
        self._flash = None
        self._show_cursor()

    def on_blur(self) -> None:
        self._end_flash()

    def _show_cursor(self) -> None:
        """Scroll the cursor slot (now, or the selected event) into view: the grid has
        no size until its view is shown, so on mount it can't be."""
        self._ensure_visible()
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
        scale, width = self.scale, self._column_width()
        if self._blocks is None or self._blocks[:2] != (scale, width):
            days, occs, _ = self._load()
            self._blocks = scale, width, layout_blocks(occs, days, scale, width)
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

    def _slot_rows(self) -> int:
        """Rows per cursor step: whole rows of at least ``SLOT_MINUTES``."""
        scale = self.scale
        return max(1, int(SLOT_MINUTES // scale.per_row)) if scale.even else 1

    def _snap(self, row: int) -> int:
        """The cursor row (a slot start) holding ``row``."""
        return row - row % self._slot_rows()

    def _cursor_row(self) -> int:
        return self._snap(self.scale.row_of(self._cursor_min))

    def _cursor_rows(self) -> range:
        """The rows the cursor slot covers."""
        row = self._cursor_row()
        return range(row, min(row + self._slot_rows(), self.scale.total_rows))

    def _columns(self) -> list[int]:
        """x of each day column's divider, plus the right edge."""
        n, avail = len(self._load()[0]), max(0, self.size.width - AXIS)
        return [AXIS + avail * i // n for i in range(n + 1)]

    def _column_width(self) -> int:
        """Width of the narrowest day column (inside its dividers)."""
        xs = self._columns()
        return min(b - a - 1 for a, b in zip(xs, xs[1:], strict=False))

    # ----- cursor & selection --------------------------------------------

    @property
    def cursor_time(self) -> datetime:
        """Start of the cursor slot (local, aware)."""
        minute = self.scale.minute_of(self._cursor_row())
        return datetime.combine(self.tcal.state.day, time(minute // 60, minute % 60), now().tzinfo)

    @property
    def selected(self) -> Occurrence | None:
        """The picked event if still under the cursor, else the topmost event at the
        cursor slot (the deepest in the cascade; of side-by-side ones the left)."""
        days = self._load()[0]
        day, rows = days.index(self.tcal.state.day), self._cursor_rows()
        at_cursor = sorted(
            (
                b
                for b in self._block_list()
                if b.day == day and b.top < rows.stop and rows.start < b.bottom
            ),
            key=lambda b: (-b.depth, b.col, b.top),
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
        scale, rows, top, height = (
            self.scale,
            self._cursor_rows(),
            self._top_row(),
            self._grid_height(),
        )
        if rows.start < top:
            self._top_min = scale.minute_of(rows.start)
        elif rows.stop > top + height:
            self._top_min = scale.minute_of(min(rows.start, rows.stop - height))

    def _scroll(self, rows: int) -> None:
        top = max(0, min(self._top_row() + rows, self.scale.total_rows - self._grid_height()))
        self._top_min = self.scale.minute_of(top)
        self._redraw()

    def select(self, occ: Occurrence) -> None:
        """Select ``occ`` (it must be in view), as n/p would: move to its day and
        (timed events) its start slot."""
        days = self._load()[0]
        day = min(max(occ.start.date(), days[0]), days[-1])
        self._picked = occ
        if not is_bar(occ) and occ.start.date() == day:
            self._cursor_min = occ.start.hour * 60 + occ.start.minute
        self._ensure_visible()
        if day != self.tcal.state.day:
            self.tcal.select_date(day)  # redraws via on_state, keeps the pick
        self._redraw()

    def _stop_key(self, occ: Occurrence) -> tuple[date, bool, datetime]:
        """n/p order: by day, all-day bars first, then by start."""
        return max(occ.start.date(), self._load()[0][0]), not is_bar(occ), occ.start

    def action_cycle(self, step: int) -> None:
        """Select the next (``step`` 1) / previous (-1) event: from the selected one, else
        from the cursor slot; wraps at the ends."""
        stops = sorted(self._occurrences(), key=self._stop_key)
        if not stops:
            return
        current = self.selected
        if current in stops:
            index = stops.index(current) + step
        else:
            here = (self.tcal.state.day, True, self.cursor_time)
            keys = [self._stop_key(occ) for occ in stops]
            if step > 0:
                index = next((i for i, k in enumerate(keys) if k > here), 0)
            else:
                index = next((i for i in reversed(range(len(keys))) if keys[i] < here), -1)
        self.select(stops[index % len(stops)])

    # ----- actions --------------------------------------------------------

    def action_cursor_down(self) -> None:
        row = min(self._cursor_row() + self._slot_rows(), self._snap(self.scale.total_rows - 1))
        self._move_cursor(self.scale.minute_of(row))

    def action_cursor_up(self) -> None:
        self._move_cursor(self.scale.minute_of(max(self._cursor_row() - self._slot_rows(), 0)))

    def action_cursor_left(self) -> None:
        self._select_day(self.tcal.state.day - timedelta(days=1))

    def action_cursor_right(self) -> None:
        self._select_day(self.tcal.state.day + timedelta(days=1))

    def _select_day(self, day: date) -> None:
        self._picked = None
        self.tcal.select_date(day)

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
            # Keep the shown time if it is a quarter hour; a level that can't show it
            # (:20 at 3 rows/hour) doesn't move it, so zooming back returns to it.
            shown = self.scale.minute_of(self._cursor_row())
            if shown % SLOT_MINUTES == 0:
                self._cursor_min = shown
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
        marker = next(
            (
                m
                for m in markers(self._frame(), self.size.height)
                if m.day == column and m.y == y and m.x0 <= x < m.x1
            ),
            None,
        )
        if marker is not None:  # scroll to (and select) the first hidden event
            self.select(marker.hidden[0])
            return
        header = self._header_height()
        if y == 0:
            self._select_day(days[column])
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
            block = next(  # the topmost: blocks are listed bottom first
                (
                    b
                    for b in reversed(self._block_list())
                    if b.day == column
                    and b.top <= row < b.bottom
                    and sub_columns(b, xs)[0] <= x < sub_columns(b, xs)[1]
                ),
                None,
            )
            self._cursor_min = self.scale.minute_of(self._snap(row))
            self._picked = None
            if days[column] != self.tcal.state.day:
                self.tcal.select_date(days[column])
            if block is not None:
                self._open(block.occ)
            elif event.chain >= 2:
                self.post_message(NewEventRequested(self.cursor_time))
            self._redraw()

    # ----- flash jump ---------------------------------------------------

    @property
    def flashing(self) -> bool:
        return self._flash is not None

    def action_flash(self) -> None:
        """Label the events and slots on screen; typing a label jumps there."""
        found = targets(self._frame(), self.size.height)
        if found:
            self._flash = Flash.of(found)
            self._redraw()

    def on_key(self, event: events.Key) -> None:
        if self._flash is None:
            return
        event.stop()
        event.prevent_default()
        target = self._flash.press(event.key)
        if self._flash.done:
            self._end_flash()
        else:
            self._redraw()
        if target is not None:
            self._jump(target)

    def _end_flash(self) -> None:
        if self._flash is not None:
            self._flash = None
            self._redraw()

    def _jump(self, target: Target) -> None:
        if target.occ is not None:
            self.select(target.occ)
            return
        self._move_cursor(target.minute)
        day = self._load()[0][target.day]
        if day != self.tcal.state.day:
            self.tcal.select_date(day)

    def _open(self, occ: Occurrence) -> None:
        self.select(occ)
        self.post_message(EventSelected(occ))

    # ----- rendering ------------------------------------------------------

    def render_line(self, y: int) -> Strip:
        if self._lines is None or len(self._lines) != self.size.height:
            self._lines = paint(self._frame(), *self.size)
            if self._flash is not None:
                self._lines = overlay(self._lines, self._flash, self.tcal.palette)
        return self._lines[y] if y < len(self._lines) else Strip.blank(self.size.width)

    def _frame(self) -> GridFrame:
        days, _, bars = self._load()
        return GridFrame(
            days=days,
            xs=self._columns(),
            scale=self.scale,
            top=self._top_row(),
            strip_rows=self._strip_rows(),
            bars=bars,
            blocks=self._block_list(),
            day=self.tcal.state.day,
            cursor_rows=self._cursor_rows(),
            selected=self.selected,
            now=now(),
            header_formats=self.header_formats,
            palette=self.tcal.palette,
            color=self.tcal.calendar_color,
            marked=self.tcal.state.marked,
        )


class DayView(TimeGrid):
    """Time grid for ``state.day`` (short header: the toolbar shows the full date)."""

    header_formats = ("%a {day}", "{day}")

    def days(self) -> list[date]:
        return [self.tcal.state.day]


class WeekView(TimeGrid):
    """Time grid for the week of ``state.day`` (starting at config ``week_start``)."""

    def days(self) -> list[date]:
        start, _ = replace(self.tcal.state, view=ViewMode.WEEK).period()
        return [start + timedelta(days=i) for i in range(7)]
