"""The undo key's history of changes (see ``TcalApp.save_event`` / ``delete_event``)."""

from dataclasses import dataclass
from datetime import datetime

from tcal.model import Event
from tcal.ui.screens.event_detail import Scope

UNDO_DEPTH = 20  # changes the undo key can take back


@dataclass(frozen=True)
class UndoStep:
    """How to take back one change: ``uid``'s rows before it (empty: it was created)."""

    uid: str
    rows: list[Event]
    message: str  # the toast after undoing it
    at: datetime | None = None  # the occurrence (start) to select once it is undone


class UndoHistory:
    """The last ``UNDO_DEPTH`` changes, plus the scope of a run of moves.

    ``move_run`` = (the moved occurrence's key, the "this/all events" answer): further
    moves of that occurrence reuse the answer; any other change ends the run.
    """

    def __init__(self) -> None:
        self._steps: list[UndoStep] = []  # last change at the end
        self.move_run: tuple[tuple[str, datetime], Scope] | None = None

    def push(self, step: UndoStep) -> None:
        self._steps = [*self._steps[-(UNDO_DEPTH - 1) :], step]
        self.move_run = None

    def pop(self) -> UndoStep | None:
        self.move_run = None
        return self._steps.pop() if self._steps else None
