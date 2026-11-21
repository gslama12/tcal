from textual.app import RenderResult

from tcal.ui.widgets.base import TcalWidget


class StatusBar(TcalWidget):
    """One-line bar at the bottom, todooit-like (package: crud).

    Left: current view mode chip; middle: sync status / messages; right: key
    hints (e.g. "? help").
    """

    def render(self) -> RenderResult:
        return f" {self.tcal.state.view.value.upper()}  ·  ? help  q quit"
