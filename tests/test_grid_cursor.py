"""Grid mode's slot cursor: visible over events, starts at the selected event's end."""

from dataclasses import replace
from datetime import date, datetime, time, timedelta

import pytest
from conftest import TODAY, RecordingApp
from rich.style import Style

from tcal.config import load_config
from tcal.model import Event
from tcal.store import Store
from tcal.ui.state import Resize
from tcal.ui.theme import MIN_WHITE_CONTRAST, PALETTES, blend, contrast, event_colors
from tcal.ui.timepaint import CURSOR_ALPHA, CURSOR_EDGE, CURSOR_LEFT, CURSOR_RIGHT
from tcal.ui.widgets import timegrid
from tcal.ui.widgets.timegrid import TimeGrid

NOW = datetime.combine(TODAY, time(10, 15)).astimezone()
SIZE = (140, 45)
SATURDAY = TODAY + timedelta(days=3)  # no demo events


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(timegrid, "now", lambda: NOW)


def at(hhmm: str, day: date = SATURDAY) -> datetime:
    return datetime.combine(day, datetime.strptime(hhmm, "%H:%M").time(), NOW.tzinfo)


def add(app: RecordingApp, start: datetime, end: datetime) -> None:
    """An event, selected in event mode."""
    app.save_event(Event("new", "work", "Workshop", start, end))
    grid = app.query_one(TimeGrid)
    grid.select(next(o for o in grid._occurrences() if o.summary == "Workshop"))


def cell(grid: TimeGrid, x: int, y: int) -> tuple[str, Style]:
    segment = next(iter(grid.render_line(y).crop(x, x + 1)))
    assert segment.style is not None
    return segment.text, segment.style


def background(grid: TimeGrid, x: int, y: int) -> str:
    color = cell(grid, x, y)[1].bgcolor
    assert color is not None
    return color.name.upper()


@pytest.mark.parametrize("theme", PALETTES)
async def test_the_cursor_shows_inside_an_event(store: Store, theme: str) -> None:
    config = load_config()
    app = RecordingApp(store, replace(config, theme=replace(config.theme, name=theme)))
    async with app.run_test(size=SIZE) as pilot:
        add(app, at("10:00"), at("14:00"))
        await pilot.press("v", "k", "k")  # 12:00, in the middle of it
        grid, p = app.query_one(TimeGrid), app.palette
        assert grid.selected is not None and grid.selected.summary == "Workshop"
        x0, x1 = grid._columns()[5:7]
        offset = grid._header_height() - grid._top_row()
        rows = [offset + row for row in grid._cursor_rows()]
        cursor = blend(p.primary, p.background1, CURSOR_ALPHA)
        fill, _ = event_colors(app.calendar_color("work"), p, True)
        for y in rows:
            assert {background(grid, x, y) for x in range(x0 + 1, x1)} == {cursor}
            assert cell(grid, x0, y)[0] == CURSOR_LEFT and cell(grid, x1, y)[0] == CURSOR_RIGHT
            edge, style = cell(grid, x0 + 1, y)  # the calendar's colour stays
            assert edge == CURSOR_EDGE and style.color is not None
            assert style.color.name.upper() == fill.upper()
            text = cell(grid, x0 + 3, y)[1].color
            assert text is not None and contrast(text.name, cursor) >= MIN_WHITE_CONTRAST
        for y in (rows[0] - 1, rows[-1] + 1):  # the rest of the event is untouched
            assert background(grid, x0 + 2, y) == fill.upper()


async def test_the_title_stays_readable_under_the_cursor(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        add(app, at("10:00"), at("14:00"))
        await pilot.press("v", *"kkkk")  # 10:00
        grid = app.query_one(TimeGrid)
        x0, x1 = grid._columns()[5:7]
        y = grid._header_height() + grid._cursor_row() - grid._top_row()
        assert "Workshop" in grid.render_line(y).text[x0:x1]


async def test_resize_mode_hides_the_slot_cursor(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        add(app, at("10:00"), at("14:00"))
        await pilot.press("v", "k")  # 13:00: over the edge that resize mode highlights
        app.set_resize(Resize("new", "end"))
        await pilot.pause()
        grid = app.query_one(TimeGrid)
        assert app.state.resize is not None and not grid._frame().cursor_rows
        y = grid._header_height() + grid.scale.row_of(14 * 60) - 1 - grid._top_row()
        x0 = grid._columns()[5]
        assert background(grid, x0 + 3, y) == app.palette.foreground3.upper()


@pytest.mark.parametrize(
    ("start", "end", "cursor"),
    [
        (at("10:00"), at("11:00"), at("11:00")),
        (at("09:15"), at("10:30"), at("10:00")),  # the slot holding the end
        (at("23:00"), at("01:00", SATURDAY + timedelta(1)), at("01:00", SATURDAY + timedelta(1))),
        # ends at midnight on Sunday: next week's Monday
        (
            at("22:00", SATURDAY + timedelta(1)),
            at("00:00", SATURDAY + timedelta(2)),
            at("00:00", SATURDAY + timedelta(2)),
        ),
    ],
)
async def test_grid_mode_starts_at_the_events_end(
    app: RecordingApp, start: datetime, end: datetime, cursor: datetime
) -> None:
    async with app.run_test(size=SIZE) as pilot:
        add(app, start, end)
        await pilot.press("v")
        grid = app.query_one(TimeGrid)
        assert grid.grid_mode and grid.cursor_time == cursor
        rows, top = grid._cursor_rows(), grid._top_row()
        assert top <= rows.start and rows.stop <= top + grid._grid_height()


async def test_without_a_timed_event_grid_mode_starts_at_the_cursor(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        grid = app.query_one(TimeGrid)
        await pilot.press("v")
        assert grid.cursor_time == at("10:00", TODAY)
        await pilot.press("v")
        bar = next(o for o in grid._day_events() if o.all_day)
        before = grid._cursor_min
        grid.select(bar)
        await pilot.press("v")
        assert grid._cursor_min == before and app.state.day == bar.start.date()
