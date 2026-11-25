#!/usr/bin/env python3
"""
Regenerate the animated demo.

    uv run --with pillow --with time-machine python site/scripts/demo.py

Same machinery as screenshots.py (the real app, driven headlessly through
Textual's pilot against the demo data on a fixed date), except that a frame is
taken after every keypress and the frames are written out as one GIF.

The frames are rasterized here rather than exported as SVG and converted: no
SVG rasterizer available offline honours an embedded web font. So this walks
the same segments Rich would have written and draws each cell with Pillow,
straight out of the JetBrainsMono Nerd Font Mono file.

Needs **JetBrainsMono Nerd Font Mono** installed, like the screenshots do.
``--frames <dir>`` also writes every frame out as a PNG, to check the script.
"""

import argparse
import asyncio
import io
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Moves HOME to a throwaway directory, so before anything from tcal
import screenshots as shots
import time_machine
from PIL import Image, ImageDraw, ImageFont
from rich.cells import cell_len
from rich.color import blend_rgb
from rich.console import Console
from rich.segment import Segment
from rich.style import Style
from rich.terminal_theme import SVG_EXPORT_THEME as THEME
from textual.pilot import Pilot

from tcal.ui.app import TcalApp

OUT_FILE = shots.REPO_ROOT / "site" / "docs" / "public" / "demo.gif"

# The terminal the demo is recorded in
COLUMNS = 132
ROWS = 44

# A cell. The font is sized so that one glyph advance (0.6em) is exactly CELL_W,
# which keeps the box-drawing characters joined up.
FONT_SIZE = 13.34
CELL_W = 8
CELL_H = 18
PADDING = 12

# Drawn to the cell's edges, where the font's glyphs would leave gaps between
# rows: the x range and height of the filled part
BLOCKS = {
    "▎": (0, 2, CELL_H),
    "▌": (0, CELL_W // 2, CELL_H),
    "▐": (CELL_W // 2, CELL_W, CELL_H),
    "▔": (0, CELL_W, 1),
}

# --------------------------------------------------------------------------
# What is played
# --------------------------------------------------------------------------

# (key, milliseconds the frame it produces is held); no key: hold the last frame
Step = tuple[str | None, int]

TYPE_MS = 55  # one keystroke of someone typing
KEY_MS = 260  # one keystroke of someone navigating


def hold(ms: int) -> list[Step]:
    return [(None, ms)]


def press(*keys: str, ms: int = KEY_MS) -> list[Step]:
    return [(key, ms) for key in keys]


def type_(text: str) -> list[Step]:
    return [(character, TYPE_MS) for character in text]


# The flash label of Sat 16:00, the slot the script jumps to. The labels go out
# by distance from the selected event; `--frames` shows them.
FLASH_SLOT = "p"

SCRIPT: Sequence[Step] = (
    hold(1200)
    # --- step through the events, then over to the next days ---------------
    + press("j", "j", "j")
    + press("l", "l")
    + hold(500)
    # --- a new event, typed as one line ------------------------------------
    + press("a")
    + hold(400)
    + type_("Lunch with Anna tomorrow 12:30-13:30 @Cafe #per")
    + press("tab")
    + hold(1200)
    + press("enter")
    + hold(900)
    # --- an hour later, and a day on ---------------------------------------
    + press("J", "J", "J", "J", ms=160)
    + press(">")
    + hold(800)
    # --- copied; flash puts a label on every event and slot ----------------
    + press("y")
    + hold(400)
    + press("f")
    + hold(1200)
    + press(FLASH_SLOT)
    + hold(800)
    # --- ...and the copy goes there; resize mode makes it longer -----------
    + press("p")
    + hold(900)
    + press("escape")
    + press("o")
    + hold(400)
    + press("j", "j", "j", "j", ms=160)
    + hold(600)
    + press("escape")
    # --- the other views ----------------------------------------------------
    + press("m")
    + hold(1300)
    + press("Y")
    + hold(1100)
    + press("s")
    + hold(1300)
    + press("w")
    + hold(1800)
)

# --------------------------------------------------------------------------
# One frame
# --------------------------------------------------------------------------


def screen_segments(app: TcalApp) -> list[Segment]:
    """What ``App.export_screenshot`` hands to Rich's SVG writer."""
    console = Console(
        width=app.size.width,
        height=app.size.height,
        file=io.StringIO(),
        force_terminal=True,
        color_system="truecolor",
        record=True,
        legacy_windows=False,
        safe_box=False,
    )
    console.print(
        app.screen._compositor.render_update(
            full=True, screen_stack=app._background_screens, simplify=False
        )
    )
    with console._record_buffer_lock:
        return list(Segment.filter_control(console._record_buffer))


def colors(style: Style) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """A style's foreground and background, as Rich's SVG writer reads it."""
    color, bgcolor = (
        default if part is None or part.is_default else part.get_truecolor(THEME)
        for part, default in (
            (style.color, THEME.foreground_color),
            (style.bgcolor, THEME.background_color),
        )
    )
    if style.reverse:
        color, bgcolor = bgcolor, color
    if style.dim:
        color = blend_rgb(color, bgcolor, 0.4)
    return tuple(color), tuple(bgcolor)


class Frames:
    """Draws the segments of a frame into an image, one cell at a time."""

    def __init__(self, font_dir: Path | None) -> None:
        regular, bold = (
            shots.find_font(shots.FONT_FILES[name], font_dir) for name in ("regular", "bold")
        )
        self.regular = ImageFont.truetype(str(regular), FONT_SIZE)
        self.bold = ImageFont.truetype(str(bold), FONT_SIZE)
        # Sit the font's own line box in the middle of the cell
        ascent, descent = self.regular.getmetrics()
        self.baseline = ascent + (CELL_H - ascent - descent) // 2

    def render(self, app: TcalApp) -> Image.Image:
        image = Image.new(
            "RGB",
            (COLUMNS * CELL_W + 2 * PADDING, ROWS * CELL_H + 2 * PADDING),
            app.palette.background1,
        )
        draw = ImageDraw.Draw(image)
        lines = Segment.split_and_crop_lines(
            screen_segments(app), length=COLUMNS, pad=True, include_new_lines=False
        )
        for row, line in enumerate(lines):
            column, top = 0, PADDING + row * CELL_H
            for text, style, _ in line:
                style = style or Style()
                foreground, background = colors(style)
                font = self.bold if style.bold else self.regular
                for character in text:
                    cells = max(cell_len(character), 1)
                    left = PADDING + column * CELL_W
                    box = (left, top, left + cells * CELL_W - 1, top + CELL_H - 1)
                    draw.rectangle(box, fill=background)
                    if character in BLOCKS:
                        x0, x1, height = BLOCKS[character]
                        bottom = top + height - 1
                        draw.rectangle((left + x0, top, left + x1 - 1, bottom), fill=foreground)
                    elif not character.isspace():
                        draw.text(
                            (left, top + self.baseline),
                            character,
                            font=font,
                            fill=foreground,
                            anchor="ls",
                        )
                    column += cells
        return image


# --------------------------------------------------------------------------
# Driving the app
# --------------------------------------------------------------------------


async def play(pilot: Pilot[None], frames: Frames) -> tuple[list[Image.Image], list[int]]:
    app = pilot.app
    assert isinstance(app, TcalApp)
    images: list[Image.Image] = []
    durations: list[int] = []
    for key, ms in SCRIPT:
        if key is not None:
            await pilot.press(key)
            await shots.settle(pilot)
        # In real time, so that toasts go away when they would
        await asyncio.sleep(ms / 1000)
        image = frames.render(app)
        # A key that drew nothing new holds the frame that is up
        if images and image.tobytes() == images[-1].tobytes():
            durations[-1] += ms
        else:
            images.append(image)
            durations.append(ms)
    return images, durations


async def record(frames: Frames) -> tuple[list[Image.Image], list[int]]:
    async with shots.running((COLUMNS, ROWS)) as pilot:
        await asyncio.sleep(0.2)
        await shots.settle(pilot)
        return await play(pilot, frames)


# --------------------------------------------------------------------------
# The GIF
# --------------------------------------------------------------------------


def dump_frames(images: Sequence[Image.Image], durations: Sequence[int], folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for index, (image, ms) in enumerate(zip(images, durations, strict=True)):
        image.save(folder / f"{index:03d}-{ms}ms.png")


def write_gif(images: Sequence[Image.Image], durations: Sequence[int]) -> None:
    """One palette for the whole animation: smaller, and no shimmer between frames."""
    sample = images[:: max(len(images) // 40, 1)]
    width, height = images[0].size
    stack = Image.new("RGB", (width, height * len(sample)))
    for index, image in enumerate(sample):
        stack.paste(image, (0, index * height))
    palette = stack.quantize(colors=256, method=Image.Quantize.MEDIANCUT)
    mapped = [image.quantize(palette=palette, dither=Image.Dither.NONE) for image in images]
    mapped[0].save(
        OUT_FILE,
        save_all=True,
        append_images=mapped[1:],
        duration=list(durations),
        loop=0,
        optimize=True,
        disposal=1,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Regenerate the docs' demo GIF.")
    parser.add_argument("--font-dir", type=Path, help="where JetBrainsMono Nerd Font is")
    parser.add_argument("--frames", type=Path, help="also write the frames here, as PNGs")
    args = parser.parse_args()

    frames = Frames(args.font_dir)
    with time_machine.travel(shots.NOW):
        images, durations = asyncio.run(record(frames))
    print(f"{len(images)} frames, {sum(durations) / 1000:.1f}s")
    if args.frames:
        dump_frames(images, durations, args.frames)
    write_gif(images, durations)
    print(f"wrote {OUT_FILE} ({OUT_FILE.stat().st_size / 1_000_000:.1f} MB)")


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(shots.INSTANCE, ignore_errors=True)
