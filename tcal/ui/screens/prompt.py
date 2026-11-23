"""Prompt: a small box asking one question, answered with a key or a click on its hint.

``Prompt(question, choices, cancel)``: ``choices`` maps a key to its (label, result);
enter takes the first one (bold), escape and n cancel (dismiss with None). ``cancel``
is the (key, label) shown for that, e.g. ``o this event · s all events · esc cancel``.
"""

from typing import Generic, TypeVar

from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Static

T = TypeVar("T")


class Hint(Static):
    """``key label``, clickable."""

    class Chosen(Message):
        def __init__(self, key: str) -> None:
            super().__init__()
            self.key = key

    def __init__(self, key: str, label: str, default: bool = False) -> None:
        super().__init__(
            f"[b $primary]{key}[/] {label}", id=key, classes="-default" if default else ""
        )
        self.key = key

    def on_click(self) -> None:
        self.post_message(self.Chosen(self.key))


class Prompt(ModalScreen[T | None], Generic[T]):
    def __init__(
        self,
        question: str,
        choices: dict[str, tuple[str, T]],
        cancel: tuple[str, str] = ("esc", "cancel"),
    ) -> None:
        super().__init__()
        self.question = question
        self.choices = choices
        self.cancel = cancel

    def compose(self) -> ComposeResult:
        with Vertical(id="prompt"):
            yield Static(self.question, id="question", markup=False)
            with Horizontal(id="choices"):
                for i, (key, (label, _)) in enumerate(self.choices.items()):
                    yield Hint(key, label, default=i == 0)
                    yield Static(" · ", classes="separator")
                yield Hint(*self.cancel)

    def on_key(self, event: events.Key) -> None:
        event.stop()
        if event.key == "enter":
            self._choose(next(iter(self.choices)))
        elif event.key in (*self.choices, "n", "escape"):
            self._choose(event.key)

    def on_hint_chosen(self, message: Hint.Chosen) -> None:
        self._choose(message.key)

    def _choose(self, key: str) -> None:
        """Dismiss with ``key``'s result; any key but the choices' cancels."""
        self.dismiss(self.choices[key][1] if key in self.choices else None)
