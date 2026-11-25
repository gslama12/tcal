from dataclasses import replace
from datetime import UTC, datetime, time, timedelta

import pytest
from conftest import TODAY
from textual.widgets import Input, OptionList, Select, TextArea

from tcal.model import Event
from tcal.tz import local_midnight, local_zone
from tcal.ui.formvalues import (
    FormError,
    build_event,
    parse_date,
    parse_time,
    show_date,
    values_of,
)
from tcal.ui.messages import EventSelected
from tcal.ui.screens.event_form import AllDay, Choice, EventForm
from tcal.ui.screens.prompt import Prompt
from tcal.ui.widgets.timegrid import TimeGrid

DAY = timedelta(days=1)


def at(hour: int, minute: int = 0, day=TODAY) -> datetime:
    return datetime.combine(day, time(hour, minute), local_zone())


def find(app, summary: str = "Standup", day=TODAY):
    return next(o for o in app.occurrences(day, day + DAY) if o.summary == summary)


async def open_form(app, pilot, summary: str = "Dentist", scope: str = "") -> EventForm:
    """The form for today's ``summary``; ``scope``: the answer for a series."""
    app.edit_occurrence(find(app, summary))
    await pilot.pause()
    if scope:
        await pilot.press(scope)
        await pilot.pause()
    assert isinstance(app.screen, EventForm)
    return app.screen


async def fill(pilot, **fields: str) -> None:
    for name, text in fields.items():
        pilot.app.screen.query_one(f"#{name}").value = text
        await pilot.pause()


def field(app, name: str) -> Input:
    return app.screen.query_one(f"#{name}", Input)


def hint(app) -> str:
    return str(app.screen.query_one("#form").border_subtitle)


# ----- values ---------------------------------------------------------------


def test_parse_time_forms() -> None:
    assert parse_time("9", "t") == time(9)
    assert parse_time("930", "t") == parse_time("9.30", "t") == time(9, 30)
    assert parse_time("09:30", "t") == time(9, 30)
    for text in ("25:00", "x", ""):
        with pytest.raises(FormError):
            parse_time(text, "t")


def test_dates_show_the_weekday_and_read_back() -> None:
    assert show_date(TODAY) == "Wed 18 Nov 2026"
    assert parse_date("Wed 18 Nov 2026", "d", TODAY) == TODAY
    assert parse_date("Mon, 18 Nov 2026", "d", TODAY) == TODAY  # the weekday is ignored
    assert parse_date("fri", "d", TODAY) == TODAY + 2 * DAY
    with pytest.raises(FormError):
        parse_date("Wed Nov", "d", TODAY)


def test_build_event_validates_and_maps_repeat() -> None:
    event = Event("u", "work", "Old", at(10), at(11))
    shown = values_of(event)
    with pytest.raises(FormError, match="End must be after start"):
        build_event(event, shown, replace(shown, end_time="09:00"), TODAY)
    with pytest.raises(FormError, match="Title"):
        build_event(event, shown, replace(shown, title=" "), TODAY)
    weekly = build_event(event, shown, replace(shown, repeat="weekly"), TODAY)
    assert weekly.rrule == "FREQ=WEEKLY"
    assert values_of(replace(event, rrule="FREQ=WEEKLY;BYDAY=MO")).repeat == "custom"
    weekdays = replace(event, rrule="FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR")
    assert values_of(weekdays).repeat == "weekdays"


def test_unchanged_fields_keep_the_events_own_values() -> None:
    event = Event(
        "u",
        "work",
        "Old",
        datetime(2026, 11, 18, 9, tzinfo=UTC),
        datetime(2026, 11, 18, 10, tzinfo=UTC),
        location="Cafe\nMain St 1",
        description="two\nlines\n",
        rrule="FREQ=WEEKLY;BYDAY=MO",
        raw="raw",
    )
    shown = values_of(event)
    assert shown.location == "Cafe, Main St 1"
    assert build_event(event, shown, shown, TODAY) == event
    renamed = build_event(event, shown, replace(shown, title="New"), TODAY)
    assert renamed == replace(event, summary="New")
    assert renamed.start.tzinfo is UTC and renamed.raw == "raw"


def test_all_day_end_is_inclusive_in_the_form() -> None:
    event = Event("u", "work", "Trip", local_midnight(TODAY), local_midnight(TODAY + 3 * DAY), True)
    shown = values_of(event)
    assert shown.end_date == show_date(TODAY + 2 * DAY)
    timed = build_event(event, shown, replace(shown, all_day=False), TODAY)
    assert (timed.start, timed.end) == (at(9), at(10, day=TODAY + 2 * DAY))


def test_dates_accept_goto_forms_and_errors_name_the_field() -> None:
    event = Event("u", "work", "Old", at(10), at(11))
    shown = values_of(event)
    moved = build_event(event, shown, replace(shown, start_date="+1d", end_date="tomorrow"), TODAY)
    assert moved.start == at(10, day=TODAY + DAY)
    with pytest.raises(FormError) as error:
        build_event(event, shown, replace(shown, end_date="09:00"), TODAY)
    assert error.value.field == "end_date"
    with pytest.raises(FormError) as error:
        build_event(event, shown, replace(shown, end_time="09:00"), TODAY)
    assert error.value.field == "end_time"


def test_a_series_ends_on_a_date_or_after_a_count() -> None:
    event = Event("u", "work", "Gym", at(18), at(19), rrule="FREQ=WEEKLY;COUNT=5")
    shown = values_of(event)
    assert (shown.repeat, shown.ends, shown.ends_value) == ("weekly", "after", "5")
    ten = build_event(event, shown, replace(shown, ends_value="10"), TODAY)
    assert ten.rrule == "FREQ=WEEKLY;COUNT=10"
    last = TODAY + 14 * DAY
    on_date = replace(shown, ends="on", ends_value=last.isoformat())
    until = build_event(event, shown, on_date, TODAY)
    end_of_day = local_midnight(last + DAY) - timedelta(seconds=1)
    assert until.rrule == f"FREQ=WEEKLY;UNTIL={end_of_day.astimezone(UTC):%Y%m%dT%H%M%SZ}"
    shown_until = values_of(until)
    assert shown_until.ends_value == show_date(last)  # shown as the local day
    all_day = build_event(until, shown_until, replace(shown_until, all_day=True), TODAY)
    assert all_day.rrule == f"FREQ=WEEKLY;UNTIL={last:%Y%m%d}"
    never = build_event(until, shown_until, replace(shown_until, ends="never"), TODAY)
    assert never.rrule == "FREQ=WEEKLY"
    with pytest.raises(FormError, match="number of times") as error:
        build_event(event, shown, replace(shown, ends_value="x"), TODAY)
    assert error.value.field == "ends_value"
    early = replace(shown, ends="on", ends_value="2026-01-01")
    with pytest.raises(FormError, match="end before it starts"):
        build_event(event, shown, early, TODAY)


def test_custom_rules_keep_their_parts() -> None:
    custom = Event("u", "work", "S", at(10), at(11), rrule="FREQ=WEEKLY;BYDAY=MO;COUNT=3")
    values = values_of(custom)
    assert values.repeat == "custom"
    stopped = build_event(custom, values, replace(values, ends="never"), TODAY)
    assert stopped.rrule == "FREQ=WEEKLY;BYDAY=MO"


# ----- the screen -----------------------------------------------------------


async def test_edit_round_trip_and_undo(make_app) -> None:
    app = make_app()
    async with app.run_test(size=(120, 50)) as pilot:
        dentist = find(app, "Dentist")
        length = dentist.end - dentist.start
        form = await open_form(app, pilot)
        assert form.query_one("#form").border_title == "Edit event"
        assert field(app, "title").value == "Dentist"
        names = [o[0] for o in form.query_one("#calendar", Select)._options]
        assert names == ["Work", "Personal", "Family", "Sport"]  # not the read-only one
        await pilot.press("X")  # typing appends to the title
        await fill(pilot, start_time="16:30", location="Main St 1", calendar="sport")
        assert field(app, "end_time").value == f"{at(16, 30) + length:%H:%M}"  # follows
        form.query_one(TextArea).text = "two\nlines"
        await pilot.press("enter")
        assert not isinstance(app.screen, EventForm)
        occ = find(app, "DentistX")
        assert (occ.start, occ.end) == (at(16, 30), at(16, 30) + length)
        assert (occ.calendar_id, occ.event.location) == ("sport", "Main St 1")
        assert occ.event.description == "two\nlines"
        assert any("Saved “DentistX” · u undo" in str(n.message) for n in app._notifications)
        selected = app.query_one(TimeGrid).selected
        assert selected is not None and selected.summary == "DentistX"
        await pilot.press("u")
        assert find(app, "Dentist").start == dentist.start


async def test_saving_unchanged_just_closes(make_app) -> None:
    app = make_app()
    async with app.run_test(size=(120, 50)) as pilot:
        await open_form(app, pilot, "Standup", "o")
        await pilot.press("enter")
        assert not isinstance(app.screen, EventForm)
        assert find(app).event.recurrence_id is None  # no override written
        assert not any("Saved" in str(n.message) for n in app._notifications)


async def test_edit_key_detail_and_read_only(make_app) -> None:
    app = make_app()
    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.press("j")
        occ = app.query_one(TimeGrid).selected
        assert occ is not None
        await pilot.press("e")
        if occ.event.rrule:
            await pilot.press("s")
        assert field(app, "title").value == occ.summary
        await pilot.press("escape")
        app.post_message(EventSelected(find(app, "Dentist")))
        await pilot.pause()
        await pilot.press("e")  # in the detail
        await pilot.pause()
        assert field(app, "title").value == "Dentist"
        await pilot.press("escape")
        year = app.source.occurrences(TODAY, TODAY + 400 * DAY)
        app.edit_event(next(o for o in year if o.calendar_id == "holidays").event)
        await pilot.pause()
        assert not isinstance(app.screen, EventForm)
        assert any(n.message == "Holidays is read-only" for n in app._notifications)


async def test_edit_this_event_of_a_series_writes_an_override(make_app) -> None:
    app = make_app()
    async with app.run_test(size=(120, 50)) as pilot:
        form = await open_form(app, pilot, "Standup", "o")
        assert form.query_one("#form").border_title == "Edit this event"
        assert form.query_one("#repeat").disabled and form.query_one("#calendar").disabled
        assert field(app, "start_date").value == show_date(TODAY)
        await fill(pilot, title="Standup (late)", start_time="11:00")
        await pilot.press("enter")
        moved = find(app, "Standup (late)")
        assert (moved.start, moved.end) == (at(11), at(11, 15))
        assert moved.event.recurrence_id == at(9)
        assert find(app, day=TODAY + DAY).start == at(9, day=TODAY + DAY)
        form = await open_form(app, pilot, "Standup (late)", "s")  # the master
        assert field(app, "title").value == "Standup"
        assert not form.query_one("#repeat").disabled


async def test_edit_all_events(make_app) -> None:
    app = make_app()
    async with app.run_test(size=(120, 50)) as pilot:
        form = await open_form(app, pilot, "Standup", "s")
        assert form.query_one("#form").border_title == "Edit all events"
        assert "first event" in str(form.query_one("#note").render())
        assert form.query_one("#repeat", Choice).value == "weekdays"
        await fill(pilot, start_time="10:00", end_time="10:30")
        await pilot.press("enter")
        for day in (TODAY, TODAY + DAY):
            occ = find(app, day=day)
            assert (occ.start, occ.end) == (at(10, day=day), at(10, 30, day=day))


async def test_errors_are_shown_below_the_field_until_one_changes(make_app) -> None:
    app = make_app()
    async with app.run_test(size=(120, 50)) as pilot:
        form = await open_form(app, pilot)
        await fill(pilot, title="")
        await pilot.press("enter")
        error = form.query_one("#error")
        assert "Title is required" in str(error.render())
        await pilot.press("V")
        await pilot.pause()
        assert str(error.render()) == ""
        await fill(pilot, end_date="[09:00")  # (no markup)
        await pilot.press("enter")
        await pilot.pause()
        assert app.screen is form and "Not a date: '[09:00'" in str(error.render())
        end_date = field(app, "end_date")
        assert end_date.has_class("-invalid") and end_date.has_focus
        children = list(form.query_one("#form").children)
        assert children.index(error) == children.index(end_date.parent) + 1
        await fill(pilot, end_date="fri")
        assert not end_date.has_class("-invalid")


async def test_cancel_asks_before_discarding_changes(make_app, write_config) -> None:
    app = make_app(write_config('[keys]\ncancel = ["ctrl+g"]\n'))
    async with app.run_test(size=(120, 50)) as pilot:
        await open_form(app, pilot)
        assert hint(app) == "enter save · tab next · ctrl+g cancel"
        await pilot.press("ctrl+g")  # unchanged: closes at once
        assert not isinstance(app.screen, EventForm)
        form = await open_form(app, pilot)
        await pilot.press("X", "tab", "ctrl+g")
        assert isinstance(app.screen, Prompt)
        await pilot.press("n")
        assert app.screen is form and field(app, "title").value == "DentistX"
        await pilot.press("ctrl+g", "y")
        assert not isinstance(app.screen, (EventForm, Prompt))
        assert find(app, "Dentist")


CURSOR_KEYS = """
[keys]
cursor_left = ["j", "left"]
cursor_up = ["k", "up"]
cursor_down = ["l", "down"]
cursor_right = ["ö", "right"]
"""


async def test_custom_cursor_keys(make_app, write_config) -> None:
    app = make_app(write_config(CURSOR_KEYS))
    async with app.run_test(size=(120, 50)) as pilot:
        form = await open_form(app, pilot)
        await pilot.press(*"jklö")  # typed in a text field
        assert field(app, "title").value == "Dentistjklö"
        await pilot.press("down")
        calendar = form.query_one("#calendar", Choice)
        assert calendar.has_focus
        assert hint(app) == "j/ö change · space list · enter save · tab next · esc cancel"
        calendar.value = "work"
        await pilot.press("ö")
        assert calendar.value == "personal"
        await pilot.press("j", "j")  # around
        assert calendar.value == "sport"
        await pilot.press("ö", "space")
        await pilot.pause()
        assert calendar.expanded and isinstance(app.focused, OptionList)
        assert hint(app) == "l/k move · enter choose · esc back"
        await pilot.press("l", "l", "k", "j", "enter")
        await pilot.pause()
        assert (calendar.value, calendar.expanded) == ("personal", False)
        assert app.screen is form and calendar.has_focus
        await pilot.press("space", "l", "escape")
        await pilot.pause()
        assert (calendar.value, calendar.expanded) == ("personal", False)
        assert app.screen is form
        await pilot.press("l")
        assert field(app, "start_date").has_focus
        await pilot.press("up", "k")
        assert field(app, "title").has_focus
        all_day = form.query_one(AllDay)
        all_day.focus()
        await pilot.press("space", "l")
        assert all_day.value and form.query_one("#repeat").has_focus
        assert not field(app, "start_time").display
        await pilot.press("k", "enter")  # on the checkbox: saves
        assert not isinstance(app.screen, EventForm)
        saved = find(app, "Dentistjklö")
        assert saved.all_day and saved.calendar_id == "personal"


async def test_tab_and_shift_tab_go_through_all_fields(make_app) -> None:
    app = make_app()
    async with app.run_test(size=(120, 50)) as pilot:
        await open_form(app, pilot, "Standup", "s")  # with the "Ends" row
        there = [app.focused]
        while app.focused is not there[0] or len(there) == 1:
            await pilot.press("tab")
            there.append(app.focused)
        assert {type(w) for w in there} == {Input, Choice, AllDay, TextArea}
        back = [app.focused]
        for _ in there[1:]:
            await pilot.press("shift+tab")
            back.append(app.focused)
        assert back == there[::-1]


@pytest.mark.parametrize(
    ("key", "target"), [("tab", "start_date"), ("shift+tab", "title")], ids=["tab", "shift+tab"]
)
async def test_leaving_an_open_list(make_app, key: str, target: str) -> None:
    app = make_app()
    async with app.run_test(size=(120, 50)) as pilot:
        form = await open_form(app, pilot)
        await pilot.press("tab", "space")
        await pilot.pause()
        calendar = form.query_one("#calendar", Choice)
        assert calendar.expanded
        await pilot.press(key)
        await pilot.pause()
        assert field(app, target).has_focus and not calendar.expanded


async def test_enter_is_a_new_line_in_the_notes(make_app) -> None:
    app = make_app()
    async with app.run_test(size=(120, 50)) as pilot:
        form = await open_form(app, pilot)
        notes = form.query_one(TextArea)
        notes.text = ""
        notes.focus()
        await pilot.press("a", "enter", "b", "up", "up")
        assert (notes.text, notes.has_focus) == ("a\nb", True)
        assert hint(app) == "ctrl+s save · tab next · esc cancel"
        await pilot.press("ctrl+s")
        assert find(app, "Dentist").event.description == "a\nb"


async def test_ends_row_shows_only_for_a_series(make_app) -> None:
    app = make_app()
    async with app.run_test(size=(120, 50)) as pilot:
        form = await open_form(app, pilot)
        assert not form.query_one("#ends_row").display
        await fill(pilot, repeat="weekly")
        assert form.query_one("#ends_row").display
        assert not form.query_one("#ends_value").display  # "Never"
        await fill(pilot, ends="on")
        assert form.query_one("#ends_value").display
        assert not form.query_one("#ends_unit").display
        await fill(pilot, ends="after", ends_value="3")
        assert form.query_one("#ends_unit").display
        await pilot.press("enter")
        assert find(app, "Dentist").event.rrule == "FREQ=WEEKLY;COUNT=3"


def bottom_border(app) -> str:
    """The form's bottom border line as drawn."""
    box = app.screen.query_one("#form").region
    strip = app.screen._compositor.render_strips()[box.bottom - 1]
    return strip.text[box.x : box.right]


@pytest.mark.parametrize("size", [(80, 24), (100, 35), (160, 50)])
@pytest.mark.parametrize("keys", ["", CURSOR_KEYS, '[keys]\ncancel = ["ctrl+g"]\n'])
async def test_every_hint_fits(make_app, write_config, size: tuple[int, int], keys: str) -> None:
    app = make_app(write_config(keys))
    async with app.run_test(size=size) as pilot:
        await open_form(app, pilot, "Standup", "s")  # with the "Ends" row
        seen = set()
        while (focused := app.focused) not in seen:
            seen.add(focused)
            assert f" {hint(app)} " in bottom_border(app)
            await pilot.press("tab")
            await pilot.pause()
        assert {type(w) for w in seen} >= {Input, Choice, AllDay, TextArea}


async def test_scrolls_at_80x24_with_the_hint_pinned(make_app) -> None:
    app = make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        form = await open_form(app, pilot)
        box = form.query_one("#form")
        assert form.region.contains_region(box.region)
        while not isinstance(app.focused, TextArea):
            await pilot.press("tab")
        await pilot.pause()
        assert box.scroll_y > 0
        assert form.region.contains_region(form.query_one("#notes").region)
