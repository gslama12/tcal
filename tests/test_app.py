from datetime import timedelta

from conftest import TODAY
from textual.widgets import ContentSwitcher

from tcal.ui.state import ViewMode
from tcal.ui.widgets.calendar_list import CalendarList
from tcal.ui.widgets.timegrid import TimeGrid
from tcal.ui.widgets.view_switcher import ViewSwitcher


async def test_boots_in_default_view(make_app) -> None:
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert app.state.view is ViewMode.WEEK
        assert isinstance(app.focused, TimeGrid)
        assert "16 – 22 November 2026" in str(app.query_one(ViewSwitcher).render())


async def test_navigation_keys(make_app) -> None:
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.press("m")
        assert app.state.view is ViewMode.MONTH
        assert app.query_one("#views", ContentSwitcher).current == "month"
        await pilot.press("L")
        assert app.state.day.month == 12
        await pilot.press("H", "H")
        assert app.state.day.month == 10
        await pilot.press("c")
        assert isinstance(app.focused, CalendarList)


async def test_keys_come_from_config(make_app, write_config) -> None:
    app = make_app(write_config('[keys]\nview_month = ["M"]\n'))
    async with app.run_test() as pilot:
        await pilot.press("m")
        assert app.state.view is ViewMode.WEEK
        await pilot.press("M")
        assert app.state.view is ViewMode.MONTH


async def test_umlaut_keys_bind_by_character(make_app, write_config) -> None:
    app = make_app(write_config('[keys]\ncursor_right = ["ö"]\nnext_period = ["Ö"]\n'))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("v", "ö")  # grid mode, next day
        assert app.state.day == TODAY + timedelta(days=1)
        await pilot.press("Ö")
        assert app.state.day == TODAY + timedelta(days=8)


async def test_hidden_calendars_filter_occurrences(make_app) -> None:
    app = make_app()
    async with app.run_test():
        before = app.occurrences(TODAY, TODAY + timedelta(days=1))
        app.toggle_calendar("work")
        after = app.occurrences(TODAY, TODAY + timedelta(days=1))
        assert any(o.calendar_id == "work" for o in before)
        assert not any(o.calendar_id == "work" for o in after)
