from datetime import date

from tcal.ui.state import AppState, ViewMode


def test_periods() -> None:
    d = date(2026, 11, 18)  # Wednesday
    assert AppState(d, ViewMode.DAY).period() == (d, date(2026, 11, 19))
    assert AppState(d, ViewMode.WEEK).period() == (date(2026, 11, 16), date(2026, 11, 23))
    assert AppState(d, ViewMode.WEEK, week_start=6).period()[0] == date(2026, 11, 15)
    assert AppState(d, ViewMode.MONTH).period() == (date(2026, 11, 1), date(2026, 12, 1))
    assert AppState(d, ViewMode.YEAR).period() == (date(2026, 1, 1), date(2027, 1, 1))
    assert AppState(d, ViewMode.SCHEDULE).period() == (d, date(2026, 12, 2))


def test_shifted_clamps_month_end() -> None:
    assert AppState(date(2027, 1, 31), ViewMode.MONTH).shifted(1).day == date(2027, 2, 28)
    assert AppState(date(2026, 12, 31), ViewMode.WEEK).shifted(1).day == date(2027, 1, 7)
    assert AppState(date(2026, 1, 1), ViewMode.DAY).shifted(-1).day == date(2025, 12, 31)
    assert AppState(date(2026, 11, 18), ViewMode.SCHEDULE).shifted(-1).day == date(2026, 11, 4)


def test_titles() -> None:
    assert AppState(date(2026, 11, 18), ViewMode.WEEK).title() == "16 – 22 November 2026"
    assert AppState(date(2026, 12, 30), ViewMode.WEEK).title() == "28 Dec 2026 – 3 Jan 2027"
    assert AppState(date(2026, 11, 18), ViewMode.MONTH).title() == "November 2026"
    assert AppState(date(2026, 11, 18), ViewMode.SCHEDULE).title() == "November 2026"


def test_short_titles() -> None:
    assert AppState(date(2026, 11, 21), ViewMode.DAY).title(short=True) == "Sat 21 Nov 2026"
    assert AppState(date(2026, 11, 18), ViewMode.WEEK).title(short=True) == "16 – 22 Nov 2026"
    assert AppState(date(2026, 11, 18), ViewMode.MONTH).title(short=True) == "Nov 2026"
