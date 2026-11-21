"""Schedule view (Google Calendar's "Schedule"): upcoming days as a list.

The list starts at the selected day; each day with events gets a date header
(today accented) followed by its events: time range or "All day", calendar
colour dot, title (multi-day events: "(Day 2/3)") and the location dimmed.
Empty days are skipped. Today's past events are dimmed and a now line sits
before its first event that hasn't started. More days are loaded (``CHUNK_DAYS`` at a time) when
the cursor or the scroll reaches either end.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from rich.style import Style
from rich.text import Text
from textual import events
from textual.app import RenderResult

from tcal.model import Occurrence
from tcal.ui.calgrid import by_day, occurrence_days
from tcal.ui.keys import EVENT_BINDINGS
from tcal.ui.messages import EventSelected
from tcal.ui.state import AppState, ViewMode
from tcal.ui.theme import legible
from tcal.ui.widgets.base import CalendarView, join_lines

CHUNK_DAYS = 28  # days loaded at a time
LOOKAHEAD_DAYS = 366  # one "load more/earlier" scans at most this far for events
SCROLL_LINES = 3  # mouse wheel step
TIME_WIDTH = 13  # "09:00 – 10:00"


def now() -> datetime:
    """The current local time (a seam for tests)."""
    return datetime.now().astimezone()


@dataclass(frozen=True)
class Row:
    """One list line: a day header, an event of ``day``, a blank or the now line."""

    day: date
    occ: Occurrence | None = None
    blank: bool = False
    now: bool = False

    @property
    def header(self) -> bool:
        return self.occ is None and not self.blank and not self.now


def build_rows(
    occurrences: list[Occurrence], start: date, end: date, current: datetime | None = None
) -> list[Row]:
    """Rows for the days [start, end): header + events per non-empty day, blank between;
    on ``current``'s day a now line before the first event starting after it."""
    rows: list[Row] = []
    for day, occs in sorted(by_day(occurrences).items()):
        if not start <= day < end:
            continue
        if rows:
            rows.append(Row(day, blank=True))
        rows.append(Row(day))
        events = [Row(day, occ) for occ in occs]
        if current is not None and day == current.date():
            later = (i for i, occ in enumerate(occs) if not occ.all_day and occ.start > current)
            events.insert(next(later, len(occs)), Row(day, now=True))
        rows.extend(events)
    return rows


def time_range(occ: Occurrence, day: date) -> str:
    """'09:00 – 10:00', 'All day', or the part of a timed event that falls on ``day``."""
    starts, ends = occ.start.date() == day, (occ.end - timedelta(microseconds=1)).date() == day
    if occ.all_day or not (starts or ends):
        return "All day"
    begin = f"{occ.start:%H:%M}" if starts else ""
    end = f"{occ.end:%H:%M}" if ends else ""
    return f"{begin} – {end}".strip() if begin != end else begin


def day_of(occ: Occurrence, day: date) -> str:
    """'Day 2/3' for a multi-day event on its second of three days, else ''."""
    days = occurrence_days(occ)
    return f"Day {days.index(day) + 1}/{len(days)}" if len(days) > 1 and day in days else ""


class ScheduleView(CalendarView):
    """The schedule list. j/k (and n/p) move between events, h/l jump to the
    previous/next day's first event, enter opens the selected event (``selected``),
    H/L (the app's prev/next period) re-start the list two weeks earlier/later.
    Moving or scrolling past the first/last loaded day loads more days."""

    BINDINGS = EVENT_BINDINGS

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self._start = self._end = date.min  # loaded days [start, end)
        self._anchor: date | None = None  # state.day the list was last set to / followed
        self._rows: list[Row] = []
        self._cursor: int | None = None  # index into _rows of the selected event
        self._top = 0  # first visible row

    # ----- data -----------------------------------------------------------

    def _load(self) -> None:
        self._rows = build_rows(
            self.tcal.occurrences(self._start, self._end), self._start, self._end, now()
        )

    def _load_more(self) -> bool:
        """Extend the list until it gains events (or ``LOOKAHEAD_DAYS`` are scanned)."""
        events_before = len(self._event_rows())
        limit = self._end + timedelta(days=LOOKAHEAD_DAYS)
        while self._end < limit:
            self._end += timedelta(days=CHUNK_DAYS)
            self._load()
            if len(self._event_rows()) > events_before:
                return True
        return False

    def _load_earlier(self) -> bool:
        """Prepend days until the list gains events (or ``LOOKAHEAD_DAYS`` are scanned);
        the cursor and scroll keep their rows."""
        events_before, rows_before = len(self._event_rows()), len(self._rows)
        limit = self._start - timedelta(days=LOOKAHEAD_DAYS)
        while self._start > limit:
            self._start -= timedelta(days=CHUNK_DAYS)
            self._load()
            if len(self._event_rows()) > events_before:
                added = len(self._rows) - rows_before
                self._top += added
                if self._cursor is not None:
                    self._cursor += added
                return True
        return False

    def _event_rows(self) -> list[int]:
        return [i for i, row in enumerate(self._rows) if row.occ is not None]

    @property
    def selected(self) -> Occurrence | None:
        return self._rows[self._cursor].occ if self._cursor is not None else None

    def on_mount(self) -> None:
        super().on_mount()
        self.set_interval(60, lambda: self.on_state(self.tcal.state))  # the now line

    def on_state(self, state: AppState) -> None:
        selected = self._rows[self._cursor] if self._cursor is not None else None
        restart, previous = state.day != self._anchor, self._anchor
        if restart:  # navigated from outside: restart the list there
            self._anchor, self._start, self._top, selected = state.day, state.day, 0, None
            self._end = state.day + timedelta(days=CHUNK_DAYS)
        self._load()
        while len(self._rows) < self.content_size.height and self._load_more():
            pass
        back = restart and previous is not None and state.day < previous
        if back and (not self._rows or self._rows[0].day >= (previous or state.day)):
            self._load_earlier()  # H onto empty days would show the same list again
            self._top = 0
        events_ = self._event_rows()
        # by row, not occurrence: a multi-day event has a row on each of its days
        same = [i for i in events_ if self._rows[i] == selected]
        if same:
            self._cursor = same[0]
        elif selected is None or not events_:
            self._cursor = events_[0] if events_ else None
        else:  # the selected event is gone (deleted, calendar hidden): its neighbour
            self._cursor = min(events_, key=lambda i: abs(i - (self._cursor or 0)))
        self._clamp()
        self.refresh()
        # the date (status bar, title) follows the first day shown, not an empty day before it
        if state.view is ViewMode.SCHEDULE and self._cursor is not None:
            first = self._rows[self._cursor].day
            if first != state.day and (restart or self._rows[0].day > state.day):
                self._anchor = first
                self.tcal.select_date(first)

    def on_resize(self) -> None:
        self.on_state(self.tcal.state)

    # ----- cursor & scrolling ---------------------------------------------

    def _select(self, index: int) -> None:
        self._cursor = index
        self._clamp()
        day = self._rows[index].day
        self._anchor = day  # following the cursor does not restart the list
        self.tcal.select_date(day)
        self.refresh()

    def _clamp(self) -> None:
        """Keep the cursor's row (and its day header, if it fits) visible."""
        height = max(1, self.content_size.height)
        if self._cursor is not None:
            header = self._cursor
            while header > 0 and not self._rows[header].header:
                header -= 1
            if self._cursor >= self._top + height:
                self._top = self._cursor - height + 1
            if header < self._top or self._cursor < self._top:
                self._top = header if self._cursor - header < height else self._cursor
        self._top = max(0, min(self._top, len(self._rows) - height))

    def _step(self, step: int) -> None:
        events_ = self._event_rows()
        if not events_:
            if self._load_more() if step > 0 else self._load_earlier():
                self._select(self._event_rows()[0 if step > 0 else -1])
            return
        pos = events_.index(self._cursor) if self._cursor in events_ else -1
        if pos + step >= len(events_):
            if not self._load_more():
                return
            events_ = self._event_rows()
        elif pos + step < 0:
            if not self._load_earlier():
                return
            events_ = self._event_rows()
            pos = events_.index(self._cursor) if self._cursor in events_ else len(events_)
        if 0 <= pos + step < len(events_):
            self._select(events_[pos + step])

    def _jump_day(self, step: int) -> None:
        """Select the first event of the previous/next listed day."""
        if self._cursor is None:
            return self._step(step)
        day = self._rows[self._cursor].day
        if step > 0:
            later = [i for i in self._day_firsts() if self._rows[i].day > day]
            if not later and self._load_more():
                later = [i for i in self._day_firsts() if self._rows[i].day > day]
            if later:
                self._select(later[0])
        else:
            earlier = [i for i in self._day_firsts() if self._rows[i].day < day]
            if not earlier and self._load_earlier():
                earlier = [i for i in self._day_firsts() if self._rows[i].day < day]
            self._select(earlier[-1] if earlier else self._day_firsts()[0])

    def _day_firsts(self) -> list[int]:
        """Row index of each listed day's first event."""
        firsts: dict[date, int] = {}
        for i in self._event_rows():
            firsts.setdefault(self._rows[i].day, i)
        return list(firsts.values())

    def _scroll(self, lines: int) -> None:
        height = self.content_size.height
        if lines > 0 and self._top + height + lines > len(self._rows):
            self._load_more()
        elif lines < 0 and self._top + lines < 0:
            self._load_earlier()
        self._top = max(0, min(self._top + lines, len(self._rows) - height))
        self.refresh()

    def select(self, occ: Occurrence) -> None:
        """Select ``occ`` on its first day (the list restarts there if it isn't loaded)."""
        day = occ.start.date()
        if not self._start <= day < self._end:
            self.tcal.select_date(day)
        rows = [i for i, row in enumerate(self._rows) if row.occ == occ]
        if rows:
            self._select(rows[0])

    def action_cursor_down(self) -> None:
        self._step(1)

    def action_cursor_up(self) -> None:
        self._step(-1)

    def action_cycle(self, step: int) -> None:
        self._step(step)

    def action_cursor_right(self) -> None:
        self._jump_day(1)

    def action_cursor_left(self) -> None:
        self._jump_day(-1)

    def action_open(self) -> None:
        if occ := self.selected:
            self.post_message(EventSelected(occ))

    def on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        event.stop()
        self._scroll(SCROLL_LINES)

    def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        event.stop()
        self._scroll(-SCROLL_LINES)

    def on_click(self, event: events.Click) -> None:
        offset = event.get_content_offset(self)
        if offset is None:
            return
        index = self._top + offset.y
        if 0 <= index < len(self._rows) and self._rows[index].occ is not None:
            self._select(index)
            self.action_open()

    # ----- drawing --------------------------------------------------------

    def render(self) -> RenderResult:
        visible = self._rows[self._top : self._top + self.content_size.height]
        if not self._rows:
            p = self.tcal.palette
            return Text(" No upcoming events", style=Style(color=p.foreground1))
        if len(visible) > 1 and visible[-1].header:  # no day header without its events
            visible = visible[:-1]
        lines = [self._line(row, self._top + i) for i, row in enumerate(visible)]
        return join_lines(lines)

    def _line(self, row: Row, index: int) -> Text:
        p, width = self.tcal.palette, self.content_size.width
        if row.blank:
            return Text()
        if row.now:
            return Text(f"   {now():%H:%M} ●" + "─" * width, style=Style(color=p.red))
        if row.occ is None:
            return self._header(row.day)
        occ, selected = row.occ, index == self._cursor
        past = occ.end <= now()
        text = Text(style=self.cursor_style() if selected else Style())
        text.append(
            f"   {time_range(occ, row.day):<{TIME_WIDTH}}  ",
            style=Style(color=p.foreground1 if past else p.foreground2),
        )
        color = legible(self.tcal.calendar_color(occ.calendar_id), p)
        text.append("● ", style=Style(color=color, dim=past))
        title = Style(color=p.foreground1 if past else p.foreground3, bold=selected)
        text.append(occ.summary or "(no title)", style=title)
        if position := day_of(occ, row.day):
            text.append(f" ({position})", style=Style(color=p.foreground2))
        if occ.event.location:
            text.append(f"  {occ.event.location}", style=Style(color=p.foreground1, dim=True))
        text.truncate(width, pad=True)
        return text

    def _header(self, day: date) -> Text:
        p = self.tcal.palette
        label = f"{day:%a %-d %b}" + (f" {day:%Y}" if day.year != date.today().year else "")
        if day == date.today():
            return Text.assemble(
                (f" {label} · Today ", Style(color=p.background1, bgcolor=p.primary, bold=True))
            )
        return Text(f" {label}", style=Style(color=p.secondary, bold=True))
