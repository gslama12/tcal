"""Day/Week time grid in the running app: navigation, zoom, selection, mouse."""

from datetime import datetime, time, timedelta
from pathlib import Path

import pytest
from conftest import TODAY
from textual import events
from textual.message import Message

from tcal.config import load_config
from tcal.source import StoreSource
from tcal.store import Store
from tcal.ui import app as app_module
from tcal.ui import messages
from tcal.ui.app import TcalApp
from tcal.ui.state import ViewMode
from tcal.ui.widgets import timegrid
from tcal.ui.widgets.timegrid import DayView, TimeGrid, WeekView

NOW = datetime.combine(TODAY, time(10, 15)).astimezone()
SIZE = (140, 45)  # week grid: 4 header rows + 35 rows -> 06:30-24:00 at 2 rows/hour


class RecordingApp(TcalApp):
    """TcalApp that records the messages the views post for CRUD."""

    CSS_PATH = str(Path(app_module.__file__).parent / "styles.tcss")

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.posted: list[Message] = []

    def on_event_selected(self, message: messages.EventSelected) -> None:
        message.prevent_default()  # record only, not TcalApp's handler (opens a screen)
        self.posted.append(message)

    def on_new_event_requested(self, message: messages.NewEventRequested) -> None:
        self.posted.append(message)
        message.prevent_default()


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(timegrid, "now", lambda: NOW)


@pytest.fixture
def app(store: Store) -> RecordingApp:
    return RecordingApp(StoreSource(store), load_config(), today=TODAY)


def text(grid: TimeGrid) -> list[str]:
    return [grid.render_line(y).text for y in range(grid.size.height)]


def at(hhmm: str, day=TODAY) -> datetime:
    return datetime.combine(day, datetime.strptime(hhmm, "%H:%M").time(), NOW.tzinfo)


async def test_week_renders_header_strip_events_and_now_line(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        grid = app.query_one(WeekView)
        lines = text(grid)
        assert "Mon 16" in lines[0] and "Wed 18" in lines[0] and "Sun 22" in lines[0]
        assert any("Conference" in line for line in lines[1:3])
        # Default visible range: 06:30 (row 4, unlabelled half hour) .. 23:30 (last row).
        assert lines[5].startswith("07:00") and lines[-2].startswith("23:00")
        body = "\n".join(lines)
        for title in ("Standup", "Sprint plann", "Dinner", "Late movie", "Haircut"):
            assert title in body
        assert "Early run" not in body  # 05:45: above the default range
        now_line = next(line for line in lines if line.startswith("10:15"))
        xs = grid._columns()
        assert "─" in now_line[xs[2] : xs[3]]  # today = Wed, clipped to its column
        assert now_line[xs[3]] == "│" and "─" not in now_line[xs[3] :]
        assert grid.rows_per_hour == 2
        assert grid.cursor_time == at("10:00")  # starts at "now", snapped to the slot
        screenshot = app.export_screenshot()
        assert "Standup" in screenshot and "Conference" in screenshot


async def test_cursor_moves_and_crosses_week(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        grid = app.query_one(WeekView)
        await pilot.press("j", "j", "k")
        assert grid.cursor_time == at("10:30")
        await pilot.press("l")
        assert app.state.day == TODAY + timedelta(days=1)
        await pilot.press("l", "l", "l", "l")  # Sun -> next Monday
        assert app.state.day == TODAY + timedelta(days=5)
        assert "Mon 23" in text(grid)[0]
        await pilot.press("h")
        assert "Sun 22" in text(grid)[0]


async def test_cursor_scrolls_to_early_hours(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        grid = app.query_one(WeekView)
        await pilot.press(*["k"] * 30)
        assert grid.cursor_time == at("00:00")
        lines = text(grid)
        assert lines[4].startswith("00:00")
        assert any("Early run" in line for line in lines)


async def test_zoom(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        grid = app.query_one(WeekView)
        await pilot.press("plus")
        assert grid.rows_per_hour == 3
        assert grid.cursor_time == at("10:00")  # zoom keeps the cursor time
        await pilot.press("minus", "minus")
        assert grid.rows_per_hour == 2  # 1 row/hour would leave empty rows below 24:00
        await pilot.resize_terminal(140, 30)
        await pilot.press("minus")
        assert grid.rows_per_hour == 1
        await pilot.press("minus")
        assert grid.rows_per_hour == 1  # lowest zoom
        await pilot.resize_terminal(140, 60)
        assert grid.rows_per_hour == 1  # the user's zoom sticks


async def test_auto_zoom_follows_resize(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        grid = app.query_one(WeekView)
        assert grid.rows_per_hour == 2
        for height in (30, 55, 70):
            await pilot.resize_terminal(140, height)
            await pilot.pause()
            # exactly 06:30..24:00: the first grid row starts at 06:30, the last ends at 24:00
            assert grid.scale.minute_of(grid._top_row()) == 6 * 60 + 30
            assert grid._top_row() + grid._grid_height() == grid.scale.total_rows
        await pilot.resize_terminal(140, 12)
        await pilot.pause()
        assert grid.rows_per_hour == 1  # too small: smallest zoom, 06:30 row on top
        assert grid.scale.row_of(6 * 60 + 30) == grid._top_row()


async def test_headers_share_one_format(store: Store) -> None:
    for width, label in ((200, "Wednesday 18"), (140, "Wed 18"), (90, "18")):
        app = RecordingApp(StoreSource(store), load_config(), today=TODAY)
        async with app.run_test(size=(width, 45)):
            line = text(app.query_one(WeekView))[0]
            assert label in line
            assert "," not in line  # "Monday, 16 November" only when every column fits it


async def test_cursor_slot_has_accent_background(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        grid = app.query_one(WeekView)
        await pilot.press("j")  # 10:30, an empty slot on Wed
        row = grid._cursor_row() - grid._top_row() + grid._header_height()
        backgrounds = {
            seg.style.bgcolor.name
            for seg in grid.render_line(row)
            if seg.style and seg.style.bgcolor and not seg.text.strip()
        }
        assert app.palette.primary.lower() in backgrounds


async def test_cycle_events_and_open(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        grid = app.query_one(WeekView)
        await pilot.press("j", "j", "j")  # 11:30 on today: inside "Dentist"
        assert grid.selected is not None and grid.selected.summary == "Dentist"
        await pilot.press("n")
        assert grid.selected is not None and grid.selected.summary == "Dinner"
        await pilot.press("n", "n")  # Late movie, then the next day's all-day event
        assert grid.selected is not None and grid.selected.summary == "Deadline: taxes"
        assert app.state.day == TODAY + timedelta(days=1)
        await pilot.press("p", "p", "p", "p")  # back over Late movie, Dinner, Dentist
        assert grid.selected is not None and grid.selected.summary == "1:1 with Alex"
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.posted[-1], messages.EventSelected)
        assert app.posted[-1].occurrence.summary == "1:1 with Alex"


async def test_new_event_on_empty_slot(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        grid = app.query_one(WeekView)
        await pilot.press("k", "k", "k")  # 08:30, free
        assert grid.selected is None
        await pilot.press("enter", "a")
        await pilot.pause()
        assert [type(m) for m in app.posted] == [messages.NewEventRequested] * 2
        assert all(
            isinstance(m, messages.NewEventRequested) and m.start == at("08:30") for m in app.posted
        )


async def test_mouse_click_slot_and_event(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        grid = app.query_one(WeekView)
        xs, header = grid._columns(), grid._header_height()
        # The widget has a 1-cell border: content (x, y) is at offset (x + 1, y + 1).
        await pilot.click(WeekView, offset=(xs[4] + 3, 1 + header + 2))  # Fri 07:30
        assert app.state.day == TODAY + timedelta(days=2)
        assert grid.cursor_time == at("07:30", TODAY + timedelta(days=2))
        assert app.posted == []
        await pilot.click(WeekView, offset=(xs[0] + 3, 1 + header + 14))  # Mon 13:30
        await pilot.pause()
        assert isinstance(app.posted[-1], messages.EventSelected)
        assert app.posted[-1].occurrence.summary == "Sprint planning"
        await pilot.click(WeekView, offset=(xs[2] + 3, 1))  # header of Wed
        assert app.state.day == TODAY


def wheel(grid: TimeGrid, event: type[events.MouseScrollUp | events.MouseScrollDown]) -> None:
    grid.post_message(event(grid, 5, 10, 0, 1, 0, False, False, False))


async def test_mouse_wheel_scrolls(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        grid = app.query_one(WeekView)
        wheel(grid, events.MouseScrollUp)
        await pilot.pause()
        assert text(grid)[5].startswith("06:00")  # two rows up: 05:30 on top
        wheel(grid, events.MouseScrollDown)
        wheel(grid, events.MouseScrollDown)
        await pilot.pause()
        assert text(grid)[5].startswith("07:00")  # clamped: 23:30 stays the last row


async def test_day_view(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("d")
        assert app.state.view is ViewMode.DAY
        grid = app.query_one(DayView)
        lines = text(grid)
        assert "Wednesday, 18 November" in lines[0]
        body = "\n".join(lines)
        assert "Design review" in body and "1:1 with Alex" in body and "Dentist" in body
        await pilot.press("l")
        assert "Thursday, 19 November" in text(grid)[0]
