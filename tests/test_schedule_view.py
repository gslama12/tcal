from datetime import date, datetime, timedelta

import pytest
from conftest import TODAY, RecordingApp
from rich.style import Style
from test_views import SIZE

from tcal.model import Event, Occurrence
from tcal.tz import local_zone
from tcal.ui.messages import EventSelected
from tcal.ui.state import ViewMode
from tcal.ui.widgets import schedule_view
from tcal.ui.widgets.schedule_view import (
    CHUNK_DAYS,
    SCROLL_LINES,
    ScheduleView,
    build_rows,
    day_of,
    time_range,
)

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


def test_day_of_multi_day_events() -> None:
    trip = occ(TODAY, "00:00", "00:00", TODAY + timedelta(days=3))
    assert [day_of(trip, TODAY + timedelta(days=i)) for i in range(3)] == [
        "Day 1/3",
        "Day 2/3",
        "Day 3/3",
    ]
    assert day_of(occ(TODAY, "09:00", "10:00"), TODAY) == ""


async def test_schedule_scrolls_into_the_past(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("s")
        view = app.query_one(ScheduleView)
        assert view.selected is not None and view.selected.summary == "Anna's birthday"
        await pilot.press("k")  # before the first loaded day: earlier days are loaded
        assert view._start < TODAY and app.state.day < TODAY
        assert view.selected is not None and view.selected.start.date() < TODAY
        assert view._cursor is not None
        assert view._top <= view._cursor < view._top + view.content_size.height
        await pilot.press("j")
        assert view.selected is not None and view.selected.summary == "Anna's birthday"
        start = view._start
        for _ in range(SIZE[1]):
            view._scroll(-SCROLL_LINES)  # the wheel step: at the top it loads earlier days
        assert view._start < start and view._top >= 0


async def test_schedule_shows_position_in_multi_day_events(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("s")
        assert "Conference (Day 3/3)" in str(app.query_one(ScheduleView).render())


def test_build_rows_puts_the_now_line_before_the_next_event() -> None:
    a, b, c = (
        occ(TODAY, "09:00", "10:00"),
        occ(TODAY, "11:00", "12:00"),
        occ(TODAY, "13:00", "14:00"),
    )
    current = datetime.combine(TODAY, datetime.strptime("10:30", "%H:%M").time(), ZONE)
    rows = build_rows([a, b, c], TODAY, TODAY + timedelta(days=1), current)
    assert [(r.occ, r.now) for r in rows[1:]] == [(a, False), (None, True), (b, False), (c, False)]
    assert not rows[2].header and rows[0].header
    late = build_rows([a], TODAY, TODAY + timedelta(days=1), current + timedelta(hours=9))
    assert late[-1].now
    other_day = build_rows([a], TODAY, TODAY + timedelta(days=1), current - timedelta(days=1))
    assert not any(r.now for r in other_day)


async def test_schedule_marks_now_and_dims_past_events(
    app: RecordingApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = datetime.combine(TODAY, datetime.strptime("12:00", "%H:%M").time(), ZONE)
    monkeypatch.setattr(schedule_view, "now", lambda: current)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("s")
        view = app.query_one(ScheduleView)
        now_row = next(i for i, r in enumerate(view._rows) if r.now)
        assert view._rows[now_row].day == TODAY
        before = [r.occ for r in view._rows[:now_row] if r.occ and r.day == TODAY]
        assert before and all(o.all_day or o.start <= current for o in before)
        assert "12:00 ●─" in str(view.render())
        await pilot.press("l", "h")  # day jumps land on events, never on the now line
        assert view.selected is not None
        past = next(i for i, r in enumerate(view._rows[:now_row]) if r.occ and not r.occ.all_day)
        line = view._line(view._rows[past], past + 1)  # not the cursor row
        title = next(
            span
            for span in line.spans
            if span.start > 3 and "●" not in line.plain[span.start : span.end]
        )
        assert title.style == Style(color=app.palette.foreground1, bold=False)


async def test_schedule_date_follows_the_first_day_shown(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("s")
        view = app.query_one(ScheduleView)
        app.select_date(TODAY + timedelta(days=400))  # past every event: restarts there
        await pilot.pause()
        if view._rows:
            assert app.state.day == view._rows[0].day
        for _ in range(3):  # H never gets stuck on empty days before the list
            day = app.state.day
            await pilot.press("H")
            assert app.state.day < day and view._cursor is not None
            assert app.state.day == view._rows[view._cursor].day


async def test_schedule_never_ends_with_a_day_header(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("s")
        view = app.query_one(ScheduleView)
        height = view.content_size.height
        header = next(i for i, r in enumerate(view._rows) if r.header and i >= height)
        view._top = header - height + 1
        lines = str(view.render()).split("\n")
        assert len(lines) == height - 1 and "No upcoming" not in lines[-1]
        assert lines[-1].strip() == ""  # the blank row before the dropped header
