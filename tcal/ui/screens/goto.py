"""Go to date: a one-line prompt (``g``) and its pure parser ``parse_date``."""

import re
from datetime import date, timedelta

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import Input

from tcal.ui.state import add_months

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MONTHS = [
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
]

_RELATIVE = re.compile(r"([+-]\d+)\s*([dwmy])")
_ISO = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")
_DOTTED = re.compile(r"(\d{1,2})\.(\d{1,2})\.?(\d{4})?")
_DAY_MONTH = re.compile(r"(\d{1,2})\s+([a-z]+)\.?(?:\s+(\d{4}))?")
_MONTH_DAY = re.compile(r"([a-z]+)\.?\s+(\d{1,2})(?:,?\s+(\d{4}))?")


def _prefix_index(word: str, names: list[str]) -> int | None:
    """Index of the name ``word`` abbreviates ("fri", "friday", "dec", "december")."""
    if len(word) < 3:
        return None
    return next((i for i, name in enumerate(names) if name.startswith(word)), None)


def _make(year: int, month: int | None, day: int) -> date | None:
    if month is None:
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_date(text: str, today: date) -> date | None:
    """Parse a date typed by the user, relative to ``today``; None if not understood.

    Accepts: today, tomorrow, yesterday; a weekday (mon .. sunday: the next one
    after today); +3d / -1w / +2m / +1y; 2026-12-24; 24.12. / 24.12.2026;
    dec 24 / 24 dec (optionally with a year). Dates without a year are in
    today's year.
    """
    s = text.strip().lower()
    if s in ("today", "now"):
        return today
    if s == "tomorrow":
        return today + timedelta(days=1)
    if s == "yesterday":
        return today - timedelta(days=1)
    if (weekday := _prefix_index(s, WEEKDAYS)) is not None:
        return today + timedelta(days=(weekday - today.weekday() - 1) % 7 + 1)
    if m := _RELATIVE.fullmatch(s):
        n, unit = int(m[1]), m[2]
        if unit == "d":
            return today + timedelta(days=n)
        if unit == "w":
            return today + timedelta(weeks=n)
        return add_months(today, n * (12 if unit == "y" else 1))
    if m := _ISO.fullmatch(s):
        return _make(int(m[1]), int(m[2]), int(m[3]))
    if m := _DOTTED.fullmatch(s):
        return _make(int(m[3] or today.year), int(m[2]), int(m[1]))
    if m := _DAY_MONTH.fullmatch(s):
        month = _prefix_index(m[2], MONTHS)
        return _make(int(m[3] or today.year), None if month is None else month + 1, int(m[1]))
    if m := _MONTH_DAY.fullmatch(s):
        month = _prefix_index(m[1], MONTHS)
        return _make(int(m[3] or today.year), None if month is None else month + 1, int(m[2]))
    return None


class GotoScreen(ModalScreen[date]):
    """One-line prompt; enter jumps to the parsed date, esc cancels."""

    BINDINGS = [Binding("escape", "dismiss", "Cancel")]

    def __init__(self, today: date) -> None:
        super().__init__()
        self.today = today

    def compose(self) -> ComposeResult:
        prompt = Input(placeholder="today, fri, +2w, 24.12., dec 24, 2026-12-24")
        prompt.border_title = "Go to date"
        yield prompt

    def on_input_changed(self, event: Input.Changed) -> None:
        event.input.border_subtitle = ""

    def on_input_submitted(self, event: Input.Submitted) -> None:
        day = parse_date(event.value, self.today)
        if day is None:
            event.input.border_subtitle = "not a date"
        else:
            self.dismiss(day)
