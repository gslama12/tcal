"""Flash jump (f) in the Week grid: labels, typing them, cancelling."""

from datetime import datetime, time, timedelta

import pytest
from conftest import TODAY, RecordingApp

from tcal.config import load_config
from tcal.store import Store
from tcal.ui.flash import ALPHABET, Flash, Target, flash_labels
from tcal.ui.state import ViewMode
from tcal.ui.widgets import timegrid
from tcal.ui.widgets.timegrid import TimeGrid

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


def label_of(grid: TimeGrid, pred) -> str:
    assert grid._flash is not None
    return next(k for k, t in grid._flash.labels.items() if pred(t))


async def test_flash_jumps_to_a_slot_in_another_day(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        grid = app.query_one(TimeGrid)
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


@pytest.mark.parametrize("zooms", [0, 2, 5])
@pytest.mark.parametrize("step, per_hour", [(60, [1]), (30, [1, 2]), (15, [2, 3, 4])])
async def test_one_slot_label_per_grid_step(
    store: Store, write_config, zooms: int, step: int, per_hour: list[int]
) -> None:
    write_config(f"[view]\ngrid_step = {step}\n")
    app = RecordingApp(store, load_config())
    async with app.run_test(size=SIZE) as pilot:
        grid = app.query_one(TimeGrid)
        await pilot.press(*["plus"] * zooms, "f")
        assert grid._flash is not None
        slots = [t for t in grid._flash.labels.values() if t.occ is None]
        for t in slots:
            row = grid.scale.row_of(t.minute)
            assert t.y == grid._header_height() + row - grid._top_row()
        free = max(range(7), key=lambda day: sum(t.day == day for t in slots))
        hours = [t.minute // 60 for t in slots if t.day == free]
        # inner hours: the first and last may be cut off by the screen
        assert max(hours.count(h) for h in hours[1:-1]) in per_hour
        if step == 60:
            assert all(t.minute % 60 == 0 for t in slots)


@pytest.mark.parametrize("step", [15, 30, 60])
@pytest.mark.parametrize("zooms", [0, 1, 2, 3])
async def test_flash_lands_on_the_slot_start(
    store: Store, write_config, step: int, zooms: int
) -> None:
    write_config(f"[view]\ngrid_step = {step}\n")
    app = RecordingApp(store, load_config())
    async with app.run_test(size=SIZE) as pilot:
        grid = app.query_one(TimeGrid)
        await pilot.press(*["plus"] * zooms, "f")
        assert grid._flash is not None
        for target in [t for t in grid._flash.labels.values() if t.occ is None]:
            grid._jump(target)
            assert grid.cursor_time.hour * 60 + grid.cursor_time.minute == target.minute
            assert app.state.day == grid.days()[target.day]


async def test_flash_selects_an_event(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        grid = app.query_one(TimeGrid)
        await pilot.press("f")
        label = label_of(grid, lambda t: t.occ is not None and t.occ.summary == "Dinner")
        await pilot.press(*label)
        assert grid.selected is not None and grid.selected.summary == "Dinner"
        assert not app.state.grid  # event labels stay in event mode


async def test_nearest_gets_a_single_key(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        grid = app.query_one(TimeGrid)
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
        grid = app.query_one(TimeGrid)
        before = grid.cursor_time
        await pilot.press("f", "escape")
        assert not grid.flashing and grid.cursor_time == before
        await pilot.press("f", "1", "j")  # "1" cancels (used up); then j moves again
        assert not grid.flashing and grid.cursor_time == before + timedelta(hours=1)
        await pilot.press("f", "w")  # a label letter is not the week-view key now
        assert app.state.view == ViewMode.WEEK


async def test_flash_does_nothing_in_month_view(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("m", "f", "j")
        assert app.state.view == ViewMode.MONTH
        assert app.state.day == TODAY + timedelta(days=7)
