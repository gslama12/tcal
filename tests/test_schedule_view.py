from datetime import date, datetime, timedelta

import pytest
from conftest import TODAY
from test_views import SIZE, RecordingApp

from tcal.model import Event, Occurrence
from tcal.store import Store
from tcal.tz import local_zone
from tcal.ui.messages import EventSelected
from tcal.ui.state import AppState, ViewMode
from tcal.ui.widgets.schedule_view import CHUNK_DAYS, ScheduleView, build_rows, time_range

ZONE = local_zone()


def occ(day: date, start: str, end: str, end_day: date | None = None) -> Occurrence:
    begin = datetime.combine(day, datetime.strptime(start, "%H:%M").time(), ZONE)
    finish = datetime.combine(end_day or day, datetime.strptime(end, "%H:%M").time(), ZONE)
    return Occurrence(Event("u", "c", "x", begin, finish), begin, finish)


def test_time_range() -> None:
    assert time_range(occ(TODAY, "09:00", "10:30"), TODAY) == "09:00 – 10:30"
    night = occ(TODAY, "22:00", "02:00", TODAY + timedelta(days=1))
    assert time_range(night, TODAY) == "22:00 –"
    assert time_range(night, TODAY + timedelta(days=1)) == "– 02:00"
    long = occ(TODAY, "22:00", "02:00", TODAY + timedelta(days=2))
    assert time_range(long, TODAY + timedelta(days=1)) == "All day"


def test_build_rows_skips_empty_days() -> None:
    later = TODAY + timedelta(days=3)
    a, b = occ(TODAY, "09:00", "10:00"), occ(later, "12:00", "13:00")
    rows = build_rows([b, a, occ(TODAY - timedelta(days=1), "09:00", "10:00")], TODAY, later)
    assert [(r.day, r.occ, r.blank) for r in rows] == [(TODAY, None, False), (TODAY, a, False)]
    rows = build_rows([a, b], TODAY, later + timedelta(days=1))
    assert [r.blank for r in rows] == [False, False, True, False, False]


def test_state_schedule_period() -> None:
    state = AppState(TODAY, ViewMode.SCHEDULE)
    assert state.period() == (TODAY, TODAY + timedelta(days=14))
    assert state.shifted(-1).day == TODAY - timedelta(days=14)
    assert state.title() == "November 2026"


@pytest.fixture
def app(store: Store) -> RecordingApp:
    return RecordingApp(store)


async def test_schedule_navigation(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("s")
        view = app.query_one(ScheduleView)
        assert app.state.view is ViewMode.SCHEDULE and app.focused is view
        assert view.selected is not None and view.selected.summary == "Anna's birthday"
        assert all(row.day >= TODAY for row in view._rows)
        await pilot.press("j")
        assert view.selected.summary == "Conference"
        assert app.selected_occurrence() is view.selected
        await pilot.press("enter")
        assert isinstance(app.posted[-1], EventSelected)
        assert app.posted[-1].occurrence.summary == "Conference"
        await pilot.press("l")  # next day's first event, list not restarted
        assert app.state.day == TODAY + timedelta(days=1) and view._start == TODAY
        await pilot.press("h")
        assert view.selected.summary == "Anna's birthday"
        await pilot.press("L")  # two weeks on: the list starts there
        assert app.state.day == view._start == TODAY + timedelta(days=14)
        await pilot.press("H")
        assert view._start == TODAY and view.selected.summary == "Anna's birthday"


async def test_schedule_loads_more_and_scrolls(app: RecordingApp) -> None:
    async with app.run_test(size=(120, 20)) as pilot:
        await pilot.press("s")
        view = app.query_one(ScheduleView)
        for _ in range(30):  # a day at a time, past the first loaded chunk
            await pilot.press("l")
        await pilot.press("j")
        assert view._end > TODAY + timedelta(days=CHUNK_DAYS)
        assert view._cursor is not None
        assert view._top <= view._cursor < view._top + view.content_size.height
        top = view._top
        await pilot.press("k")
        assert view._top <= top


async def test_schedule_follows_hidden_calendars(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("s")
        view = app.query_one(ScheduleView)
        app.toggle_calendar("family")
        await pilot.pause()
        assert all(row.occ.calendar_id != "family" for row in view._rows if row.occ)
        assert view.selected is not None and view.selected.summary == "Conference"


async def test_schedule_screenshot(app: RecordingApp, tmp_path) -> None:
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("s")
        text = app.query_one(ScheduleView).render()
        assert "Wed 18 Nov" in str(text) and "Room 4" in str(text)
        app.save_screenshot(str(tmp_path / "schedule.svg"))
