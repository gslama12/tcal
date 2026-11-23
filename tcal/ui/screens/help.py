"""``HelpScreen``: the key bindings, read from the active config (so overrides show)."""

from rich.cells import cell_len
from rich.console import Group, RenderableType
from rich.rule import Rule
from rich.table import Table
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.keys import format_key
from textual.screen import ModalScreen
from textual.widgets import Static

FRAME = 5  # cells the box adds around a line: border, padding and scrollbar

# section -> [(action, description)], in display order. Actions missing here
# (added to [keys] later) are still listed, under "Other".
GROUPS: dict[str, list[tuple[str, str]]] = {
    "Navigation": [
        ("cursor_left", "Previous day (time grid: its nearest event) / move left"),
        ("cursor_right", "Next day (time grid: its nearest event) / move right"),
        ("cursor_up", "Up (time grid: previous event, grid mode: earlier slot)"),
        ("cursor_down", "Down (time grid: next event, grid mode: later slot)"),
        ("grid_mode", "Grid mode: cursor keys move a slot cursor (again / esc: back)"),
        ("prev_period", "Previous day/week/month/year (schedule: 2 weeks)"),
        ("next_period", "Next day/week/month/year (schedule: 2 weeks)"),
        ("today", "Jump to today"),
        ("goto_date", "Go to date"),
        ("flash", "Flash jump: type a label to jump to an event or slot (time grid)"),
    ],
    "Views": [
        ("view_day", "Day view"),
        ("view_week", "Week view"),
        ("view_month", "Month view"),
        ("view_year", "Year view"),
        ("view_schedule", "Schedule view (upcoming events)"),
        ("zoom_in", "Zoom in (time grid)"),
        ("zoom_out", "Zoom out (time grid)"),
        ("focus_calendars", "Focus the calendar list"),
        ("focus_minical", "Focus the mini month (enter jumps to the day)"),
        ("toggle_calendar", "Show/hide calendar (in the list)"),
        ("toggle_sidebar", "Show/hide the sidebar"),
    ],
    "Events": [
        ("open", "Open event / else a new event"),
        ("new_event", "New event (time grid: after the selected event / at the grid slot)"),
        ("quick_add", "New event (same)"),
        ("edit_event", "Edit event"),
        ("delete_event", "Delete event"),
        ("undo", "Undo the last change"),
        ("redo", "Redo the last undone change"),
        ("toggle_mark", "Mark / unmark event (several: y copies all, esc clears)"),
        ("yank", "Copy (yank) event, or all marked events"),
        ("paste", "Paste at the selected event / grid slot / day (several: from that day on)"),
        ("duplicate", "Duplicate event to the next day"),
        ("move_up", "Move event 15 min earlier (time grid)"),
        ("move_down", "Move event 15 min later (time grid)"),
        ("move_left", "Move event one day earlier"),
        ("move_right", "Move event one day later"),
        ("resize_mode", "Resize mode: up/down move the end, again: the start (esc: back)"),
        ("search", "Search events"),
    ],
    "Event prompt": [
        ("save", "Save (as enter)"),
        ("cancel", "Cancel / close dialog / leave resize, grid mode / clear marks"),
    ],
    "App": [
        ("sync", "Sync now"),
        ("sync_log", "Sync log (recent warnings and errors)"),
        ("help", "This help"),
        ("quit", "Quit"),
    ],
}


def sections(keys: dict[str, list[str]]) -> list[tuple[str, list[tuple[str, str]]]]:
    """(section, [(key labels, description)]) for the keymap ``keys`` (action -> keys)."""

    def label(action: str) -> str:
        return " ".join(format_key(k) for k in keys[action])

    known = {action for rows in GROUPS.values() for action, _ in rows}
    result = [
        (title, [(label(a), d) for a, d in rows if a in keys]) for title, rows in GROUPS.items()
    ]
    other = [(label(a), a.replace("_", " ").capitalize()) for a in keys if a not in known]
    if other:
        result.append(("Other", other))
    return [(title, rows) for title, rows in result if rows]


def line_width(keys: dict[str, list[str]]) -> int:
    """Cells the longest line (keys, a space, description) needs."""
    rows = [row for _, group in sections(keys) for row in group]
    key_width = max(cell_len(key) for key, _ in rows)
    return key_width + 1 + max(cell_len(description) for _, description in rows)


class KeyTable(Static):
    COMPONENT_CLASSES = {"keytable--key", "keytable--title", "keytable--separator"}

    def __init__(self, keys: dict[str, list[str]]) -> None:
        super().__init__()
        self.keys = keys

    def render(self) -> RenderableType:
        groups = sections(self.keys)
        key_width = max(cell_len(key) for _, rows in groups for key, _ in rows)
        parts: list[RenderableType] = []
        for title, rows in groups:
            if parts:
                parts.append(Rule(style=self.get_component_rich_style("keytable--separator")))
            parts.append(Text(f" {title}", style=self.get_component_rich_style("keytable--title")))
            table = Table.grid(expand=True, padding=(0, 1))
            table.add_column(width=key_width)
            table.add_column(ratio=1)
            for key, description in rows:
                table.add_row(
                    Text(key, style=self.get_component_rich_style("keytable--key")), description
                )
            parts.append(table)
        return Group(*parts)


class HelpScreen(ModalScreen[None]):
    """Key bindings over the dimmed app. esc, q or the help key closes it;
    the configured up/down keys (and arrows) scroll, page keys / space page,
    home/end (g/G) jump to the top/bottom; the mouse wheel scrolls too."""

    def __init__(self, keys: dict[str, list[str]]) -> None:
        super().__init__()
        self.keys = keys

    def compose(self) -> ComposeResult:
        with Vertical(id="help") as box:
            box.border_title = "Key bindings"
            box.styles.width = line_width(self.keys) + FRAME  # capped by max-width
            with VerticalScroll(id="help-panel", can_focus=False):
                yield KeyTable(self.keys)
            down, up = (format_key(self.keys[a][0]) for a in ("cursor_down", "cursor_up"))
            yield Static(f"{down}/{up} scroll · space page · G end · esc close", id="help-hint")

    def on_key(self, event: events.Key) -> None:
        # The modal owns every key: the app's bindings are for the panes behind it.
        event.stop()
        event.prevent_default()
        panel = self.query_one("#help-panel", VerticalScroll)
        scrolls = {
            "down": panel.scroll_down,
            "up": panel.scroll_up,
            "pagedown": panel.scroll_page_down,
            "pageup": panel.scroll_page_up,
            "space": panel.scroll_page_down,
            "shift+space": panel.scroll_page_up,
            "end": panel.scroll_end,
            "G": panel.scroll_end,
            "home": panel.scroll_home,
            "g": panel.scroll_home,
            **{k: panel.scroll_down for k in self.keys["cursor_down"]},
            **{k: panel.scroll_up for k in self.keys["cursor_up"]},
        }
        if event.key in ("escape", "q", *self.keys["help"]):
            self.dismiss()
        elif scroll := scrolls.get(event.key):
            scroll()
