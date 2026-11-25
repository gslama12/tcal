"""``SyncLogScreen``: this session's sync warnings and errors, newest first."""

from collections.abc import Sequence
from datetime import date
from pathlib import Path

from rich.console import RenderableType
from rich.style import Style
from rich.table import Table
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from tcal.synclog import LogEntry


def entry_table(
    entries: Sequence[LogEntry], today: date, styles: dict[str, Style]
) -> RenderableType:
    """One row per entry, newest first: time (with the day when not ``today``), ⚠/✗,
    message. ``styles``: "time", "warning", "error"."""
    if not entries:
        return Text("No sync warnings or errors so far.")
    table = Table.grid(padding=(0, 1))
    table.add_column(no_wrap=True)
    table.add_column(no_wrap=True)
    table.add_column(ratio=1)
    for entry in reversed(entries):
        when = entry.at.strftime("%H:%M:%S" if entry.at.date() == today else "%a %d %H:%M")
        mark = Text("✗", styles["error"]) if entry.error else Text("⚠", styles["warning"])
        table.add_row(Text(when, styles["time"]), mark, entry.message)
    return table


def _short(path: Path) -> str:
    """``path`` with the home directory as ``~``."""
    try:
        return f"~/{path.relative_to(Path.home())}"
    except ValueError:
        return str(path)


class EntryList(Static):
    COMPONENT_CLASSES = {"synclog--time", "synclog--warning", "synclog--error"}

    def __init__(self, entries: Sequence[LogEntry]) -> None:
        super().__init__()
        self.entries = entries

    def render(self) -> RenderableType:
        names = ("time", "warning", "error")
        styles = {n: self.get_component_rich_style(f"synclog--{n}") for n in names}
        return entry_table(self.entries, date.today(), styles)


class SyncLogScreen(ModalScreen[None]):
    """The recent entries over the dimmed app; esc, q or the ``close_keys`` close it,
    up/down (and the configured cursor keys) scroll."""

    def __init__(
        self,
        entries: Sequence[LogEntry],
        log_file: Path,
        close_keys: Sequence[str] = (),
        scroll_keys: tuple[Sequence[str], Sequence[str]] = ((), ()),
    ) -> None:
        super().__init__()
        self.entries = list(entries)
        self.log_file = log_file
        self.close_keys = ("escape", "q", *close_keys)
        self.down_keys = ("down", *scroll_keys[0])
        self.up_keys = ("up", *scroll_keys[1])

    def compose(self) -> ComposeResult:
        with Vertical(id="synclog") as box:
            box.border_title = "Sync log"
            with VerticalScroll(id="synclog-panel", can_focus=False):
                yield EntryList(self.entries)
            yield Static(f"esc close · full log: {_short(self.log_file)}", id="synclog-hint")

    def on_key(self, event: events.Key) -> None:
        event.stop()
        event.prevent_default()
        panel = self.query_one("#synclog-panel", VerticalScroll)
        if event.key in self.close_keys:
            self.dismiss()
        elif event.key in self.down_keys:
            panel.scroll_down()
        elif event.key in self.up_keys:
            panel.scroll_up()
