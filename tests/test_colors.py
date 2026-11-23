"""Apple Calendar's colours and event look."""

import pytest
from rich.style import Style

from tcal.colors import APPLE_COLORS, BLUE, RED, YELLOW
from tcal.providers.fake import CALENDARS
from tcal.ui.theme import (
    BLACK,
    MIN_CONTRAST,
    MIN_WHITE_CONTRAST,
    PALETTES,
    WHITE,
    blend,
    contrast,
    event_colors,
    luma,
    tint,
)
from tcal.ui.widgets.timegrid import WeekView


async def test_calendar_colours_are_exact(make_app, write_config) -> None:
    for name in PALETTES:
        app = make_app(write_config(f'[theme]\nname = "{name}"\n'))
        async with app.run_test():
            assert [app.calendar_color(c.id) for c in CALENDARS] == [c.color for c in CALENDARS]


def test_contrast() -> None:
    assert contrast(BLACK, WHITE) == contrast(WHITE, BLACK) == 21
    assert contrast(RED, RED) == 1


@pytest.mark.parametrize("name", PALETTES)
@pytest.mark.parametrize("color", [*APPLE_COLORS, "#000080", "#FFFF80", BLACK, WHITE, "#808080"])
def test_event_colours_are_readable(name: str, color: str) -> None:
    palette = PALETTES[name]
    fill, text = event_colors(color, palette, selected=False)
    assert fill == blend(color, palette.background1, 0.3)
    assert contrast(text, fill) >= MIN_CONTRAST
    assert contrast(tint(color, palette.background1, palette), palette.background1) >= MIN_CONTRAST
    fill, text = event_colors(color, palette, selected=True)
    assert fill == color and contrast(text, fill) >= MIN_WHITE_CONTRAST


def test_tints_follow_the_theme() -> None:
    dark, light = PALETTES["tokyo-night"], PALETTES["catppuccin-latte"]
    text = event_colors(BLUE, dark, selected=False)[1]
    assert luma(text) > luma(BLUE) and text != WHITE
    text = event_colors(BLUE, light, selected=False)[1]
    assert luma(text) < luma(BLUE) and text != BLACK
    assert event_colors(RED, dark, selected=True) == (RED, WHITE)
    assert event_colors(YELLOW, dark, selected=True) == (YELLOW, BLACK)


async def test_wrapped_titles_are_bold(make_app) -> None:
    app = make_app()
    async with app.run_test(size=(150, 46)) as pilot:
        await pilot.pause()
        grid = app.query_one(WeekView)
        segments = [seg for y in range(grid.size.height) for seg in grid.render_line(y)]
        for word in ("Sprint", "planning"):  # one title on two lines
            assert any(word in s.text and s.style and s.style.bold for s in segments)
        times = [s for s in segments if "13:00–15:00" in s.text]
        assert times and not any(s.style and s.style.bold for s in times)


async def test_selected_block_is_filled_with_the_calendar_colour(make_app) -> None:
    app = make_app()
    async with app.run_test(size=(140, 45)) as pilot:
        grid = app.query_one(WeekView)
        await pilot.press("n")
        assert grid.selected is not None
        color = app.calendar_color(grid.selected.calendar_id)
        filled: list[Style] = [
            seg.style
            for y in range(grid.size.height)
            for seg in grid.render_line(y)
            if seg.style and seg.style.bgcolor and seg.style.bgcolor.name == color.lower()
        ]
        assert filled
