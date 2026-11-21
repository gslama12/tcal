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

PALETTES = {"nord": NORD, "tokyo-night": TOKYO_NIGHT}


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
        dark=True,
        variables=variables,
    )
