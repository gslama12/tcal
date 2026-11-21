"""Go to date: a one-line prompt (``g``) parsed by ``tcal.dates.parse_jump``."""

from datetime import date

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import Input

from tcal.dates import parse_jump


class GotoScreen(ModalScreen[date]):
    """One-line prompt; enter jumps to the parsed date, esc cancels."""

    BINDINGS = [Binding("escape", "dismiss", "Cancel")]

    def __init__(self, today: date) -> None:
        super().__init__()
        self.today = today

    def compose(self) -> ComposeResult:
        prompt = Input(placeholder="fri, +2w, in 3 days, 24.12., dec 24, dec, 2027")
        prompt.border_title = "Go to date"
        yield prompt

    def on_input_changed(self, event: Input.Changed) -> None:
        event.input.border_subtitle = ""

    def on_input_submitted(self, event: Input.Submitted) -> None:
        day = parse_jump(event.value, self.today)
        if day is None:
            event.input.border_subtitle = "not a date"
        else:
            self.dismiss(day)
