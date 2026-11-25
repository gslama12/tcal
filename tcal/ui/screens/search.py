"""Search (``/``): a modal over the cached events with a live result list."""

from collections.abc import Callable, Sequence
from datetime import datetime

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList
from textual.widgets.option_list import Option

from tcal.model import Occurrence
from tcal.repeat import describe_rrule
from tcal.ui.keys import binding


def search(occurrences: Sequence[Occurrence], query: str, now: datetime) -> list[Occurrence]:
    """Occurrences whose summary, location or notes contain ``query`` (case-insensitive).

    A series is listed once, by its next instance (or its latest, if all are
    past). Upcoming events come first, soonest first; then past ones, latest first.
    """
    needle = query.strip().casefold()
    if not needle:
        return []
    best: dict[str, Occurrence] = {}
    for occ in occurrences:
        ev = occ.event
        if needle not in f"{ev.summary}\n{ev.location}\n{ev.description}".casefold():
            continue
        seen = best.get(ev.uid)
        if seen is None or _rank(occ, now) < _rank(seen, now):
            best[ev.uid] = occ
    return sorted(best.values(), key=lambda o: _rank(o, now))


def _rank(occ: Occurrence, now: datetime) -> tuple[bool, float]:
    upcoming = occ.end > now
    seconds = occ.start.timestamp()
    return not upcoming, seconds if upcoming else -seconds


class ResultList(OptionList):
    BINDINGS = [
        binding("cursor_down", action="cursor_down"),
        binding("cursor_up", action="cursor_up"),
    ]


class SearchScreen(ModalScreen[Occurrence]):
    """Type to filter; up/down (j/k in the list) move, enter picks, esc cancels.

    ``occurrences()`` is asked again after every data refresh (e.g. a sync), so the
    results follow server changes."""

    BINDINGS = [
        Binding("escape", "dismiss", "Cancel"),
        Binding("down", "move(1)", show=False),
        Binding("up", "move(-1)", show=False),
    ]

    def __init__(
        self,
        occurrences: Callable[[], Sequence[Occurrence]],
        now: datetime,
        color: Callable[[str], str],
    ) -> None:
        super().__init__()
        self.occurrences = occurrences
        self.now = now
        self.color = color  # calendar id -> "#RRGGBB"
        self.results: list[Occurrence] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="search"):
            query = Input(placeholder="summary, location or notes")
            query.border_title = "Search"
            yield query
            yield ResultList()

    def on_mount(self) -> None:
        self.watch(self.app, "state", self._data_changed, init=False)

    def on_input_changed(self) -> None:
        self._run_query(0)

    def _data_changed(self) -> None:
        self._run_query(self.query_one(ResultList).highlighted or 0)

    def _run_query(self, highlight: int) -> None:
        """Fill the list for the query, highlighting row ``highlight`` (or the last)."""
        query = self.query_one(Input).value
        results = self.query_one(ResultList)
        self.results = search(self.occurrences(), query, self.now)
        results.set_options(Option(self._label(o)) for o in self.results)
        results.highlighted = min(highlight, len(self.results) - 1) if self.results else None
        results.border_subtitle = f"{len(self.results)} found" if query.strip() else ""

    def _label(self, occ: Occurrence) -> Text:
        when = "all day" if occ.all_day else f"{occ.start:%H:%M}"
        label = Text.assemble(
            ("● ", self.color(occ.calendar_id)),
            (f"{occ.start:%a %d %b %Y}  {when:>7}  ", "dim"),
            occ.summary,
        )
        if rrule := occ.event.rrule:  # a series is listed once: say that it repeats
            label.append(f" · {describe_rrule(rrule).replace('Every', 'every', 1)}", "dim")
        if occ.event.location:
            label.append(f"  · {occ.event.location}", "dim")
        return label

    def action_move(self, step: int) -> None:
        results = self.query_one(ResultList)
        (results.action_cursor_down if step > 0 else results.action_cursor_up)()

    def on_input_submitted(self) -> None:
        index = self.query_one(ResultList).highlighted
        if index is not None:
            self.dismiss(self.results[index])

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(self.results[event.option_index])
