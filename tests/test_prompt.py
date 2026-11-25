import pytest
from textual.geometry import Size

from tcal.ui.screens.prompt import Prompt

CHOICES = {"o": ("overwrite", 1), "d": ("discard", 2)}


@pytest.mark.parametrize(
    ("key", "result"),
    [("o", 1), ("d", 2), ("enter", 1), ("escape", None), ("n", None)],
)
async def test_keys(make_app, key: str, result: int | None) -> None:
    app = make_app()
    answers: list[int | None] = []
    async with app.run_test() as pilot:
        app.push_screen(Prompt("Sure?", CHOICES), answers.append)
        await pilot.press("x", "q", "tab")  # other keys do nothing
        assert isinstance(app.screen, Prompt) and not answers
        await pilot.press(key)
        assert answers == [result] and not isinstance(app.screen, Prompt)


@pytest.mark.parametrize(("hint", "result"), [("o", 1), ("d", 2), ("cancel", None)])
async def test_clicking_a_hint_chooses_it(make_app, hint: str, result: int | None) -> None:
    app = make_app()
    answers: list[int | None] = []
    async with app.run_test() as pilot:
        app.push_screen(Prompt("Sure?", CHOICES), answers.append)
        await pilot.pause()
        await pilot.click("#question")  # not a hint
        assert not answers
        await pilot.click(f"#{hint}")
        await pilot.pause()
        assert answers == [result]


async def test_box_is_compact_and_wraps_a_long_question(make_app) -> None:
    app = make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        app.push_screen(Prompt("Delete [b]?", CHOICES))  # (titles aren't markup)
        await pilot.pause()
        hints = len("o overwrite · d discard · esc cancel")
        assert app.screen.query_one("#prompt").size == Size(hints, 2)
        await pilot.press("escape")
        app.push_screen(Prompt("long " * 30, CHOICES))
        await pilot.pause()
        box = app.screen.query_one("#prompt")
        assert box.size.height > 2 and box.region.right <= 80
