"""Tab marks + batch yank/paste (Apple Calendar style: the earliest copy lands on the
selected day, the others keep their day offsets and times) as one undo step."""

from datetime import date, timedelta

from conftest import TODAY

from tcal.model import Occurrence
from tcal.tz import local_midnight
from tcal.ui.widgets.month_view import MonthView
from tcal.ui.widgets.schedule_view import ScheduleView
from tcal.ui.widgets.statusbar import StatusBar
from tcal.ui.widgets.timegrid import TimeGrid

SIZE = (140, 50)
THURSDAY = TODAY + timedelta(1)


def find(app, summary: str, day: date = TODAY) -> Occurrence:
    return next(o for o in app.occurrences(day, day + timedelta(1)) if o.summary == summary)


def named(app, summary: str, day: date) -> list[Occurrence]:
    return [o for o in app.occurrences(day, day + timedelta(1)) if o.summary == summary]


def messages(app) -> list[str]:
    return [str(n.message) for n in app._notifications]


async def mark(app, pilot, occ: Occurrence) -> None:
    app.editor.select_event(occ.event.uid, occ.start)
    await pilot.press("tab")


async def test_tab_marks_and_unmarks_and_escape_clears(make_app) -> None:
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        dentist, dinner = find(app, "Dentist"), find(app, "Dinner")
        await mark(app, pilot, dentist)
        await mark(app, pilot, dinner)
        assert app.state.marked == {dentist.key, dinner.key}
        assert isinstance(app.focused, TimeGrid)  # tab no longer cycles panes
        assert "2 selected" in str(app.query_one(StatusBar).render())
        assert "✓" in app.export_screenshot()
        await mark(app, pilot, dinner)  # again: unmarked
        assert app.state.marked == {dentist.key}
        await pilot.press("L", "L")  # marks survive navigation
        assert app.state.marked == {dentist.key}
        await pilot.press("escape")
        assert app.state.marked == frozenset()
        assert "selected" not in str(app.query_one(StatusBar).render())


async def test_batch_copy_to_the_next_week_is_one_undo_step(make_app) -> None:
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        gym = find(app, "Gym", THURSDAY)  # an instance of a series
        for occ in (find(app, "Deadline: taxes", THURSDAY), gym, find(app, "Dentist")):
            await mark(app, pilot, occ)
        await pilot.press("L", "y")  # next week (Wed 25), copy all marked
        assert "Copied 3 events · p paste" in messages(app)
        assert app.state.marked == frozenset()
        await pilot.press("p")
        await pilot.pause()
        wed, thu = TODAY + timedelta(7), THURSDAY + timedelta(7)
        [dentist] = named(app, "Dentist", wed)  # the earliest lands on the selected day
        assert (dentist.start.date(), dentist.start.time()) == (
            wed,
            find(app, "Dentist").start.time(),
        )
        [deadline] = named(app, "Deadline: taxes", thu)
        assert deadline.all_day and deadline.start == local_midnight(thu)
        copy = next(o for o in named(app, "Gym", thu) if not o.event.rrule)
        assert (
            copy.start.time() == gym.start.time() and copy.end - copy.start == gym.end - gym.start
        )
        assert "Pasted 3 events to Wed 25 · u undo" in messages(app)
        await pilot.press("u")
        await pilot.pause()
        assert named(app, "Dentist", wed) == [] and named(app, "Deadline: taxes", thu) == []
        assert all(o.event.rrule for o in named(app, "Gym", thu))  # only the series is left
        assert "Removed 3 pasted events" in messages(app)
        assert len(named(app, "Dentist", TODAY)) == 1  # originals untouched


async def test_anchor_is_the_earliest_copied_day(make_app) -> None:
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        for occ in (find(app, "Dinner"), find(app, "Haircut", TODAY + timedelta(2))):
            await mark(app, pilot, occ)
        await pilot.press("y")
        app.select_date(TODAY + timedelta(3))  # Sat: Dinner there, Haircut two days later
        await pilot.press("p")
        await pilot.pause()
        assert len(named(app, "Dinner", TODAY + timedelta(3))) == 1
        assert len(named(app, "Haircut", TODAY + timedelta(5))) == 1


async def test_marks_show_in_month_and_schedule(make_app) -> None:
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await mark(app, pilot, find(app, "Haircut", TODAY + timedelta(2)))
        await pilot.press("m")
        assert isinstance(app.focused, MonthView)
        assert app.export_screenshot().count("✓") == 1
        await mark(app, pilot, find(app, "Release", THURSDAY))  # month view marks too
        assert len(app.state.marked) == 2
        await pilot.press("s")
        assert app.export_screenshot().count("✓") == 2
        assert isinstance(app.focused, ScheduleView)
