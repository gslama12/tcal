from datetime import date, datetime, time

import pytest
from conftest import TODAY
from test_views import SIZE, RecordingApp

from tcal.model import Event, Occurrence
from tcal.store import Store
from tcal.ui.calgrid import month_weeks, occurrence_days
from tcal.ui.messages import EventSelected, NewEventRequested
from tcal.ui.widgets.month_view import Grid, MonthView, layout_week

WEEK = month_weeks(2026, 11, 0)[3]  # Mon 16 .. Sun 22 Nov 2026


@pytest.fixture
def app(store: Store) -> RecordingApp:
    return RecordingApp(store)


def occ(summary: str, start: datetime, end: datetime, all_day: bool = False) -> Occurrence:
    event = Event(
        uid=summary, calendar_id="c", summary=summary, start=start, end=end, all_day=all_day
    )
    return Occurrence(event, start, end)


def day(d: date, hour: int = 0) -> datetime:
    return datetime.combine(d, time(hour)).astimezone()


def test_grid_rows_share_the_full_height() -> None:
    weeks = month_weeks(2026, 11, 0)  # 6 weeks
    grid = Grid.build(weeks, 70, 29)
    assert sum(grid.heights) == 28 and set(grid.heights) == {4, 5}
    assert grid.tops[0] == 1 and grid.tops[-1] + grid.heights[-1] == 29
    assert grid.widths[-1] >= grid.widths[0]  # spare columns go to the weekend, not Monday


def test_layout_week_keeps_a_bar_in_one_lane() -> None:
    trip = occ("Trip", day(WEEK[1]), day(WEEK[4]), all_day=True)  # Tue..Thu
    dentist = occ("Dentist", day(WEEK[2], 11), day(WEEK[2], 12))
    party = occ("Party", day(WEEK[5]), day(WEEK[6]), all_day=True)
    cells = layout_week(WEEK, [dentist, trip, party], slots=3)
    assert [cells[i][:1] for i in range(1, 4)] == [[trip]] * 3
    assert cells[2] == [trip, dentist] and cells[0] == [] and cells[5] == [party]


def test_layout_week_overflow_counts_hidden_events() -> None:
    timed = [occ(f"E{h}", day(WEEK[0], h), day(WEEK[0], h + 1)) for h in range(8, 12)]
    assert layout_week(WEEK, timed, slots=2)[0] == [timed[0], 3]
    assert layout_week(WEEK, timed, slots=1)[0] == [4]
    assert layout_week(WEEK, timed, slots=0)[0] == []


async def test_multi_day_bar_title_once(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("m")
        await pilot.pause()
        rendered = str(app.query_one(MonthView).render())
        assert rendered.count("Conference") == 1  # Wed..Fri drawn as one bar


async def test_month_event_cursor(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("m")
        view = app.query_one(MonthView)
        assert view.selected is None and app.selected_occurrence() is None
        today = app.state.day
        await pilot.press("n")  # the first event on or after the selected day
        first = view.selected
        assert first is not None and app.selected_occurrence() == first
        assert max(occurrence_days(first)) >= today and app.state.day >= today
        stops = [occ for occ, _ in view._stops()]
        before = stops[: stops.index(first)]
        assert before and all(max(occurrence_days(occ)) < today for occ in before)
        await pilot.press("n", "N")
        assert view.selected == first
        await pilot.press("N")
        assert view.selected == before[-1]
        await pilot.press("enter")
        assert isinstance(app.posted[-1], EventSelected)
        assert app.posted[-1].occurrence == view.selected
        await pilot.press("l")  # moving the day drops the event cursor
        assert view.selected is None
        await pilot.press("enter")
        assert app.state.view.value == "day"


async def test_month_cursor_reaches_todays_events(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("m")
        view = app.query_one(MonthView)
        seen = set()
        for _ in range(60):
            await pilot.press("n")
            assert view.selected is not None
            seen.add((view.selected.summary, app.state.day))
        assert ("Conference", TODAY) in seen
        assert all(d.month == TODAY.month for _, d in seen)  # stays in the shown month


async def test_month_double_click_requests_all_day_event(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("m")
        view = app.query_one(MonthView)
        grid = view.grid()
        week, column = 1, 2  # Wed 4 Nov
        target = grid.weeks[week][column]
        y = grid.tops[week] + grid.rule + grid.slots(week)  # the cell's last chip line
        offset = (grid.xs[column] + 2 + view.gutter.left, y + view.gutter.top)
        await pilot.click(MonthView, offset=offset, times=2)
        assert app.state.day == target and len(app.posted) == 1
        assert isinstance(app.posted[0], NewEventRequested) and app.posted[0].start == target


async def test_month_chip_times_are_zero_padded(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("m")
        rendered = str(app.query_one(MonthView).render())
        assert "09:00" in rendered and " 9:00" not in rendered
