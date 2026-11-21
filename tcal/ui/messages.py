"""Messages the views post for the CRUD screens (handled by the app)."""

from datetime import date, datetime

from textual.message import Message

from tcal.model import Occurrence


class NewEventRequested(Message):
    """The user asked for a new event: at a time slot (datetime) or on a day (date)."""

    def __init__(self, start: date | datetime) -> None:
        super().__init__()
        self.start = start


class EventSelected(Message):
    """The user opened an event (enter or click on it)."""

    def __init__(self, occurrence: Occurrence) -> None:
        super().__init__()
        self.occurrence = occurrence
