"""Event detail modal and the delete confirmation flow."""

from datetime import timedelta

from conftest import TODAY
from textual.widgets import Static

from tcal.model import Occurrence
from tcal.ui.app import TcalApp
from tcal.ui.messages import EventSelected
from tcal.ui.screens.event_detail import ConfirmDelete, EventDetail, describe_rrule
from tcal.ui.widgets.timegrid import TimeGrid

SIZE = (140, 45)


def find(app: TcalApp, summary: str, days: int = 1, start=TODAY) -> list[Occurrence]:
    occs = app.occurrences(start, start + timedelta(days=days))
    return [o for o in occs if o.summary == summary]


def text(app: TcalApp, widget_id: str) -> str:
    return str(app.screen.query_one(f"#{widget_id}", Static).render())


async def test_open_shows_details_and_closes(make_app) -> None:
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        app.post_message(EventSelected(find(app, "Design review")[0]))
        await pilot.pause()
        assert isinstance(app.screen, EventDetail)
        assert text(app, "title") == "Design review"
        assert text(app, "calendar") == "● Work"
        assert text(app, "time") == "Wed 18 Nov 2026, 10:00 – 11:30"
        assert text(app, "location") == "Room 4"
        await pilot.press("escape")
        assert not isinstance(app.screen, EventDetail)

        app.post_message(EventSelected(find(app, "Standup")[0]))
        await pilot.pause()
        assert text(app, "recurrence") == "Every week on weekdays"
        await pilot.press("q")  # closes the modal, does not quit
        assert app.is_running and not isinstance(app.screen, EventDetail)


async def test_delete_single_event_from_detail(make_app) -> None:
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        app.post_message(EventSelected(find(app, "Dentist")[0]))
        await pilot.pause()
        await pilot.press("x")
        assert isinstance(app.screen, ConfirmDelete)
        await pilot.press("n")  # cancel keeps it
        assert find(app, "Dentist")
        app.post_message(EventSelected(find(app, "Dentist")[0]))
        await pilot.pause()
        await pilot.press("x", "y")
        assert not find(app, "Dentist")
        assert not isinstance(app.screen, (ConfirmDelete, EventDetail))
        assert any(str(n.message) == "Deleted “Dentist” · u undo" for n in app._notifications)
        await pilot.press("u")
        assert find(app, "Dentist")
        await pilot.press("u")  # only once
        assert any(str(n.message) == "Nothing to undo" for n in app._notifications)


async def test_delete_one_occurrence_with_x_in_view(make_app) -> None:
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        grid = app.query_one("#week", TimeGrid)
        while grid.selected is None or grid.selected.summary != "Standup":
            await pilot.press("n")
        picked = grid.selected
        monday = TODAY - timedelta(days=TODAY.weekday())
        week = find(app, "Standup", days=7, start=monday)
        await pilot.press("x")
        assert isinstance(app.screen, ConfirmDelete)
        await pilot.press("o")
        left = find(app, "Standup", days=7, start=monday)
        assert len(left) == len(week) - 1 and picked.start not in [o.start for o in left]


async def test_delete_whole_series(make_app) -> None:
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        app.post_message(EventSelected(find(app, "Standup")[0]))
        await pilot.pause()
        before = len(find(app, "Standup", days=30))
        await pilot.press("x", "s")
        assert not find(app, "Standup", days=30)
        await pilot.press("u")
        assert len(find(app, "Standup", days=30)) == before


async def test_readonly_calendar_cannot_delete(make_app) -> None:
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        holiday = find(app, "Public holiday", days=30)[0]
        app.post_message(EventSelected(holiday))
        await pilot.pause()
        assert "(read-only)" in text(app, "calendar")
        await pilot.press("x")
        assert not isinstance(app.screen, ConfirmDelete)
        assert find(app, "Public holiday", days=30)
        assert any("read-only" in str(n.message) for n in app._notifications)


async def test_edit_key_calls_the_edit_hook(make_app) -> None:
    app = make_app()
    edited: list[Occurrence] = []
    app.edit_occurrence = edited.append
    async with app.run_test(size=SIZE) as pilot:
        occ = find(app, "Dinner")[0]
        app.post_message(EventSelected(occ))
        await pilot.pause()
        await pilot.press("e")
        assert edited == [occ] and not isinstance(app.screen, EventDetail)


def test_describe_rrule() -> None:
    assert describe_rrule("FREQ=DAILY") == "Every day"
    assert describe_rrule("FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,FR") == "Every 2 weeks on Mon, Fri"
    assert describe_rrule("FREQ=MONTHLY;COUNT=5") == "Every month, 5 times"
    assert describe_rrule("FREQ=YEARLY;UNTIL=20271231T225959Z") == "Every year, until 31 Dec 2027"
