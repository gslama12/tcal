"""Day/Week time grid in the running app: navigation, zoom, selection, mouse."""

from datetime import datetime, time, timedelta

import pytest
from conftest import TODAY, RecordingApp
from textual import events

from tcal.model import Event
from tcal.store import Store
from tcal.ui import messages, timepaint
from tcal.ui.state import ViewMode
from tcal.ui.theme import EDGE, blend
from tcal.ui.timelayout import sub_columns
from tcal.ui.timepaint import CURSOR_ALPHA, HOUR_LINE
from tcal.ui.widgets import timegrid
from tcal.ui.widgets.timegrid import AXIS, DayView, TimeGrid, WeekView

NOW = datetime.combine(TODAY, time(10, 15)).astimezone()
SIZE = (140, 45)  # week grid: 4 header rows + 35 rows -> 06:30-24:00 at 2 rows/hour


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(timegrid, "now", lambda: NOW)


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
        for title in ("Standup", "Sprint", "planning", "Dinner", "Late movie", "Haircut"):
            assert title in body
        assert "Early run" not in body  # 05:45: above the default range
        xs = grid._columns()
        now_line = next(line for line in lines if line[xs[2]] == "●")  # on Wed's edge
        assert "─" in now_line[xs[2] : xs[3]] or "Design" in now_line  # today = Wed
        assert now_line[xs[3]] == "│" and "─" not in now_line[xs[3] :]
        assert "10:15" not in body and "10:00" in body  # hour labels stay
        assert grid.rows_per_hour == 2
        assert grid.cursor_time == at("10:00")  # starts at "now", snapped to the slot
        screenshot = app.export_screenshot()
        assert "Standup" in screenshot and "Conference" in screenshot


@pytest.mark.usefixtures("quarter_steps")
async def test_cursor_moves_and_crosses_week(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        app.set_grid_mode(True)  # the slot cursor
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
        app.set_grid_mode(True)  # the slot cursor
        grid = app.query_one(WeekView)
        await pilot.press(*["k"] * 30)
        assert grid.cursor_time == at("00:00")
        lines = text(grid)
        assert lines[4].startswith("00:00")
        assert any("Early run" in line for line in lines)


@pytest.mark.usefixtures("quarter_steps")
async def test_zoom(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        app.set_grid_mode(True)  # the slot cursor
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
        assert grid.rows_per_hour == 1  # too small: smallest zoom, scrolled to the cursor
        top = grid._top_row()
        assert top <= grid._cursor_row() < top + grid._grid_height()


async def test_headers_share_one_format(store: Store) -> None:
    for width, label in ((200, "Wednesday 18"), (140, "Wed 18"), (90, "18")):
        app = RecordingApp(store)
        async with app.run_test(size=(width, 45)):
            line = text(app.query_one(WeekView))[0]
            assert label in line
            assert "," not in line  # "Monday, 16 November" only when every column fits it


@pytest.mark.usefixtures("quarter_steps")
async def test_cursor_slot_has_accent_background(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        app.set_grid_mode(True)  # the slot cursor
        grid = app.query_one(WeekView)
        await pilot.press(*"jjjjj")  # 12:30, an empty slot on Wed
        row = grid._cursor_row() - grid._top_row() + grid._header_height()
        backgrounds = {
            seg.style.bgcolor.name
            for seg in grid.render_line(row)
            if seg.style and seg.style.bgcolor and not seg.text.strip()
        }
        p = app.palette
        assert blend(p.primary, p.background1, CURSOR_ALPHA).lower() in backgrounds


@pytest.mark.usefixtures("quarter_steps")
async def test_cycle_events_and_open(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        app.set_grid_mode(True)  # the slot cursor
        grid = app.query_one(WeekView)
        await pilot.press("j", "j", "j")  # 11:30 on today: inside "Dentist"
        assert grid.selected is not None and grid.selected.summary == "Dentist"
        await pilot.press("n")
        assert grid.selected is not None and grid.selected.summary == "Dinner"
        await pilot.press("n", "n")  # Late movie, then the next day's all-day event
        assert grid.selected is not None and grid.selected.summary == "Deadline: taxes"
        assert app.state.day == TODAY + timedelta(days=1)
        await pilot.press("N", "N", "N", "N")  # back over Late movie, Dinner, Dentist
        assert grid.selected is not None and grid.selected.summary == "1:1 with Alex"
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.posted[-1], messages.EventSelected)
        assert app.posted[-1].occurrence.summary == "1:1 with Alex"


@pytest.mark.usefixtures("quarter_steps")
async def test_new_event_on_empty_slot(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        app.set_grid_mode(True)  # the slot cursor
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
        assert lines[0].strip() == "Wed 18"  # the toolbar already shows the full date
        body = "\n".join(lines)
        assert "Design review" in body and "1:1 with Alex" in body and "Dentist" in body
        await pilot.press("l")
        assert "Thu 19" in text(grid)[0]


FITTED = (140, 40)  # 30-row grid: 06:30-24:00 at 1.71 rows/hour (35 min per row)


@pytest.mark.usefixtures("quarter_steps")
async def test_fitted_slots_snap_to_quarter_hours(app: RecordingApp) -> None:
    async with app.run_test(size=FITTED) as pilot:
        app.set_grid_mode(True)  # the slot cursor
        grid = app.query_one(WeekView)
        assert grid.scale.even is False
        assert grid.cursor_time == at("10:00")  # now = 10:15
        xs, header = grid._columns(), grid._header_height()
        y = next(y for y, line in enumerate(text(grid)) if line.startswith("16:00"))
        await pilot.click(WeekView, offset=(xs[2] + 3, 1 + y))  # next to the 16:00 label
        assert grid.cursor_time == at("16:00")
        assert text(grid)[y].startswith("16:00")
        times = set()
        for _ in range(8):
            await pilot.press("j")
            times.add(grid.cursor_time)
        assert len(times) == 8 and all(t.minute % 15 == 0 for t in times)
        assert y >= header


async def test_zoom_ladder_returns_to_fit(app: RecordingApp) -> None:
    async with app.run_test(size=FITTED) as pilot:
        grid = app.query_one(WeekView)
        fitted = grid.scale
        await pilot.press(*["plus"] * 5)
        assert grid.rows_per_hour == 8
        await pilot.press("minus", "minus", "minus", "minus")
        assert grid.rows_per_hour == 2
        await pilot.press("minus")
        assert grid.scale == fitted  # the fit is the stop below 2 rows/hour
        assert grid._top_row() == fitted.row_of(6 * 60 + 30)  # 06:30 on top again
        await pilot.press("minus", "minus")
        assert grid.scale == fitted  # 1 row/hour would leave empty rows below 24:00
        await pilot.press("plus")
        assert grid.rows_per_hour == 2


async def test_hidden_events_have_markers(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        app.set_grid_mode(True)  # the slot cursor
        grid = app.query_one(WeekView)
        lines, xs, header = text(grid), grid._columns(), grid._header_height()
        early = next(o for o in grid._occurrences() if o.summary == "Early run")
        col = grid._load()[0].index(early.start.date())
        assert "▲ 1 earlier" in lines[header][xs[col] : xs[col + 1]]
        assert "▲" not in "".join(line[xs[col + 1] :] for line in lines)
        await pilot.press(*["k"] * 30)  # scroll to 00:00
        lines = text(grid)
        assert "▲" not in "".join(lines)
        assert any("later" in line for line in lines[-1:])


async def test_overlaps_stack_google_style(
    app: RecordingApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(timegrid, "now", lambda: at("08:00"))  # nothing selected, no now line
    async with app.run_test(size=(200, 55)) as pilot:
        await pilot.press("d")
        await pilot.pause()
        grid = app.query_one(DayView)
        blocks = {b.occ.summary: b for b in grid._block_list() if b.day == 0}
        review, one, dentist = blocks["Design review"], blocks["1:1 with Alex"], blocks["Dentist"]
        assert (review.depth, one.depth, dentist.depth) == (0, 1, 1)
        xs = grid._columns()
        under, above = sub_columns(review, xs), sub_columns(one, xs)
        assert above == (under[0] + 2, under[1])  # indented on top of it
        lines = text(grid)
        y = grid._header_height() + one.top - grid._top_row()
        # the covered event shows beside it: its accent bar and fill
        assert lines[y][under[0] : above[0]] == f"{EDGE} "
        assert grid.render_line(y).crop(under[0], above[0]).text == f"{EDGE} "
        assert "1:1 with Alex" in lines[y] and "Design review" not in lines[y]


async def test_narrow_columns_collapse_cluster(app: RecordingApp) -> None:
    async with app.run_test(size=(70, 35)) as pilot:
        await pilot.pause()
        grid = app.query_one(WeekView)
        group = next(b for b in grid._block_list() if b.group)
        assert [o.summary for o in group.occs] == ["Design review", "1:1 with Alex", "Dentist"]
        assert any("Des… +2" in line for line in text(grid))  # first title + count
        await pilot.press("n")  # cycling reaches the events of the collapsed block
        while grid.selected not in group.occs:
            await pilot.press("n")
        first = grid.selected
        await pilot.press("n")
        assert grid.selected in group.occs and grid.selected != first
        await pilot.press("enter")
        opened = app.posted[-1]
        assert isinstance(opened, messages.EventSelected) and opened.occurrence == grid.selected


@pytest.mark.usefixtures("quarter_steps")
async def test_now_line_keeps_event_text(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        app.set_grid_mode(True)  # the slot cursor
        await pilot.press("d")
        await pilot.pause()
        grid = app.query_one(DayView)
        row = next(line for line in text(grid) if line[AXIS] == "●")
        assert row.startswith("10:00")  # the slot keeps its label; no "10:15" replaces it
        event = row[AXIS + 1 : row.index("Design review") + len("Design review")]
        assert event == " 10:00 Design review"  # text not covered (one free row: time + title)
        assert "─" in row[row.index("Design review") :]  # the line goes on beside the event


@pytest.mark.usefixtures("quarter_steps")
async def test_cycle_starts_at_the_cursor(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        app.set_grid_mode(True)  # the slot cursor
        grid = app.query_one(WeekView)
        tue, mon = TODAY - timedelta(days=1), TODAY - timedelta(days=2)
        await pilot.press("h", "k", "k", "k")  # Tue 08:30, free
        assert grid.selected is None
        await pilot.press("n")
        assert grid.selected is not None and grid.selected.start == at("09:00", tue)
        await pilot.press("k", "N")  # Tue 08:30 again: the event before is on Monday
        assert grid.selected is not None and grid.selected.start.date() == mon
        await pilot.press("h", *["k"] * 30, "N")  # nothing before Mon 00:00: wraps to the end
        assert grid.selected == sorted(grid._occurrences(), key=grid._stop_key)[-1]


async def test_double_click_empty_slot_requests_new_event(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        grid = app.query_one(WeekView)
        xs, header = grid._columns(), grid._header_height()
        await pilot.click(WeekView, offset=(xs[4] + 3, 1 + header + 2), times=2)  # Fri 07:30
        await pilot.pause()
        assert [type(m) for m in app.posted] == [messages.NewEventRequested]
        assert isinstance(app.posted[0], messages.NewEventRequested)
        assert app.posted[0].start == at("07:30", TODAY + timedelta(days=2))


async def test_text_is_cut_with_ellipsis_never_mid_number(app: RecordingApp) -> None:
    async with app.run_test(size=(100, 35)) as pilot:
        await pilot.pause()
        body = "\n".join(text(app.query_one(WeekView)))
        assert "Anna's bir…" in body and "Rele…" in body
        assert "13:00–15:00" in body and "14:00 Rele…" in body  # no "14:00–1"
        assert "–1 " not in body and "–1│" not in body


async def test_markers_and_hour_lines_leave_events_alone(app: RecordingApp) -> None:
    async with app.run_test(size=(100, 35)) as pilot:
        await pilot.press(*["plus"] * 6)  # 8 rows/hour: events cross the bottom edge
        grid = app.query_one(WeekView)
        xs, lines = grid._columns(), text(grid)
        for block in grid._block_list():
            left, right = sub_columns(block, xs)
            for row in range(max(block.top, grid._top_row()), block.bottom):
                y = grid._header_height() + row - grid._top_row()
                if y < len(lines):
                    assert not {"▲", "▼"} & set(lines[y][left:right])
                    assert "▔" not in lines[y][right : right + 1] + lines[y][left - 1 : left]
        assert any("later" in line for line in lines)


def test_wrap_breaks_titles_at_words() -> None:
    assert timepaint.wrap("Design review", 8, 3) == ["Design", "review"]
    assert timepaint.wrap("Design review", 4, 3) == ["Des…", "rev…"]
    assert timepaint.wrap("Release party tonight", 13, 1) == ["Release part…"]
    assert timepaint.wrap("Release party tonight", 6, 2) == ["Relea…", "party…"]
    assert timepaint.wrap("", 5, 2) == []


async def test_tall_blocks_wrap_the_title_before_the_time(app: RecordingApp) -> None:
    async with app.run_test(size=(100, 35)) as pilot:
        await pilot.pause()
        lines = text(app.query_one(WeekView))
        sprint = next(i for i, line in enumerate(lines) if "Sprint" in line)
        assert "planning" in lines[sprint + 1] and "13:00–15:00" in lines[sprint + 2]


@pytest.mark.usefixtures("quarter_steps")
async def test_later_marker_moves_to_the_header_off_the_cursor_row(app: RecordingApp) -> None:
    async with app.run_test(size=(100, 35)) as pilot:
        app.set_grid_mode(True)  # the slot cursor
        await pilot.press(*["plus"] * 7, *["j"] * 30)  # 8 rows/hour, cursor on the bottom rows
        await pilot.press(*["k"] * 10, *["j"] * 10)  # (scrolls down while moving, so back up)
        grid = app.query_one(WeekView)
        xs, lines = grid._columns(), text(grid)
        cursor_y = grid._header_height() + grid._cursor_row() - grid._top_row()
        column = slice(xs[2] + 1, xs[3])  # Wed, the selected day
        assert cursor_y == len(lines) - 2  # the 15-min slot: two rows
        assert "▼" not in "".join(line[column] for line in lines[1:])  # never mid-grid
        assert lines[0][column].endswith("▼2")  # in the day's header instead
        assert "▼ 1 later" in lines[-1][xs[1] + 1 : xs[2]]  # other columns: the edge row


@pytest.mark.usefixtures("quarter_steps")
async def test_max_zoom_keeps_the_cursor_on_quarter_hours(app: RecordingApp) -> None:
    async with app.run_test(size=(100, 35)) as pilot:
        app.set_grid_mode(True)  # the slot cursor
        grid = app.query_one(WeekView)
        await pilot.press("plus", "plus", "plus", "j")
        assert grid.rows_per_hour == 4
        before = grid.cursor_time
        assert before == at("10:15")
        await pilot.press("plus", "plus")  # 6 rows/hour can't show 10:15 (10:10), 8 can
        assert grid.rows_per_hour == 8
        assert grid.cursor_time == before  # zooming doesn't drift (no 18:08)
        times = []
        for key in ("j", "j", "j", "k"):
            await pilot.press(key)
            times.append(grid.cursor_time)
        assert [(t - before).seconds // 60 for t in times] == [15, 30, 45, 30]
        assert len(grid._cursor_rows()) == 2
        xs, header = grid._columns(), grid._header_height()
        odd = grid._cursor_row() + 1 - grid._top_row()  # the slot's second row
        await pilot.click(WeekView, offset=(xs[2] + 3, 1 + header + odd))
        assert grid.cursor_time.minute % 15 == 0
        await pilot.press(*["minus"] * 7)
        assert grid.cursor_time.minute % 15 == 0


async def test_later_marker_goes_to_the_header_when_events_fill_the_edge_row(
    store: Store,
) -> None:
    app = RecordingApp(store)
    async with app.run_test(size=(80, 24)) as pilot:  # 1 row/hour, 06:00-20:00 shown
        app.set_grid_mode(True)  # the slot cursor
        grid = app.query_one(WeekView)
        await pilot.press(*["j"] * 9)  # 19:00, the last row: Dinner fills it
        xs, col = grid._columns(), grid._load()[0].index(TODAY)
        frame = grid._frame()
        late = next(o for o in grid._occurrences() if o.summary == "Late movie")
        assert late.start.date() == TODAY
        assert grid.scale.row_of(late.start.hour * 60) >= frame.bottom(grid.size.height)
        marker = next(m for m in timepaint.markers(frame, grid.size.height) if m.day == col)
        assert late in marker.hidden and marker.label == "▼1" and marker.y == 0
        assert text(grid)[0][xs[col] : xs[col + 1]].endswith("18▼1")  # not above Dinner
        await pilot.click(WeekView, offset=(1 + marker.x0, 1))
        assert grid.selected == late


async def test_clicking_a_marker_scrolls_to_the_hidden_event(app: RecordingApp) -> None:
    async with app.run_test(size=(200, 55)) as pilot:
        await pilot.pause()
        grid = app.query_one(WeekView)
        early = next(o for o in grid._occurrences() if o.summary == "Early run")
        frame = grid._frame()
        marker = next(m for m in timepaint.markers(frame, grid.size.height) if "▲" in m.label)
        assert early in marker.hidden
        assert marker.y == grid._header_height()  # the top edge row
        await pilot.click(WeekView, offset=(1 + marker.x0 + 1, 1 + marker.y))
        assert grid.selected == early
        assert grid._top_row() <= grid.scale.row_of(5 * 60 + 45)  # now in view
        assert not app.posted  # selects, doesn't open


async def test_opening_the_week_scrolls_to_the_cursor(
    store: Store, write_config, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(timegrid, "now", lambda: at("19:30"))
    config = write_config(
        '[view]\nday_start = "08:00"\nday_end = "20:00"\nrows_per_hour = 4\n'
        'default_view = "schedule"\n'
    )
    app = RecordingApp(store, config)
    async with app.run_test(size=(100, 35)) as pilot:
        app.set_grid_mode(True)  # the slot cursor
        await pilot.press("w")
        await pilot.pause()
        grid = app.query_one(WeekView)
        top = grid._top_row()
        assert top <= grid._cursor_row() < top + grid._grid_height()
        assert grid.selected is not None and grid.selected.summary == "Dinner"
        assert any("Dinner" in line for line in text(grid))  # what enter would open


@pytest.mark.parametrize("size", [(100, 35), (200, 55)])
async def test_a_covered_time_moves_below_its_cover(
    app: RecordingApp, size: tuple[int, int]
) -> None:
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        grid = app.query_one(WeekView)
        xs, lines = grid._columns(), text(grid)
        thu = slice(xs[3] + 1, xs[4])  # Release 14:00 under Interview 14:30
        cells = [line[thu] for line in lines]
        title = next(i for i, c in enumerate(cells) if "Inte" in c)
        assert "14:00" not in cells[title]
        assert any("14:00" in c for c in cells[:title] + cells[title + 1 :])  # still shown


@pytest.mark.parametrize("height", [24, 40, 45, 53])
@pytest.mark.parametrize("zooms", range(3))
async def test_an_hour_fills_the_cell_between_two_hour_lines(
    app: RecordingApp, height: int, zooms: int
) -> None:
    sat, sun = TODAY + timedelta(days=3), TODAY + timedelta(days=4)
    async with app.run_test(size=(140, height)) as pilot:
        await pilot.press(*["plus"] * zooms)
        app.save_event(Event("new", "work", "Hour", at("10:00", sat), at("11:00", sat)))
        for calendar in app.calendars():
            if calendar.id != "work":  # the weekend's demo events
                app.toggle_calendar(calendar.id)
        await pilot.pause()
        grid = app.query_one(WeekView)
        xs, lines = grid._columns(), text(grid)
        first, end = (
            next(y for y, t in enumerate(lines) if t[:5] == h) for h in ("10:00", "11:00")
        )
        cell = list(range(first, end))
        assert [y for y, t in enumerate(lines) if t[xs[5] + 1] == EDGE] == cell
        if grid.rows_per_hour >= 2:  # the lines are the top edges of the rows below them
            ruled = [y for y, t in enumerate(lines) if t[xs[6] + 1] == HOUR_LINE]
            assert ruled[ruled.index(first) + 1] == end

        app.set_grid_mode(True)
        app.select_date(sun)
        await pilot.pause()
        accent = blend(app.palette.primary, app.palette.background1, CURSOR_ALPHA).lower()
        rows = []
        for y in range(grid.size.height):
            style = next(iter(grid.render_line(y).crop(xs[6] + 1, xs[6] + 2))).style
            if style and style.bgcolor and style.bgcolor.name == accent:
                rows.append(y)
        assert rows == cell
