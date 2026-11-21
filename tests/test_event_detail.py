"""Event detail modal and the delete confirmation flow."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import icalendar
from conftest import TODAY
from textual.widgets import Static

from tcal import ics
from tcal.model import Occurrence
from tcal.providers.ics_url import split_feed
from tcal.tz import local_zone
from tcal.ui.app import TcalApp
from tcal.ui.messages import EventSelected
from tcal.ui.screens.event_detail import (
    ConfirmDelete,
    EventDetail,
    alarm_text,
    describe_rrule,
    duration_text,
)
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
        assert text(app, "hints") == "esc close"
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


FIXTURES = Path(__file__).parent / "fixtures"
MEETING = (FIXTURES / "meeting.ics").read_text()
FEED = (FIXTURES / "holidays.ics").read_text()


async def test_detail_shows_people_alarms_url_and_zone(make_app) -> None:
    [event] = ics.from_ics(MEETING, "work")
    local = local_zone()
    occ = Occurrence(event, event.start.astimezone(local), event.end.astimezone(local))
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        app.post_message(EventSelected(occ))
        await pilot.pause()
        assert text(app, "timezone") == "Pacific/Kiritimati: Thu 19 Nov 2026, 08:00 – 09:00"
        assert text(app, "url") == "https://example.com/planning"
        assert text(app, "people").splitlines() == [
            "Organizer: Ann Organizer",
            "Ann Organizer · accepted",
            "bob@example.com · declined",
            "Cleo · invited",
        ]
        assert text(app, "alarms").splitlines() == [
            "Alert: 10 min before",
            "Alert: 1 hour after",
            f"Alert: At {datetime(2026, 11, 18, 18, tzinfo=UTC).astimezone(local):%a %-d %b %Y, %H:%M}",
        ]


async def test_detail_without_extras_has_no_extra_rows(make_app) -> None:
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        app.post_message(EventSelected(find(app, "Design review")[0]))
        await pilot.pause()
        for widget_id in ("timezone", "url", "people", "alarms"):
            assert not app.screen.query(f"#{widget_id}")


def test_all_day_alarm_and_durations() -> None:
    feed = icalendar.Calendar.from_ical(FEED)
    texts = [t for t in split_feed(feed) if "UID:national-day" in t]
    [event] = ics.from_ics(texts[0], "h")
    occ = Occurrence(event, event.start, event.end)
    assert ics.extras(event).alarms == (timedelta(hours=-15),)
    assert alarm_text(timedelta(hours=-15), occ) == "1 day before at 09:00"
    assert alarm_text(timedelta(hours=9), occ) == "On the day at 09:00"
    assert duration_text(timedelta(minutes=-90)) == "1 h 30 min"
    assert duration_text(timedelta(days=2)) == "2 days"
    assert duration_text(timedelta(weeks=1)) == "1 week"
