"""A cell grid drawn into with ``fill``/``text`` and handed to Textual as Strips."""

from functools import lru_cache

from rich.cells import cell_len
from rich.segment import Segment
from rich.style import Style
from textual.strip import Strip


@lru_cache(maxsize=256)
def style(fg: str, bg: str, bold: bool = False, reverse: bool = False) -> Style:
    """A cached Style (frames reuse the same few)."""
    return Style(color=fg, bgcolor=bg, bold=bold, reverse=reverse)


class Canvas:
    """A width x height grid of cells (char + style), converted to Strips."""

    def __init__(self, width: int, height: int, style: Style) -> None:
        self.width = width
        self.chars = [[" "] * width for _ in range(height)]
        self.styles = [[style] * width for _ in range(height)]

    def fill(self, y: int, x0: int, x1: int, style: Style, char: str = " ") -> None:
        x0, x1 = max(0, x0), min(self.width, x1)
        self.chars[y][x0:x1] = [char] * (x1 - x0)
        self.styles[y][x0:x1] = [style] * (x1 - x0)

    def text(self, y: int, x0: int, x1: int, text: str, style: Style | None = None) -> None:
        """Write ``text`` into [x0, x1), clipped; wide chars take two cells."""
        x, x1 = x0, min(self.width, x1)
        for ch in text:
            w = cell_len(ch)
            if w == 0:
                continue
            if x + w > x1:
                break
            self.chars[y][x : x + w] = [ch] + [""] * (w - 1)
            if style is not None:
                self.styles[y][x : x + w] = [style] * w
            x += w

    def strips(self) -> list[Strip]:
        strips = []
        for chars, styles in zip(self.chars, self.styles, strict=True):
            segments: list[Segment] = []
            run_start = 0
            for x in range(1, self.width + 1):
                if x == self.width or styles[x] != styles[run_start]:
                    segments.append(Segment("".join(chars[run_start:x]), styles[run_start]))
                    run_start = x
            strips.append(Strip(segments, self.width))
        return strips
