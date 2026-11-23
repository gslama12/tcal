from dataclasses import replace
from datetime import UTC, datetime, time, timedelta

import pytest
from conftest import TODAY
from textual.widgets import Checkbox, Input, Label, Select, TextArea

from tcal.model import Event
from tcal.tz import local_midnight, local_zone
from tcal.ui.messages import NewEventRequested
from tcal.ui.screens.event_form import (
    EventForm,
    FormError,
    build_event,
    parse_date,
    parse_time,
    show_date,
    values_of,
)
from tcal.ui.screens.prompt import Prompt
from tcal.ui.widgets.timegrid import WeekView


def at(hour: int, minute: int = 0, day=TODAY) -> datetime:
    return datetime.combine(day, time(hour, minute), local_zone())


def test_parse_time_forms() -> None:
    assert parse_time("9") == time(9)
    assert parse_time("930") == time(9, 30)
    assert parse_time("09:30") == time(9, 30)
    with pytest.raises(FormError):
        parse_time("25:00")


def test_build_event_validates_and_maps_repeat() -> None:
    event = Event("u", "work", "Old", at(10), at(11))
    shown = values_of(event)
    with pytest.raises(FormError, match="End must be after start"):
        build_event(event, shown, replace_values(shown, end_time="09:00"))
    with pytest.raises(FormError, match="Title"):
        build_event(event, shown, replace_values(shown, title=" "))
    weekly = build_event(event, shown, replace_values(shown, repeat="weekly"))
    assert weekly.rrule == "FREQ=WEEKLY"
    custom = Event("u", "work", "S", at(10), at(11), rrule="FREQ=WEEKLY;BYDAY=MO")
    assert values_of(custom).repeat == "custom"
    weekdays = replace(custom, rrule="FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR")
    assert values_of(weekdays).repeat == "weekdays"
    kept = build_event(custom, values_of(custom), values_of(custom))
    assert kept.rrule == custom.rrule and kept.start is custom.start


def test_all_day_end_is_inclusive_in_the_form() -> None:
    event = Event(
        "u", "work", "Trip", local_midnight(TODAY), local_midnight(TODAY + timedelta(3)), True
    )
    shown = values_of(event)
    assert shown.end_date == show_date(TODAY + timedelta(2))
    timed = build_event(event, shown, replace_values(shown, all_day=False))
    assert (timed.start, timed.end) == (at(9), at(10, day=TODAY + timedelta(2)))


def replace_values(values, **changes):
    return replace(values, **changes)


async def type_into(pilot, selector: str, text: str) -> None:
    widget = pilot.app.screen.query_one(selector)
    widget.value = text
    await pilot.pause()


async def test_create_from_slot_and_edit_round_trip(make_app) -> None:
    app = make_app()
    async with app.run_test(size=(120, 50)) as pilot:
        app.post_message(NewEventRequested(at(14)))
        await pilot.pause()
        form = app.screen
        assert isinstance(form, EventForm)
        assert form.query_one("#end_time", Input).value == "15:00"
        assert [o[0] for o in form.query_one("#calendar", Select)._options] == [
            "Work", "Personal", "Family", "Sport"
        ]  # fmt: skip
        await pilot.press(*"Vet")
        await type_into(pilot, "#start_time", "16:30")  # the end follows
        assert form.query_one("#end_time", Input).value == "17:30"
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert not isinstance(app.screen, EventForm)
        [occ] = [o for o in app.occurrences(TODAY, TODAY + timedelta(1)) if o.summary == "Vet"]
        assert (occ.start, occ.end) == (at(16, 30), at(17, 30))

        app.edit_event(occ.event)
        await pilot.pause()
        assert app.screen.query_one("#title", Input).value == "Vet"
        await type_into(pilot, "#title", "Vet (moved)")
        await type_into(pilot, "#end_time", "18:00")
        await type_into(pilot, "#location", "Main St 1")
        await pilot.press("ctrl+s")
        await pilot.pause()
        event = app.source.store.get_event(occ.event.uid)
        assert event.summary == "Vet (moved)"
        assert event.end == at(18) and event.location == "Main St 1"


async def test_invalid_input_keeps_form_open_and_esc_cancels(make_app) -> None:
    app = make_app()
    async with app.run_test(size=(120, 50)) as pilot:
        app.new_event(TODAY)
        await pilot.pause()
        form = app.screen
        assert form.query_one("#all_day").value is True
        await pilot.press(*"Party")
        await type_into(pilot, "#end_date", (TODAY - timedelta(1)).isoformat())
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert app.screen is form
        assert "End must be after start" in str(form.query_one("#error").render())
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, EventForm)
        assert not any(o.summary == "Party" for o in app.occurrences(TODAY, TODAY + timedelta(1)))


async def test_edit_key_on_selected_event_and_readonly(make_app) -> None:
    app = make_app()
    async with app.run_test(size=(120, 50)) as pilot:
        grid = app.query_one(WeekView)
        await pilot.press("j")
        occ = grid.selected
        assert occ is not None
        await pilot.press("e")
        await pilot.pause()
        if occ.event.rrule:
            await pilot.press("s")  # all events
            await pilot.pause()
        assert isinstance(app.screen, EventForm)
        assert app.screen.query_one("#title", Input).value == occ.summary
        await pilot.press("escape")
        await pilot.pause()

        holiday = next(
            o
            for o in app.source.occurrences(TODAY, TODAY + timedelta(400))
            if o.calendar_id == "holidays"
        )
        app.edit_event(holiday.event)
        await pilot.pause()
        assert not isinstance(app.screen, EventForm)
        assert any(n.message == "Holidays is read-only" for n in app._notifications)


def find(app, summary: str = "Standup", day=TODAY):
    return next(o for o in app.occurrences(day, day + timedelta(1)) if o.summary == summary)


async def test_edit_this_event_of_a_series_writes_an_override(make_app) -> None:
    app = make_app()
    async with app.run_test(size=(120, 50)) as pilot:
        app.edit_occurrence(find(app))
        await pilot.pause()
        await pilot.press("o")  # this event
        await pilot.pause()
        form = app.screen
        assert isinstance(form, EventForm) and form.query_one("#repeat").disabled
        assert form.query_one("#start_date", Input).value == show_date(TODAY)
        await type_into(pilot, "#title", "Standup (late)")
        await type_into(pilot, "#start_time", "11:00")
        await pilot.press("ctrl+s")
        await pilot.pause()
        moved = find(app, "Standup (late)")
        assert (moved.start, moved.end) == (at(11), at(11, 15))
        assert moved.event.recurrence_id == at(9)
        tomorrow = find(app, day=TODAY + timedelta(1))
        assert tomorrow.start == at(9, day=TODAY + timedelta(1))
        assert not any(o.summary == "Standup" for o in app.occurrences(TODAY, TODAY + timedelta(1)))
        master = app.source.get_event(moved.event.uid)
        assert master.rrule and "RECURRENCE-ID" in master.raw

        app.edit_occurrence(moved)  # all events: the master, from an override
        await pilot.pause()
        await pilot.press("s")
        await pilot.pause()
        assert app.screen.query_one("#title", Input).value == "Standup"
        assert not app.screen.query_one("#repeat").disabled


async def test_error_clears_when_a_field_changes(make_app) -> None:
    app = make_app()
    async with app.run_test(size=(120, 50)) as pilot:
        app.new_event(at(14))
        await pilot.pause()
        await pilot.press("ctrl+s")
        error = app.screen.query_one("#error")
        assert "Title is required" in str(error.render())
        await pilot.press("V")
        await pilot.pause()
        assert str(error.render()) == ""


@pytest.mark.parametrize("keys", [("m", "a"), ("Y", "i"), ("c", "a")])
async def test_new_event_key_is_timed_at_the_next_hour_off_the_grid(make_app, keys) -> None:
    app = make_app()
    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.press(*keys)
        await pilot.pause()
        form = app.screen
        assert isinstance(form, EventForm) and not form.query_one("#all_day", Checkbox).value
        hour = min(datetime.now().hour + 1, 23)
        assert form.query_one("#start_date", Input).value == show_date(TODAY)
        assert form.query_one("#start_time", Input).value == f"{hour:02d}:00"


def test_dates_accept_goto_forms_and_errors_name_the_field() -> None:
    event = Event("u", "work", "Old", at(10), at(11))
    shown = values_of(event)
    moved = build_event(event, shown, replace(shown, start_date="+1d", end_date="tomorrow"), TODAY)
    assert moved.start == at(10, day=TODAY + timedelta(1))
    with pytest.raises(FormError) as error:
        build_event(event, shown, replace(shown, end_date="09:00"), TODAY)
    assert error.value.field == "end_date"
    with pytest.raises(FormError) as error:
        build_event(event, shown, replace(shown, end_time="09:00"), TODAY)
    assert error.value.field == "end_time"


async def test_error_is_shown_below_the_invalid_field(make_app) -> None:
    app = make_app()
    async with app.run_test(size=(120, 50)) as pilot:
        app.new_event(at(14))
        await pilot.pause()
        await pilot.press(*"Vet")
        await type_into(pilot, "#end_date", "09:00")
        await pilot.press("ctrl+s")
        await pilot.pause()
        form = app.screen
        end_date = form.query_one("#end_date", Input)
        assert end_date.has_class("-invalid") and end_date.has_focus
        children = list(form.query_one("#form").children)
        assert children.index(form.query_one("#error")) == children.index(end_date.parent) + 1
        await type_into(pilot, "#end_date", "fri")
        assert not end_date.has_class("-invalid")


async def test_esc_asks_before_discarding_changes(make_app) -> None:
    app = make_app()
    async with app.run_test(size=(120, 50)) as pilot:
        app.new_event(at(14))
        await pilot.pause()
        await pilot.press("escape")  # unchanged: closes at once
        await pilot.pause()
        assert not isinstance(app.screen, EventForm)
        app.new_event(at(14))
        await pilot.pause()
        form = app.screen
        await pilot.press(*"Vet", "tab", "escape")
        await pilot.pause()
        assert isinstance(app.screen, Prompt)
        await pilot.press("n")
        await pilot.pause()
        assert app.screen is form and form.query_one("#title", Input).value == "Vet"
        await pilot.press("escape", "y")
        await pilot.pause()
        assert not isinstance(app.screen, (EventForm, Prompt))
        assert not any(o.summary == "Vet" for o in app.occurrences(TODAY, TODAY + timedelta(1)))


async def test_edit_all_events_form_wording(make_app) -> None:
    app = make_app()
    async with app.run_test(size=(120, 50)) as pilot:
        app.edit_occurrence(find(app))
        await pilot.pause()
        await pilot.press("s")
        await pilot.pause()
        form = app.screen
        assert form.query_one("#form").border_title == "Edit all events"
        assert "first event" in str(form.query_one("#note").render())
        repeat = form.query_one("#repeat", Select)
        assert repeat.value == "weekdays" and ("Every weekday", "weekdays") in repeat._options
        await pilot.press("escape")
        await pilot.pause()
        app.edit_occurrence(find(app))
        await pilot.pause()
        await pilot.press("o")
        await pilot.pause()
        assert app.screen.query_one("#form").border_title == "Edit this event"


async def test_form_scrolls_at_80x24_with_the_hint_pinned(make_app) -> None:
    app = make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        app.new_event(at(14))
        await pilot.pause()
        form = app.screen
        screen_region = form.region
        hint = form.query_one("#hint")
        assert screen_region.contains_region(hint.region)
        while not isinstance(app.focused, TextArea):
            await pilot.press("tab")
        await pilot.pause()
        notes = form.query_one("#notes")
        assert form.query_one("#form").scroll_y > 0
        assert screen_region.contains_region(notes.region)  # scrolled into view
        assert screen_region.contains_region(hint.region)


def test_a_series_ends_on_a_date_or_after_a_count() -> None:
    event = Event("u", "work", "Gym", at(18), at(19), rrule="FREQ=WEEKLY;COUNT=5")
    shown = values_of(event)
    assert (shown.repeat, shown.ends, shown.ends_value) == ("weekly", "after", "5")
    kept = build_event(event, shown, shown)
    assert kept.rrule == "FREQ=WEEKLY;COUNT=5"
    ten = build_event(event, shown, replace_values(shown, ends_value="10"))
    assert ten.rrule == "FREQ=WEEKLY;COUNT=10"
    last = TODAY + timedelta(days=14)
    until = build_event(event, shown, replace_values(shown, ends="on", ends_value=last.isoformat()))
    end_of_day = local_midnight(last + timedelta(1)) - timedelta(seconds=1)
    assert until.rrule == f"FREQ=WEEKLY;UNTIL={end_of_day.astimezone(UTC):%Y%m%dT%H%M%SZ}"
    assert values_of(until).ends_value == show_date(last)  # shown as the local day
    never = build_event(until, values_of(until), replace_values(values_of(until), ends="never"))
    assert never.rrule == "FREQ=WEEKLY"
    with pytest.raises(FormError, match="number of times") as error:
        build_event(event, shown, replace_values(shown, ends_value="x"))
    assert error.value.field == "ends_value"
    with pytest.raises(FormError, match="end before it starts"):
        build_event(event, shown, replace_values(shown, ends="on", ends_value="2026-01-01"))


def test_all_day_series_ends_on_a_date_and_custom_rules_keep_their_parts() -> None:
    trip = Event(
        "u", "work", "Trip", local_midnight(TODAY), local_midnight(TODAY + timedelta(1)), True,
        rrule="FREQ=MONTHLY",
    )  # fmt: skip
    shown = replace_values(values_of(trip), ends="on", ends_value="2027-03-31")
    assert build_event(trip, values_of(trip), shown).rrule == "FREQ=MONTHLY;UNTIL=20270331"
    custom = Event("u", "work", "S", at(10), at(11), rrule="FREQ=WEEKLY;BYDAY=MO;COUNT=3")
    values = values_of(custom)
    assert values.repeat == "custom"
    stopped = build_event(custom, values, replace_values(values, ends="never"))
    assert stopped.rrule == "FREQ=WEEKLY;BYDAY=MO"


async def test_ends_row_shows_only_for_a_series(make_app) -> None:
    app = make_app()
    async with app.run_test(size=(120, 50)) as pilot:
        app.new_event(at(14))
        await pilot.pause()
        form = app.screen
        assert not form.query_one("#ends_row").display
        form.query_one("#repeat", Select).value = "weekly"
        await pilot.pause()
        assert form.query_one("#ends_row").display
        assert not form.query_one("#ends_value").display  # "Never"
        form.query_one("#ends", Select).value = "after"
        await pilot.pause()
        assert form.query_one("#ends_value").display
        await pilot.press(*"Yoga")
        await type_into(pilot, "#ends_value", "3")
        await pilot.press("ctrl+s")
        await pilot.pause()
        [event] = [e for e in app.source.store.events_between(at(0), at(0) + timedelta(60))
                   if e.summary == "Yoga"]  # fmt: skip
        assert event.rrule == "FREQ=WEEKLY;COUNT=3"


async def test_saved_new_event_is_selected(make_app) -> None:
    app = make_app()
    async with app.run_test(size=(120, 50)) as pilot:
        app.post_message(NewEventRequested(at(19, day=TODAY + timedelta(3))))
        await pilot.pause()
        await pilot.press(*"QA series")
        app.screen.query_one("#repeat", Select).value = "weekly"
        await pilot.press("ctrl+s")
        await pilot.pause()
        selected = app.query_one(WeekView).selected
        assert selected is not None and selected.summary == "QA series"
        assert selected.start == at(19, day=TODAY + timedelta(3))


async def test_typing_after_edit_appends_to_the_title(make_app) -> None:
    app = make_app()
    async with app.run_test(size=(120, 50)) as pilot:
        dentist = next(
            o for o in app.occurrences(TODAY, TODAY + timedelta(1)) if o.summary == "Dentist"
        )
        app.edit_event(dentist.event)
        await pilot.pause()
        await pilot.press("X")
        assert app.screen.query_one("#title", Input).value == "DentistX"


def test_dates_show_the_weekday_and_read_back() -> None:
    assert show_date(TODAY) == "Wed 18 Nov 2026"
    assert parse_date("Wed 18 Nov 2026") == TODAY
    assert parse_date("Mon, 18 Nov 2026") == TODAY  # the weekday is ignored
    assert parse_date("fri", today=TODAY) == TODAY + timedelta(2)
    with pytest.raises(FormError):
        parse_date("Wed Nov")


async def test_ends_after_shows_its_unit(make_app) -> None:
    app = make_app()
    async with app.run_test(size=(120, 50)) as pilot:
        app.post_message(NewEventRequested(at(14)))
        await pilot.pause()
        form = app.screen
        form.query_one("#repeat", Select).value = "weekly"
        form.query_one("#ends", Select).value = "after"
        await pilot.pause()
        assert form.query_one("#ends_unit", Label).display
        form.query_one("#ends", Select).value = "on"
        await pilot.pause()
        assert not form.query_one("#ends_unit", Label).display
