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
    return canvas.strips()


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
        (fm for fm in f.header_formats if max(len(_day(fm, d)) for d in f.days) + 2 <= narrowest),
        f.header_formats[-1],
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

    lines = [(block, *_lines(f, block)) for block in f.blocks]
    for block, texts, at in lines:
        _block(canvas, f, block, bottom, _place_time(f, block, texts, at, lines))
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


def _lines(f: GridFrame, block: Block) -> tuple[list[str], int | None]:
    """The text lines of ``block`` from its first visible row (with ``pad``), and the
    index of its time line."""
    occ = _shown(f, block)
    x0, x1 = sub_columns(block, f.xs)
    pad = _pad(f, block)
    width = x1 - x0 - len(pad)
    title, span = _clean(occ.summary), _span(occ, width)
    if block.group:
        more = f" +{len(block.group) - 1}"
        label = fit(title, width - len(more)) + more if width - len(more) >= 2 else ""
        texts = [label or fit(f"{len(block.group)}×", width), span]
    elif block.bottom - block.top == 1:
        texts = [fit(f"{occ.start:%H:%M} {title}" if width >= 11 else title, width)]
        span = ""
    else:  # the title wraps over the lines the time doesn't need, then the location
        height = block.bottom - block.top
        lines = wrap(title, width, max(1, height - 1 if span else height))
        texts = lines + [fit(t, width) for t in (span, _clean(occ.event.location)) if t]
    at = texts.index(span) if span and span in texts else None
    return [pad + t for t in texts], at


def _place_time(
    f: GridFrame,
    block: Block,
    texts: list[str],
    at: int | None,
    lines: list[tuple[Block, list[str], int | None]],
) -> list[str]:
    """``texts`` with the time line moved down past the rows where a block to the
    right shows a title or location ("10:00  1:1…" would read as the neighbour's
    time), or dropped if no row of the block is left."""
    if at is None:
        return texts
    first = max(block.top, f.top)
    x1 = sub_columns(block, f.xs)[1]

    def beside_text(row: int) -> bool:
        return any(
            other.day == block.day
            and sub_columns(other, f.xs)[0] >= x1
            and other.top <= row < other.bottom
            and row - max(other.top, f.top) < len(other_texts)
            and row - max(other.top, f.top) != other_at
            for other, other_texts, other_at in lines
        )

    texts = list(texts)
    while beside_text(first + at):
        if first + at + 1 >= block.bottom:
            return texts[:at] + texts[at + 1 :]
        texts.insert(at, "")
        at += 1
    return texts


def _shown(f: GridFrame, block: Block) -> Occurrence:
    """The occurrence ``block`` shows: the selected one of a collapsed cluster."""
    return f.selected if f.selected is not None and f.selected in block.occs else block.occ


def _pad(f: GridFrame, block: Block) -> str:
    x0, x1 = sub_columns(block, f.xs)
    return " " if x1 - x0 >= 6 or f.selected in block.occs else ""


def _block(canvas: Canvas, f: GridFrame, block: Block, bottom: int, texts: list[str]) -> None:
    first, last = max(block.top, f.top), min(block.bottom, bottom)
    if first >= last:
        return
    p = f.palette
    selected = f.selected in block.occs
    color = f.color(_shown(f, block).calendar_id)
    fg = text_on(color, p)
    x0, x1 = sub_columns(block, f.xs)
    gaps = [x for x in (x0 - 1, x1) if f.xs[block.day] < x < f.xs[block.day + 1]]
    for row in range(first, last):
        y = f.header + row - f.top
        canvas.fill(y, x0, x1, style(fg, color, bold=selected))
        for x in gaps:  # the gap beside an event stays blank (no hour or now line)
            if canvas.chars[y][x] in ("╌", "─"):
                canvas.chars[y][x] = " "
        index = row - first
        if index < len(texts):
            bold = style(fg, color, bold=True) if index == 0 else None
            canvas.text(y, x0, x1, texts[index], bold)
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
