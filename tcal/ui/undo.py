"""The undo and redo keys' history of changes (see ``TcalApp.save_event`` / ``delete_event``)."""

from dataclasses import dataclass
from datetime import datetime

from tcal.model import Event
from tcal.ui.screens.event_detail import Scope

UNDO_DEPTH = 20  # changes the undo key can take back

Changes = list[tuple[str, list[Event]]]


@dataclass(frozen=True)
class UndoStep:
    """How to take back one change (or, once undone, to make it again: ``inverse``):
    each changed event's uid with the rows to put back (empty: to delete it).
    A batch paste is one step with several."""

    changes: Changes
    message: str  # the toast after undoing it
    redo_message: str  # ... and after redoing it
    at: datetime | None = None  # the occurrence (start) of ``uid`` to select once undone
    redo_at: datetime | None = None  # ... and once redone

    @property
    def uid(self) -> str:
        return self.changes[0][0]

    def inverse(self, changes: Changes) -> "UndoStep":
        """The step that takes back this one; ``changes``: the rows before it."""
        return UndoStep(changes, self.redo_message, self.message, self.redo_at, self.at)


class UndoHistory:
    """The last ``UNDO_DEPTH`` changes and the undone ones, plus the scope of a run of
    moves/resizes.

    ``move_run`` = (the moved occurrence's key, the "this/all events" answer): further
    moves and resizes of that occurrence reuse the answer; any other change ends the run.
    """

    def __init__(self) -> None:
        self._steps: list[UndoStep] = []  # last change at the end
        self._undone: list[UndoStep] = []  # last undone change at the end
        self.move_run: tuple[tuple[str, datetime], Scope] | None = None

    def push(self, step: UndoStep) -> None:
        """Record a new change; the undone ones can't be redone any more."""
        self._undone.clear()
        self.push_redone(step)

    def push_redone(self, step: UndoStep) -> None:
        self._steps = [*self._steps[-(UNDO_DEPTH - 1) :], step]
        self.move_run = None

    def push_undone(self, step: UndoStep) -> None:
        self._undone.append(step)
        self.move_run = None

    def pop(self) -> UndoStep | None:
        return self._steps.pop() if self._steps else None

    def pop_undone(self) -> UndoStep | None:
        return self._undone.pop() if self._undone else None
