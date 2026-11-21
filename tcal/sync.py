"""SyncEngine: push the store's pending ops to a provider, then pull a time window.

Conflict policy: the server wins. An op rejected for an etag mismatch is
dropped (and logged); the following pull brings in the server's version.
Any other provider error aborts the sync and leaves the remaining ops queued.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from dateutil.relativedelta import relativedelta

from tcal.config import SyncConfig
from tcal.providers.base import ConflictError, Provider
from tcal.store import Store
from tcal.tz import local_midnight

log = logging.getLogger(__name__)


@dataclass
class SyncSummary:
    calendars: int = 0
    events: int = 0
    pushed: int = 0
    conflicts: int = 0

    def __str__(self) -> str:
        text = f"{self.calendars} calendars, {self.events} events"
        if self.pushed:
            text += f", pushed {self.pushed} change(s)"
        if self.conflicts:
            text += f", {self.conflicts} conflict(s) (server version kept)"
        return text


class SyncEngine:
    def __init__(
        self,
        provider: Provider,
        store: Store,
        past_months: int = 3,
        future_months: int = 12,
        today: date | None = None,
    ) -> None:
        self.provider = provider
        self.store = store
        self.past_months = past_months
        self.future_months = future_months
        self.today = today

    def window(self) -> tuple[datetime, datetime]:
        """The pulled range: today - past_months .. today + future_months."""
        today = self.today or date.today()
        return (
            local_midnight(today - relativedelta(months=self.past_months)),
            local_midnight(today + relativedelta(months=self.future_months)),
        )

    def sync(self) -> SyncSummary:
        summary = SyncSummary()
        self._push(summary)
        self._pull(summary)
        return summary

    def _push(self, summary: SyncSummary) -> None:
        for op in self.store.pending_ops():
            event = op.event
            try:
                if op.kind == "delete":
                    self.provider.delete_event(event)
                else:
                    if op.kind == "create":
                        done = self.provider.create_event(event)
                    else:
                        done = self.provider.update_event(event)
                    self.store.set_remote(event.uid, done.href, done.etag)
                summary.pushed += 1
            except ConflictError as e:
                log.warning(
                    "%s of %r conflicts (%s); keeping the server version", op.kind, event.summary, e
                )
                summary.conflicts += 1
            self.store.clear_op(op.id)

    def _pull(self, summary: SyncSummary) -> None:
        start, end = self.window()
        calendars = self.provider.list_calendars()
        self.store.upsert_calendars(calendars)
        for cal in calendars:
            events = self.provider.fetch_events(cal, start, end)
            self.store.upsert_events(cal.id, events)
            summary.events += len(events)
        summary.calendars = len(calendars)


def sync_job(
    provider: Provider, database: Path, config: SyncConfig, today: date | None = None
) -> Callable[[], SyncSummary]:
    """A function running one sync on its own Store connection (safe in a worker thread)."""

    def run() -> SyncSummary:
        with Store(database) as store:
            return SyncEngine(
                provider, store, config.past_months, config.future_months, today
            ).sync()

    return run
