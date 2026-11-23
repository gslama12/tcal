"""``MainScreen``: the app's base screen."""

from typing import ClassVar

from textual.binding import Binding, BindingType
from textual.screen import Screen


class MainScreen(Screen[None], inherit_bindings=False):
    """Textual's screen without its tab / shift+tab focus cycling: panes are reached
    with their own keys (``focus_calendars``, ``focus_minical``, ``cancel``)."""

    BINDINGS: ClassVar[list[BindingType]] = [
        b for b in Screen.BINDINGS if isinstance(b, Binding) and "tab" not in b.key
    ]
