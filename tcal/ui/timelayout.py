"""Pure geometry of the Day/Week time grid (no widgets), shared with the month view.

``TimeScale`` maps minutes to grid rows (``fit_scale`` fits a day range to a
height); ``layout_blocks`` packs timed occurrences into side-by-side columns,
``layout_bars`` all-day / multi-day ones into strip lanes (``is_bar`` decides which).
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from fractions import Fraction

from tcal.model import Occurrence

ZOOMS = (1, 2, 3, 4, 6, 8)  # rows per hour
MINUTES = 24 * 60


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


def sub_columns(block: Block, xs: Sequence[int]) -> tuple[int, int]:
    """[x0, x1) of ``block`` in its day column (``xs``: the column dividers), leaving
    a 1-col gap to its right neighbour (the last one's gap is the divider)."""
    x0, x1 = xs[block.day] + 1, xs[block.day + 1]
    inner, end = x1 - x0 + 1, block.col + block.span
    left = x0 + inner * block.col // block.cols
    right = x0 + inner * end // block.cols - 1
    return left, min(right, x1)
