from dataclasses import replace
from datetime import date, datetime, time, timedelta

import pytest
from conftest import TODAY

from tcal.model import Event, Occurrence
from tcal.tz import local_midnight, local_zone
from tcal.ui.clipboard import copy_at, shifted
from tcal.ui.screens.event_detail import MoveScope
from tcal.ui.widgets.month_view import MonthView
from tcal.ui.widgets.timegrid import TimeGrid


def at(hour: int, minute: int = 0, day: date = TODAY) -> datetime:
    return datetime.combine(day, time(hour, minute), local_zone())


def find(app, summary: str, day: date = TODAY) -> Occurrence:
    return next(o for o in app.occurrences(day, day + timedelta(1)) if o.summary == summary)


def named(app, summary: str, start: date, days: int = 14) -> list[Occurrence]:
    return [o for o in app.occurrences(start, start + timedelta(days)) if o.summary == summary]


def test_copy_at_keeps_duration_and_drops_the_series() -> None:
    master = Event("u", "work", "Standup", at(9), at(9, 15), rrule="FREQ=DAILY", exdates=(at(9),))
    occ = Occurrence(master, at(9), at(9, 15))
    copy = copy_at(occ, at(14, 30), "home")
    assert (copy.start, copy.end, copy.calendar_id) == (at(14, 30), at(14, 45), "home")
    assert copy.uid != "u" and copy.rrule is None and copy.exdates == () and copy.href is None
    on_day = copy_at(occ, TODAY + timedelta(2), "home")  # a day keeps the time of day
    assert on_day.start == at(9, day=TODAY + timedelta(2))


def test_copy_at_all_day_keeps_its_days() -> None:
    start = local_midnight(TODAY)
    trip = Event("t", "family", "Trip", start, local_midnight(TODAY + timedelta(3)), all_day=True)
    copy = copy_at(Occurrence(trip, trip.start, trip.end), at(10, day=TODAY + timedelta(7)), "x")
    assert copy.all_day
    assert copy.start == local_midnight(TODAY + timedelta(7))
    assert copy.end == local_midnight(TODAY + timedelta(10))


def test_shifted_moves_exdates_along() -> None:
    event = Event("u", "work", "S", at(9), at(10), rrule="FREQ=DAILY", exdates=(at(9, day=TODAY),))
    moved = shifted(event, timedelta(days=1))
    assert moved is not None
    assert moved.start == at(9, day=TODAY + timedelta(1))
    assert moved.exdates == (at(9, day=TODAY + timedelta(1)),)


@pytest.mark.parametrize(
    ("rrule", "days", "expected"),
    [
        ("FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR", 1, "FREQ=WEEKLY;BYDAY=TU,WE,TH,FR,SA"),
        ("FREQ=WEEKLY;BYDAY=TU,TH", -1, "FREQ=WEEKLY;BYDAY=MO,WE"),
        ("FREQ=WEEKLY;BYDAY=SU;COUNT=3", 1, "FREQ=WEEKLY;BYDAY=MO;COUNT=3"),
        ("FREQ=WEEKLY;BYDAY=MO", 7, "FREQ=WEEKLY;BYDAY=MO"),
        ("FREQ=DAILY", 1, "FREQ=DAILY"),
        ("FREQ=MONTHLY;BYDAY=2MO", 1, None),
    ],
)
def test_shifted_moves_byday_weekdays(rrule: str, days: int, expected: str | None) -> None:
    moved = shifted(Event("u", "work", "S", at(9), at(10), rrule=rrule), timedelta(days=days))
    assert (moved.rrule if moved else None) == expected
    assert shifted(Event("u", "work", "S", at(9), at(10), rrule=rrule), timedelta(hours=1))


async def test_move_weekday_series_by_a_day_keeps_every_instance(make_app) -> None:
    app = make_app()
    async with app.run_test(size=(140, 50)) as pilot:
        grid = app.query_one("#week", TimeGrid)
        monday = TODAY - timedelta(TODAY.weekday())
        grid.select(find(app, "Standup"))
        await pilot.press(">", "s")
        await pilot.pause()
        days = [o.start.date() for o in named(app, "Standup", monday, 7)]
        assert days == [monday + timedelta(i) for i in range(1, 6)]  # Tue..Sat
        await pilot.press("u")
        assert "Undid move of all “Standup” events (back to Wed 18 09:00)" in [
            str(n.message) for n in app._notifications
        ]


async def test_yank_and_paste_at_the_cursor_slot(make_app) -> None:
    app = make_app()
    async with app.run_test(size=(140, 50)) as pilot:
        grid = app.query_one("#week", TimeGrid)
        grid.select(find(app, "Dentist"))
        await pilot.press("y", "l")  # yank, then the next day (cursor stays at 11:00)
        cursor = grid.cursor_time
        await pilot.press("p")
        await pilot.pause()
        copies = named(app, "Dentist", TODAY + timedelta(1), 1)
        assert [(o.start, o.end - o.start) for o in copies] == [(cursor, timedelta(hours=1))]
        assert grid.selected == copies[0]
        assert len(named(app, "Dentist", TODAY, 1)) == 1  # the original stays


async def test_paste_in_month_view_uses_the_selected_day(make_app) -> None:
    app = make_app()
    async with app.run_test(size=(140, 50)) as pilot:
        await pilot.press("p")
        assert app.editor.yanked is None  # nothing to paste yet
        app.query_one("#week", TimeGrid).select(find(app, "Dinner"))
        await pilot.press("y", "m", "l", "l", "P")
        await pilot.pause()
        day = TODAY + timedelta(2)
        [copy] = named(app, "Dinner", day, 1)
        assert copy.start == at(19, day=day)
        assert app.query_one(MonthView).selected == copy


async def test_duplicate_to_the_next_day(make_app) -> None:
    app = make_app()
    async with app.run_test(size=(140, 50)) as pilot:
        app.query_one("#week", TimeGrid).select(find(app, "Late movie"))
        await pilot.press("D")
        await pilot.pause()
        tomorrow = TODAY + timedelta(1)
        [copy] = named(app, "Late movie", tomorrow, 1)
        assert (copy.start, copy.end) == (at(22, 30, tomorrow), at(23, 59, tomorrow))
        assert app.state.day == tomorrow


async def test_move_by_quarter_hours_and_days(make_app) -> None:
    app = make_app()
    async with app.run_test(size=(140, 50)) as pilot:
        grid = app.query_one("#week", TimeGrid)
        grid.select(find(app, "Dentist"))
        await pilot.press("ctrl+j", "ctrl+j", "ctrl+k", "ctrl+l")
        await pilot.pause()
        [moved] = named(app, "Dentist", TODAY - timedelta(7))
        tomorrow = TODAY + timedelta(1)
        assert (moved.start, moved.end) == (at(11, 15, tomorrow), at(12, 15, tomorrow))
        assert grid.selected == moved and app.state.day == tomorrow
        await pilot.press("ctrl+h")
        await pilot.pause()
        assert named(app, "Dentist", TODAY - timedelta(7))[0].start == at(11, 15)


async def test_move_by_time_needs_a_timed_event_in_a_time_grid(make_app) -> None:
    app = make_app()
    async with app.run_test(size=(140, 50)) as pilot:
        grid = app.query_one("#week", TimeGrid)
        grid.select(find(app, "Anna's birthday"))
        await pilot.press("ctrl+j")
        await pilot.pause()
        assert find(app, "Anna's birthday").start == local_midnight(TODAY)
        await pilot.press("ctrl+l")  # by day works
        await pilot.pause()
        assert named(app, "Anna's birthday", TODAY)[0].start == local_midnight(TODAY + timedelta(1))


async def test_move_respects_readonly_calendars(make_app) -> None:
    app = make_app()
    holiday = TODAY + timedelta(16)
    async with app.run_test(size=(140, 50)) as pilot:
        app.select_date(holiday)
        await pilot.pause()
        app.query_one("#week", TimeGrid).select(find(app, "Public holiday", holiday))
        await pilot.press("ctrl+l", "D")
        await pilot.pause()
        originals = named(app, "Public holiday", holiday - timedelta(7))
        starts = [o.start for o in originals if o.calendar_id == "holidays"]
        assert starts == [local_midnight(holiday)]
        # a copy of a read-only event goes to a writable calendar
        [copy] = named(app, "Public holiday", holiday + timedelta(1), 1)
        assert not app.calendar(copy.calendar_id).readonly


async def test_move_one_instance_or_the_series(make_app) -> None:
    app = make_app()
    async with app.run_test(size=(140, 50)) as pilot:
        grid = app.query_one("#week", TimeGrid)
        grid.select(find(app, "Standup"))
        await pilot.press("ctrl+j")
        await pilot.pause()
        assert isinstance(app.screen, MoveScope)
        await pilot.press("o")  # this event
        await pilot.pause()
        starts = {o.start for o in named(app, "Standup", TODAY - timedelta(2), 5)}
        assert at(9, 15) in starts and at(9) not in starts
        assert at(9, day=TODAY + timedelta(1)) in starts
        assert grid.selected is not None and grid.selected.start == at(9, 15)

        grid.select(find(app, "Standup", TODAY + timedelta(1)))
        await pilot.press("ctrl+k", "s")  # all events
        await pilot.pause()
        starts = {o.start for o in named(app, "Standup", TODAY - timedelta(2), 5)}
        assert at(8, 45, TODAY + timedelta(1)) in starts
        assert at(8, 45, TODAY - timedelta(1)) in starts


def resynced(app, store, uid: str) -> None:
    """What a background sync does to a pushed event: a new etag, then a redraw."""
    event = store.get_event(uid)
    store.set_remote(uid, event.href, f"{event.etag}-synced")
    app.refresh_data()


async def test_moved_event_stays_selected_after_a_sync(make_app, store) -> None:
    app = make_app()
    tomorrow = TODAY + timedelta(1)
    store.save_event(
        Event("other@x", "family", "Other", at(11, day=tomorrow), at(12, day=tomorrow))
    )
    async with app.run_test(size=(140, 50)) as pilot:
        grid = app.query_one("#week", TimeGrid)
        grid.select(find(app, "Dentist"))
        await pilot.press("greater_than_sign")
        await pilot.pause()
        resynced(app, store, find(app, "Dentist", tomorrow).event.uid)
        await pilot.pause()
        assert grid.selected is not None and grid.selected.summary == "Dentist"


async def test_month_view_keeps_the_copy_selected_for_repeated_moves(make_app, store) -> None:
    app = make_app()
    async with app.run_test(size=(140, 50)) as pilot:
        app.query_one("#week", TimeGrid).select(find(app, "Dinner"))
        await pilot.press("y", "m", "l", "l", "l", "p")  # Sat 21 (Thu is full: "+N more")
        await pilot.pause()
        month = app.query_one(MonthView)
        copy = month.selected
        assert copy is not None and copy.start == at(19, day=TODAY + timedelta(3))
        resynced(app, store, copy.event.uid)
        await pilot.press("greater_than_sign")
        await pilot.pause()
        resynced(app, store, copy.event.uid)
        await pilot.press("greater_than_sign")
        await pilot.pause()
        assert month.selected is not None
        assert month.selected.start == at(19, day=TODAY + timedelta(5))


async def test_paste_and_duplicate_toast_and_name_another_calendar(make_app) -> None:
    app = make_app()
    holiday = TODAY + timedelta(16)
    async with app.run_test(size=(140, 50)) as pilot:
        app.query_one("#week", TimeGrid).select(find(app, "Dinner"))
        await pilot.press("D")
        await pilot.pause()
        app.select_date(holiday)
        await pilot.pause()
        app.query_one("#week", TimeGrid).select(find(app, "Public holiday", holiday))
        await pilot.press("D")
        await pilot.pause()
        messages = [str(n.message) for n in app._notifications]
        assert "Duplicated “Dinner” to Thu 19 · u undo" in messages
        writable = app.calendar(
            named(app, "Public holiday", holiday + timedelta(1), 1)[0].calendar_id
        )
        day = holiday + timedelta(1)
        assert (
            f"Duplicated “Public holiday” to {day:%a} {day.day} · {writable.name} · u undo"
            in messages
        )


async def test_override_moves_without_asking_and_a_series_run_asks_once(make_app) -> None:
    app = make_app()
    async with app.run_test(size=(140, 50)) as pilot:
        grid = app.query_one("#week", TimeGrid)
        grid.select(find(app, "Standup"))
        await pilot.press("J", "o")  # this event -> an override
        await pilot.press("J")  # no dialog for the override
        await pilot.pause()
        assert not isinstance(app.screen, MoveScope)
        assert grid.selected is not None and grid.selected.start == at(9, 30)

        grid.select(find(app, "Standup", TODAY + timedelta(1)))
        await pilot.press("K", "s", "K")  # all events, then again without asking
        await pilot.pause()
        assert not isinstance(app.screen, MoveScope)
        starts = {o.start for o in named(app, "Standup", TODAY - timedelta(2), 5)}
        assert at(8, 30, TODAY - timedelta(1)) in starts


async def test_undo_takes_back_moves_pastes_and_edits_in_turn(make_app) -> None:
    app = make_app()
    async with app.run_test(size=(140, 50)) as pilot:
        grid = app.query_one("#week", TimeGrid)
        grid.select(find(app, "Dinner"))
        await pilot.press("greater_than_sign", "D")
        await pilot.pause()
        event = find(app, "Dentist").event
        app.save_event(replace(event, summary="Dentist!"))
        await pilot.press("u")
        assert find(app, "Dentist").summary == "Dentist"
        await pilot.press("u")  # the duplicate is gone
        assert len(named(app, "Dinner", TODAY, 7)) == 1
        await pilot.press("u")  # the move
        assert find(app, "Dinner").start == at(19)
        messages = [str(n.message) for n in app._notifications]
        assert "Undid edit of “Dentist”" in messages and "Removed “Dinner”" in messages
        assert "Undid move of “Dinner” (back to Wed 18 19:00)" in messages
        # a series moved by "all events" comes back whole
        grid.select(find(app, "Standup"))
        await pilot.press("J", "s", "u")
        await pilot.pause()
        starts = {o.start for o in named(app, "Standup", TODAY - timedelta(2), 5)}
        assert at(9) in starts and at(9, day=TODAY - timedelta(1)) in starts
