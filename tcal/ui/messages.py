"""Messages the views post for the app / CRUD screens to handle.

Handlers on TcalApp: ``on_event_selected`` and ``on_new_event_requested``.
"""

from datetime import datetime

from textual.message import Message

from tcal.model import Occurrence


class EventSelected(Message):
    """The user wants to open ``occurrence`` (enter or click on an event)."""

    def __init__(self, occurrence: Occurrence) -> None:
        super().__init__()
        self.occurrence = occurrence


class NewEventRequested(Message):
    """The user wants a new event starting at ``start`` (local, aware)."""

    def __init__(self, start: datetime) -> None:
        super().__init__()
        self.start = start
