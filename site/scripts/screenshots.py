#!/usr/bin/env python3
"""
Regenerate the SVG screenshots the docs site embeds.

Runs tcal headlessly through Textual's own pilot (no terminal, nothing on
screen) against the demo data (``FakeProvider``) on a fixed date, walks to each
feature and writes an SVG of the rendered frame.

    uv run --with "fonttools[woff]" --with time-machine python site/scripts/screenshots.py

Names limit it to those scenes: ``... screenshots.py week month``. fonttools
(subsets the font below) and time-machine (stops the clock at ``NOW``) are asked
for on the command line rather than added to the project: nothing the app or its
tests do needs them.

Rich's SVG template points at Fira Code on a CDN, which an <img> is not allowed
to fetch. The font is swapped for a subset of JetBrainsMono Nerd Font Mono,
base64'd into each file, which keeps the SVG self-contained.

``HOME`` is pointed at a temporary directory before tcal is imported (and the
variables that would win over it are dropped), so nothing here can touch a real
calendar or config. The demo has no account, so there is no password either.
"""

import argparse
import asyncio
import base64
import io
import os
import re
import shutil
import tempfile
import time
import xml.etree.ElementTree as ET
from collections.abc import AsyncIterator, Iterable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "site" / "docs" / "public" / "screenshots"

# The frame every screenshot is taken in: wide enough for the sidebar, tall
# enough for two rows per hour in the week view.
COLUMNS = 140
ROWS = 46

# When the screenshots are taken: a Wednesday, early afternoon. The demo data is
# laid out around this day.
TIME_ZONE = "Europe/Vienna"
NOW = datetime(2026, 11, 18, 13, 20, tzinfo=ZoneInfo(TIME_ZONE))

# The *Mono* cut of the Nerd Font has exactly the 0.6em advance of Fira Code, so
# the columns Rich positioned still line up with the font swapped.
FONT_FAMILY = "JetBrainsMono Nerd Font Mono"
FONT_FILES = {
    "regular": "JetBrainsMonoNerdFontMono-Regular.ttf",
    "bold": "JetBrainsMonoNerdFontMono-Bold.ttf",
}
FONT_DIRS = (
    Path.home() / "Library/Fonts",
    Path("/Library/Fonts"),
    Path.home() / ".local/share/fonts",
    Path.home() / ".fonts",
    Path("/usr/share/fonts"),
    Path("/usr/local/share/fonts"),
)

INSTANCE = Path(tempfile.mkdtemp(prefix="tcal-shots-"))
os.environ["HOME"] = str(INSTANCE)
for variable in ("TCAL_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME"):
    os.environ.pop(variable, None)
os.environ["TZ"] = TIME_ZONE
time.tzset()

import time_machine  # noqa: E402
from textual.pilot import Pilot  # noqa: E402
from textual.widgets import Input, TextArea  # noqa: E402

from tcal import paths  # noqa: E402
from tcal.config import load_config  # noqa: E402
from tcal.model import Calendar, Event  # noqa: E402
from tcal.providers.base import ProviderError  # noqa: E402
from tcal.providers.fake import FakeProvider, demo_feed  # noqa: E402
from tcal.source import StoreSource  # noqa: E402
from tcal.store import Store  # noqa: E402
from tcal.sync import sync_job  # noqa: E402
from tcal.ui.app import TcalApp  # noqa: E402
from tcal.ui.sync_status import SyncState  # noqa: E402

# --------------------------------------------------------------------------
# The app
# --------------------------------------------------------------------------


class BrokenFeed(FakeProvider):
    """The demo's feed, which stopped working (for the sync log)."""

    def __init__(self) -> None:
        super().__init__(demo=False)
        self.calendars = demo_feed().calendars

    def fetch_events(self, calendar: Calendar, start: datetime, end: datetime) -> list[Event]:
        raise ProviderError("404 Not Found")


async def settle(pilot: Pilot[None]) -> None:
    """Wait for the running sync (an edit starts one) and the redraws it causes."""
    app = pilot.app
    assert isinstance(app, TcalApp)
    for _ in range(200):
        await pilot.pause()
        if app.sync_status.state is not SyncState.SYNCING:
            break
        await asyncio.sleep(0.02)
    # A caret that blinks would be there in one frame and gone in the next
    for field in (*app.screen.query(Input), *app.screen.query(TextArea)):
        field.cursor_blink = False
    await pilot.pause()


@asynccontextmanager
async def running(
    size: tuple[int, int], theme: str = "", broken_feed: bool = False
) -> AsyncIterator[Pilot[None]]:
    """tcal with fresh demo data, synced once, as ``tcal --demo`` starts it."""
    shutil.rmtree(paths.data_dir(), ignore_errors=True)
    config = load_config()
    if theme:
        config = replace(config, theme=replace(config.theme, name=theme))
    database = paths.demo_database_file()
    feed = BrokenFeed() if broken_feed else demo_feed()
    job = sync_job(FakeProvider(), database, config.sync, subscriptions=feed)
    job()
    with Store(database) as store:
        app = TcalApp(StoreSource(store), config, sync=job)
        async with app.run_test(size=size, notifications=True) as pilot:
            await settle(pilot)
            yield pilot


def press(*parts: str) -> tuple[str, ...]:
    """Keys, and text to type: ``"=text"`` is typed one character at a time."""
    keys: list[str] = []
    for part in parts:
        keys += part[1:] if part.startswith("=") else [part]
    return tuple(keys)


# --------------------------------------------------------------------------
# What is photographed
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Scene:
    """A screenshot: the keys to it from a fresh start (today's week)."""

    name: str
    keys: tuple[str, ...] = ()
    theme: str = ""
    broken_feed: bool = False


def find(text: str, *then: str) -> tuple[str, ...]:
    """Select an event with the search (which also opens its detail: esc closes it)."""
    return press("/", f"={text}", "enter", "escape", *then)


LUNCH = "Lunch with Anna fri 12:30-13:30 @Cafe Central #personal // bring the tickets"

SCENES: Sequence[Scene] = (
    # --- the views ---------------------------------------------------------
    Scene("week", find("Design review")),
    Scene("month", press("m")),
    Scene("year", press("Y")),
    Scene("schedule", press("s", "=jjjjjjj")),
    Scene("zoom", find("Design review", "+", "+", "+")),
    Scene("calendars", press("c", "j", "space", "j")),
    # --- events ------------------------------------------------------------
    Scene("prompt", press("a", f"={LUNCH}")),
    Scene("prompt-repeat", press("a", "=Choir every mon, wed 19:00 for 90m until dec #fam", "tab")),
    Scene("prompt-warning", press("a", "=Offsite 25:00 #wokr")),
    Scene("detail", find("Budget", "enter")),
    Scene("form", find("Design review", "e")),
    Scene("form-series", find("Gym", "e", "s", "tab", "tab", "tab", "tab", "tab", "tab", "tab")),
    Scene("scope", find("Standup", "d")),
    Scene("undo", find("Dinner", "K", "K", ">", "u")),
    # --- moving around -----------------------------------------------------
    Scene("flash", find("Dentist", "f")),
    Scene("grid", find("Dentist", "v", "j")),
    Scene("resize", find("Dinner", "o", "=jjjj")),
    Scene("marks", find("Design review", "tab", "j", "tab", "j", "tab", "j", "tab")),
    Scene("goto", press("g", "=next fri")),
    Scene("search", press("/", "=re")),
    # --- the rest ----------------------------------------------------------
    Scene("help", press("?")),
    Scene("sync-log", press("R"), broken_feed=True),
    Scene("theme-nord", find("Design review"), theme="nord"),
    Scene("theme-gruvbox", find("Design review"), theme="gruvbox"),
    Scene("theme-catppuccin-mocha", find("Design review"), theme="catppuccin-mocha"),
    Scene("theme-catppuccin-latte", find("Design review"), theme="catppuccin-latte"),
)


async def capture(scene: Scene) -> Path:
    async with running((COLUMNS, ROWS), scene.theme, scene.broken_feed) as pilot:
        for key in scene.keys:
            await pilot.press(key)
            await settle(pilot)
        await asyncio.sleep(0.1)
        pilot.app.save_screenshot(filename=f"{scene.name}.svg", path=str(OUT_DIR))
    return OUT_DIR / f"{scene.name}.svg"


# --------------------------------------------------------------------------
# Putting the real font into the frames
# --------------------------------------------------------------------------

# Rich writes two of these, both pointing at Fira Code on a CDN
FONT_FACE_RE = re.compile(r"@font-face\s*\{[^}]*\}\s*")
MATRIX_FAMILY_RE = re.compile(r"font-family:\s*Fira Code,\s*monospace;")


def find_font(name: str, extra: Path | None) -> Path:
    for root in (extra, *FONT_DIRS):
        if root and root.exists() and (found := next(root.rglob(name), None)):
            return found
    raise SystemExit(
        f"Could not find {name}.\nInstall JetBrainsMono Nerd Font, or pass --font-dir <path>."
    )


def characters_used(paths: Iterable[Path]) -> set[str]:
    """Every character the frames draw (and the blanks Rich pads rows with)."""
    used = {" ", " "}
    for path in paths:
        for element in ET.parse(path).getroot().iter():
            if element.tag.rsplit("}", 1)[-1] == "text":
                used.update(element.text or "")
    return {character for character in used if character == "\u00a0" or character.isprintable()}


def subset_woff2(font_path: Path, characters: set[str]) -> bytes:
    from fontTools import subset
    from fontTools.ttLib import TTFont

    font = TTFont(font_path, recalcTimestamp=False)
    if missing := {c for c in characters if ord(c) not in font.getBestCmap()}:
        print(f"  not in {font_path.name}: {' '.join(sorted(missing))}")

    options = subset.Options()
    # Ligatures would merge two cells into one glyph and take the row's columns
    # with them, so the layout tables go entirely
    options.layout_features = []
    options.notdef_outline = True
    options.drop_tables += ["PfEd"]  # FontForge's own notes
    subsetter = subset.Subsetter(options=options)
    subsetter.populate(unicodes={ord(character) for character in characters})
    subsetter.subset(font)

    font.flavor = "woff2"
    buffer = io.BytesIO()
    font.save(buffer)
    return buffer.getvalue()


def font_face_css(data: bytes, weight: int) -> str:
    encoded = base64.b64encode(data).decode("ascii")
    return (
        "    @font-face {\n"
        f'        font-family: "{FONT_FAMILY}";\n'
        f'        src: url("data:font/woff2;base64,{encoded}") format("woff2");\n'
        "        font-style: normal;\n"
        f"        font-weight: {weight};\n"
        "    }\n"
    )


def embed_font(path: Path, font_dir: Path | None) -> None:
    """Swap Rich's web font for the glyphs the frame uses."""
    characters = characters_used([path])
    faces = "".join(
        font_face_css(subset_woff2(find_font(FONT_FILES[name], font_dir), characters), weight)
        for name, weight in (("regular", 400), ("bold", 700))
    )
    svg = FONT_FACE_RE.sub("", path.read_text(encoding="utf-8"))
    svg = svg.replace("<style>\n", "<style>\n" + faces, 1)
    svg = MATRIX_FAMILY_RE.sub(
        f'font-family: "{FONT_FAMILY}", monospace;\n        font-variant-ligatures: none;', svg
    )
    path.write_text(svg, encoding="utf-8", newline="\n")


# --------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Regenerate the docs' screenshots.")
    parser.add_argument("names", nargs="*", help="scenes to take (default: all)")
    parser.add_argument("--font-dir", type=Path, help="where JetBrainsMono Nerd Font is")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"writing to {OUT_DIR}")
    for scene in SCENES:
        if args.names and scene.name not in args.names:
            continue
        with time_machine.travel(NOW):
            path = asyncio.run(capture(scene))
        embed_font(path, args.font_dir)
        print(f"  {path.name}")


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(INSTANCE, ignore_errors=True)
