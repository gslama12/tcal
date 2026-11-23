"""Drawing one frame of the Week time grid (see ``tcal.ui.widgets.timegrid``).

``paint(frame, width, height)`` is pure: the widget gathers what is shown into a
``GridFrame`` (geometry from ``tcal.ui.timelayout``, cursor, selection, current time)
and gets the lines back.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from rich.cells import cell_len
from rich.style import Style
from textual.strip import Strip

from tcal.model import Occurrence
from tcal.ui.canvas import Canvas, style
from tcal.ui.state import Edge
from tcal.ui.theme import EDGE, Palette, blend, event_colors
from tcal.ui.timelayout import Bar, Block, TimeScale, sub_columns
from tcal.ui.widgets.base import fit

AXIS = 6  # width of the time axis: "HH:MM "
HOUR_ALPHA = 0.1  # hour lines through an event: its text colour over its fill, faint
NOW_ALPHA = 0.7  # the now line through an event
CURSOR_ALPHA = 0.45  # the cursor slot: the primary colour over the background
HOUR_LINE = "▔"  # on the top edge of the hour's first row: where its events start
LINE_ALPHA = 0.6  # the grid's hour lines: the divider colour over the background

HEADER_FORMATS = ("%A, {day} %B", "%A {day}", "%a {day}", "{day}")  # widest first


@dataclass(frozen=True)
class GridFrame:
    """Everything one frame shows."""

    days: list[date]  # the columns
    xs: list[int]  # x of each column's divider, plus the right edge
    scale: TimeScale
    top: int  # first visible grid row
    strip_rows: int  # all-day strip rows shown
    bars: list[Bar]
    blocks: list[Block]
    day: date  # the selected day (cursor column)
    cursor_rows: range  # the cursor slot; empty: none is drawn
    cursor_minute: int  # the slot's start, its label
    selected: Occurrence | None
    now: datetime
    palette: Palette
    color: Callable[[str], str]  # calendar id -> colour
    marked: frozenset[tuple[str, datetime]] = frozenset()  # ``Occurrence.key``s with a ✓
    edge: Edge | None = None  # resize mode: the edge of the selected event it moves

    @property
    def header(self) -> int:
        """Rows above the grid: day header + strip + separator."""
        return 2 + self.strip_rows

    def now_row(self) -> int:
        return self.scale.row_of(self.now.hour * 60 + self.now.minute)

    def bottom(self, height: int) -> int:
        """The first grid row below the visible ones (``height``: the widget's)."""
        return min(self.scale.total_rows, self.top + height - self.header)


@dataclass(frozen=True)
class Marker:
    """``▲ N earlier`` / ``▼ N later`` for day column ``day``, on widget line ``y``
    (the column's edge row, or its header line), x [x0, x1)."""

    day: int
    y: int
    x0: int
    x1: int
    label: str
    hidden: tuple[Occurrence, ...]  # the events it stands for, by start


def paint(frame: GridFrame, width: int, height: int) -> list[Strip]:
    if width <= AXIS or height <= frame.header:
        return [Strip.blank(width)] * height
    p = frame.palette
    canvas = Canvas(width, height, style(p.foreground1, p.background1))
    _header(canvas, frame)
    _strip(canvas, frame)
    _grid(canvas, frame, frame.bottom(height))
    _edge(canvas, frame, frame.bottom(height))
    _marks(canvas, frame, frame.bottom(height))
    return canvas.strips()


MARK = "✓"


def _marks(canvas: Canvas, f: GridFrame, bottom: int) -> None:
    """A ✓ badge in the top-right cell of each marked (tab) bar and block."""
    if not f.marked:
        return
    badge = style(f.palette.background1, f.palette.primary, bold=True)
    for bar in f.bars:
        if bar.lane < f.strip_rows and bar.occ.key in f.marked:
            x = f.xs[bar.last] - 1
            canvas.text(1 + bar.lane, x, x + 1, MARK, badge)
    for block in f.blocks:
        first = max(block.top, f.top)
        if first < min(block.bottom, bottom) and any(o.key in f.marked for o in block.occs):
            x = sub_columns(block, f.xs)[1] - 1
            canvas.text(f.header + first - f.top, x, x + 1, MARK, badge)


def _edge(canvas: Canvas, f: GridFrame, bottom: int) -> None:
    """Resize mode: the selected block's first / last row in bright, with an arrow at its
    right end (cells another event covers stay as they are)."""
    occ = f.selected
    if f.edge is None or occ is None:
        return
    p = f.palette
    fill = style(p.foreground3, event_colors(f.color(occ.calendar_id), p, True)[0]).bgcolor
    bright = style(p.background1, p.foreground3, bold=True)
    for block in f.blocks:
        if occ != block.occ or block.group:
            continue
        day = f.days[block.day]
        here = occ.start.date() == day if f.edge == "start" else occ.end <= _midnight(f, day)
        row = block.top if f.edge == "start" else block.bottom - 1
        if not here or not f.top <= row < bottom:
            continue
        y, (x0, x1) = f.header + row - f.top, sub_columns(block, f.xs)
        for x in range(x0, x1):
            if canvas.styles[y][x].bgcolor == fill:
                canvas.styles[y][x] = bright
                if canvas.chars[y][x] in ("╌", "─"):
                    canvas.chars[y][x] = " "
        if canvas.styles[y][x1 - 1] == bright and canvas.chars[y][x1 - 1] == " ":
            canvas.text(y, x1 - 1, x1, "▲" if f.edge == "start" else "▼", bright)


def _midnight(f: GridFrame, day: date) -> datetime:
    """The end of ``day``."""
    return datetime.combine(day + timedelta(days=1), time(), f.now.tzinfo)


def _header(canvas: Canvas, f: GridFrame) -> None:
    p = f.palette
    for i, day in enumerate(f.days):
        x0, label = _header_label(f, i)
        if day == f.now.date():
            st = style(p.background1, p.primary, bold=True)
        elif day == f.day:
            st = style(p.foreground3, p.background3, bold=True)
        else:
            st = style(p.foreground2, p.background1)
        canvas.text(0, x0, f.xs[i + 1], label, st)


def _header_label(f: GridFrame, i: int) -> tuple[int, str]:
    """x and text of column ``i``'s header label (one format for all columns)."""
    xs = f.xs
    narrowest = min(b - a - 1 for a, b in zip(xs, xs[1:], strict=False))
    fmt = next(
        (fm for fm in HEADER_FORMATS if max(len(_day(fm, d)) for d in f.days) + 2 <= narrowest),
        HEADER_FORMATS[-1],
    )
    x0, x1 = xs[i] + 1, xs[i + 1]
    label = f" {_day(fmt, f.days[i])} "
    return x0 + max(0, (x1 - x0 - len(label)) // 2), label


def _header_end(f: GridFrame, i: int) -> int:
    """The first x right of column ``i``'s header text (its trailing pad is free)."""
    x0, label = _header_label(f, i)
    return min(x0 + len(label.rstrip()), f.xs[i + 1])


def _strip(canvas: Canvas, f: GridFrame) -> None:
    p, xs, rows = f.palette, f.xs, f.strip_rows
    divider = style(p.background3, p.background1)
    for y in range(1, rows + 1):
        for x in xs[:-1]:
            canvas.fill(y, x, x + 1, divider, "│")
    hidden = sum(1 for bar in f.bars if bar.lane >= rows)
    if hidden:
        canvas.text(rows, 0, AXIS, f"+{hidden}", style(p.foreground1, p.background1))
    period_end = _midnight(f, f.days[-1])
    for bar in f.bars:
        if bar.lane >= rows:
            continue
        color = f.color(bar.occ.calendar_id)
        selected = bar.occ == f.selected
        fill, fg = event_colors(color, p, selected)
        accent = fg if selected else color
        y, x0, x1 = 1 + bar.lane, xs[bar.first] + 1, xs[bar.last]
        canvas.fill(y, x0, x1, style(fg, fill, bold=True))
        continued = bar.occ.start.date() < f.days[0]
        after = bar.last == len(f.days) and bar.occ.end > period_end
        title = fit(_clean(bar.occ.summary), x1 - x0 - 1 - after)
        canvas.text(y, x0, x1, f"{'◂' if continued else ' '}{title}")
        # Like a timed block: an accent bar in the calendar colour (none when selected).
        edge = "◂" if continued else " " if selected else EDGE
        canvas.text(y, x0, x0 + 1, edge, style(accent, fill, bold=True))
        if after:
            canvas.text(y, x1 - 1, x1, "▸", style(accent, fill, bold=True))
    sep = 1 + rows
    canvas.fill(sep, 0, canvas.width, divider, "─")
    for x in xs[:-1]:
        canvas.fill(sep, x, x + 1, divider, "┼")


def _grid(canvas: Canvas, f: GridFrame, bottom: int) -> None:
    p, xs, scale, top = f.palette, f.xs, f.scale, f.top
    divider = style(p.background3, p.background1)
    hour_line = style(blend(p.background3, p.background1, LINE_ALPHA), p.background1)
    label = style(p.foreground1, p.background1)
    cursor = style(p.foreground3, blend(p.primary, p.background1, CURSOR_ALPHA))
    cursor_label = style(p.primary, p.background1, bold=True)
    hour_rows = {scale.row_of(hour * 60): hour for hour in range(24)}
    sel_col = f.days.index(f.day)
    now_col = f.days.index(f.now.date()) if f.now.date() in f.days else None

    for row in range(top, bottom):
        y = f.header + row - top
        hour_start = row in hour_rows
        if f.cursor_rows and row == f.cursor_rows.start:
            hour, minute = divmod(f.cursor_minute, 60)
            canvas.text(y, 0, AXIS, f"{hour:02d}:{minute:02d}", cursor_label)
        elif hour_start:
            canvas.text(y, 0, AXIS, f"{hour_rows[row]:02d}:00", label)
        for i, x in enumerate(xs[:-1]):
            canvas.fill(y, x, x + 1, divider, "│")
            if hour_start and scale.rows_per_hour >= 2:
                canvas.fill(y, x + 1, xs[i + 1], hour_line, HOUR_LINE)
        if row in f.cursor_rows:
            canvas.fill(y, xs[sel_col] + 1, xs[sel_col + 1], cursor)
        if now_col is not None and row == f.now_row():
            # ● replaces the column's divider (never covered); events drawn later show
            # the line through, dimmed, and their text covers it. The hour label stays.
            red = Style(color=p.red, bold=True)
            for x in range(xs[now_col], xs[now_col + 1]):
                canvas.chars[y][x] = "●" if x == xs[now_col] else "─"
                canvas.styles[y][x] = canvas.styles[y][x] + red

    empty = [list(chars) for chars in canvas.chars]  # the grid without events
    for block in f.blocks:
        _gaps(canvas, f, block, bottom)
    for index, block in enumerate(f.blocks):
        rows = _text_rows(f, index, bottom)
        _block(canvas, f, block, bottom, empty, rows, *_lines(f, block, len(rows)))
    _hidden(canvas, f, bottom)


def _hidden(canvas: Canvas, f: GridFrame, bottom: int) -> None:
    st = style(f.palette.foreground2, f.palette.background2)
    for m in _markers(f, bottom):
        canvas.text(m.y, m.x0, m.x1, m.label, st)


def markers(f: GridFrame, height: int) -> list[Marker]:
    """The markers ``paint(f, width, height)`` draws (for clicks on them)."""
    return _markers(f, f.bottom(height))


def _markers(f: GridFrame, bottom: int) -> list[Marker]:
    """``▲ N earlier`` / ``▼ N later`` per column for events scrolled out of view, on
    the edge row right of its events. Where that row holds the column's cursor or
    now-line, or its events leave no room, the marker goes to the column's header
    line instead: never next to an unrelated visible event."""
    xs, top = f.xs, f.top
    taken = {(f.days.index(f.day), row) for row in f.cursor_rows}
    if f.now.date() in f.days:
        taken.add((f.days.index(f.now.date()), f.now_row()))
    result: list[Marker] = []
    for i in range(len(xs) - 1):
        blocks = [b for b in f.blocks if b.day == i]
        header_x1 = xs[i + 1]  # header room is used from the right
        for edge, arrow, word, hidden in (
            (bottom - 1, "▼", "later", [b for b in blocks if b.top >= bottom]),
            (top, "▲", "earlier", [b for b in blocks if b.bottom <= top]),
        ):
            occs = tuple(sorted((o for b in hidden for o in b.occs), key=lambda o: o.start))
            if not occs:
                continue
            labels = (f" {arrow} {len(occs)} {word} ", f"{arrow}{len(occs)}", arrow)
            if (i, edge) not in taken:  # right of the events on the row (plus a gap)
                ends = [sub_columns(b, xs)[1] + 1 for b in blocks if b.top <= edge < b.bottom]
                x0, x1 = max(ends, default=xs[i] + 1), xs[i + 1]
                label = next((t for t in labels if len(t) <= x1 - x0), "")
                if label:
                    y = f.header + edge - top
                    result.append(Marker(i, y, x1 - len(label), x1, label, occs))
                    continue
            x0 = _header_end(f, i)
            label = next((t for t in labels[1:] if len(t) <= header_x1 - x0), "")
            if label:
                result.append(Marker(i, 0, header_x1 - len(label), header_x1, label, occs))
                header_x1 -= len(label)
    return result


def _text_rows(f: GridFrame, index: int, bottom: int) -> list[int]:
    """The visible rows of ``f.blocks[index]`` that no block drawn above it covers
    (its text goes there, so a covered event's title moves below its cover)."""
    block = f.blocks[index]
    x0, x1 = sub_columns(block, f.xs)
    above = [
        b
        for b in f.blocks[index + 1 :]
        if b.day == block.day and sub_columns(b, f.xs)[0] < x1 and x0 < sub_columns(b, f.xs)[1]
    ]
    return [
        row
        for row in range(max(block.top, f.top), min(block.bottom, bottom))
        if not any(b.top <= row < b.bottom for b in above)
    ]


def _lines(f: GridFrame, block: Block, height: int) -> tuple[list[str], int]:
    """The text lines of ``block`` for its ``height`` free rows (with ``pad``), and how
    many of them are its title."""
    occ = _shown(f, block)
    pad, width = _text_box(f, block)
    titles = 1
    title, span = _clean(occ.summary), _span(occ, width)
    if block.group:
        more = f" +{len(block.group) - 1}"
        label = fit(title, width - len(more)) + more if width - len(more) >= 2 else ""
        texts = [label or fit(f"{len(block.group)}×", width), span]
    elif height <= 1:
        texts = [fit(f"{occ.start:%H:%M} {title}" if width >= 11 else title, width)]
    else:  # the title wraps over the lines the time doesn't need, then the location
        lines = wrap(title, width, max(1, height - 1 if span else height))
        titles = len(lines)
        texts = lines + [fit(t, width) for t in (span, _clean(occ.event.location)) if t]
    return [pad + t for t in texts], titles


def _shown(f: GridFrame, block: Block) -> Occurrence:
    """The occurrence ``block`` shows: the selected one of a collapsed cluster."""
    return f.selected if f.selected is not None and f.selected in block.occs else block.occ


def _text_box(f: GridFrame, block: Block) -> tuple[str, int]:
    """The left pad (the accent bar's cell) and the text width of ``block``."""
    x0, x1 = sub_columns(block, f.xs)
    pad = " " if x1 - x0 >= 3 else ""
    return pad, x1 - x0 - len(pad)


def _gaps(canvas: Canvas, f: GridFrame, block: Block, bottom: int) -> None:
    """Blank the cells beside ``block``: no hour or now line there (unless another
    event, drawn later, shows it)."""
    x0, x1 = sub_columns(block, f.xs)
    for row in range(max(block.top, f.top), min(block.bottom, bottom)):
        y = f.header + row - f.top
        for x in (x0 - 1, x1):
            inside = f.xs[block.day] < x < f.xs[block.day + 1]
            if inside and canvas.chars[y][x] in (HOUR_LINE, "─"):
                canvas.chars[y][x] = " "


def _block(
    canvas: Canvas,
    f: GridFrame,
    block: Block,
    bottom: int,
    empty: list[list[str]],
    rows: list[int],
    texts: list[str],
    titles: int,
) -> None:
    """Draw ``block`` translucent over the empty grid (its chars: ``empty``), replacing
    any event below so colours never mix: hour and now lines show through faintly,
    an accent bar in the calendar colour marks its left edge (the selected block is
    all in that colour), ``texts`` go on ``rows`` (the first ``titles`` of them in bold)."""
    first, last = max(block.top, f.top), min(block.bottom, bottom)
    if first >= last:
        return
    p = f.palette
    selected = f.selected in block.occs
    color = f.color(_shown(f, block).calendar_id)
    bg, fg = event_colors(color, p, selected)
    now_line = fg if selected else p.red  # red may be the fill
    x0, x1 = sub_columns(block, f.xs)
    lines = dict(zip(rows, texts, strict=False))
    title_rows = rows[:titles]
    for row in range(first, last):
        y = f.header + row - f.top
        for x in range(x0, x1):
            char = empty[y][x]
            if char == "─" or (char == HOUR_LINE and row > block.top):
                # Hour lines inside and the now line show through, in the block's tone.
                line, strength = (fg, HOUR_ALPHA) if char == HOUR_LINE else (now_line, NOW_ALPHA)
                canvas.chars[y][x] = char
                canvas.styles[y][x] = style(blend(line, bg, strength), bg)
            else:
                canvas.chars[y][x] = " "
                canvas.styles[y][x] = style(fg, bg)
        text = lines.get(row, "")
        canvas.text(y, x0, x1, text)
        for x in range(x0, min(x1, x0 + cell_len(text))):
            canvas.styles[y][x] = style(fg, bg, bold=row in title_rows)
        if x1 - x0 >= 3 and not selected:
            canvas.text(y, x0, x0 + 1, EDGE, style(color, bg, bold=True))


def _day(fmt: str, day: date) -> str:
    return day.strftime(fmt).replace("{day}", str(day.day))


def _clean(text: str) -> str:
    return " ".join(text.split())


def wrap(text: str, width: int, max_lines: int) -> list[str]:
    """``text`` word-wrapped to ``width`` cells in at most ``max_lines`` lines; a word
    too long for a line, and the last line when text is left over, end with ``…``."""
    lines: list[str] = []
    words = text.split()
    while words and len(lines) < max_lines - 1:
        line = words.pop(0)
        while words and cell_len(f"{line} {words[0]}") <= width:
            line += " " + words.pop(0)
        lines.append(fit(line, width))
    return [*lines, fit(" ".join(words), width)] if words else lines


def _span(occ: Occurrence, width: int) -> str:
    """``HH:MM–HH:MM``, just the start if that doesn't fit, else nothing (digits never cut)."""
    start, full = f"{occ.start:%H:%M}", f"{occ.start:%H:%M}–{occ.end:%H:%M}"
    return next((t for t in (full, start) if len(t) <= width), "")
