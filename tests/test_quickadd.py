from datetime import date, datetime, time, timedelta

import pytest
from conftest import TODAY
from textual.widgets import Input, Static

from tcal.quickadd import parse
from tcal.tz import local_midnight, local_zone
from tcal.ui.screens.event_form import ConfirmDiscard, EventForm
from tcal.ui.screens.quick_add import QuickAddScreen

# TODAY is Wednesday 2026-11-18
NAMES = ["Work", "Personal", "Family"]


def at(day: date, h: int, m: int = 0) -> datetime:
    return datetime.combine(day, time(h, m), local_zone())


def test_full_example() -> None:
    q = parse("Lunch with Anna tomorrow 12:30-13:30 @Cafe Central #Personal", TODAY, NAMES)
    tomorrow = TODAY + timedelta(days=1)
    assert (q.summary, q.location, q.calendar) == ("Lunch with Anna", "Cafe Central", "Personal")
    assert (q.start, q.end, q.all_day) == (at(tomorrow, 12, 30), at(tomorrow, 13, 30), False)


@pytest.mark.parametrize(
    ("text", "start", "end"),
    [
        ("Call 12:30", (12, 30), (13, 30)),
        ("Call 12-13", (12, 0), (13, 0)),
        ("Call 9am", (9, 0), (10, 0)),
        ("Call at 9pm", (21, 0), (22, 0)),
        ("Call 18h", (18, 0), (19, 0)),
        ("Call 18h for 2h", (18, 0), (20, 0)),
        ("Call for 90 min at 10:00", (10, 0), (11, 30)),
        ("Call for 1h30 at 10:00", (10, 0), (11, 30)),
        ("Call from 9-11am", (9, 0), (11, 0)),
        ("Call 11-1pm", (11, 0), (13, 0)),
        ("Call 0:00", (0, 0), (1, 0)),
    ],
)
def test_times(text: str, start: tuple[int, int], end: tuple[int, int]) -> None:
    q = parse(text, TODAY, NAMES)
    assert (q.summary, q.all_day) == ("Call", False)
    assert (q.start, q.end) == (at(TODAY, *start), at(TODAY, *end))


def test_end_before_start_is_next_day() -> None:
    q = parse("Party 22-1", TODAY, NAMES)
    assert (q.start, q.end) == (at(TODAY, 22), at(TODAY + timedelta(days=1), 1))


@pytest.mark.parametrize(
    ("text", "day"),
    [
        ("Trip dec 24", date(2026, 12, 24)),
        ("Trip on fri", date(2026, 11, 20)),
        ("Trip 24.12.", date(2026, 12, 24)),
        ("Trip 2026-12-24", date(2026, 12, 24)),
        ("Trip next week", date(2026, 11, 25)),
        ("Trip +2w", date(2026, 12, 2)),
        ("Trip", TODAY),
    ],
)
def test_no_time_is_all_day(text: str, day: date) -> None:
    q = parse(text, TODAY, NAMES)
    assert (q.summary, q.all_day) == ("Trip", True)
    assert (q.start, q.end) == (local_midnight(day), local_midnight(day + timedelta(days=1)))


def test_date_and_time_in_any_order() -> None:
    q = parse("3pm meet on fri", TODAY, NAMES)
    assert (q.summary, q.start) == ("meet", at(date(2026, 11, 20), 15))


def test_calendar_prefix_and_unknown() -> None:
    assert parse("x #fa", TODAY, NAMES).calendar == "Family"
    assert parse("x #WORK", TODAY, NAMES).calendar == "Work"
    q = parse("x #zz", TODAY, NAMES)
    assert (q.calendar, q.unknown_calendar, q.summary) == (None, "zz", "x")
    assert parse("x", TODAY, NAMES).calendar is None


@pytest.mark.parametrize(
    ("text", "first", "last"),
    [
        ("Trip dec 3 - dec 5", date(2026, 12, 3), date(2026, 12, 5)),
        ("Workshop 1.12.-3.12.", date(2026, 12, 1), date(2026, 12, 3)),
        ("Trip dec 30 – jan 2", date(2026, 12, 30), date(2027, 1, 2)),
    ],
)
def test_date_range_is_multi_day_all_day(text: str, first: date, last: date) -> None:
    q = parse(text, TODAY, NAMES)
    assert (q.summary, q.all_day) == (text.split()[0], True)
    assert (q.start, q.end) == (local_midnight(first), local_midnight(last + timedelta(1)))


def test_date_range_with_times() -> None:
    q = parse("Conf dec 3 - dec 5 9:00-17:00", TODAY, NAMES)
    assert (q.summary, q.start, q.end) == (
        "Conf",
        at(date(2026, 12, 3), 9),
        at(date(2026, 12, 5), 17),
    )


def test_next_weekday_and_in_n_days() -> None:
    q = parse("Review next friday 10:00", TODAY, NAMES)
    assert (q.summary, q.start) == ("Review", at(date(2026, 11, 27), 10))
    q = parse("Doctor in 2 days 9:00", TODAY, NAMES)
    assert (q.summary, q.start) == ("Doctor", at(date(2026, 11, 20), 9))


def test_plain_words_stay_in_summary() -> None:
    q = parse("mail bob@x.com for the win", TODAY, NAMES)
    assert (q.summary, q.location, q.all_day) == ("mail bob@x.com for the win", "", True)


async def test_quick_add_saves(make_app) -> None:
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.press("A")
        assert isinstance(app.screen, QuickAddScreen)
        await pilot.press(*"Dentist dec 24 9:15 @Clinic #fam")
        preview = str(app.screen.query_one("#preview", Static).render())
        assert "Dentist" in preview and "09:15–10:15" in preview and "Family" in preview
        await pilot.press("enter")
        assert not isinstance(app.screen, QuickAddScreen)
        day = date(date.today().year, 12, 24)
        [occ] = [o for o in app.occurrences(day, day + timedelta(1)) if o.summary == "Dentist"]
        assert (occ.start, occ.calendar_id, occ.event.location) == (
            at(day, 9, 15),
            "family",
            "Clinic",
        )


async def test_quick_add_tab_opens_form_and_rejects_unknown_calendar(make_app) -> None:
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.press("A", *"Gym 18h #nope", "enter")
        assert isinstance(app.screen, QuickAddScreen)
        assert "nope" in str(app.screen.query_one("#preview", Static).render())
        app.screen.query_one(Input).value = "Gym 18h #sp"
        await pilot.press("tab")
        assert isinstance(app.screen, EventForm)
        assert app.screen.event.summary == "Gym"
        assert app.screen.event.calendar_id == "sport"


async def test_quick_add_names_read_only_calendar(make_app) -> None:
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.press("A", *"Party #Holidays", "enter")
        assert isinstance(app.screen, QuickAddScreen)
        assert "Holidays is read-only" in str(app.screen.query_one("#preview", Static).render())


async def test_new_events_default_to_a_shown_calendar(make_app) -> None:
    app = make_app()
    async with app.run_test() as pilot:
        app.toggle_calendar("work")  # hide Work, the first writable calendar
        await pilot.press("A", *"Meeting 16:00")
        assert "Personal" in str(app.screen.query_one("#preview", Static).render())
        await pilot.press("enter")
        today = date.today()
        occs = app.occurrences(today, today + timedelta(1))
        [occ] = [o for o in occs if o.summary == "Meeting"]
        assert occ.calendar_id == "personal"
        await pilot.press("a")
        assert isinstance(app.screen, EventForm)
        assert app.screen.values().calendar_id == "personal"


async def test_saving_into_a_hidden_calendar_shows_it(make_app) -> None:
    app = make_app()
    async with app.run_test() as pilot:
        app.toggle_calendar("work")
        await pilot.press("A", *"Meeting 16:00 #work", "enter")
        assert "work" not in app.state.hidden_calendars


async def test_quick_add_uses_configured_keys_and_form_asks_before_discarding(
    make_app, write_config
) -> None:
    app = make_app(write_config('[keys]\ncancel = ["ctrl+g"]\nfocus_next = ["ctrl+o"]\n'))
    async with app.run_test() as pilot:
        await pilot.press("A")
        assert "^o full form" in str(app.screen.query_one(Input).border_subtitle)
        await pilot.press("ctrl+g")
        assert not isinstance(app.screen, QuickAddScreen)
        await pilot.press("A", *"Gym 18h", "ctrl+o")
        assert isinstance(app.screen, EventForm)
        await pilot.press("ctrl+g")  # the quick-add text counts as a change
        assert isinstance(app.screen, ConfirmDiscard)
