from datetime import date, timedelta

from conftest import TODAY, RecordingApp

from tcal.ui.state import ViewMode
from tcal.ui.widgets.calendar_list import CalendarList
from tcal.ui.widgets.minical import MiniCal
from tcal.ui.widgets.month_view import MonthView
from tcal.ui.widgets.view_switcher import ViewSwitcher
from tcal.ui.widgets.year_view import Layout, YearView

SIZE = (120, 40)


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


async def test_year_view(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("Y", "j", "l")
        assert app.state.day == TODAY + timedelta(days=8)
        view = app.query_one(YearView)
        layout = Layout.build(*view.content_size)
        x, y = layout.origin(2)  # March title
        await pilot.click(YearView, offset=content(view, x + 1, y))
        assert app.state.view is ViewMode.MONTH and app.state.day == date(2026, 3, 26)
        await pilot.press("Y", "enter")
        assert app.state.view is ViewMode.DAY and app.state.day == date(2026, 3, 26)


async def test_screenshot_sanity(app: RecordingApp) -> None:
    async with app.run_test(size=SIZE) as pilot:
        for key, expected in [("m", "Conference"), ("Y", "December")]:
            await pilot.press(key)
            await pilot.pause()
            svg = app.export_screenshot().replace("&#160;", " ")
            assert expected in svg and "My calendars" in svg and "November" in svg


async def test_year_view_compact_click(app: RecordingApp) -> None:
    async with app.run_test(size=(100, 35)) as pilot:
        await pilot.press("b", "Y")  # show the auto-hidden sidebar: a small year view
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


async def test_year_view_scrolls_to_the_selected_month(app: RecordingApp) -> None:
    async with app.run_test(size=(80, 24)) as pilot:  # QA4 #9: too small for 12 months
        await pilot.press("Y")
        view = app.query_one(YearView)
        text = str(view.render())
        assert "November" in text and "January" not in text and "▲" in text
        app.select_date(date(2026, 1, 5))
        await pilot.pause()
        text = str(view.render())
        assert "January" in text and "November" not in text and "▼" in text
        layout = view._layout()
        x, y = layout.origin(0)
        await pilot.click(YearView, offset=content(view, x + 3 * layout.cell, y + 1))
        assert app.state.day == date(2026, 1, 1)


async def test_escape_in_the_sidebar_returns_to_the_view(app: RecordingApp) -> None:
    async with app.run_test(size=(100, 35)) as pilot:  # QA4 #13
        sidebar = app.query_one("#sidebar")
        await pilot.press("c", "space", "escape")
        await pilot.pause()
        assert app.focused is app.query_one(f"#{app.state.view.value}")
        assert not sidebar.display
        await pilot.press("c")
        app.query_one(MiniCal).focus()
        await pilot.press("escape")
        await pilot.pause()
        assert app.focused is app.query_one(f"#{app.state.view.value}")


async def test_zoom_outside_the_time_grid_says_where_it_works(app: RecordingApp) -> None:
    async with app.run_test(size=(120, 40)) as pilot:
        for view in ("m", "Y", "s"):
            await pilot.press(view)
            app.clear_notifications()
            await pilot.press("plus", "minus")
            assert [str(n.message) for n in app._notifications] == [
                "Zoom works in the day/week view"
            ] * 2
