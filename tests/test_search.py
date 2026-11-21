from datetime import datetime, time, timedelta

import pytest
from conftest import TODAY

from tcal.model import Event, Occurrence
from tcal.recurrence import expand
from tcal.ui.app import TcalApp
from tcal.ui.screens.event_detail import EventDetail
from tcal.ui.screens.search import ResultList, SearchScreen, search
from tcal.ui.state import ViewMode
from tcal.ui.widgets.month_view import MonthView
from tcal.ui.widgets.timegrid import WeekView

NOW = datetime.combine(TODAY, time(12, 0)).astimezone()


def occ(uid: str, days: int, summary: str = "x", **fields) -> Occurrence:
    start = NOW + timedelta(days=days)
    ev = Event(uid, "work", summary, start, start + timedelta(hours=1), **fields)
    return Occurrence(ev, ev.start, ev.end)


def test_matches_summary_location_notes_case_insensitive() -> None:
    occs = [
        occ("a", 1, "Design Review"),
        occ("b", 2, location="Room DESIGN"),
        occ("c", 3, description="bring design docs"),
        occ("d", 4, "Lunch"),
    ]
    assert [o.event.uid for o in search(occs, "  design ", NOW)] == ["a", "b", "c"]
    assert search(occs, "", NOW) == []
    assert search(occs, "nothing", NOW) == []


def test_upcoming_first_then_past_latest_first() -> None:
    occs = [occ("p2", -9), occ("u2", 5), occ("p1", -1), occ("u1", 1)]
    occs.append(occ("running", 0))  # started now, ends in an hour: still upcoming
    order = [o.event.uid for o in search(occs, "x", NOW)]
    assert order == ["running", "u1", "u2", "p1", "p2"]


def test_series_listed_once_by_next_instance() -> None:
    start = NOW - timedelta(days=14)
    weekly = Event("w", "work", "Standup", start, start + timedelta(hours=1), rrule="FREQ=WEEKLY")
    occs = expand([weekly], NOW - timedelta(days=30), NOW + timedelta(days=30))
    found = search(occs, "standup", NOW + timedelta(hours=2))
    assert [o.start.date() for o in found] == [(NOW + timedelta(days=7)).date()]
    past = search(occs, "standup", NOW + timedelta(days=60))
    assert [o.start.date() for o in past] == [(NOW + timedelta(days=28)).date()]


@pytest.fixture
def app(make_app) -> TcalApp:
    return make_app()


async def test_search_keeps_the_view_selects_and_opens(app: TcalApp) -> None:
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.press("slash")
        assert isinstance(app.screen, SearchScreen)
        await pilot.press(*"kids")
        results = app.screen.query_one(ResultList)
        assert results.option_count == 1
        assert "Kids' play" in str(results.get_option_at_index(0).prompt)
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, EventDetail)
        assert app.screen.occ.summary == "Kids' play"
        await pilot.press("escape")
        assert app.state.view is ViewMode.WEEK
        assert app.state.day == TODAY - timedelta(days=5)
        view = app.query_one(WeekView)
        assert app.focused is view
        assert view.selected is not None and view.selected.summary == "Kids' play"


async def test_search_list_navigation(app: TcalApp) -> None:
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.press("slash", *"e")
        screen = app.screen
        assert isinstance(screen, SearchScreen)
        results = screen.query_one(ResultList)
        assert results.option_count > 2 and results.highlighted == 0
        await pilot.press("down", "down", "up")
        assert results.highlighted == 1
        await pilot.press("tab", "j", "j", "k")
        assert app.focused is results and results.highlighted == 2
        await pilot.press("escape", "m", "slash", *"kids")  # in the month view
        assert isinstance(app.screen, SearchScreen)
        picked = app.screen.results[0]
        await pilot.press("enter", "escape")
        await pilot.pause()
        assert app.state.view is ViewMode.MONTH
        assert app.state.day == picked.start.date()
        assert app.query_one(MonthView).selected == picked


async def test_search_escape_cancels(app: TcalApp) -> None:
    async with app.run_test() as pilot:
        await pilot.press("slash", *"dinner", "escape")
        assert not isinstance(app.screen, SearchScreen)
        assert app.state.view is ViewMode.WEEK and app.state.day == TODAY


async def test_search_says_a_series_repeats(app: TcalApp) -> None:
    async with app.run_test(size=(140, 45)) as pilot:  # QA4 #19
        await pilot.press("slash", *"gym")
        results = app.screen.query_one(ResultList)
        assert results.option_count == 1
        assert "Gym · every week on Tue, Thu" in str(results.get_option_at_index(0).prompt)
