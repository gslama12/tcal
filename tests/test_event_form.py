from dataclasses import replace
from datetime import datetime, time, timedelta

import pytest
from conftest import TODAY
from textual.widgets import Input, Select

from tcal.model import Event
from tcal.tz import local_midnight, local_zone
from tcal.ui.messages import NewEventRequested
from tcal.ui.screens.event_form import (
    EventForm,
    FormError,
    build_event,
    parse_time,
    values_of,
)
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
    kept = build_event(custom, values_of(custom), values_of(custom))
    assert kept.rrule == custom.rrule and kept.start is custom.start


def test_all_day_end_is_inclusive_in_the_form() -> None:
    event = Event(
        "u", "work", "Trip", local_midnight(TODAY), local_midnight(TODAY + timedelta(3)), True
    )
    shown = values_of(event)
    assert shown.end_date == (TODAY + timedelta(2)).isoformat()
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
        await pilot.press("n")
        occ = grid.selected
        assert occ is not None
        await pilot.press("e")
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
