from datetime import date, datetime, time, timedelta

from conftest import TODAY, RecordingApp
from test_views import SIZE, content

from tcal.model import Event, Occurrence
from tcal.ui.calgrid import month_weeks, occurrence_days
from tcal.ui.messages import EventSelected, NewEventRequested
from tcal.ui.state import ViewMode
from tcal.ui.widgets.month_view import Grid, MonthView, layout_week

WEEK = month_weeks(2026, 11, 0)[3]  # Mon 16 .. Sun 22 Nov 2026


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
        assert "more" in rendered and "Nov 1" in rendered


async def test_month_selected_event(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("m")
        view = app.query_one(MonthView)
        assert view.selected is None and app.selected_occurrence() is None
        picked = next(o for o in view._shown() if o.summary == "Conference")
        view.select(picked)
        assert view.selected == picked and app.selected_occurrence() == picked
        assert app.state.day == picked.start.date()
        await pilot.press("enter")
        assert isinstance(app.posted[-1], EventSelected)
        assert app.posted[-1].occurrence == picked
        await pilot.press("l")  # moving the day drops the selection
        assert view.selected is None
        await pilot.press("enter")
        assert app.state.view.value == "week"


async def test_month_shows_only_its_own_days_events(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("m")
        shown = list(app.query_one(MonthView)._shown())
        assert "Conference" in {o.summary for o in shown}
        assert all(any(d.month == TODAY.month for d in occurrence_days(o)) for o in shown)


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


async def test_cut_chips_end_with_an_ellipsis(app: RecordingApp) -> None:
    async with app.run_test(size=(100, 35)) as pilot:
        await pilot.press("m")
        await pilot.pause()
        rendered = str(app.query_one(MonthView).render())
        assert "09:00 Stand…" in rendered and "Call m…" in rendered
        assert "09:00 Standu│" not in rendered and "Standup│" not in rendered


async def test_month_view_navigation(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("m", "l", "j")
        assert app.state.day == TODAY + timedelta(days=8)
        await pilot.press("k", "k", "k", "k")
        assert app.state.day == date(2026, 10, 29)  # crossed into October
        assert app.state.title() == "October 2026"
        await pilot.press("enter")
        assert app.state.view is ViewMode.WEEK


async def test_month_view_clicks(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("m")
        await pilot.pause()
        view = app.query_one(MonthView)
        grid = view.grid()
        week = next(i for i, w in enumerate(grid.weeks) if TODAY in w)
        x = grid.xs[TODAY.weekday()] + 1
        y = grid.tops[week] + grid.rule  # TODAY's day-number line
        first_chip = view.week_cells(grid)[week][TODAY.weekday()][0]
        await pilot.click(MonthView, offset=content(view, x, y + 1))
        assert isinstance(app.posted[-1], EventSelected)
        assert app.posted[-1].occurrence == first_chip
        await pilot.click(MonthView, offset=content(view, x, y))
        assert app.state.view is ViewMode.WEEK and app.state.day == TODAY
