"""Grid mode moves in slots of ``[view] grid_step`` minutes (default an hour)."""

from datetime import datetime, time, timedelta

import pytest
from conftest import TODAY, RecordingApp

from tcal.config import load_config
from tcal.store import Store
from tcal.ui import messages
from tcal.ui.widgets import timegrid
from tcal.ui.widgets.timegrid import TimeGrid

NOW = datetime.combine(TODAY, time(10, 50)).astimezone()
SIZES = [(140, 45), (140, 40), (140, 24), (140, 53)]  # 2, 1.7 (uneven), 1 and 2.5 rows/hour


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(timegrid, "now", lambda: NOW)


def at(hhmm: str) -> datetime:
    return datetime.combine(TODAY, datetime.strptime(hhmm, "%H:%M").time(), NOW.tzinfo)


def label(grid: TimeGrid) -> str:
    y = grid._header_height() + grid._cursor_row() - grid._top_row()
    return grid.render_line(y).text[:5]


@pytest.mark.parametrize("size", SIZES)
@pytest.mark.parametrize("zooms", [0, 1, 2, 3, 5])
async def test_the_cursor_is_a_full_hour(
    app: RecordingApp, size: tuple[int, int], zooms: int
) -> None:
    async with app.run_test(size=size) as pilot:
        grid = app.query_one(TimeGrid)
        await pilot.press(*["plus"] * zooms, "v")
        assert grid.cursor_time == at("10:00")  # 10:50 snapped
        for hour in (11, 12, 13):
            await pilot.press("j")
            assert grid.cursor_time == at(f"{hour}:00") and label(grid) == f"{hour}:00"
            rows, scale = grid._cursor_rows(), grid.scale
            assert rows == range(scale.row_of(hour * 60), scale.row_of((hour + 1) * 60))
            top = grid._top_row()
            assert top <= rows.start and rows.stop <= top + grid._grid_height()
        await pilot.press("k")
        assert grid.cursor_time == at("12:00")
        await pilot.press(*["j"] * 20)
        assert grid.cursor_time == at("23:00")
        assert grid._cursor_rows().stop == grid.scale.total_rows
        await pilot.press(*["k"] * 30)
        assert grid.cursor_time == at("00:00")


async def test_entering_grid_mode_shows_the_whole_slot(app: RecordingApp) -> None:
    async with app.run_test(size=(140, 24)) as pilot:
        grid = app.query_one(TimeGrid)
        await pilot.press(*["plus"] * 7)
        grid._scroll(grid.scale.row_of(10 * 60 + 45) - grid._top_row())  # 10:00 is above
        await pilot.press("v")
        assert grid._top_row() <= grid._cursor_row()


async def test_new_events_and_clicks_use_the_hour(app: RecordingApp) -> None:
    async with app.run_test(size=SIZES[0]) as pilot:
        grid = app.query_one(TimeGrid)
        await pilot.press("v", "k", "k", "a")
        x, y = grid._columns()[2] + 3, 1 + grid._header_height()
        await pilot.click(TimeGrid, offset=(x, y + 2 * 8 + 2), times=2)  # 15:30
        await pilot.pause()
        starts = [m.start for m in app.posted if isinstance(m, messages.NewEventRequested)]
        assert starts == [at("08:00"), at("15:00")]
        assert grid.paste_at == at("15:00")


async def test_a_pick_keeps_its_place(app: RecordingApp) -> None:
    async with app.run_test(size=SIZES[0]) as pilot:
        grid = app.query_one(TimeGrid)
        timed = sorted((o for o in grid._occurrences() if not o.all_day), key=lambda o: o.start)
        await pilot.press("v")
        for occ in grid._occurrences():
            grid.select(occ)  # also if it starts mid-slot
            assert grid.selected == occ
            if occ in timed and not timegrid.is_bar(occ) and occ.start.date() >= grid.days()[0]:
                assert grid.cursor_time <= occ.start < grid.cursor_time + timedelta(hours=1)


async def test_half_hour_step(store: Store, write_config) -> None:
    write_config("[view]\ngrid_step = 30\n")
    app = RecordingApp(store, load_config())
    async with app.run_test(size=SIZES[0]) as pilot:
        grid = app.query_one(TimeGrid)
        await pilot.press("plus", "v")  # 3 rows/hour: 10:30 starts on the 10:20 row
        assert grid.cursor_time == at("10:30") and label(grid) == "10:30"
        await pilot.press("j", "j")
        assert grid.cursor_time == at("11:30")
