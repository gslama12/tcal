"""Sync warnings and errors, so the user gets to see them.

Everything logs through ``logging`` under the ``tcal`` logger. ``collect()`` gathers
what one sync logs (in its own thread) into ``SyncSummary.warnings``; the app keeps
the recent ones as ``LogEntry``s for the sync-log screen; ``log_to_file`` also writes
them to a small rotating file (``paths.log_file()``).
"""

import logging
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOGGER = "tcal"
MAX_BYTES = 256_000  # per file; one backup is kept
FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


@dataclass(frozen=True)
class LogEntry:
    at: datetime
    error: bool  # an error (the sync failed), else a warning
    message: str


class _ListHandler(logging.Handler):
    """Appends the messages of one thread's warnings/errors to a list."""

    def __init__(self, messages: list[str]) -> None:
        super().__init__(logging.WARNING)
        self.messages = messages
        self.thread = threading.get_ident()

    def emit(self, record: logging.LogRecord) -> None:
        if record.thread == self.thread:
            self.messages.append(record.getMessage())


@contextmanager
def collect() -> Iterator[list[str]]:
    """The messages of the warnings/errors this thread logs under ``tcal`` meanwhile."""
    messages: list[str] = []
    handler = _ListHandler(messages)
    logger = logging.getLogger(LOGGER)
    logger.addHandler(handler)
    try:
        yield messages
    finally:
        logger.removeHandler(handler)


def log_to_file(path: Path) -> None:
    """Also write ``tcal``'s warnings/errors to ``path`` (rotating; once per path)."""
    logger = logging.getLogger(LOGGER)
    target = str(path.resolve())
    if any(getattr(h, "baseFilename", None) == target for h in logger.handlers):
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(path, maxBytes=MAX_BYTES, backupCount=1, encoding="utf-8")
    handler.setLevel(logging.WARNING)
    handler.setFormatter(logging.Formatter(FORMAT))
    logger.addHandler(handler)
