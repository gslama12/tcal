"""Event detail modal and the delete confirmation flow."""

from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from conftest import TODAY
from textual.containers import VerticalScroll
from textual.widgets import Button, Static

from tcal import ics
from tcal.model import Calendar, Occurrence
from tcal.tz import local_zone
from tcal.ui.app import TcalApp
from tcal.ui.messages import EventSelected
from tcal.ui.screens import event_detail
from tcal.ui.screens.event_detail import (
    ConfirmDelete,
    EditScope,
    EventDetail,
    describe_rrule,
    people_text,
    until_date,
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
        day = f"{picked.start:%a %-d %H:%M}"
        messages = [str(n.message) for n in app._notifications]
        assert f"Deleted this “Standup” ({day}) · u undo" in messages


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
        messages = [str(n.message) for n in app._notifications]
        assert "Deleted all “Standup” events · u undo" in messages
        assert "Restored all “Standup” events" in messages


async def test_readonly_calendar_cannot_delete(make_app) -> None:
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        holiday = find(app, "Public holiday", days=30)[0]
        app.post_message(EventSelected(holiday))
        await pilot.pause()
        assert "(read-only)" in text(app, "calendar")
        assert text(app, "hints") == "y copy  esc close"
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


async def test_detail_shows_people_url_and_zone_but_no_alerts(make_app) -> None:
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
            "3 guests · 1 yes, 1 no, 1 awaiting",
            "Ann Organizer · yes · organizer",
            "bob@example.com · no",
            "Cleo · awaiting",
        ]
        assert not app.screen.query("#alarms")
        assert not any("Alert" in str(s.render()) for s in app.screen.query(Static))


async def test_detail_without_extras_has_no_extra_rows(make_app) -> None:
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        app.post_message(EventSelected(find(app, "Design review")[0]))
        await pilot.pause()
        for widget_id in ("timezone", "url", "people"):
            assert not app.screen.query(f"#{widget_id}")


def test_people_text_lists_an_organizer_who_is_no_guest_once() -> None:
    extras = ics.Extras(organizer="Maria", attendees=(("Ann", "TENTATIVE"),))
    assert people_text(extras).splitlines() == [
        "2 guests · 1 maybe",
        "Maria · organizer",
        "Ann · maybe",
    ]
    assert people_text(ics.Extras()) == ""


def test_until_is_shown_as_a_local_day(monkeypatch) -> None:
    monkeypatch.setattr(event_detail, "local_zone", lambda: ZoneInfo("America/New_York"))
    assert until_date("20270101T045959Z") == date(2026, 12, 31)
    assert until_date("20261231") == date(2026, 12, 31)


async def test_long_detail_scrolls_with_title_and_hints_pinned(make_app) -> None:
    [event] = ics.from_ics(MEETING, "work")
    notes = "\n".join(f"{i}. Item" for i in range(1, 20))
    occ = Occurrence(replace(event, description=notes), event.start, event.end)
    app = make_app()
    async with app.run_test(size=(100, 35)) as pilot:
        app.post_message(EventSelected(occ))
        await pilot.pause()
        await pilot.pause()
        dialog = app.screen.query_one("#dialog", VerticalScroll)
        assert dialog.max_scroll_y > 0
        assert text(app, "hints").endswith("j/k scroll")
        await pilot.press("j", "j")
        assert dialog.scroll_y == 2
        for pinned in ("title", "hints"):
            assert dialog.region.contains_region(app.screen.query_one(f"#{pinned}").region)


async def test_edit_and_delete_keep_a_read_only_detail_open(store, make_app) -> None:
    store.upsert_calendars([Calendar("feed", "Feed", "#888888", readonly=True)])
    [event] = ics.from_ics(MEETING, "feed")
    occ = Occurrence(event, event.start, event.end)
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        app.post_message(EventSelected(occ))
        await pilot.pause()
        await pilot.press("e", "x")
        assert isinstance(app.screen, EventDetail)
        assert text(app, "hints") == "y copy  esc close"
        assert [str(n.message) for n in app._notifications] == ["Feed is read-only"] * 2


def test_demo_has_an_invitation_an_alarm_and_another_zone(provider) -> None:
    events = {e.summary: e for e in provider.events.values()}
    invite = ics.extras(events["Budget planning"])
    assert invite.organizer == "Maria Lang" and len(invite.attendees) == 4 and invite.url
    assert "TRIGGER:-PT1H" in events["Dentist"].raw  # kept in raw, not shown
    assert str(events["Call with New York"].start.tzinfo) == "America/New_York"


async def test_scope_dialogs_name_the_instance_and_only_delete_is_red(make_app) -> None:
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        app.query_one("#week", TimeGrid).select(find(app, "Standup")[0])
        for key, dialog, question, variant in (
            ("e", EditScope, "Edit “Standup” on Wed 18 Nov?", "primary"),
            ("x", ConfirmDelete, "Delete “Standup” on Wed 18 Nov?", "error"),
        ):
            await pilot.press(key)
            await pilot.pause()
            assert isinstance(app.screen, dialog)
            assert str(app.screen.query_one(Static).render()) == question
            assert {b.variant for b in app.screen.query("#o, #s").results(Button)} == {variant}
            await pilot.press("escape")


async def test_yank_and_duplicate_from_detail(make_app) -> None:
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        holiday = find(app, "Public holiday", days=30)[0]
        app.post_message(EventSelected(holiday))
        await pilot.pause()
        await pilot.press("y")
        assert isinstance(app.screen, EventDetail)  # copying keeps the detail open
        assert app.editor.yanked == [holiday]
        await pilot.press("D")
        await pilot.pause()
        assert not isinstance(app.screen, EventDetail)
        assert len(find(app, "Public holiday", days=30)) == 2  # copied to a writable calendar


async def test_detail_scroll_hint_follows_the_keymap(make_app, write_config) -> None:
    [event] = ics.from_ics(MEETING, "work")
    notes = "\n".join(f"{i}. Item" for i in range(1, 20))
    occ = Occurrence(replace(event, description=notes), event.start, event.end)
    app = make_app(
        write_config('[keys]\ncursor_down = ["l"]\ncursor_up = ["k"]\ncursor_right = ["ö"]\n')
    )
    async with app.run_test(size=(100, 35)) as pilot:
        app.post_message(EventSelected(occ))
        await pilot.pause()
        await pilot.pause()
        assert text(app, "hints").endswith("l/k scroll")
        await pilot.press("l")
        assert app.screen.query_one("#dialog", VerticalScroll).scroll_y == 1
