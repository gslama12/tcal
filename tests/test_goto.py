from datetime import date

from conftest import TODAY
from textual.widgets import Input

from tcal.dates import parse_date
from tcal.ui.screens.goto import GotoScreen


async def test_goto_prompt_jumps(make_app) -> None:
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.press("g")
        assert isinstance(app.screen, GotoScreen)
        await pilot.press(*"24.12.", "enter")
        assert not isinstance(app.screen, GotoScreen)
        assert app.state.day == date(date.today().year, 12, 24)


async def test_goto_weekday_is_relative_to_today_not_selected_day(make_app) -> None:
    app = make_app()
    async with app.run_test() as pilot:
        app.select_date(date(2020, 2, 10))
        await pilot.press("g", *"fri", "enter")
        assert app.state.day == parse_date("fri", date.today())


async def test_goto_prompt_keeps_open_on_bad_input_and_cancels(make_app) -> None:
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.press("g", *"nope", "enter")
        assert isinstance(app.screen, GotoScreen)
        assert app.screen.query_one(Input).border_subtitle == "not a date"
        await pilot.press("escape")
        assert not isinstance(app.screen, GotoScreen)
        assert app.state.day == TODAY


async def test_goto_jumps_to_a_month(make_app) -> None:
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.press("g", *"jan 2027", "enter")
        assert app.state.day == date(2027, 1, 1)
