"""Resizing: , . move the selected event's end and ; : its start by quarter hours."""

from datetime import date, datetime, time, timedelta

import pytest
from conftest import TODAY

from tcal.model import Event, Occurrence
from tcal.tz import local_midnight, local_zone
from tcal.ui.app import TcalApp
from tcal.ui.clipboard import quarter_step, shifted
from tcal.ui.screens.event_detail import ResizeScope
from tcal.ui.widgets.month_view import MonthView
from tcal.ui.widgets.schedule_view import ScheduleView
from tcal.ui.widgets.timegrid import TimeGrid

SIZE = (140, 50)


def at(hour: int, minute: int = 0, day: date = TODAY) -> datetime:
    return datetime.combine(day, time(hour, minute), local_zone())


def find(app: TcalApp, summary: str, day: date = TODAY) -> Occurrence:
    return next(o for o in app.occurrences(day, day + timedelta(1)) if o.summary == summary)


def span(app: TcalApp, summary: str, day: date = TODAY) -> tuple[datetime, datetime]:
    occ = find(app, summary, day)
    return occ.start, occ.end


def messages(app: TcalApp) -> list[str]:
    return [str(n.message) for n in app._notifications]


@pytest.mark.parametrize(
    ("minute", "step", "expected"),
    [(0, 1, 15), (0, -1, -15), (20, 1, 10), (20, -1, -5), (59, 1, 1), (45, 1, 15)],
)
def test_quarter_step_snaps_to_the_grid(minute: int, step: int, expected: int) -> None:
    assert quarter_step(at(10, minute), step) == timedelta(minutes=expected)


def test_shifted_start_over_midnight_shifts_the_series_days() -> None:
    event = Event(
        "u", "work", "S", at(0), at(1), rrule="FREQ=WEEKLY;BYDAY=WE", exdates=(at(0, day=TODAY),)
    )
    moved = shifted(event, timedelta(minutes=-15), timedelta(0))
    assert moved is not None
    assert (moved.start, moved.end) == (at(23, 45, TODAY - timedelta(1)), at(1))
    assert moved.rrule == "FREQ=WEEKLY;BYDAY=TU"
    assert moved.exdates == (moved.start,)


@pytest.mark.parametrize("view", ["day", "week"])
@pytest.mark.parametrize("grid_mode", [False, True])
async def test_keys_move_the_end_and_the_start(make_app, view: str, grid_mode: bool) -> None:
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        app.action_set_view(view)
        app.set_grid_mode(grid_mode)
        await pilot.pause()
        grid = app.query_one(f"#{view}", TimeGrid)
        grid.select(find(app, "Dentist"))  # 11:00 - 12:00
        for key, expected in [
            ("full_stop", (at(11), at(12, 15))),
            ("shift+down", (at(11), at(12, 30))),
            ("comma", (at(11), at(12, 15))),
            ("shift+up", (at(11), at(12))),
            ("semicolon", (at(10, 45), at(12))),
            ("colon", (at(11), at(12))),
            (":", (at(11, 15), at(12))),  # as typed
            (".", (at(11, 15), at(12, 15))),
            (",", (at(11, 15), at(12))),
            (";", (at(11), at(12))),
        ]:
            await pilot.press(key)
            await pilot.pause()
            assert span(app, "Dentist") == expected, key
            assert grid.selected is not None and grid.selected == find(app, "Dentist")


async def test_undo_takes_back_each_step(make_app) -> None:
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        grid = app.query_one("#week", TimeGrid)
        grid.select(find(app, "Dentist"))
        await pilot.press("full_stop", "semicolon")
        await pilot.pause()
        assert span(app, "Dentist") == (at(10, 45), at(12, 15))
        await pilot.press("u")
        await pilot.pause()
        assert span(app, "Dentist") == (at(11), at(12, 15))
        assert grid.selected == find(app, "Dentist")
        await pilot.press("u")
        await pilot.pause()
        assert span(app, "Dentist") == (at(11), at(12))
        assert "Undid resize of “Dentist” (back to Wed 18 Nov 2026, 11:00 – 12:00)" in messages(app)


async def test_events_stay_at_least_15_min_long(make_app, store) -> None:
    store.save_event(Event("short@x", "family", "Short", at(15), at(15, 20)))
    store.save_event(Event("tiny@x", "family", "Tiny", at(16, 5), at(16, 10)))
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        grid = app.query_one("#week", TimeGrid)
        grid.select(find(app, "Short"))
        await pilot.press("colon")  # 15:15 - 15:20 would be too short
        await pilot.pause()
        assert span(app, "Short") == (at(15), at(15, 20))
        assert messages(app) == ["Events are at least 15 min long"]
        await pilot.press("comma")
        await pilot.pause()
        assert span(app, "Short") == (at(15), at(15, 15))
        await pilot.press("comma")
        await pilot.pause()
        assert span(app, "Short") == (at(15), at(15, 15))
        await pilot.press("u")  # the refused steps are not on the undo stack
        await pilot.pause()
        assert span(app, "Short") == (at(15), at(15, 20))

        grid.select(find(app, "Tiny"))  # shorter already: growing is fine
        await pilot.press("full_stop")
        await pilot.pause()
        assert span(app, "Tiny") == (at(16, 5), at(16, 15))


async def test_over_midnight(make_app) -> None:
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        grid = app.query_one("#week", TimeGrid)
        grid.select(find(app, "Late movie"))  # 22:30 - 23:59
        await pilot.press("full_stop", "full_stop")
        await pilot.pause()
        assert span(app, "Late movie") == (at(22, 30), at(0, 15, TODAY + timedelta(1)))
        assert app.state.day == TODAY and grid.selected == find(app, "Late movie")


async def test_resized_event_is_scrolled_into_view(make_app) -> None:
    app = make_app()
    async with app.run_test(size=(140, 24)) as pilot:
        await pilot.press("plus", "plus", "plus")
        grid = app.query_one("#week", TimeGrid)
        grid.select(find(app, "Dentist"))
        for _ in range(6):
            await pilot.press("full_stop")
        await pilot.pause()
        rows, top = grid._focus_rows(), grid._top_row()
        assert top <= rows.start and rows.stop <= top + grid._grid_height()


async def test_only_timed_events_in_a_time_grid(make_app) -> None:
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("full_stop")
        assert messages(app) == ["No event selected"]
        app.query_one("#week", TimeGrid).select(find(app, "Anna's birthday"))
        await pilot.press("full_stop")
        await pilot.pause()
        assert span(app, "Anna's birthday")[0] == local_midnight(TODAY)
        assert messages(app)[-1] == "All-day event: only timed events can be resized"
        yesterday = TODAY - timedelta(1)
        gym = span(app, "Gym", yesterday)
        for key, view in (("m", MonthView), ("s", ScheduleView)):
            await pilot.press(key)
            await pilot.pause()
            app.query_one(view).select(find(app, "Gym", yesterday))
            await pilot.press("full_stop")
            await pilot.pause()
            assert span(app, "Gym", yesterday) == gym
            assert messages(app)[-1] == "Resizing works in the day/week view"


async def test_read_only_calendar(make_app, store) -> None:
    store.save_event(Event("ro@x", "holidays", "Fixed", at(15), at(16)))
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        app.query_one("#week", TimeGrid).select(find(app, "Fixed"))
        await pilot.press("full_stop", "colon")
        await pilot.pause()
        assert span(app, "Fixed") == (at(15), at(16))
        assert messages(app) == ["Holidays is read-only"] * 2


async def test_series_this_event_or_all_events(make_app) -> None:
    app = make_app()
    tomorrow, yesterday = TODAY + timedelta(1), TODAY - timedelta(1)
    async with app.run_test(size=SIZE) as pilot:
        grid = app.query_one("#week", TimeGrid)
        start, end = span(app, "Standup")
        quarter = timedelta(minutes=15)
        grid.select(find(app, "Standup"))
        await pilot.press("full_stop")
        await pilot.pause()
        assert isinstance(app.screen, ResizeScope)
        await pilot.press("o", "full_stop")  # this event; the override just resizes on
        await pilot.pause()
        assert not isinstance(app.screen, ResizeScope)
        assert span(app, "Standup") == (start, end + 2 * quarter)
        assert span(app, "Standup", tomorrow)[1] == end + timedelta(1)

        grid.select(find(app, "Standup", tomorrow))
        await pilot.press("semicolon", "s", "full_stop")  # all events, asked once
        await pilot.pause()
        assert not isinstance(app.screen, ResizeScope)
        for day, n in ((yesterday, -1), (tomorrow, 1)):
            by = timedelta(n)
            assert span(app, "Standup", day) == (start + by - quarter, end + by + quarter)
        assert grid.selected == find(app, "Standup", tomorrow)
        await pilot.press("u", "u")
        await pilot.pause()
        assert span(app, "Standup", tomorrow) == (start + timedelta(1), end + timedelta(1))
        assert span(app, "Standup") == (start, end + 2 * quarter)
