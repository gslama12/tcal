"""``configs/georg.toml``: a valid keymap whose umlaut keys reach the app."""

from datetime import timedelta
from pathlib import Path

from conftest import TODAY

from tcal.config import key_conflicts
from tcal.ui.screens.help import HelpScreen
from tcal.ui.state import ViewMode

GEORG = (Path(__file__).parents[1] / "configs" / "georg.toml").read_text()


def test_georg_keymap_has_no_conflicts(write_config) -> None:
    assert key_conflicts(write_config(GEORG)) == {}


async def test_georg_keymap_keys(make_app, write_config) -> None:
    app = make_app(write_config(GEORG))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("d", "ö")  # day view, next day
        assert app.state.view is ViewMode.DAY and app.state.day == TODAY + timedelta(days=1)
        await pilot.press("j", "j")
        assert app.state.day == TODAY - timedelta(days=1)
        await pilot.press("Ö")
        assert app.state.day == TODAY
        await pilot.press("J")
        assert app.state.day == TODAY - timedelta(days=1)
        await pilot.press("M", "ö", "enter")  # the mini month uses the same keys
        assert app.state.day == TODAY
        await pilot.press("question_mark")
        help_screen = app.screen
        assert isinstance(help_screen, HelpScreen)
        panel = help_screen.query_one("#help-panel")
        await pilot.press("l", "l")
        assert panel.scroll_y == 2
        await pilot.press("k")
        assert panel.scroll_y == 1
