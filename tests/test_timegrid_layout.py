"""Pure geometry of the time grid: slot mapping, zoom fit, overlap packing."""

from datetime import date, datetime, timedelta

import pytest

from tcal.model import Event, Occurrence
from tcal.ui.widgets.timegrid import (
    ZOOMS,
    TimeScale,
    fit_scale,
    layout_bars,
    layout_blocks,
    pack_columns,
    pack_lanes,
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
    assert haircut.bottom <= standup.top and (haircut.cols, standup.cols) == (1, 1)
    assert standup.bottom == review.top
    for block, hour in ((standup, 9), (review, 10), (dentist, 11)):
        assert block.top == scale.row_of(hour * 60)  # starts in its hour label's row


def test_pack_columns() -> None:
    assert pack_columns([]) == []
    assert pack_columns([(0, 2), (2, 4)]) == [(0, 1, 1), (0, 1, 1)]  # touching: no overlap
    # A long event with two short ones beside it: two columns, short ones share one.
    assert pack_columns([(0, 4), (1, 2), (2, 3)]) == [(0, 1, 2), (1, 1, 2), (1, 1, 2)]
    # Transitive cluster: 0 and 2 don't overlap, so they stack in column 0.
    assert pack_columns([(0, 2), (1, 3), (2, 4)]) == [(0, 1, 2), (1, 1, 2), (0, 1, 2)]
    # Three at once, then an independent event later.
    assert pack_columns([(5, 6), (0, 3), (0, 3), (1, 2)]) == [
        (0, 1, 1),
        (0, 1, 3),
        (1, 1, 3),
        (2, 1, 3),
    ]


def test_pack_columns_expands_into_free_columns() -> None:
    # a spans 0-6; b, c side by side early; d late overlaps only a -> widens over cols 1-2.
    spans = [(0, 6), (0, 2), (0, 2), (3, 5)]
    assert pack_columns(spans) == [(0, 1, 3), (1, 1, 3), (2, 1, 3), (1, 2, 3)]
    # Design review 10:00-11:30, 1:1 10:30-11:00, Dentist 11:00-12:00 (2 rows/h).
    assert pack_columns([(20, 23), (21, 22), (22, 24)]) == [(0, 1, 2), (1, 1, 2), (1, 1, 2)]


def test_wide_clusters_collapse() -> None:
    three = [occ("10:00", "11:30"), occ("10:30", "11:00"), occ("11:00", "12:00")]  # 2 columns
    alone = occ("14:00", "15:00")
    blocks = layout_blocks([*three, alone], [DAY], TimeScale(2), max_cols=1)
    group, single = blocks
    assert (group.top, group.bottom, group.col, group.span, group.cols) == (20, 24, 0, 1, 1)
    assert group.occ == three[0] and group.occs == tuple(three)
    assert single.occs == (alone,) and not single.group
    assert len(layout_blocks(three, [DAY], TimeScale(2), max_cols=2)) == 3


def test_pack_lanes() -> None:
    assert pack_lanes([(0, 3), (1, 2), (3, 5), (2, 4)]) == [0, 1, 0, 1]


def test_layout_blocks() -> None:
    short = occ("09:00", "09:05")
    overnight = occ("22:00", "02:00", days=1)
    a, b = occ("10:00", "11:30"), occ("10:30", "11:00")
    blocks = layout_blocks([short, overnight, a, b], WEEK, TimeScale(2))
    got = {(blk.occ.event.uid, blk.day): (blk.top, blk.bottom, blk.col, blk.cols) for blk in blocks}
    assert got == {
        (short.event.uid, 2): (18, 19, 0, 1),  # shorter than a row: still one row
        (a.event.uid, 2): (20, 23, 0, 2),
        (b.event.uid, 2): (21, 22, 1, 2),
        (overnight.event.uid, 2): (44, 48, 0, 1),
        (overnight.event.uid, 3): (0, 4, 0, 1),  # continues the next day
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
