"""``HelpScreen``: the key bindings, read from the active config (so overrides show)."""

from dataclasses import dataclass
from itertools import product
from textwrap import wrap

from rich.console import Console, ConsoleOptions, Group, RenderableType, RenderResult
from rich.rule import Rule
from rich.style import Style
from rich.table import Table
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.keys import format_key
from textual.screen import ModalScreen
from textual.widgets import Static

MIN_COLUMN = 48  # cells a column of sections needs
MAX_COLUMNS = 3
GAP = 3  # cells between columns

Section = tuple[str, list[tuple[str, str]]]  # title, [(key labels, description)]

# section -> [(action, description)], in display order. Actions missing here
# (added to [keys] later) are still listed, under "Other".
GROUPS: dict[str, list[tuple[str, str]]] = {
    "Navigation": [
        ("cursor_left", "Previous day (time grid: its nearest event) / move left"),
        ("cursor_right", "Next day (time grid: its nearest event) / move right"),
        ("cursor_up", "Up (time grid: previous event, grid mode: earlier slot)"),
        ("cursor_down", "Down (time grid: next event, grid mode: later slot)"),
        ("grid_mode", "Grid mode: cursor keys move a 15-min slot cursor (again / esc: back)"),
        ("prev_period", "Previous day/week/month/year (schedule: 2 weeks)"),
        ("next_period", "Next day/week/month/year (schedule: 2 weeks)"),
        ("today", "Jump to today"),
        ("goto_date", "Go to date"),
        ("flash", "Flash jump: type a label to jump to an event or slot (time grid)"),
        ("next_event", "Next event in view"),
        ("prev_event", "Previous event in view"),
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
        ("focus_next", "Cycle panes"),
        ("toggle_sidebar", "Show/hide the sidebar"),
    ],
    "Events": [
        ("open", "Open event / else a new event"),
        ("new_event", "New event (time grid: after the selected event / at the grid slot)"),
        ("quick_add", "Quick add (one line)"),
        ("edit_event", "Edit event"),
        ("delete_event", "Delete event"),
        ("undo", "Undo the last change"),
        ("toggle_mark", "Mark / unmark event (several: y copies all, esc clears)"),
        ("yank", "Copy (yank) event, or all marked events"),
        ("paste", "Paste at the selected event / grid slot / day (several: from that day on)"),
        ("duplicate", "Duplicate event to the next day"),
        ("move_up", "Move event 15 min earlier (time grid)"),
        ("move_down", "Move event 15 min later (time grid)"),
        ("move_left", "Move event one day earlier"),
        ("move_right", "Move event one day later"),
        ("end_earlier", "End event 15 min earlier (time grid)"),
        ("end_later", "End event 15 min later (time grid)"),
        ("start_earlier", "Start event 15 min earlier (time grid)"),
        ("start_later", "Start event 15 min later (time grid)"),
        ("search", "Search events"),
    ],
    "Event form": [
        ("save", "Save"),
        ("cancel", "Cancel / close dialog / leave grid mode / clear marks"),
    ],
    "App": [
        ("sync", "Sync now"),
        ("sync_log", "Sync log (recent warnings and errors)"),
        ("help", "This help"),
        ("quit", "Quit"),
    ],
}


def sections(keys: dict[str, list[str]]) -> list[Section]:
    """The sections for the keymap ``keys`` (action -> keys)."""

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


def split_columns(heights: list[int], count: int) -> list[list[int]]:
    """Indices of ``heights`` in ``count`` columns (each in order), the tallest as short as
    possible; of equally short splits, the one that fills the left columns first."""

    def tallest(columns: tuple[int, ...]) -> int:
        return max(
            sum(h for h, c in zip(heights, columns, strict=True) if c == column)
            for column in range(count)
        )

    best = min(product(range(count), repeat=len(heights)), key=tallest)
    return [[i for i, c in enumerate(best) if c == column] for column in range(count)]


@dataclass(frozen=True)
class KeyColumns:
    """Rich renderable: the sections in as many columns as make it shortest at its width."""

    sections: list[Section]
    key_style: Style
    title_style: Style
    separator_style: Style

    @property
    def key_width(self) -> int:
        return max((len(key) for _, rows in self.sections for key, _ in rows), default=0)

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        _, columns = min(
            (self.arrange(options.max_width, count) for count in self.counts(options.max_width)),
            key=lambda arranged: arranged[0],
        )
        grid = Table.grid(expand=True, padding=(0, GAP, 0, 0), pad_edge=False)
        for _ in columns:
            grid.add_column(ratio=1)
        grid.add_row(*(self.column([self.sections[i] for i in column]) for column in columns))
        yield grid

    def counts(self, width: int) -> range:
        """The column counts that fit in ``width`` (one always does)."""
        fitting = (width + GAP) // (MIN_COLUMN + GAP)
        return range(1, max(1, min(MAX_COLUMNS, fitting)) + 1)

    def arrange(self, width: int, count: int) -> tuple[int, list[list[int]]]:
        """(height, section indices per column) for ``count`` columns."""
        text_width = max(1, (width + GAP) // count - GAP - self.key_width - 2)
        heights = [
            2 + sum(len(wrap(description, text_width)) for _, description in rows)
            for _, rows in self.sections
        ]
        columns = split_columns(heights, count)
        return max(sum(heights[i] for i in column) for column in columns), columns

    def column(self, groups: list[Section]) -> Group:
        parts: list[RenderableType] = []
        for title, rows in groups:
            if parts:
                parts.append(Rule(style=self.separator_style))
            parts.append(Text(f" {title}", style=self.title_style))
            table = Table.grid(expand=True, padding=(0, 1))
            table.add_column(width=self.key_width)
            table.add_column(ratio=1)
            for key, description in rows:
                table.add_row(Text(key, style=self.key_style), description)
            parts.append(table)
        return Group(*parts)


class KeyTable(Static):
    COMPONENT_CLASSES = {"keytable--key", "keytable--title", "keytable--separator"}

    def __init__(self, keys: dict[str, list[str]]) -> None:
        super().__init__()
        self.keys = keys

    def render(self) -> RenderableType:
        return KeyColumns(
            sections(self.keys),
            key_style=self.get_component_rich_style("keytable--key"),
            title_style=self.get_component_rich_style("keytable--title"),
            separator_style=self.get_component_rich_style("keytable--separator"),
        )


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
