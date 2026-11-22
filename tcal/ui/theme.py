"""Color palettes (todooit's look) exposed as Textual themes.

Every palette field becomes a CSS variable (``$background1``, ``$red``, ...) for
styles.tcss; ``primary``/``secondary`` map to Textual's own ``$primary`` and
``$secondary``. Python code that needs a color (e.g. to blend an event block)
reads ``app.palette``.
"""

from dataclasses import asdict, dataclass

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
MAX_TEXT_LUMA = 0.45  # brighter text (e.g. a pastel calendar colour) is hard to read on light


def luma(hex_color: str) -> float:
    """Perceived brightness of ``#RRGGBB``, 0 (black) .. 1 (white)."""
    r, g, b = (int(hex_color.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4))
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255


def legible(color: str, palette: Palette) -> str:
    """``color`` as text on the palette's background: darkened on light themes."""
    level = luma(color)
    if luma(palette.background1) < 0.5 or level <= MAX_TEXT_LUMA:
        return color
    scale = MAX_TEXT_LUMA / level
    r, g, b = (round(int(color.lstrip("#")[i : i + 2], 16) * scale) for i in (0, 2, 4))
    return f"#{r:02X}{g:02X}{b:02X}"


def text_on(color: str, palette: Palette) -> str:
    """The palette's background or text colour, whichever reads better on ``color``."""
    dark, light = sorted((palette.background1, palette.foreground3), key=luma)
    return dark if luma(color) > 0.6 else light


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
