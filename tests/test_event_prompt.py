from datetime import date, datetime, time, timedelta

import pytest
from conftest import TODAY
from textual.widgets import Input, Static

from tcal.tz import local_midnight, local_zone
from tcal.ui.messages import NewEventRequested
from tcal.ui.screens.event_prompt import EventPrompt, when_texts
from tcal.ui.widgets.timegrid import TimeGrid

DAY = timedelta(days=1)


def at(hour: int, minute: int = 0, day=TODAY) -> datetime:
    return datetime.combine(day, time(hour, minute), local_zone())


def find(app, summary: str = "Standup", day=TODAY):
    return next(o for o in app.occurrences(day, day + DAY) if o.summary == summary)


def preview(app) -> dict[str, str]:
    """The card's rows: label -> value."""
    table = app.screen.query_one("#preview", Static).visual._renderable
    labels, values = (list(c.cells) for c in table.columns)
    return {str(k): str(v) for k, v in zip(labels, values, strict=True)}


def dim(app, label: str) -> bool:
    """Whether the (last part of the) row's value is shown as a default."""
    table = app.screen.query_one("#preview", Static).visual._renderable
    labels, values = (list(c.cells) for c in table.columns)
    value = next(v for k, v in zip(labels, values, strict=True) if str(k) == label)
    return "dim" in str(value.spans[-1].style if value.spans else value.style)


def warning(app) -> str:
    widget = app.screen.query_one("#warning", Static)
    return str(widget.render()) if widget.display else ""


async def open_new(app, pilot, start) -> Input:
    app.post_message(NewEventRequested(start))
    await pilot.pause()
    assert isinstance(app.screen, EventPrompt)
    return app.screen.query_one(Input)


async def open_edit(app, pilot, occ, scope: str = "") -> Input:
    app.edit_occurrence(occ)
    await pilot.pause()
    if scope:
        await pilot.press(scope)
        await pilot.pause()
    assert isinstance(app.screen, EventPrompt)
    return app.screen.query_one(Input)


def test_when_texts() -> None:
    assert when_texts(at(10), at(11, 30), False) == ("Wed 18 Nov 2026", "10:00 – 11:30")
    assert when_texts(at(22), at(1, day=TODAY + DAY), False) == (
        "Wed 18 Nov 2026",
        "22:00 – 01:00 (Thu)",
    )
    assert when_texts(at(9), at(17, day=TODAY + 2 * DAY), False) == (
        "Wed 18 Nov 2026 – Fri 20 Nov 2026",
        "09:00 – 17:00",
    )
    midnight = local_midnight(TODAY)
    assert when_texts(midnight, midnight + DAY, True) == ("Wed 18 Nov 2026", "all day")


async def test_preview_follows_the_typing(make_app) -> None:
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        line = await open_new(app, pilot, at(14))
        assert line.value == ""
        assert preview(app) == {
            "Title": "(no title)",
            "When": "Wed 18 Nov 2026  14:00 – 15:00",
            "Calendar": "● Work",
            "Location": "–",
            "Repeats": "Does not repeat",
            "Notes": "–",
        }
        assert all(dim(app, label) for label in ("When", "Calendar", "Location", "Repeats"))
        await pilot.press(*"Vet 16:30-17")
        await pilot.pause()
        assert preview(app)["When"] == "Wed 18 Nov 2026  16:30 – 17:00"
        assert preview(app)["Title"] == "Vet" and not dim(app, "When")
        line.value = "Vet dec 24 16:30 every week 3 times @Clinic #fam // cat"
        await pilot.pause()
        assert preview(app) == {
            "Title": "Vet",
            "When": f"{date(date.today().year, 12, 24):%a %-d %b %Y}  16:30 – 17:30",
            "Calendar": "● Family",
            "Location": "Clinic",
            "Repeats": "Every week, 3 times",
            "Notes": "cat",
        }
        assert not any(dim(app, label) for label in ("Calendar", "Repeats", "Notes"))


async def test_create_and_select(make_app) -> None:
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await open_new(app, pilot, at(19, day=TODAY + 3 * DAY))
        await pilot.press(*"QA series weekly @Home #sp", "enter")
        await pilot.pause()
        assert not isinstance(app.screen, EventPrompt)
        selected = app.query_one(TimeGrid).selected
        assert selected is not None and selected.summary == "QA series"
        assert (selected.start, selected.calendar_id) == (at(19, day=TODAY + 3 * DAY), "sport")
        assert (selected.event.location, selected.event.rrule) == ("Home", "FREQ=WEEKLY")
        assert any("Saved “QA series” · u undo" in str(n.message) for n in app._notifications)
        await pilot.press("u")
        assert not any(o.summary == "QA series" for o in app.occurrences(TODAY, TODAY + 5 * DAY))


async def test_all_day_slot_and_cancel(make_app, write_config) -> None:
    app = make_app(write_config('[keys]\ncancel = ["ctrl+g"]\n'))
    async with app.run_test(size=(120, 40)) as pilot:
        line = await open_new(app, pilot, TODAY)
        assert preview(app)["When"] == "Wed 18 Nov 2026  all day"
        assert "enter save · ctrl+g cancel" in str(line.border_subtitle)
        await pilot.press(*"Party", "ctrl+g")
        assert not isinstance(app.screen, EventPrompt)
        assert not any(o.summary == "Party" for o in app.occurrences(TODAY, TODAY + DAY))


@pytest.mark.parametrize("keys", [("m", "a"), ("Y", "i"), ("c", "a"), ("A",)])
async def test_new_event_key_is_timed_at_the_next_hour(make_app, keys) -> None:
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press(*keys)
        await pilot.pause()
        hour = min(datetime.now().hour + 1, 23)
        assert preview(app)["When"].startswith(f"Wed 18 Nov 2026  {hour:02d}:00")


async def test_errors_keep_the_prompt_open(make_app) -> None:
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        line = await open_new(app, pilot, at(14))
        for text, message in (
            ("", "Type a title"),
            ("Gym #nope", "No calendar “nope”"),
            ("Gym #Holidays", "Holidays is read-only"),
            ("Gym daily until 1.1.2020", "The series can't end before it starts"),
        ):
            line.value = text
            await pilot.press("enter")
            assert isinstance(app.screen, EventPrompt)
            assert warning(app) == message
            assert app.screen.query_one("#warning").has_class("-error")
        line.value = "Gym 25:00"  # not an error: "25:00" stays in the title
        await pilot.pause()
        assert warning(app) == "“25:00” not understood (kept as text)"
        assert not app.screen.query_one("#warning").has_class("-error")
        await pilot.press("ctrl+s")  # saves too
        assert find(app, "Gym 25:00").start == at(14)


async def test_tab_completes_calendars(make_app) -> None:
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        line = await open_new(app, pilot, at(14))
        await pilot.press("tab")
        assert line.value == "" and line.has_focus
        await pilot.press(*"Gym #p", "tab")
        assert line.value == "Gym #Personal "
        line.value = "Gym # 18:00"
        line.cursor_position = 5
        for name in ("Work", "Personal", "Family", "Sport", "Work"):  # not the read-only one
            await pilot.press("tab")
            assert line.value == f"Gym #{name} 18:00"


async def test_new_events_default_to_a_shown_calendar_and_show_a_hidden_one(make_app) -> None:
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        app.toggle_calendar("work")
        line = await open_new(app, pilot, at(14))
        assert preview(app)["Calendar"] == "● Personal"
        line.value = "Meeting #work"
        await pilot.press("enter")
        assert "work" not in app.state.hidden_calendars
        assert find(app, "Meeting").calendar_id == "work"


async def test_edit_round_trip(make_app) -> None:
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        dentist = find(app, "Dentist")
        line = await open_edit(app, pilot, dentist)
        assert line.value.startswith("Dentist wed 18 nov")
        await pilot.press("enter")  # unchanged
        unchanged = find(app, "Dentist").event
        assert (unchanged.start, unchanged.location) == (
            dentist.start,
            dentist.event.location,
        )
        line = await open_edit(app, pilot, find(app, "Dentist"))
        await pilot.press("X")  # typing appends to the title
        assert line.value.startswith("DentistX wed 18 nov")
        line.value = line.value.replace("@Dr. Huber", "@Main St 1")
        await pilot.press("enter")
        assert find(app, "DentistX").event.location == "Main St 1"


async def test_edit_key_and_read_only(make_app) -> None:
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("j")
        occ = app.query_one(TimeGrid).selected
        assert occ is not None
        await pilot.press("e")
        if occ.event.rrule:
            await pilot.press("s")
        assert app.screen.query_one(Input).value.startswith(occ.summary)
        await pilot.press("escape")
        year = app.source.occurrences(TODAY, TODAY + 400 * DAY)
        app.edit_event(next(o for o in year if o.calendar_id == "holidays").event)
        await pilot.pause()
        assert not isinstance(app.screen, EventPrompt)
        assert any(n.message == "Holidays is read-only" for n in app._notifications)


async def test_edit_this_event_of_a_series_writes_an_override(make_app) -> None:
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        line = await open_edit(app, pilot, find(app), "o")
        assert line.border_title == "Edit this event"
        assert line.value == "Standup wed 18 nov 09:00-09:15"
        line.value = "Standup (late) 11:00 daily"
        await pilot.press("enter")
        assert "can't change its repeat" in warning(app)
        line.value = "Standup (late) 11:00"
        await pilot.press("enter")
        moved = find(app, "Standup (late)")
        assert (moved.start, moved.end) == (at(11), at(11, 15))
        assert moved.event.recurrence_id == at(9)
        assert find(app, day=TODAY + DAY).start == at(9, day=TODAY + DAY)


async def test_edit_all_events(make_app) -> None:
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        line = await open_edit(app, pilot, find(app), "s")
        assert line.border_title == "Edit all events"
        assert "every weekday" in line.value
        assert any("first event" in str(w.render()) for w in app.screen.query("#card > Static"))
        line.value = line.value.replace("09:00-09:15", "10:00-10:30")
        await pilot.press("enter")
        for day in (TODAY, TODAY + DAY):
            occ = find(app, day=day)
            assert (occ.start, occ.end) == (at(10, day=day), at(10, 30, day=day))


async def test_fits_80x24(make_app) -> None:
    app = make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        line = await open_edit(app, pilot, find(app), "s")
        line.value += " #nope"
        await pilot.pause()
        for selector in ("Input", "#card", "#hints"):
            assert app.screen.region.contains_region(app.screen.query_one(selector).region)
