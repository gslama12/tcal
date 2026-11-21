from collections.abc import Callable
from functools import partial

from rich.style import Style
from rich.text import Text
from textual import events
from textual.app import RenderResult

from tcal.ui.state import ViewMode
from tcal.ui.widgets.base import TcalWidget

Part = tuple[str, Style, Callable[[], None] | None]


class ViewSwitcher(TcalWidget):
    """Top bar: [Today] ‹ › range title on the left, Day | Week | Month | Year | Schedule on the right.

    Every button is clickable: Today, prev/next period and the view tabs (the
    active one highlighted) call the app's actions.
    """

    def _parts(self, short: bool, compact: bool = False) -> tuple[list[Part], list[Part]]:
        app, p = self.tcal, self.tcal.palette
        button = Style(color=p.foreground3, bgcolor=p.background3, bold=True)
        arrow = Style(color=p.primary, bold=True)
        left: list[Part] = [
            (" Today ", button, app.action_today),
            ("  ", Style(), None),
            (" ‹ ", arrow, app.action_prev_period),
            (" › ", arrow, app.action_next_period),
            ("  ", Style(), None),
            (app.state.title(short), Style(color=p.foreground3, bold=True), None),
        ]
        right: list[Part] = []
        for mode in ViewMode:
            if right:
                right.append(("│", Style(color=p.background3), None))
            active = mode is app.state.view
            style = (
                Style(color=p.background1, bgcolor=p.primary, bold=True)
                if active
                else Style(color=p.foreground1)
            )
            label = mode.value.title() if compact else f" {mode.value.title()} "
            right.append((label, style, partial(app.action_set_view, mode.value)))
        return left, right

    def _placed(self) -> list[tuple[int, Part]]:
        """Every part with its x offset; the tabs are right-aligned (if tight: a short
        title, then unpadded tabs)."""
        width = self.content_size.width
        for short, compact in ((False, False), (True, False), (True, True)):
            left, right = self._parts(short, compact)
            if sum(len(part[0]) for part in left + right) + 2 <= width:
                break
        placed, x = [], 0
        for part in left:
            placed.append((x, part))
            x += len(part[0])
        x = max(0, width - sum(len(part[0]) for part in right))
        for part in right:
            placed.append((x, part))
            x += len(part[0])
        return placed

    def render(self) -> RenderResult:
        text = Text(no_wrap=True, overflow="crop")
        for x, (label, style, _) in self._placed():
            text.truncate(x, pad=True)  # tabs overlay a title that is too long
            text.append(label, style=style)
        return text

    def on_click(self, event: events.Click) -> None:
        offset = event.get_content_offset(self)
        if offset is None:
            return
        for x, (label, _, action) in reversed(self._placed()):
            if action and x <= offset.x < x + len(label):
                action()
                return
