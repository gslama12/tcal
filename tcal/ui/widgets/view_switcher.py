from rich.text import Text
from textual.app import RenderResult

from tcal.ui.state import ViewMode
from tcal.ui.widgets.base import TcalWidget


class ViewSwitcher(TcalWidget):
    """Top bar: Day | Week | Month | Year tabs, "Today" and the range title (package: views).

    The active tab is ``state.view``; clicking a tab calls
    ``self.tcal.set_view(mode)``, clicking Today calls ``self.tcal.action_today()``.
    The title is ``state.title()``.
    """

    def render(self) -> RenderResult:
        state = self.tcal.state
        text = Text()
        for mode in ViewMode:
            style = "bold reverse" if mode is state.view else ""
            text.append(f" {mode.value.title()} ", style=style)
            text.append(" ")
        text.append(f"   {state.title()}", style="bold")
        return text
