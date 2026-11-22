"""Flash jump (f) in the Day/Week grid: labels, typing them, cancelling."""

from datetime import datetime, time, timedelta

import pytest
from conftest import TODAY, RecordingApp

from tcal.ui.flash import ALPHABET, Flash, Target, flash_labels
from tcal.ui.state import ViewMode
from tcal.ui.widgets import timegrid
from tcal.ui.widgets.timegrid import WeekView

NOW = datetime.combine(TODAY, time(10, 15)).astimezone()
SIZE = (140, 45)


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(timegrid, "now", lambda: NOW)


def at(hhmm: str, day=TODAY) -> datetime:
    return datetime.combine(day, datetime.strptime(hhmm, "%H:%M").time(), NOW.tzinfo)


def test_labels_are_prefix_free_and_shortest_first() -> None:
    assert flash_labels(3) == ["a", "s", "d"]
    for count in (len(ALPHABET) + 1, 100, 300, len(ALPHABET) ** 2):
        labels = flash_labels(count)
        assert len(set(labels)) == count
        assert [len(k) for k in labels] == sorted(len(k) for k in labels)
        assert not any(a != b and b.startswith(a) for a in labels for b in labels)
    assert flash_labels(100)[0] == "a"  # room for single keys still


def test_press_narrows_jumps_and_cancels() -> None:
    one, two = Target(0, 0, 0, 60), Target(0, 1, 0, 120)
    flash = Flash({"a": one, "sd": two})
    assert flash.press("s") is None and not flash.done
    assert [k for k, _ in flash.shown()] == ["sd"]
    assert flash.press("backspace") is None and flash.typed == ""
    assert flash.press("s") is None
    assert flash.press("d") == two and flash.done
    flash = Flash({"a": one})
    assert flash.press("escape") is None and flash.done


def label_of(grid: WeekView, pred) -> str:
    assert grid._flash is not None
    return next(k for k, t in grid._flash.labels.items() if pred(t))


async def test_flash_jumps_to_a_slot_in_another_day(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        grid = app.query_one(WeekView)
        await pilot.press("f")
        assert grid.flashing
        friday = (TODAY + timedelta(days=2) - grid.days()[0]).days
        label = label_of(grid, lambda t: t.occ is None and t.day == friday and t.minute == 19 * 60)
        assert len(label) == 2  # far away: a pair
        body = "\n".join(grid.render_line(y).text for y in range(grid.size.height))
        assert label in body
        await pilot.press(*label)
        assert not grid.flashing and app.state.grid  # a slot label enters grid mode
        assert app.state.day == TODAY + timedelta(days=2)
        assert grid.cursor_time == at("19:00", TODAY + timedelta(days=2))


async def test_flash_selects_an_event(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        grid = app.query_one(WeekView)
        await pilot.press("f")
        label = label_of(grid, lambda t: t.occ is not None and t.occ.summary == "Dinner")
        await pilot.press(*label)
        assert grid.selected is not None and grid.selected.summary == "Dinner"
        assert not app.state.grid  # event labels stay in event mode


async def test_nearest_gets_a_single_key(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        grid = app.query_one(WeekView)
        await pilot.press("f")
        assert grid._flash is not None
        first = grid._flash.labels["a"]
        assert (first.day, first.y) == (
            2,
            grid._header_height() + grid._cursor_row() - grid._top_row(),
        )


async def test_other_keys_cancel_without_acting(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        app.set_grid_mode(True)  # j moves the slot cursor
        grid = app.query_one(WeekView)
        before = grid.cursor_time
        await pilot.press("f", "escape")
        assert not grid.flashing and grid.cursor_time == before
        await pilot.press("f", "1", "j")  # "1" cancels (used up); then j moves again
        assert not grid.flashing and grid.cursor_time == before + timedelta(minutes=30)
        await pilot.press("f", "w")  # a label letter is not the week-view key now
        assert app.state.view == ViewMode.WEEK


async def test_flash_does_nothing_in_month_view(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("m", "f", "j")
        assert app.state.view == ViewMode.MONTH
        assert app.state.day == TODAY + timedelta(days=7)
