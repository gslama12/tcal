"""Drawing one frame of the Day/Week time grid (see ``tcal.ui.widgets.timegrid``).

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
from tcal.ui.theme import Palette, text_on
from tcal.ui.timelayout import Bar, Block, TimeScale, sub_columns
from tcal.ui.widgets.base import fit

AXIS = 6  # width of the time axis: "HH:MM "


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
    cursor_rows: range  # the cursor slot (two rows at 8 rows/hour)
    selected: Occurrence | None
    now: datetime
    header_formats: tuple[str, ...]  # widest first
    palette: Palette
    color: Callable[[str], str]  # calendar id -> colour

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
    """``▲ N earlier`` / ``▼ N later`` in day column ``day``, grid ``row``, x [x0, x1)."""

    day: int
    row: int
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
    return canvas.strips()


def _header(canvas: Canvas, f: GridFrame) -> None:
    p, xs = f.palette, f.xs
    narrowest = min(b - a - 1 for a, b in zip(xs, xs[1:], strict=False))
    fmt = next(
        (fm for fm in f.header_formats if max(len(_day(fm, d)) for d in f.days) + 2 <= narrowest),
        f.header_formats[-1],
    )
    for i, day in enumerate(f.days):
        x0, x1 = xs[i] + 1, xs[i + 1]
        label = f" {_day(fmt, day)} "
        if day == f.now.date():
            st = style(p.background1, p.primary, bold=True)
        elif day == f.day:
            st = style(p.foreground3, p.background3, bold=True)
        else:
            st = style(p.foreground2, p.background1)
        canvas.text(0, x0 + max(0, (x1 - x0 - len(label)) // 2), x1, label, st)


def _strip(canvas: Canvas, f: GridFrame) -> None:
    p, xs, rows = f.palette, f.xs, f.strip_rows
    divider = style(p.background3, p.background1)
    for y in range(1, rows + 1):
        for x in xs[:-1]:
            canvas.fill(y, x, x + 1, divider, "│")
    hidden = sum(1 for bar in f.bars if bar.lane >= rows)
    if hidden:
        canvas.text(rows, 0, AXIS, f"+{hidden}", style(p.foreground1, p.background1))
    period_end = datetime.combine(f.days[-1] + timedelta(days=1), time(), f.now.tzinfo)
    for bar in f.bars:
        if bar.lane >= rows:
            continue
        color = f.color(bar.occ.calendar_id)
        y, x0, x1 = 1 + bar.lane, xs[bar.first] + 1, xs[bar.last]
        canvas.fill(y, x0, x1, style(text_on(color, p), color, bold=True))
        before = "◂" if bar.occ.start.date() < f.days[0] else " "
        if bar.occ == f.selected:  # accent bar, as for selected blocks
            before = "▌" if before == " " else before
        after = bar.last == len(f.days) and bar.occ.end > period_end
        canvas.text(y, x0, x1, f"{before}{fit(_clean(bar.occ.summary), x1 - x0 - 1 - after)}")
        if bar.occ == f.selected:
            canvas.text(y, x0, x0 + 1, before, style(p.foreground3, color, bold=True))
        if after:
            canvas.text(y, x1 - 1, x1, "▸")
    sep = 1 + rows
    canvas.fill(sep, 0, canvas.width, divider, "─")
    for x in xs[:-1]:
        canvas.fill(sep, x, x + 1, divider, "┼")


def _grid(canvas: Canvas, f: GridFrame, bottom: int) -> None:
    p, xs, scale, top = f.palette, f.xs, f.scale, f.top
    divider = style(p.background3, p.background1)  # also the hour lines
    label = style(p.foreground1, p.background1)
    cursor = style(p.background1, p.primary)
    cursor_label = style(p.primary, p.background1, bold=True)
    hour_rows = {scale.row_of(hour * 60): hour for hour in range(24)}
    sel_col = f.days.index(f.day)
    now_col = f.days.index(f.now.date()) if f.now.date() in f.days else None

    for row in range(top, bottom):
        y = f.header + row - top
        hour_start = row in hour_rows
        if row == f.cursor_rows.start:
            minute = scale.minute_of(row)
            canvas.text(y, 0, AXIS, f"{minute // 60:02d}:{minute % 60:02d}", cursor_label)
        elif hour_start:
            canvas.text(y, 0, AXIS, f"{hour_rows[row]:02d}:00", label)
        for i, x in enumerate(xs[:-1]):
            canvas.fill(y, x, x + 1, divider, "│")
            if hour_start and scale.rows_per_hour >= 2:
                canvas.fill(y, x + 1, xs[i + 1], divider, "╌")
        if row in f.cursor_rows:
            canvas.fill(y, xs[sel_col] + 1, xs[sel_col + 1], cursor)
        if now_col is not None and row == f.now_row():
            # ● replaces the column's divider (never covered); events drawn later cover
            # the line, so it never hides their text. The hour label stays.
            red = Style(color=p.red, bold=True)
            for x in range(xs[now_col], xs[now_col + 1]):
                canvas.chars[y][x] = "●" if x == xs[now_col] else "─"
                canvas.styles[y][x] = canvas.styles[y][x] + red

    for block in f.blocks:
        _block(canvas, f, block, bottom)
    _hidden(canvas, f, bottom)


def _hidden(canvas: Canvas, f: GridFrame, bottom: int) -> None:
    st = style(f.palette.foreground2, f.palette.background2)
    for m in _markers(f, bottom):
        canvas.text(f.header + m.row - f.top, m.x0, m.x1, m.label, st)


def markers(f: GridFrame, height: int) -> list[Marker]:
    """The markers ``paint(f, width, height)`` draws (for clicks on them)."""
    return _markers(f, f.bottom(height))


def _markers(f: GridFrame, bottom: int) -> list[Marker]:
    """``▲ N earlier`` / ``▼ N later`` per column for events scrolled out of view, on
    the edge row, or further in where that row holds the column's cursor or now-line,
    or where the events on it leave no room (never over an event)."""
    xs, top = f.xs, f.top
    taken = {(f.days.index(f.day), row) for row in f.cursor_rows}
    if f.now.date() in f.days:
        taken.add((f.days.index(f.now.date()), f.now_row()))
    result: list[Marker] = []
    for i in range(len(xs) - 1):
        blocks = [b for b in f.blocks if b.day == i]
        for edge, step, arrow, word, hidden in (
            (top, 1, "▲", "earlier", [b for b in blocks if b.bottom <= top]),
            (bottom - 1, -1, "▼", "later", [b for b in blocks if b.top >= bottom]),
        ):
            occs = tuple(sorted((o for b in hidden for o in b.occs), key=lambda o: o.start))
            if not occs:
                continue
            labels = (f" {arrow} {len(occs)} {word} ", f"{arrow}{len(occs)}", arrow)
            for row in range(edge, bottom if step > 0 else top - 1, step):
                if (i, row) in taken:
                    continue
                # right of the events on the row (plus a gap)
                ends = [sub_columns(b, xs)[1] + 1 for b in blocks if b.top <= row < b.bottom]
                x0, x1 = max(ends, default=xs[i] + 1), xs[i + 1]
                label = next((t for t in labels if len(t) <= x1 - x0), "")
                if label:
                    result.append(Marker(i, row, x1 - len(label), x1, label, occs))
                    break
    return result


def _block(canvas: Canvas, f: GridFrame, block: Block, bottom: int) -> None:
    first, last = max(block.top, f.top), min(block.bottom, bottom)
    if first >= last:
        return
    p, selected_occ = f.palette, f.selected
    selected = selected_occ in block.occs
    occ = selected_occ if selected and selected_occ is not None else block.occ
    color = f.color(occ.calendar_id)
    fg = text_on(color, p)
    x0, x1 = sub_columns(block, f.xs)
    pad = " " if x1 - x0 >= 6 or selected else ""
    width = x1 - x0 - len(pad)
    title, span = _clean(occ.summary), _span(occ, width)
    if block.group:
        more = f" +{len(block.group) - 1}"
        label = fit(title, width - len(more)) + more if width - len(more) >= 2 else ""
        texts = [label or fit(f"{len(block.group)}×", width), span]
    elif block.bottom - block.top == 1:
        texts = [fit(f"{occ.start:%H:%M} {title}" if width >= 11 else title, width)]
    else:  # the title wraps over the lines the time doesn't need, then the location
        height = block.bottom - block.top
        lines = wrap(title, width, max(1, height - 1 if span else height))
        texts = lines + [fit(t, width) for t in (span, _clean(occ.event.location)) if t]
    gaps = [x for x in (x0 - 1, x1) if f.xs[block.day] < x < f.xs[block.day + 1]]
    for row in range(first, last):
        y = f.header + row - f.top
        canvas.fill(y, x0, x1, style(fg, color, bold=selected))
        for x in gaps:  # the gap beside an event stays blank (no hour line)
            if canvas.chars[y][x] == "╌":
                canvas.chars[y][x] = " "
        index = row - first
        if index < len(texts):
            bold = style(fg, color, bold=True) if index == 0 else None
            canvas.text(y, x0, x1, pad + texts[index], bold)
        if selected:  # Google-like: keep the colour, add a bright accent bar + bold text
            canvas.text(y, x0, x0 + 1, "▌", style(p.foreground3, color, bold=True))


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
