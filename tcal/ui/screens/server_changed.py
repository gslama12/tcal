"""``ServerChanged``: asks what to do when a sync changed the event being edited."""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class ServerChanged(ModalScreen[bool | None]):
    """At save, the event changed (or was deleted) on the server since the prompt opened:
    o = overwrite with the prompt's version (True), d = discard it (False), esc = back."""

    BINDINGS = [
        Binding("o", "dismiss(True)", show=False),
        Binding("d", "dismiss(False)", show=False),
        Binding("escape", "dismiss(None)", show=False),
    ]

    def __init__(self, summary: str, now: str | None) -> None:
        """``summary``: the event's title when the prompt opened; ``now``: its title on
        the server (None: deleted)."""
        super().__init__()
        self.summary = summary
        self.now = now
        self.deleted = now is None

    def compose(self) -> ComposeResult:
        if self.now is None:
            question = f"“{self.summary}” was deleted on the server."
        elif self.now != self.summary:
            question = f"“{self.summary}” was changed on the server (now “{self.now}”)."
        else:
            question = f"“{self.summary}” was changed on the server."
        with Vertical(id="dialog"):
            yield Static(question, classes="question")
            with Horizontal(id="buttons"):
                yield Button("Save again (o)" if self.deleted else "Overwrite (o)", id="o")
                yield Button("Discard mine (d)", id="d", variant="error")
                yield Button("Back (esc)", id="back")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss({"o": True, "d": False}.get(event.button.id or ""))
