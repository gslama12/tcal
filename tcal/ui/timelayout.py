"""Pure geometry of the Day/Week time grid (no widgets), shared with the month view.

``TimeScale`` maps minutes to grid rows (``fit_scale`` fits a day range to a
height); ``layout_blocks`` stacks overlapping timed occurrences (``cascade``),
``layout_bars`` all-day / multi-day ones into strip lanes (``is_bar`` decides which).
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from fractions import Fraction
from typing import TypeVar

from tcal.model import Occurrence

# A span edge: a row / day index, or ``(row, minute)`` so that events whose times
# overlap count as overlapping even when they round to touching rows.
Edge = TypeVar("Edge", int, tuple[int, int])

ZOOMS = (1, 2, 3, 4, 6, 8)  # rows per hour
INDENT = 2  # cells per cascade level of overlapping events
MIN_WIDTH = 4  # narrowest event block; a cluster needing narrower ones collapses
MINUTES = 24 * 60


@dataclass(frozen=True)
class TimeScale:
    """Mapping between minutes after midnight and grid rows.

    Row ``r`` starts at minute ``offset + r * 60 / rows_per_hour``. A minute belongs to
    the row whose start is nearest (ties: the earlier row), so event edges, hour lines
    and the cursor all round the same way; 24:00 is the end of the grid. Zoom levels are whole rows per hour aligned
    to midnight; a fitted scale may be fractional, with ``offset`` (within half a row
    of 0) aligning a row start to ``day_start``.
    """

    rows_per_hour: Fraction | int
    offset: Fraction | int = 0

    @classmethod
    def aligned(cls, rows_per_hour: Fraction, minute: int) -> "TimeScale":
        """The scale whose rows start exactly at ``minute``."""
        per_row = 60 / rows_per_hour
        return cls(rows_per_hour, minute - math.floor(minute / per_row + Fraction(1, 2)) * per_row)

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
        """The row whose start is nearest ``minute`` (24:00: the row after the last)."""
        if minute >= MINUTES:
            return self.total_rows
        row = math.ceil((minute - self.offset) / self.per_row - Fraction(1, 2))
        return min(row, self.total_rows - 1)

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


def _greedy(spans: Sequence[tuple[Edge, Edge]], order: Sequence[int]) -> dict[int, int]:
    """Assign each span (in ``order``) the first lane that is free at its start."""
    lane_ends: list[Edge] = []
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


def _order(spans: Sequence[tuple[Edge, Edge]]) -> list[int]:
    """Indices by start, the longer span first."""
    by_end = sorted(range(len(spans)), key=lambda i: spans[i][1], reverse=True)
    return sorted(by_end, key=lambda i: spans[i][0])


def pack_lanes(spans: Sequence[tuple[Edge, Edge]]) -> list[int]:
    """Lane per [start, end) span so that spans in one lane never overlap."""
    lanes = _greedy(spans, _order(spans))
    return [lanes[i] for i in range(len(spans))]


def cascade(spans: Sequence[tuple[Edge, Edge]]) -> list[tuple[int, int, int]]:
    """``(depth, column, columns)`` per [start, end) span for the stacked layout.

    Google-style cascade: spans are taken by start (the longer first, so of two
    with the same start the shorter goes on top); each is one level deeper than
    the deepest earlier span it overlaps (touching is no overlap). Spans with the
    same start *and* end would cover each other, so they share one level side by
    side (``column`` of ``columns``).
    """
    result: list[tuple[int, int, int]] = [(0, 0, 1)] * len(spans)
    same: dict[tuple[Edge, Edge], list[int]] = {}
    for i in _order(spans):
        same.setdefault(spans[i], []).append(i)
    placed: list[tuple[tuple[Edge, Edge], int]] = []  # (span, depth), earlier first
    for span, members in same.items():
        start, end = span
        depth = 1 + max((d for (s, e), d in placed if s < end and start < e), default=-1)
        placed.append((span, depth))
        for col, i in enumerate(members):
            result[i] = (depth, col, len(members))
    return result


def _clusters(spans: Sequence[tuple[Edge, Edge]]) -> list[list[int]]:
    """Indices of transitively overlapping spans, in ``_order`` (the cascade's)."""
    clusters: list[list[int]] = []
    ends: list[Edge] = []  # the end of the current cluster
    for i in _order(spans):
        start, end = spans[i]
        if not clusters or start >= ends[-1]:
            clusters.append([])
            ends.append(end)
        clusters[-1].append(i)
        ends[-1] = max(ends[-1], end)
    return clusters


def is_bar(occ: Occurrence) -> bool:
    """All-day and >= 24 h events go to the all-day strip, not the grid."""
    return occ.all_day or occ.end - occ.start >= timedelta(days=1)


def minute_in(day: date, moment: datetime) -> int:
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
    depth: int = 0  # cascade level: indented ``INDENT`` cells per level
    col: int = 0  # side by side with events of the same times: column ``col`` of ``cols``
    cols: int = 1
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
    width: int | None = None,
) -> list[Block]:
    """Grid blocks of the timed occurrences, clipped per day and stacked (``cascade``),
    in drawing order (bottom first).

    An event shorter than a row still gets one row; events crossing midnight
    get one block per day. Events overlap if their rows or their times do (so a
    30-min overlap shows even when the rows only touch). A cluster with a block
    narrower than ``MIN_WIDTH`` in a day column ``width`` cells wide becomes one
    block over the whole column (``group``).
    """
    blocks: list[Block] = []
    for i, day in enumerate(days):
        spans: list[tuple[Occurrence, int, int]] = []
        minutes: list[tuple[int, int]] = []
        for occ in occs:
            if is_bar(occ):
                continue
            start, end = minute_in(day, occ.start), minute_in(day, occ.end)
            if start < end or (start == end and occ.start.date() == day and start < MINUTES):
                top = scale.row_of(start)
                spans.append((occ, top, max(top + 1, scale.row_of(end))))
                minutes.append((start, end))
        rows = [(top, bottom) for _, top, bottom in spans]
        edges = [
            ((top, s), (bottom, e)) for (top, bottom), (s, e) in zip(rows, minutes, strict=True)
        ]
        stacked = cascade(edges)
        for cluster in _clusters(edges):
            if width is not None and any(_width(width, stacked[j]) < MIN_WIDTH for j in cluster):
                top, bottom = rows[cluster[0]][0], max(rows[j][1] for j in cluster)
                group = tuple(sorted((spans[j][0] for j in cluster), key=_by_start))
                blocks.append(Block(group[0], i, top, bottom, group=group))
                continue
            for j in cluster:  # in cascade order: the lower block first
                (occ, top, bottom), (depth, col, cols) = spans[j], stacked[j]
                blocks.append(Block(occ, i, top, bottom, depth, col, cols))
    return blocks


def _width(width: int, stacked: tuple[int, int, int]) -> int:
    """Narrowest block width of a ``(depth, col, cols)`` block (1-col gaps)."""
    depth, _, cols = stacked
    return (width - INDENT * depth + 1) // cols - 1


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


def sub_columns(block: Block, xs: Sequence[int]) -> tuple[int, int]:
    """[x0, x1) of ``block`` in its day column (``xs``: the column dividers): indented
    by its depth; side-by-side blocks leave a 1-col gap to their right neighbour
    (the last one's gap is the divider)."""
    x0, x1 = xs[block.day] + 1 + INDENT * block.depth, xs[block.day + 1]
    inner = x1 - x0 + 1
    left = x0 + inner * block.col // block.cols
    right = x0 + inner * (block.col + 1) // block.cols - 1
    return left, min(right, x1)
