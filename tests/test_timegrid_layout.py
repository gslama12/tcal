"""Pure geometry of the time grid: slot mapping, zoom fit, overlap packing."""

from datetime import date, datetime, timedelta

import pytest

from tcal.model import Event, Occurrence
from tcal.ui.timelayout import (
    ZOOMS,
    TimeScale,
    cascade,
    fit_scale,
    layout_bars,
    layout_blocks,
    pack_lanes,
    sub_columns,
)

TZ = datetime.now().astimezone().tzinfo
DAY = date(2026, 11, 18)
WEEK = [date(2026, 11, 16) + timedelta(days=i) for i in range(7)]


def occ(start: str, end: str, day: date = DAY, all_day: bool = False, days: int = 0) -> Occurrence:
    s = datetime.combine(day, datetime.strptime(start, "%H:%M").time(), TZ)
    e = datetime.combine(day + timedelta(days=days), datetime.strptime(end, "%H:%M").time(), TZ)
    return Occurrence(Event(f"{day}{start}{end}", "work", "x", s, e, all_day=all_day), s, e)


@pytest.mark.parametrize("rph", ZOOMS)
def test_slot_mapping_round_trips(rph: int) -> None:
    scale = TimeScale(rph)
    assert scale.total_rows == 24 * rph
    for row in range(scale.total_rows):
        assert scale.row_of(scale.minute_of(row)) == row
    assert scale.row_of(0) == 0 and scale.row_of(24 * 60) == scale.total_rows


def test_slot_mapping_values() -> None:
    assert TimeScale(2).row_of(9 * 60 + 14) == 18  # nearest row start: 09:00
    assert TimeScale(2).row_of(9 * 60 + 15) == 18  # ties: the earlier row
    assert TimeScale(2).row_of(9 * 60 + 16) == 19
    assert TimeScale(4).minute_of(5) == 75
    assert TimeScale(3).minute_of(1) == 20


@pytest.mark.parametrize("height", [20, 26, 28, 31, 35, 46, 52, 53, 100, 140])
def test_fit_scale_shows_day_start_to_end_exactly(height: int) -> None:
    start, end = 6 * 60 + 30, 24 * 60  # 17.5 h
    scale = fit_scale(height, start, end)
    first = scale.row_of(start)
    assert scale.row_of(end) - first == height
    assert scale.minute_of(first) == start
    assert scale.row_of(end) == scale.total_rows  # nothing below 24:00
    assert scale.row_of(0) == 0
    for row in range(scale.total_rows):
        assert scale.row_of(scale.minute_of(row)) == row
        if height <= 70:  # rows of >= 15 min: slots snap to 15 min
            assert scale.minute_of(row) % 15 == 0
    for hour in range(24):  # the row an hour label sits in starts at that hour
        assert scale.minute_of(scale.row_of(hour * 60)) == hour * 60


def test_fit_scale_limits_and_slot_times() -> None:
    start, end = 6 * 60 + 30, 24 * 60
    assert fit_scale(35, start, end) == TimeScale(2)
    assert fit_scale(5, start, end) == TimeScale(1)  # never below the smallest zoom
    assert fit_scale(200, start, end) == TimeScale(8)
    stretched = fit_scale(46, start, end)  # 22.8 min per row
    first = stretched.row_of(start)
    slots = [stretched.minute_of(first + i) for i in range(5)]
    assert slots == [390, 420, 435, 450, 480]  # 06:30, 07:00, 07:15, 07:30, 08:00
    assert TimeScale(3).minute_of(1) == 20


def test_back_to_back_events_never_share_a_row() -> None:
    scale = fit_scale(28, 6 * 60 + 30, 24 * 60)  # 100x35: 37.5 min per row
    blocks = layout_blocks(
        [
            occ("08:00", "08:45"),
            occ("09:00", "10:00"),
            occ("10:00", "11:30"),
            occ("11:00", "12:00"),
        ],
        [DAY],
        scale,
    )
    haircut, standup, review, dentist = blocks
    assert haircut.bottom <= standup.top and (haircut.depth, standup.depth) == (0, 0)
    assert standup.bottom == review.top
    for block, hour in ((standup, 9), (review, 10), (dentist, 11)):
        assert block.top == scale.row_of(hour * 60)  # starts in its hour label's row


def test_cascade() -> None:
    assert cascade([]) == []
    assert cascade([(0, 2), (2, 4)]) == [(0, 0, 1), (0, 0, 1)]  # touching: no overlap
    # A long event with two short ones on it: both one level deeper.
    assert cascade([(0, 4), (1, 2), (2, 3)]) == [(0, 0, 1), (1, 0, 1), (1, 0, 1)]
    # Each later start goes one level above the deepest one it overlaps.
    assert cascade([(0, 3), (1, 4), (2, 5), (4, 6)]) == [(0, 0, 1), (1, 0, 1), (2, 0, 1), (3, 0, 1)]
    # Same start: the shorter one on top.
    assert cascade([(0, 2), (0, 4)]) == [(1, 0, 1), (0, 0, 1)]


def test_cascade_puts_identical_times_side_by_side() -> None:
    assert cascade([(5, 6), (0, 3), (0, 3), (1, 2)]) == [
        (0, 0, 1),
        (0, 0, 2),
        (0, 1, 2),
        (1, 0, 1),  # on top of both
    ]


def test_wide_clusters_collapse() -> None:
    four = [occ("10:00", "13:00"), occ("10:30", "12:30"), occ("11:00", "12:00")]
    four.append(occ("11:30", "12:00"))  # depth 3: 6 cells of indent
    alone = occ("14:00", "15:00")
    blocks = layout_blocks([*four, alone], [DAY], TimeScale(2), width=9)
    group, single = blocks
    assert (group.top, group.bottom, group.depth, group.col, group.cols) == (20, 26, 0, 0, 1)
    assert group.occ == four[0] and group.occs == tuple(four)
    assert single.occs == (alone,) and not single.group
    assert len(layout_blocks(four, [DAY], TimeScale(2), width=10)) == 4
    pair = [occ("10:00", "11:00"), occ("10:00", "11:00")]  # side by side: 2 x 4 + gap
    assert len(layout_blocks(pair, [DAY], TimeScale(2), width=9)) == 2
    assert len(layout_blocks(pair, [DAY], TimeScale(2), width=8)) == 1


def test_blocks_come_in_drawing_order() -> None:
    long, short = occ("10:00", "12:00"), occ("10:00", "10:30")
    late = occ("11:00", "11:30")
    blocks = layout_blocks([late, short, long], [DAY], TimeScale(2))
    assert [(b.occ, b.depth) for b in blocks] == [(long, 0), (short, 1), (late, 1)]
    xs = [6, 26]
    assert sub_columns(blocks[0], xs) == (7, 26)
    assert sub_columns(blocks[1], xs) == (9, 26)  # indented two cells per level


def test_identical_blocks_split_the_column() -> None:
    a, b = occ("10:00", "11:00"), occ("10:00", "11:00")
    left, right = layout_blocks([a, b], [DAY], TimeScale(2))
    xs = [6, 26]
    assert sub_columns(left, xs) == (7, 16) and sub_columns(right, xs) == (17, 26)  # 1-col gap


def test_pack_lanes() -> None:
    assert pack_lanes([(0, 3), (1, 2), (3, 5), (2, 4)]) == [0, 1, 0, 1]


def test_layout_blocks() -> None:
    short = occ("09:00", "09:05")
    overnight = occ("22:00", "02:00", days=1)
    a, b = occ("10:00", "11:30"), occ("10:30", "11:00")
    blocks = layout_blocks([short, overnight, a, b], WEEK, TimeScale(2))
    got = {(blk.occ.event.uid, blk.day): (blk.top, blk.bottom, blk.depth) for blk in blocks}
    assert got == {
        (short.event.uid, 2): (18, 19, 0),  # shorter than a row: still one row
        (a.event.uid, 2): (20, 23, 0),
        (b.event.uid, 2): (21, 22, 1),
        (overnight.event.uid, 2): (44, 48, 0),
        (overnight.event.uid, 3): (0, 4, 0),  # continues the next day
    }


def test_layout_bars() -> None:
    birthday = occ("00:00", "00:00", day=WEEK[2], all_day=True, days=1)
    trip = occ("00:00", "00:00", day=WEEK[5], all_day=True, days=5)  # runs past the week
    long_timed = occ("12:00", "13:00", day=WEEK[0], days=2)  # >= 24 h: a bar
    timed = occ("09:00", "10:00")
    bars = layout_bars([birthday, trip, long_timed, timed], WEEK)
    got = {bar.occ.event.uid: (bar.first, bar.last, bar.lane) for bar in bars}
    assert got == {
        long_timed.event.uid: (0, 3, 0),
        birthday.event.uid: (2, 3, 1),
        trip.event.uid: (5, 7, 0),
    }


def test_overlap_shorter_than_a_row_stacks() -> None:
    # 1 row/hour: 18:30-19:30 and 19:00-21:00 round to touching rows but overlap 30 min.
    qa, dinner = occ("18:30", "19:30"), occ("19:00", "21:00")
    a, b = layout_blocks([qa, dinner], [DAY], TimeScale(1))
    assert a.bottom == b.top  # the rows only touch ...
    assert (a.depth, b.depth) == (0, 1)  # ... yet stacked
    c, d = layout_blocks([qa, occ("19:30", "20:00")], [DAY], TimeScale(1))
    assert (c.depth, d.depth) == (0, 0)  # back to back: no overlap
    short = layout_blocks([occ("18:00", "18:10"), occ("18:10", "18:40")], [DAY], TimeScale(1))
    assert [b.depth for b in short] == [0, 1]  # same row, no time overlap: still stacked
