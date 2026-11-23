"""The Week view: a Google-Calendar-like time grid.

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

Two modes (``state.grid``): in event mode (default) the cursor keys move between the
events (up/down within the day, left/right to the nearest one on the next day); in
grid mode (``grid_mode`` key, escape leaves) they move a slot cursor by config
``grid_step`` minutes (default an hour).
In either, resize mode (``state.resize``, the app's ``resize_mode`` key, escape leaves)
makes up/down move the selected event's start or end.
"""

from dataclasses import replace
from datetime import date, datetime, time, timedelta
from fractions import Fraction

from textual import events
from textual.binding import Binding
from textual.strip import Strip

from tcal.model import Occurrence
from tcal.ui.flash import Flash, Target, overlay, targets
from tcal.ui.keys import EVENT_BINDINGS, binding
from tcal.ui.messages import EventSelected, NewEventRequested
from tcal.ui.state import AppState, Edge, ViewMode
from tcal.ui.timelayout import (
    MINUTES,
    ZOOMS,
    Bar,
    Block,
    TimeScale,
    fit_scale,
    is_bar,
    layout_bars,
    layout_blocks,
    minute_in,
    sub_columns,
)
from tcal.ui.timepaint import AXIS, GridFrame, markers, paint
from tcal.ui.widgets.base import CalendarView

MAX_LANES = 3  # all-day strip rows shown at most
SCROLL_ROWS = 2  # rows per mouse-wheel step
SLOT_MINUTES = 15  # event mode: the slot a click or the remembered time falls in
# The grid's own actions that still work in resize mode.
RESIZE_ACTIONS = {"cursor_up", "cursor_down", "cancel", "zoom_in", "zoom_out"}


def now() -> datetime:
    """Current local time (patched in tests)."""
    return datetime.now().astimezone()


class TimeGrid(CalendarView):
    """The week of ``state.day`` (starting at config ``week_start``), a column per day.

    Keys: in event mode j/k select the previous/next event of the day, h/l the
    nearest event on the previous/next day; in grid mode (v) j/k move the slot cursor,
    h/l the day. Enter opens the selected event (``EventSelected``) or requests a new
    one (``NewEventRequested``), +/- zoom.
    Mouse: click selects a slot / opens an event, double-click on an empty slot
    requests a new one, the wheel scrolls.
    """

    BINDINGS = [
        *(b for b in EVENT_BINDINGS if not (isinstance(b, Binding) and b.id == "cancel")),
        binding("cancel", "Leave resize / grid mode, clear marks"),
        binding("grid_mode", "Grid mode"),
        binding("new_event", "New event"),
        binding("quick_add", "New event", action="new_event"),
        binding("flash", "Flash"),
    ]

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self._zoom: int | None = None  # rows per hour; None = fit day_start..day_end
        self._cursor_min = 0  # the cursor time (its slot holds it), minutes after midnight
        self._top_min = 0  # first visible grid row, as minutes
        self._picked: Occurrence | None = None  # chosen by a key, flash or click
        self._data: tuple[list[date], list[Occurrence], list[Bar]] | None = None
        self._blocks: tuple[TimeScale, int, list[Block]] | None = None
        self._lines: list[Strip] | None = None
        self._edge: Edge | None = None  # resize mode: the edge it moved at the last redraw
        self._flash: Flash | None = None  # labels up (f) until a jump or cancel

    def days(self) -> list[date]:
        """The dates of the columns, for the current state."""
        start, _ = replace(self.tcal.state, view=ViewMode.WEEK).period()
        return [start + timedelta(days=i) for i in range(7)]

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
        if state.resize is not None and state.view.value == self.id:
            self.call_later(self._check_resize)  # once an edit has selected its event again
            if self._edge != state.resize.edge:
                self._ensure_visible()
        self._edge = state.resize.edge if state.resize is not None else None
        self._redraw()

    def on_show(self) -> None:
        self._show_cursor()

    def on_resize(self) -> None:
        self._flash = None
        self._show_cursor()

    def on_blur(self) -> None:
        self._end_flash()
        if self.app.app_focus:  # not just the terminal losing focus
            self.tcal.set_resize(None)

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

    @property
    def _step(self) -> int:
        """Minutes per cursor slot."""
        return self.tcal.config.view.grid_step if self.grid_mode else SLOT_MINUTES

    @property
    def _row_slots(self) -> bool:
        """Rows are longer than the step: the slots are the rows."""
        return self.scale.per_row > self._step

    def _slot_of(self, minute: int) -> int:
        """Start minute of the slot holding ``minute``."""
        if self._row_slots:
            return self.scale.minute_of(self.scale.row_of(minute))
        return minute - minute % self._step

    def _slot_at(self, row: int) -> int:
        """Start minute of the slot shown on ``row``."""
        scale = self.scale
        if self._row_slots:
            return scale.minute_of(row)
        starts = range(0, MINUTES, self._step)
        return max((m for m in starts if scale.row_of(m) <= row), default=0)

    def _grid_slots(self) -> list[int]:
        """Start minutes of grid mode's slots, whatever the mode."""
        scale, step = self.scale, self.tcal.config.view.grid_step
        if scale.per_row > step:
            return [scale.minute_of(row) for row in range(scale.total_rows)]
        return list(range(0, MINUTES, step))

    @property
    def _cursor_slot(self) -> int:
        return self._slot_of(self._cursor_min)

    def _cursor_row(self) -> int:
        return max(0, self.scale.row_of(self._cursor_slot))

    def _cursor_rows(self) -> range:
        """The rows the cursor slot covers."""
        scale, row, end = self.scale, self._cursor_row(), self._cursor_slot + self._step
        if self._row_slots:
            return range(row, row + 1)
        return range(row, scale.row_of(end))

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
        minute = self._cursor_slot
        return datetime.combine(self.tcal.state.day, time(minute // 60, minute % 60), now().tzinfo)

    @property
    def grid_mode(self) -> bool:
        return self.tcal.state.grid

    @property
    def selected(self) -> Occurrence | None:
        """Event mode: the picked event while it is on the selected day. Grid mode: the
        picked event if still under the cursor (or starting in its slot, though drawn
        on the next row), else the topmost event at the cursor slot (the deepest in the
        cascade; of side-by-side ones the left)."""
        if not self.grid_mode:
            return self._picked if self._picked in self._day_events() else None
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
            or (
                picked in self._day_events()
                and self._slot_of(self._span(picked)[0]) == self._cursor_slot
            )
        ):
            return picked
        return at_cursor[0].occ if at_cursor else None

    def _move_cursor(self, minute: int) -> None:
        self._cursor_min = minute
        self._picked = None
        self._ensure_visible()
        self._redraw()

    def _ensure_visible(self) -> None:
        """Scroll the cursor slot (event mode: the selected event's rows) into view."""
        scale, rows, top, height = (
            self.scale,
            self._focus_rows(),
            self._top_row(),
            self._grid_height(),
        )
        if rows.start < top:
            self._top_min = scale.minute_of(rows.start)
        elif rows.stop > top + height:
            self._top_min = scale.minute_of(min(rows.start, rows.stop - height))

    def _focus_rows(self) -> range:
        """The rows to keep on screen: the cursor slot, or the selected event's block
        (resize mode: the row of the edge it moves)."""
        resize = self.tcal.state.resize
        occ = self.selected if resize is not None or not self.grid_mode else None
        if occ is not None:
            day = self._load()[0].index(self.tcal.state.day)
            block = next((b for b in self._block_list() if b.day == day and occ in b.occs), None)
            if block is not None and resize is not None:
                row = block.top if resize.edge == "start" else block.bottom - 1
                return range(row, row + 1)
            if block is not None:
                return range(block.top, block.bottom)
        return self._cursor_rows()

    def _scroll(self, rows: int) -> None:
        top = max(0, min(self._top_row() + rows, self.scale.total_rows - self._grid_height()))
        self._top_min = self.scale.minute_of(top)
        self._redraw()

    def select(self, occ: Occurrence) -> None:
        """Select ``occ`` (it must be in view): move to its day and (timed events) its
        start slot."""
        days = self._load()[0]
        day = min(max(occ.start.date(), days[0]), days[-1])
        self._picked = occ
        if not is_bar(occ) and occ.start.date() == day:
            self._cursor_min = occ.start.hour * 60 + occ.start.minute
        if day != self.tcal.state.day:
            self.tcal.select_date(day)  # redraws via on_state, keeps the pick
        self._ensure_visible()
        self._redraw()

    def _day_events(self) -> list[Occurrence]:
        """The events of the selected day in event-mode order: all-day bars first,
        then the timed ones by start."""
        days, day = self._load()[0], self.tcal.state.day
        index = days.index(day)
        bars = [bar.occ for bar in self._bars() if bar.first <= index < bar.last]
        timed = [o for b in self._block_list() if b.day == index for o in b.occs]
        return sorted(bars, key=lambda o: o.start) + sorted(timed, key=lambda o: (o.start, o.end))

    def _span(self, occ: Occurrence) -> tuple[int, int]:
        """``occ``'s [start, end) minutes on the selected day."""
        day = self.tcal.state.day
        return minute_in(day, occ.start), minute_in(day, occ.end)

    def _reference(self) -> int | None:
        """Where h/l look for the nearest event: the selected event's start minute, None
        for an all-day one; with nothing selected the cursor minute."""
        occ = self.selected
        if occ is None:
            return self._cursor_min
        return None if is_bar(occ) else self._span(occ)[0]

    def _nearest(self, minute: int | None) -> Occurrence | None:
        """The selected day's event nearest ``minute`` (the earlier on a tie); for
        None (all-day) its first all-day event. Falls back to the other kind."""
        stops = self._day_events()
        bars = [o for o in stops if is_bar(o)]
        timed = [o for o in stops if not is_bar(o)]
        if minute is None or not timed:
            return next(iter(bars or timed), None)

        def distance(occ: Occurrence) -> int:
            start, end = self._span(occ)
            return max(start - minute, minute - (end - 1), 0)

        return min(timed, key=distance)

    def _step_event(self, step: int) -> None:
        """Select the next (``step`` 1) / previous (-1) event of the day; with none
        selected the first / last. Stops at the ends."""
        stops = self._day_events()
        if not stops:
            return
        current = self.selected
        if current is None:
            self.select(stops[0 if step > 0 else -1])
        elif 0 <= (index := stops.index(current) + step) < len(stops):
            self.select(stops[index])

    def _step_day(self, step: int) -> None:
        """Event mode: go to the previous/next day and select the event nearest the
        current one there (none on an empty day)."""
        minute = self._reference()
        self._select_day(self.tcal.state.day + timedelta(days=step))
        if (occ := self._nearest(minute)) is not None:
            self.select(occ)
        elif minute is not None:
            self._cursor_min = minute

    # ----- resize mode ----------------------------------------------------

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if self.tcal.state.resize is not None:
            return action in RESIZE_ACTIONS
        return super().check_action(action, parameters)

    def _resize(self, step: int) -> bool:
        """Resize mode: move the active edge (False: not in the mode)."""
        resize, occ = self.tcal.state.resize, self.selected
        if resize is None:
            return False
        if occ is not None:
            self.tcal.editor.resize(occ, resize.edge, step)
        return True

    def _check_resize(self) -> None:
        """Leave resize mode once its event is not the selected one any more (an undo of
        another change, a sync, another day)."""
        resize, occ = self.tcal.state.resize, self.selected
        if resize is not None and (occ is None or occ.event.uid != resize.uid):
            self.tcal.set_resize(None)

    # ----- actions --------------------------------------------------------

    def action_cursor_down(self) -> None:
        if self._resize(1):
            return
        if not self.grid_mode:
            self._step_event(1)
            return
        row = min(self._cursor_rows().stop, self.scale.total_rows - 1)
        self._move_cursor(self._slot_at(row))

    def action_cursor_up(self) -> None:
        if self._resize(-1):
            return
        if not self.grid_mode:
            self._step_event(-1)
            return
        self._move_cursor(self._slot_at(max(self._cursor_row() - 1, 0)))

    def action_cursor_left(self) -> None:
        if self.grid_mode:
            self._select_day(self.tcal.state.day - timedelta(days=1))
        else:
            self._step_day(-1)

    def action_cursor_right(self) -> None:
        if self.grid_mode:
            self._select_day(self.tcal.state.day + timedelta(days=1))
        else:
            self._step_day(1)

    def _select_day(self, day: date) -> None:
        self._picked = None
        self.tcal.select_date(day)

    def action_open(self) -> None:
        if occ := self.selected:
            self.post_message(EventSelected(occ))
        else:
            self.action_new_event()

    def action_new_event(self) -> None:
        """Grid mode: at the cursor slot. Event mode: at the selected timed event's end,
        else at the next full hour (as the app's default)."""
        occ = self.selected
        if self.grid_mode:
            start = self.cursor_time
        elif occ is not None and not is_bar(occ):
            start = occ.end
        else:
            hour = min(now().hour + 1, 23)
            start = datetime.combine(self.tcal.state.day, time(hour), now().tzinfo)
        self.post_message(NewEventRequested(start))

    @property
    def paste_at(self) -> date | datetime:
        """Where a paste lands: the cursor slot (grid mode), the selected timed event's
        start (event mode), else the selected day."""
        occ = self.selected
        if self.grid_mode:
            return self.cursor_time
        return occ.start if occ is not None and not is_bar(occ) else self.tcal.state.day

    def action_grid_mode(self) -> None:
        """Toggle grid mode; leaving it selects the event under / nearest the cursor."""
        if not self.grid_mode:
            self.tcal.set_grid_mode(True)
            self._show_cursor()
            return
        occ = self.selected or self._nearest(self._cursor_slot)
        self._picked = occ
        self.tcal.set_grid_mode(False)
        if occ is not None:
            self.select(occ)

    def action_cancel(self) -> None:
        """Escape: leave resize mode, else grid mode, else clear the marks."""
        if self.tcal.state.resize is not None:
            self.tcal.set_resize(None)
        elif self.grid_mode:
            self.action_grid_mode()
        else:
            self.tcal.clear_marks()

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
            # Keep the slot shown (grid mode) if it is a quarter hour; a level that can't show it
            # (:20 at 3 rows/hour) doesn't move it, so zooming back returns to it.
            shown = self._cursor_slot
            if self.grid_mode and shown % SLOT_MINUTES == 0:
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
        self.tcal.set_resize(None)
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
            self._cursor_min = self._slot_at(row)
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
        found = targets(self._frame(), self.size.height, self._grid_slots())
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
        """An event label selects the event; a slot label goes to grid mode, to the slot."""
        if target.occ is not None:
            self.select(target.occ)
            return
        self.tcal.set_grid_mode(True)
        self._move_cursor(self._slot_of(target.minute))
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

    def _event_rows(self) -> range:
        """Event mode has no slot cursor: an empty range at the selected event (or
        the cursor minute), where flash labels start counting from."""
        row = self._focus_rows().start
        return range(row, row)

    def _frame(self) -> GridFrame:
        days, _, bars = self._load()
        resize = self.tcal.state.resize
        return GridFrame(
            days=days,
            xs=self._columns(),
            scale=self.scale,
            top=self._top_row(),
            strip_rows=self._strip_rows(),
            bars=bars,
            blocks=self._block_list(),
            day=self.tcal.state.day,
            cursor_rows=self._cursor_rows() if self.grid_mode else self._event_rows(),
            cursor_minute=self._cursor_slot,
            selected=self.selected,
            now=now(),
            palette=self.tcal.palette,
            color=self.tcal.calendar_color,
            marked=self.tcal.state.marked,
            edge=resize.edge if resize is not None else None,
        )
