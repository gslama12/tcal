"""Color palettes (todooit's look) exposed as Textual themes.

Every palette field becomes a CSS variable (``$background1``, ``$red``, ...) for
styles.tcss; ``primary``/``secondary`` map to Textual's own ``$primary`` and
``$secondary``. Python code that needs a color (e.g. to blend an event block)
reads ``app.palette``.
"""

from dataclasses import asdict, dataclass
from functools import lru_cache

from textual.theme import Theme


@dataclass(frozen=True)
class Palette:
    background1: str  # darkest: screen
    background2: str  # bars, modals
    background3: str  # borders, highlights
    foreground1: str  # dim text
    foreground2: str
    foreground3: str  # brightest text
    red: str
    orange: str
    yellow: str
    green: str
    blue: str
    purple: str
    magenta: str
    cyan: str
    primary: str  # focus border, accents
    secondary: str


NORD = Palette(
    background1="#2E3440", background2="#3B4252", background3="#434C5E",
    foreground1="#D8DEE9", foreground2="#E5E9F0", foreground3="#ECEFF4",
    red="#BF616A", orange="#D08770", yellow="#EBCB8B", green="#A3BE8C",
    blue="#81A1C1", purple="#B48EAD", magenta="#B48EAD", cyan="#8FBCBB",
    primary="#8FBCBB", secondary="#81A1C1",
)  # fmt: skip

TOKYO_NIGHT = Palette(
    background1="#1A1B26", background2="#1F2335", background3="#2F334D",
    foreground1="#A9B1D6", foreground2="#C0CAF5", foreground3="#D0D7F7",
    red="#F7768E", orange="#FF9E64", yellow="#E0AF68", green="#9ECE6A",
    blue="#7AA2F7", purple="#9D7CD8", magenta="#BB9AF7", cyan="#7DCFFF",
    primary="#7AA2F7", secondary="#BB9AF7",
)  # fmt: skip

GRUVBOX = Palette(
    background1="#282828", background2="#32302F", background3="#504945",
    foreground1="#BDAE93", foreground2="#D5C4A1", foreground3="#EBDBB2",
    red="#FB4934", orange="#FE8019", yellow="#FABD2F", green="#B8BB26",
    blue="#83A598", purple="#D3869B", magenta="#D3869B", cyan="#8EC07C",
    primary="#FABD2F", secondary="#83A598",
)  # fmt: skip

CATPPUCCIN_MOCHA = Palette(
    background1="#1E1E2E", background2="#181825", background3="#313244",
    foreground1="#A6ADC8", foreground2="#BAC2DE", foreground3="#CDD6F4",
    red="#F38BA8", orange="#FAB387", yellow="#F9E2AF", green="#A6E3A1",
    blue="#89B4FA", purple="#CBA6F7", magenta="#F5C2E7", cyan="#94E2D5",
    primary="#CBA6F7", secondary="#89B4FA",
)  # fmt: skip

# Light: background1 is the lightest, foreground3 the darkest.
CATPPUCCIN_LATTE = Palette(
    background1="#EFF1F5", background2="#E6E9EF", background3="#CCD0DA",
    foreground1="#6C6F85", foreground2="#5C5F77", foreground3="#4C4F69",
    red="#D20F39", orange="#FE640B", yellow="#DF8E1D", green="#40A02B",
    blue="#1E66F5", purple="#8839EF", magenta="#EA76CB", cyan="#179299",
    primary="#1E66F5", secondary="#8839EF",
)  # fmt: skip

PALETTES = {
    "tokyo-night": TOKYO_NIGHT,  # default, same colours as todooit's TokyoNight
    "nord": NORD,
    "gruvbox": GRUVBOX,
    "catppuccin-mocha": CATPPUCCIN_MOCHA,
    "catppuccin-latte": CATPPUCCIN_LATTE,
}
LIGHT = {"catppuccin-latte"}
# Events look like Apple Calendar's: the calendar colour at this opacity over the
# background, an accent bar in the full colour on the left, text in a tint of it;
# the selected event is filled with the full colour.
ALPHA = 0.3
EDGE = "▎"
TINT = 0.45  # text: the calendar colour mixed this far toward white (light themes: black)
MIN_CONTRAST = 4.5  # of tinted text; colours needing it are mixed further
MIN_WHITE_CONTRAST = 3.0  # of white text on a full-colour fill; else black
BLACK, WHITE = "#000000", "#FFFFFF"


def luma(hex_color: str) -> float:
    """Perceived brightness of ``#RRGGBB``, 0 (black) .. 1 (white)."""
    r, g, b = (int(hex_color.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4))
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255


@lru_cache(maxsize=1024)
def blend(color: str, below: str, alpha: float) -> str:
    """``#RRGGBB`` of ``color`` at opacity ``alpha`` over ``below``."""
    top, bottom = _rgb(color), _rgb(below)
    r, g, b = (round(alpha * c + (1 - alpha) * d) for c, d in zip(top, bottom, strict=True))
    return f"#{r:02X}{g:02X}{b:02X}"


def _rgb(hex_color: str) -> tuple[int, int, int]:
    r, g, b = (int(hex_color.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4))
    return r, g, b


def contrast(a: str, b: str) -> float:
    """The WCAG contrast ratio of two colours, 1 .. 21."""
    dark, light = sorted((_luminance(a), _luminance(b)))
    return (light + 0.05) / (dark + 0.05)


def _luminance(color: str) -> float:
    r, g, b = (
        c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
        for c in (v / 255 for v in _rgb(color))
    )
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


@lru_cache(maxsize=256)
def tint(color: str, fill: str, palette: Palette) -> str:
    """``color`` as text on ``fill``: a light tint (light themes: a dark shade) of it."""
    toward = BLACK if luma(palette.background1) > 0.5 else WHITE
    steps = (blend(toward, color, TINT + i * 0.05) for i in range(11))
    return next((c for c in steps if contrast(c, fill) >= MIN_CONTRAST), toward)


def event_colors(color: str, palette: Palette, selected: bool) -> tuple[str, str]:
    """(fill, text) of an event in a calendar's ``color``."""
    if selected:
        return color, WHITE if contrast(WHITE, color) >= MIN_WHITE_CONTRAST else BLACK
    fill = blend(color, palette.background1, ALPHA)
    return fill, tint(color, fill, palette)


def make_theme(name: str) -> Theme:
    """The Textual theme for palette ``name``; raises KeyError for unknown names."""
    p = PALETTES[name]
    variables = {k: v for k, v in asdict(p).items() if k not in ("primary", "secondary")}
    return Theme(
        name=f"tcal-{name}",
        primary=p.primary,
        secondary=p.secondary,
        accent=p.secondary,
        background=p.background1,
        surface=p.background2,
        panel=p.background3,
        foreground=p.foreground3,
        error=p.red,
        warning=p.yellow,
        success=p.green,
        dark=name not in LIGHT,
        variables=variables,
    )
