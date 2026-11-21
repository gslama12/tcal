"""One-line bar at the bottom in todooit's style.

Left: view-mode badge; middle: selected date; right: sync status, pending
edits (if any) and the help key.
"""

from time import monotonic

from rich.text import Text
from textual.app import RenderResult
from textual.keys import format_key

from tcal.ui.sync_status import SyncState
from tcal.ui.widgets.base import TcalWidget

SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
MAX_ERROR = 40


class StatusBar(TcalWidget):
    def on_mount(self) -> None:
        super().on_mount()
        self.set_interval(0.1, self._spin)

    def _spin(self) -> None:
        if self.tcal.sync_status.state is SyncState.SYNCING:
            self.refresh()

    def render(self) -> RenderResult:
        p = self.tcal.palette
        state = self.tcal.state
        badge = Text(f" {state.view.value.upper()} ", style=f"bold {p.background1} on {p.primary}")
        day = Text(f"{state.day:%a %-d %b %Y}", style=p.foreground2)

        right = Text()
        right.append_text(self._sync_text())
        if pending := self.tcal.source.pending_count():
            right.append(f"  ↑{pending} pending", style=p.yellow)
        help_key = format_key(self.tcal.config.keys["help"][0])
        right.append("  ")
        right.append(f" {help_key} help ", style=f"{p.background1} on {p.secondary}")

        # The date is centred on the bar, unless the sides leave too little room.
        width = self.size.width
        left_gap = max(1, (width - day.cell_len) // 2 - badge.cell_len)
        right_gap = max(1, width - badge.cell_len - left_gap - day.cell_len - right.cell_len)
        return Text.assemble(badge, " " * left_gap, day, " " * right_gap, right)

    def _sync_text(self) -> Text:
        p = self.tcal.palette
        status = self.tcal.sync_status
        last = f"last sync {status.last_sync:%H:%M}" if status.last_sync else "never synced"
        error = status.error[:MAX_ERROR]
        match status.state:
            case SyncState.OFF:
                return Text("local only", style=p.foreground1)
            case SyncState.SYNCING:
                frame = SPINNER[int(monotonic() * 10) % len(SPINNER)]
                return Text(f"{frame} syncing…", style=p.primary)
            case SyncState.SYNCED if status.failed_feeds:
                feeds = ", ".join(status.failed_feeds)[:MAX_ERROR]
                return Text(f"⚠ synced {status.last_sync:%H:%M} · {feeds} failed", style=p.yellow)
            case SyncState.SYNCED:
                return Text(f"✓ synced {status.last_sync:%H:%M}", style=p.green)
            case SyncState.OFFLINE:
                return Text(f"offline · {last}", style=p.yellow)
            case SyncState.FAILED:
                return Text(f"✗ sync failed: {error} · {last}", style=p.red)
