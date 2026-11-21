from datetime import date, timedelta
from pathlib import Path

import pytest
from conftest import TODAY
from textual.message import Message

from tcal.config import load_config
from tcal.source import StoreSource
from tcal.store import Store
from tcal.ui import app as app_module
from tcal.ui.app import TcalApp
from tcal.ui.messages import EventSelected, NewEventRequested
from tcal.ui.state import ViewMode
from tcal.ui.widgets.calendar_list import CalendarList
from tcal.ui.widgets.minical import MiniCal
from tcal.ui.widgets.month_view import MonthView
from tcal.ui.widgets.view_switcher import ViewSwitcher
from tcal.ui.widgets.year_view import Layout, YearView

SIZE = (120, 40)


class RecordingApp(TcalApp):
    """TcalApp that records the messages the views post for the CRUD screens."""

    CSS_PATH = str(Path(app_module.__file__).parent / "styles.tcss")

    def __init__(self, store: Store) -> None:
        super().__init__(StoreSource(store), load_config(), today=TODAY)
        self.posted: list[Message] = []

    def on_new_event_requested(self, message: NewEventRequested) -> None:
        self.posted.append(message)
        message.prevent_default()  # not TcalApp's handler (it opens a screen)

    def on_event_selected(self, message: EventSelected) -> None:
        message.prevent_default()  # record only, not TcalApp's handler (opens a screen)
        self.posted.append(message)


@pytest.fixture
def app(store: Store) -> RecordingApp:
    return RecordingApp(store)


def content(widget, x: int, y: int) -> tuple[int, int]:
    """Widget-relative click offset of content offset (x, y) (border + padding)."""
    return x + widget.gutter.left, y + widget.gutter.top


async def test_minical_keyboard_and_click(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        minical = app.query_one(MiniCal)
        minical.focus()
        await pilot.press("l", "j")
        assert minical.cursor == TODAY + timedelta(days=8)
        assert app.state.day == TODAY  # only enter commits
        await pilot.press("enter")
        assert app.state.day == TODAY + timedelta(days=8)
        assert app.focused is app.query_one(f"#{app.state.view.value}")  # enter focuses the view
        minical.focus()
        await pilot.press("H")
        assert minical.cursor == date(2026, 10, 26)
        assert app.state.day == TODAY + timedelta(days=8)

        # the browsed month (October) is shown: week row 2 is Oct 12..18, column 2 Wed
        await pilot.click(MiniCal, offset=content(minical, 6, 4))
        assert app.state.day == date(2026, 10, 14)
        assert app.focused is app.query_one(f"#{app.state.view.value}")  # click focuses the view
        await pilot.click(MiniCal, offset=content(minical, 19, 0))  # "›"
        assert minical.cursor == date(2026, 11, 14) and app.state.day == date(2026, 10, 14)


async def test_calendar_list_toggles(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("c", "j", "space")
        assert app.state.hidden_calendars == {"personal"}
        await pilot.press("k", "enter")
        assert app.state.hidden_calendars == {"personal", "work"}
        assert not any(
            o.calendar_id == "work" for o in app.occurrences(TODAY, TODAY + timedelta(days=1))
        )
        cal_list = app.query_one(CalendarList)
        await pilot.click(CalendarList, offset=content(cal_list, 2, 1))
        assert app.state.hidden_calendars == {"work"}
        assert "□ Work" in str(cal_list.render())


async def test_view_switcher_clicks(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        switcher = app.query_one(ViewSwitcher)
        assert "16 – 22 November 2026" in str(switcher.render())

        def x_of(label: str) -> int:
            return next(x for x, part in switcher._placed() if part[0].strip() == label)

        await pilot.click(ViewSwitcher, offset=content(switcher, x_of("Month"), 0))
        assert app.state.view is ViewMode.MONTH
        assert isinstance(app.focused, MonthView)
        await pilot.click(ViewSwitcher, offset=content(switcher, x_of("›"), 0))
        assert app.state.day == date(2026, 12, 18)
        await pilot.click(ViewSwitcher, offset=content(switcher, x_of("Today"), 0))
        assert app.state.day == date.today()


async def test_month_view_navigation(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("m", "l", "j")
        assert app.state.day == TODAY + timedelta(days=8)
        await pilot.press("k", "k", "k", "k")
        assert app.state.day == date(2026, 10, 29)  # crossed into October
        assert app.state.title() == "October 2026"
        await pilot.press("enter")
        assert app.state.view is ViewMode.DAY


async def test_month_view_clicks(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("m")
        await pilot.pause()
        view = app.query_one(MonthView)
        grid = view.grid()
        week = next(i for i, w in enumerate(grid.weeks) if TODAY in w)
        x = grid.xs[TODAY.weekday()] + 1
        y = grid.tops[week] + grid.rule  # TODAY's day-number line
        first_chip = view.week_cells(grid)[week][TODAY.weekday()][0]
        await pilot.click(MonthView, offset=content(view, x, y + 1))
        assert isinstance(app.posted[-1], EventSelected)
        assert app.posted[-1].occurrence == first_chip
        await pilot.click(MonthView, offset=content(view, x, y))
        assert app.state.view is ViewMode.DAY and app.state.day == TODAY


async def test_month_view_shows_more(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("m")
        await pilot.pause()
        rendered = str(app.query_one(MonthView).render())
        assert "Conference" in rendered and "more" in rendered and "Nov 1" in rendered


async def test_year_view(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("y", "j", "l")
        assert app.state.day == TODAY + timedelta(days=8)
        view = app.query_one(YearView)
        layout = Layout.build(*view.content_size)
        x, y = layout.origin(2)  # March title
        await pilot.click(YearView, offset=content(view, x + 1, y))
        assert app.state.view is ViewMode.MONTH and app.state.day == date(2026, 3, 26)
        await pilot.press("y", "enter")
        assert app.state.view is ViewMode.DAY and app.state.day == date(2026, 3, 26)


async def test_screenshot_sanity(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        for key, expected in [("m", "Conference"), ("y", "December")]:
            await pilot.press(key)
            await pilot.pause()
            svg = app.export_screenshot().replace("&#160;", " ")
            assert expected in svg and "My calendars" in svg and "November" in svg


async def test_year_view_compact_click(app: RecordingApp) -> None:
    async with app.run_test(size=(100, 35)) as pilot:
        await pilot.press("b", "y")  # show the auto-hidden sidebar: a small year view
        view = app.query_one(YearView)
        layout = Layout.build(*view.content_size)
        assert not layout.header  # QA #7: too small for weekday initials
        x, y = layout.origin(11)  # December: first week row is right below the title
        await pilot.click(YearView, offset=content(view, x + 3 * layout.cell, y + 1))
        assert app.state.day == date(2026, 12, 3)


async def test_sidebar_toggle_and_auto_hide(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        sidebar = app.query_one("#sidebar")
        assert sidebar.display
        app.query_one(MiniCal).focus()
        await pilot.press("b")
        assert not sidebar.display and app.focused is app.query_one(f"#{app.state.view.value}")
        await pilot.press("b")
        assert sidebar.display
        await pilot.resize_terminal(100, 35)
        await pilot.pause()
        assert sidebar.display  # an explicit toggle wins over resizes


async def test_sidebar_hidden_by_toggle_stays_hidden_on_resize(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        sidebar = app.query_one("#sidebar")
        await pilot.press("b")
        await pilot.resize_terminal(100, 35)
        await pilot.pause()
        await pilot.resize_terminal(*SIZE)
        await pilot.pause()
        assert not sidebar.display


async def test_narrow_sidebar_auto_hides_when_focus_leaves(app: RecordingApp) -> None:
    async with app.run_test(size=(100, 35)) as pilot:
        sidebar = app.query_one("#sidebar")
        assert not sidebar.display
        await pilot.press("c")  # focusing the calendar list shows it
        assert sidebar.display
        await pilot.press("question_mark")  # a modal on top keeps it
        await pilot.pause()
        assert sidebar.display
        await pilot.press("escape")
        await pilot.pause()
        assert sidebar.display and isinstance(app.focused, CalendarList)
        await pilot.press("tab")
        await pilot.pause()
        assert not sidebar.display and app.focused is not None
        await pilot.resize_terminal(*SIZE)
        await pilot.pause()
        assert sidebar.display


async def test_view_switcher_shortens_title_not_tabs(app: RecordingApp) -> None:
    async with app.run_test(size=(70, 24)) as pilot:
        await pilot.press("d")
        text = str(app.query_one(ViewSwitcher).render())
        assert "Day│Week│Month│Year│Schedule" in text and "Wed 18 Nov 2026" in text
