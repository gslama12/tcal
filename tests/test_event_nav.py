"""Week event mode (the default: cursor keys move between events) and grid mode (v)."""

from datetime import datetime, time, timedelta

import pytest
from conftest import TODAY, RecordingApp

from tcal.ui import messages
from tcal.ui.widgets import timegrid
from tcal.ui.widgets.statusbar import StatusBar
from tcal.ui.widgets.timegrid import TimeGrid

NOW = datetime.combine(TODAY, time(10, 15)).astimezone()
SIZE = (140, 45)


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(timegrid, "now", lambda: NOW)


def at(hhmm: str, day=TODAY) -> datetime:
    return datetime.combine(day, datetime.strptime(hhmm, "%H:%M").time(), NOW.tzinfo)


def summary(grid: TimeGrid) -> str | None:
    return grid.selected.summary if grid.selected else None


def body(grid: TimeGrid) -> str:
    return "\n".join(grid.render_line(y).text for y in range(grid.size.height))


async def test_up_down_step_through_the_day(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        grid = app.query_one(TimeGrid)
        assert not app.state.grid and grid.selected is None
        await pilot.press("j")  # nothing selected: the first event, all-day ones first
        assert grid.selected is not None and grid.selected.all_day
        await pilot.press("j", "j")
        assert summary(grid) == "Early run"
        assert "Early run" in body(grid)  # scrolled up to 05:45
        await pilot.press("j", "j")
        assert summary(grid) == "Design review"
        await pilot.press("k")
        assert summary(grid) == "Standup" and app.state.day == TODAY


async def test_up_with_nothing_selected_picks_the_last_and_stops_at_the_end(
    app: RecordingApp,
) -> None:
    async with app.run_test(size=SIZE) as pilot:
        grid = app.query_one(TimeGrid)
        await pilot.press("k")
        assert summary(grid) == "Late movie"
        assert "Late movie" in body(grid)
        await pilot.press("j")  # the last: stays
        assert summary(grid) == "Late movie"
        await pilot.press("k")
        assert summary(grid) == "Dinner"


async def test_left_right_pick_the_nearest_event_and_cross_weeks(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        grid = app.query_one(TimeGrid)
        await pilot.press("k", "k", "k")
        assert summary(grid) == "Dentist"  # 11:00-12:00
        await pilot.press("l")  # Thu: Standup 9:00 is nearer than Release 14:00
        assert app.state.day == TODAY + timedelta(days=1) and summary(grid) == "Standup"
        await pilot.press("l", "l")  # Fri: Standup 9:00; Sat: empty, the day only
        assert app.state.day == TODAY + timedelta(days=3) and grid.selected is None
        await pilot.press("l")  # Sun: the nearest to 9:00 is Call mum
        assert summary(grid) == "Call mum"
        await pilot.press("l")  # next week's Monday
        assert "Mon 23" in body(grid) and app.state.day == TODAY + timedelta(days=5)
        await pilot.press("h")
        assert "Sun 22" in body(grid) and summary(grid) == "Call mum"


async def test_all_day_event_goes_to_the_next_days_all_day_event(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        grid = app.query_one(TimeGrid)
        await pilot.press("j", "j")
        assert summary(grid) == "Conference"
        await pilot.press("l")
        assert summary(grid) == "Conference"  # Wed-Fri: also Thursday's first bar


async def test_grid_mode_toggles_and_leaving_selects_the_event_at_the_cursor(
    app: RecordingApp,
) -> None:
    async with app.run_test(size=SIZE) as pilot:
        grid = app.query_one(TimeGrid)
        bar = app.query_one(StatusBar)
        assert "WEEK · GRID" not in str(bar.render())
        await pilot.press("v")
        assert app.state.grid and "WEEK · GRID" in str(bar.render())
        assert grid.cursor_time == at("10:00")
        await pilot.press("j")
        assert grid.cursor_time == at("11:00")
        await pilot.press("escape")  # back; the event under the cursor is selected
        assert not app.state.grid and summary(grid) == "Dentist"
        await pilot.press("v", "k", "k", "k", "v")  # 08:00: nearest Standup
        assert not app.state.grid and summary(grid) == "Standup"


async def test_enter_and_new_event_in_event_mode(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("k", "k", "k", "enter", "a")  # Dentist: open, then a after it
        opened, new = app.posted
        assert isinstance(opened, messages.EventSelected) and opened.occurrence.summary == "Dentist"
        assert isinstance(new, messages.NewEventRequested) and new.start == at("12:00")
        saturday = TODAY + timedelta(days=3)
        await pilot.press("l", "l", "l", "a", "enter")  # Sat: empty, the next full hour
        await pilot.press("v", "i")  # grid mode: at the cursor slot (kept from Fri's 9:00)
        starts = [m.start for m in app.posted[2:] if isinstance(m, messages.NewEventRequested)]
        assert starts == [at("11:00", saturday)] * 2 + [at("09:00", saturday)]


async def test_paste_lands_at_the_selected_events_time(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("k", "k", "k", "y", "j", "p")  # copy Dentist, paste at Dinner
        day = app.occurrences(TODAY, TODAY + timedelta(days=1))
        copies = [o for o in day if o.summary == "Dentist"]
        assert sorted(o.start for o in copies) == [at("11:00"), at("19:00")]
