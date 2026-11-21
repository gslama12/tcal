from datetime import date, datetime, timedelta

import pytest

from tcal.model import Event, Occurrence
from tcal.ui.calgrid import by_day, month_weeks, occurrence_days, weekday_names
from tcal.ui.widgets.minimonth import day_at
from tcal.ui.widgets.month_view import Grid, chips
from tcal.ui.widgets.year_view import Layout


def occ(start: datetime, end: datetime, all_day: bool = False, name: str = "e") -> Occurrence:
    return Occurrence(Event(name, "cal", name, start, end, all_day=all_day), start, end)


def test_month_weeks() -> None:
    weeks = month_weeks(2026, 11, week_start=0)  # Nov 1 2026 is a Sunday
    assert len(weeks) == 6
    assert weeks[0][0] == date(2026, 10, 26) and weeks[0][6] == date(2026, 11, 1)
    assert weeks[-1][0] == date(2026, 11, 30) and weeks[-1][6] == date(2026, 12, 6)
    assert all(len(w) == 7 for w in weeks)

    sunday = month_weeks(2026, 11, week_start=6)
    assert len(sunday) == 5 and sunday[0][0] == date(2026, 11, 1)
    assert len(month_weeks(2021, 2, week_start=0)) == 4  # Feb 2021: Monday 1st, 28 days
    assert len(month_weeks(2021, 2, week_start=0, weeks=6)) == 6


def test_weekday_names() -> None:
    assert weekday_names(0)[0] == "Mon"
    assert weekday_names(6) == ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]


def test_occurrence_days() -> None:
    d = datetime(2026, 11, 18).astimezone()
    assert occurrence_days(occ(d, d + timedelta(days=3), all_day=True)) == [
        date(2026, 11, 18),
        date(2026, 11, 19),
        date(2026, 11, 20),
    ]
    assert occurrence_days(occ(d + timedelta(hours=22), d + timedelta(days=1))) == [d.date()]
    assert occurrence_days(occ(d + timedelta(hours=9), d + timedelta(hours=9))) == [d.date()]
    late = occ(d + timedelta(hours=23), d + timedelta(hours=25))
    assert occurrence_days(late) == [date(2026, 11, 18), date(2026, 11, 19)]


def test_by_day_puts_all_day_first() -> None:
    d = datetime(2026, 11, 18).astimezone()
    timed = occ(d + timedelta(hours=8), d + timedelta(hours=9), name="timed")
    all_day = occ(d, d + timedelta(days=2), all_day=True, name="trip")
    days = by_day([timed, all_day])
    assert [o.summary for o in days[d.date()]] == ["trip", "timed"]
    assert [o.summary for o in days[date(2026, 11, 19)]] == ["trip"]


def test_chips_overflow() -> None:
    d = datetime(2026, 11, 18).astimezone()
    events = [occ(d, d + timedelta(hours=1), name=str(i)) for i in range(5)]
    assert chips(events[:2], 3) == events[:2]
    assert chips(events, 3) == [events[0], events[1], 3]
    assert chips(events, 1) == [5]
    assert chips(events, 0) == []


def test_month_grid_geometry() -> None:
    weeks = month_weeks(2026, 11, 0)
    grid = Grid.build(weeks, width=90, height=37)
    assert sum(grid.widths) + 6 == 90
    assert grid.block == 6 and grid.rule and grid.slots == 4
    assert grid.at(0, 0) is None  # header
    assert grid.at(0, 1) == (date(2026, 10, 26), -1)  # separator
    assert grid.at(grid.xs[6], 2) == (date(2026, 11, 1), 0)  # day number
    assert grid.at(grid.xs[2] + 1, 1 + 6 * 3 + 3) == (date(2026, 11, 18), 2)  # 2nd chip
    tight = Grid.build(weeks, width=50, height=13)
    assert tight.block == 2 and not tight.rule and tight.slots == 1


def test_minimonth_day_at() -> None:
    nov = date(2026, 11, 1)
    assert day_at(nov, 0, 0, 1) == date(2026, 10, 26)
    assert day_at(nov, 0, 18, 1) == date(2026, 11, 1)
    assert day_at(nov, 0, 6, 4) == date(2026, 11, 18)
    assert day_at(nov, 0, 6, 0) is None  # weekday initials


def test_minimonth_day_at_scaled() -> None:
    nov = date(2026, 11, 1)
    assert day_at(nov, 0, 6 * 5, 1, cell=5, row_height=2) == date(2026, 11, 1)
    assert day_at(nov, 0, 2 * 5 + 3, 8, cell=5, row_height=2) == date(2026, 11, 18)
    assert day_at(nov, 0, 0, 13, cell=5, row_height=2) is None


@pytest.mark.parametrize(
    ("size", "grid"),
    [((88, 30), (4, 3)), ((66, 40), (3, 4)), ((46, 60), (2, 6)), ((170, 50), (4, 3))],
)
def test_year_layout_fits_all_months(size: tuple[int, int], grid: tuple[int, int]) -> None:
    width, height = size
    layout = Layout.build(width, height)
    assert (layout.cols, layout.rows) == grid
    assert layout.header and layout.vgap >= 1  # a blank line between rows
    assert_fits(layout, width, height)


def test_year_layout_compact() -> None:
    """Too small for any full grid: weekday initials go first, then the blank lines."""
    lean = Layout.build(66, 31)
    assert not lean.header and lean.vgap == 1
    assert_fits(lean, 66, 31)
    tight = Layout.build(68, 29)  # QA: 100x35 terminal
    assert not tight.header and tight.vgap == 0
    assert_fits(tight, 68, 29)


def assert_fits(layout: Layout, width: int, height: int) -> None:
    for index in range(12):
        x, y = layout.origin(index)  # all 12 months on screen
        assert x >= 0 and x + layout.width <= width and y >= 0 and y + layout.height <= height
        assert layout.at(x, y) == (index, 0, 0)


def test_year_layout_scales_up() -> None:
    big = Layout.build(170, 50)
    assert big.cell > 3 and big.row_height > 1
    used = big.cols * big.width + (big.cols - 1) * big.hgap
    assert used > 170 * 0.8
