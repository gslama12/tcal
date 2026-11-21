"""SyncEngine: push the store's pending ops to a provider, then pull a time window.

Conflict policy: the server wins. An op rejected for an etag mismatch is
dropped (and logged); the following pull brings in the server's version.
Any other provider error aborts the sync and leaves the remaining ops queued.
Subscribed feeds (``subscriptions``, read-only) are pulled after the account; a feed
that fails keeps its cached events and is named in the summary.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from dateutil.relativedelta import relativedelta

from tcal.config import SyncConfig
from tcal.providers.base import ConflictError, Provider, ProviderError
from tcal.store import Store
from tcal.tz import local_midnight

log = logging.getLogger(__name__)


@dataclass
class SyncSummary:
    calendars: int = 0
    events: int = 0
    pushed: int = 0
    conflicts: int = 0
    failed: list[str] = field(default_factory=list)  # subscriptions that could not be fetched

    def __str__(self) -> str:
        text = f"{self.calendars} calendars, {self.events} events"
        if self.pushed:
            text += f", pushed {self.pushed} change(s)"
        if self.conflicts:
            text += f", {self.conflicts} conflict(s) (server version kept)"
        if self.failed:
            text += f", could not fetch {', '.join(self.failed)}"
        return text


class SyncEngine:
    def __init__(
        self,
        provider: Provider,
        store: Store,
        past_months: int = 3,
        future_months: int = 12,
        today: date | None = None,
        subscriptions: Provider | None = None,
    ) -> None:
        self.provider = provider
        self.subscriptions = subscriptions
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
        pulls = [(self.provider, cal) for cal in self.provider.list_calendars()]
        if self.subscriptions:
            pulls += [(self.subscriptions, cal) for cal in self.subscriptions.list_calendars()]
        self.store.upsert_calendars(cal for _, cal in pulls)
        for provider, cal in pulls:
            try:
                events = provider.fetch_events(cal, start, end)
            except (ProviderError, OSError) as e:
                if not cal.subscribed:
                    raise
                log.warning("could not fetch subscription %r: %s", cal.name, e)
                summary.failed.append(cal.name)
                continue
            self.store.upsert_events(cal.id, events)
            summary.events += len(events)
        summary.calendars = len(pulls)


def sync_job(
    provider: Provider,
    database: Path,
    config: SyncConfig,
    today: date | None = None,
    subscriptions: Provider | None = None,
) -> Callable[[], SyncSummary]:
    """A function running one sync on its own Store connection (safe in a worker thread)."""

    def run() -> SyncSummary:
        with Store(database) as store:
            return SyncEngine(
                provider, store, config.past_months, config.future_months, today, subscriptions
            ).sync()

    return run
