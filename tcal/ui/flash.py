"""Flash jump for the Day/Week grid (``f``), after todooit's flash mode.

Every event on screen and every visible hour (and half hour, when it has a row of
its own) of each day column gets a red label; typing a label moves the cursor there.
Nearest the cursor get the shortest labels. While the labels are up every key goes
to the flash: a label prefix narrows them, anything else (escape too) cancels.

Pure: ``targets`` reads a ``GridFrame``, ``overlay`` draws over painted lines.
"""

from dataclasses import dataclass

from rich.segment import Segment
from rich.style import Style
from textual.color import Color
from textual.filter import dim_color
from textual.strip import Strip

from tcal.model import Occurrence
from tcal.ui.theme import Palette
from tcal.ui.timelayout import sub_columns
from tcal.ui.timepaint import GridFrame

# todooit's: home row first (qwertz), then the rest of the letters
ALPHABET = "asdfghjklöqwertzuiopyxcvbnm"
DIM = 0.5  # how far the grid's text is pulled towards its background
DAY_WEIGHT = 4  # cells across that count as far as one row down


@dataclass(frozen=True)
class Target:
    """A jump target: an event (``occ``) or the slot at ``minute`` of column ``day``;
    its label goes at widget cell (``x``, ``y``)."""

    x: int
    y: int
    day: int
    minute: int = 0
    occ: Occurrence | None = None


def flash_labels(count: int, alphabet: str = ALPHABET) -> list[str]:
    """``count`` prefix-free labels, shortest first: as many single keys as still
    leave enough pairs (on the remaining letters) for the rest."""
    n = len(alphabet)
    if count <= n:
        return list(alphabet[:count])
    singles = max(0, (n * n - count) // (n - 1))  # singles + (n - singles) * n >= count
    pairs = [a + b for a in alphabet[singles:] for b in alphabet]
    return (list(alphabet[:singles]) + pairs)[:count]


def targets(frame: GridFrame, height: int) -> list[Target]:
    """The events and slots on screen, nearest the cursor first."""
    xs, scale, top, header = frame.xs, frame.scale, frame.top, frame.header
    bottom = frame.bottom(height)
    found: list[Target] = []
    for bar in frame.bars:
        if bar.lane < frame.strip_rows:
            found.append(Target(xs[bar.first] + 1, 1 + bar.lane, bar.first, occ=bar.occ))
    for block in frame.blocks:
        if block.bottom > top and block.top < bottom:
            y = header + max(block.top, top) - top
            found.append(Target(sub_columns(block, xs)[0], y, block.day, occ=block.occ))
    taken = {(t.x + dx, t.y) for t in found for dx in (0, 1)}
    step = 30 if scale.rows_per_hour >= 2 else 60
    rows: dict[int, int] = {}  # row -> its first slot minute
    for minute in range(0, 24 * 60, step):
        rows.setdefault(scale.row_of(minute), minute)
    for day in range(len(frame.days)):
        x = xs[day] + 1
        for row, minute in rows.items():
            y = header + row - top
            if top <= row < bottom and not {(x, y), (x + 1, y)} & taken:
                found.append(Target(x, y, day, minute))
    cursor = (xs[frame.days.index(frame.day)] + 1, header + frame.cursor_rows.start - top)
    return sorted(found, key=lambda t: (_distance(t, cursor), t.occ is None))


def _distance(target: Target, cursor: tuple[int, int]) -> float:
    """Screen distance; rows are taller than cells are wide."""
    return abs(target.y - cursor[1]) + abs(target.x - cursor[0]) / DAY_WEIGHT


@dataclass
class Flash:
    """The labels while flashing, and the keys typed into them."""

    labels: dict[str, Target]
    typed: str = ""
    done: bool = False

    @classmethod
    def of(cls, found: list[Target], alphabet: str = ALPHABET) -> "Flash":
        return cls(dict(zip(flash_labels(len(found), alphabet), found, strict=False)))

    def press(self, key: str) -> Target | None:
        """One key: a whole label returns its target, a label's first key narrows,
        backspace takes a typed key back; anything else cancels. ``done`` once over."""
        if key == "backspace" and self.typed:
            self.typed = ""
            return None
        typed = self.typed + key
        target = self.labels.get(typed)
        if target is None and len(key) == 1 and any(k.startswith(typed) for k in self.labels):
            self.typed = typed
            return None
        self.done = True
        return target

    def shown(self) -> list[tuple[str, Target]]:
        """The labels still matching what was typed."""
        return [(k, t) for k, t in self.labels.items() if k.startswith(self.typed)]


def overlay(lines: list[Strip], flash: Flash, palette: Palette) -> list[Strip]:
    """``lines`` with their text dimmed and the flash's labels drawn over them."""
    background = Color.parse(palette.background1).rich_color

    def dim(st: Style | None) -> Style | None:
        if st is None or st.color is None:
            return st
        return st + Style(color=dim_color(st.bgcolor or background, st.color, DIM))

    out = [Strip([Segment(s.text, dim(s.style)) for s in line], line.cell_length) for line in lines]
    red = Color.parse(palette.red)
    typed_style = Style(
        color=red.blend(Color.parse(palette.background1), DIM).rich_color, bold=True
    )
    label_style = Style(color=red.rich_color, bgcolor=background, bold=True)
    n = len(flash.typed)
    for label, t in flash.shown():
        if not 0 <= t.y < len(out):
            continue
        line = out[t.y]
        x = max(0, min(t.x, line.cell_length - len(label)))
        drawn = Strip(
            [Segment(label[:n], label_style + typed_style), Segment(label[n:], label_style)],
            len(label),
        )
        out[t.y] = Strip.join([line.crop(0, x), drawn, line.crop(x + len(label), line.cell_length)])
    return out
