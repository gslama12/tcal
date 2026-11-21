from datetime import date, datetime, timedelta

from tcal.model import Event, Occurrence
from tcal.ui.calgrid import by_day, month_weeks, occurrence_days, weekday_names
from tcal.ui.widgets.minimonth import day_at
from tcal.ui.widgets.month_view import Grid
from tcal.ui.widgets.year_view import BLOCK_HEIGHT, Layout


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


def test_month_grid_geometry() -> None:
    weeks = month_weeks(2026, 11, 0)
    grid = Grid.build(weeks, width=90, height=37)
    assert sum(grid.widths) + 6 == 90
    assert grid.heights == [6] * 6 and grid.rule and grid.slots(0) == 4
    assert grid.at(0, 0) is None  # header
    assert grid.at(0, 1) == (0, 0, -1)  # separator
    assert grid.at(grid.xs[6], 2) == (0, 6, 0)  # day number of Nov 1
    assert grid.at(grid.xs[2] + 1, 1 + 6 * 3 + 3) == (3, 2, 2)  # 2nd chip of Wed 18
    tight = Grid.build(weeks, width=50, height=13)
    assert tight.heights == [2] * 6 and not tight.rule and tight.slots(0) == 1


def test_minimonth_day_at() -> None:
    nov = date(2026, 11, 1)
    assert day_at(nov, 0, 0, 1) == date(2026, 10, 26)
    assert day_at(nov, 0, 18, 1) == date(2026, 11, 1)
    assert day_at(nov, 0, 6, 4) == date(2026, 11, 18)
    assert day_at(nov, 0, 6, 0) is None  # weekday initials


def test_year_layout() -> None:
    wide = Layout.build(88, 40, month=10)
    assert wide.cols == 4 and wide.y0 >= 0
    assert wide.at(*wide.origin(10)) == (10, 0, 0)
    narrow = Layout.build(46, 17, month=10)  # 2 columns, only 2 rows fit
    assert narrow.cols == 2
    assert narrow.origin(10)[1] == BLOCK_HEIGHT  # November's row is on screen
    assert narrow.origin(0)[1] < 0  # January scrolled away
