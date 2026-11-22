"""Stacked (cascading), translucent event blocks in the Day/Week grid."""

from datetime import datetime, timedelta

import pytest
from conftest import TODAY, RecordingApp
from rich.style import Style

from tcal.model import Event
from tcal.providers.fake import FakeProvider
from tcal.tz import local_zone
from tcal.ui import messages
from tcal.ui.theme import blend
from tcal.ui.timelayout import Block, sub_columns
from tcal.ui.timepaint import ALPHA
from tcal.ui.widgets import timegrid
from tcal.ui.widgets.timegrid import TimeGrid, WeekView

FRI = TODAY + timedelta(days=2)
SIZE = (140, 45)  # 2 rows/hour, 06:30-24:00


def at(hhmm: str, day=FRI) -> datetime:
    return datetime.combine(day, datetime.strptime(hhmm, "%H:%M").time(), local_zone())


@pytest.fixture
def provider() -> FakeProvider:
    """The demo data plus, on Friday, a pair with the same start (Workshop 13-16 under
    Coffee 13-14) and a pair with identical times (Pickup A/B 17-18)."""
    provider = FakeProvider(today=TODAY)
    for uid, cal, summary, start, end in (
        ("x1", "work", "Workshop", "13:00", "16:00"),
        ("x2", "personal", "Coffee", "13:00", "14:00"),
        ("x3", "family", "Pickup A", "17:00", "18:00"),
        ("x4", "sport", "Pickup B", "17:00", "18:00"),
    ):
        provider.create_event(Event(uid, cal, summary, at(start), at(end)))
    return provider


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(timegrid, "now", lambda: at("10:15", TODAY))


def text(grid: TimeGrid) -> list[str]:
    return [grid.render_line(y).text for y in range(grid.size.height)]


def blocks(grid: TimeGrid) -> dict[str, Block]:
    return {b.occ.summary: b for b in grid._block_list()}


def y_of(grid: TimeGrid, row: int) -> int:
    return grid._header_height() + row - grid._top_row()


async def test_same_start_stacks_the_shorter_on_top(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        grid = app.query_one(WeekView)
        workshop, coffee = blocks(grid)["Workshop"], blocks(grid)["Coffee"]
        assert (workshop.depth, coffee.depth) == (0, 1)
        order = grid._block_list()
        assert order.index(workshop) < order.index(coffee)  # drawn first: below
        xs, lines = grid._columns(), text(grid)
        x0, x1 = sub_columns(workshop, xs)
        assert sub_columns(coffee, xs) == (x0 + 2, x1)
        cells = [line[x0:x1] for line in lines]
        assert "Coffee" in cells[y_of(grid, coffee.top)]
        # Both titles read: Workshop's moves to its first row below Coffee.
        assert "Workshop" in cells[y_of(grid, coffee.bottom)]


async def test_identical_times_go_side_by_side(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        grid = app.query_one(WeekView)
        a, b = blocks(grid)["Pickup A"], blocks(grid)["Pickup B"]
        assert (a.depth, a.col, a.cols, b.depth, b.col, b.cols) == (0, 0, 2, 0, 1, 2)
        xs = grid._columns()
        assert sub_columns(a, xs)[1] + 1 == sub_columns(b, xs)[0]  # a 1-col gap


async def test_now_line_skips_the_gap_between_events(
    app: RecordingApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(timegrid, "now", lambda: at("17:00"))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        grid = app.query_one(WeekView)
        xs, a = grid._columns(), blocks(grid)["Pickup A"]
        gap = sub_columns(a, xs)[1]
        line = next(line for line in text(grid) if line[xs[4]] == "●")
        assert line[gap] == " "


async def test_cursor_and_clicks_pick_the_topmost_block(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        grid = app.query_one(WeekView)
        await pilot.press("l", "l")  # Fri
        await pilot.press(*"jjjjjj")  # 13:00
        assert grid.selected is not None and grid.selected.summary == "Coffee"
        await pilot.press("j", "j")  # 14:00: only Workshop
        assert grid.selected is not None and grid.selected.summary == "Workshop"
        xs = grid._columns()
        coffee = blocks(grid)["Coffee"]
        x0 = sub_columns(coffee, xs)[0]
        y = 1 + y_of(grid, coffee.top)  # +1: the view's border
        await pilot.click(WeekView, offset=(x0 + 3, y))
        await pilot.click(WeekView, offset=(x0 - 1, y))  # the strip of the one below
        opened = [m.occurrence.summary for m in app.posted if isinstance(m, messages.EventSelected)]
        assert opened == ["Coffee", "Workshop"]


async def test_cycling_visits_stacked_and_side_by_side_events(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        grid = app.query_one(WeekView)
        await pilot.press("l", "l", *"jjjjj")  # Fri 12:30
        seen = []
        for _ in range(5):
            await pilot.press("n")
            assert grid.selected is not None
            seen.append(grid.selected.summary)
        assert sorted(seen[:2]) == ["Coffee", "Workshop"]
        assert seen[2] == "Call with New York"  # 15:00, on top of Workshop
        assert sorted(seen[3:]) == ["Pickup A", "Pickup B"]


async def test_blocks_are_translucent_and_rounded(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        grid = app.query_one(WeekView)
        p, xs = app.palette, grid._columns()
        workshop, coffee = blocks(grid)["Workshop"], blocks(grid)["Coffee"]
        x0, x1 = sub_columns(workshop, xs)
        work, personal = app.calendar_color("work"), app.calendar_color("personal")

        def cell(row: int, x: int) -> tuple[str, Style]:
            strip = grid.render_line(y_of(grid, row)).crop(x, x + 1)
            segment = next(iter(strip))
            return segment.text, segment.style or Style()

        fill = blend(work, p.background1, ALPHA)
        char, style = cell(workshop.top + 2, x0 + 1)  # 14:00: an hour row below Coffee
        assert style.bgcolor and style.bgcolor.name == fill.lower()
        assert cell(workshop.top + 2, x1 - 1)[0] == "╌"  # the hour line shows through
        on_top = blend(personal, fill, ALPHA)  # Coffee over Workshop
        assert cell(coffee.top + 1, x1 - 2)[1].bgcolor.name == on_top.lower()  # type: ignore[union-attr]
        assert cell(workshop.top, x0)[0] == "▗"  # rounded corners
        assert cell(workshop.bottom - 1, x0)[0] == "▝"
        assert cell(coffee.top, x1 - 1)[0] == "▖"


def test_blend() -> None:
    assert blend("#FF0000", "#000000", 1) == "#FF0000"
    assert blend("#FF0000", "#0000FF", 0.5) == "#800080"
    assert blend("#FFFFFF", "#000000", 0) == "#000000"
