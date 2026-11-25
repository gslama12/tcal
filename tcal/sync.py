"""SyncEngine: push the store's pending ops to a provider, then pull a time window.

Conflict policy: the server wins. An op rejected for an etag mismatch is
dropped (and logged); the following pull brings in the server's version. It is no
conflict if the server's copy still says what the edit was based on (or already says
what it changes): then only the etag is new, and the op is sent again with that.
Any other provider error aborts the sync and leaves the remaining ops queued.
Subscribed feeds (``subscriptions``, read-only) are pulled after the account; a feed
that fails keeps its cached events and is named in the summary.
Everything a sync logs as a warning (also from the provider) ends up in
``SyncSummary.warnings`` (see ``tcal.synclog``).
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from pathlib import Path

from dateutil.relativedelta import relativedelta

from tcal import ics
from tcal.config import SyncConfig
from tcal.model import Event
from tcal.providers.base import ConflictError, Provider, ProviderError
from tcal.store import OpKind, PendingOp, Store
from tcal.synclog import collect
from tcal.tz import local_midnight

log = logging.getLogger(__name__)


@dataclass
class SyncSummary:
    calendars: int = 0
    events: int = 0
    pushed: int = 0
    conflicts: list[str] = field(default_factory=list)  # titles of the dropped local changes
    failed: list[str] = field(default_factory=list)  # subscriptions that could not be fetched
    warnings: list[str] = field(default_factory=list)  # every warning logged during the sync

    def __str__(self) -> str:
        text = f"{self.calendars} calendars, {self.events} events"
        if self.pushed:
            text += f", pushed {self.pushed} change(s)"
        if self.conflicts:
            text += f", {len(self.conflicts)} conflict(s) (server version kept)"
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
        with collect() as summary.warnings:
            self._push(summary)
            self._pull(summary)
        return summary

    def _push(self, summary: SyncSummary) -> None:
        for op in self.store.pending_ops():
            event = op.event
            try:
                self.store.record_push(op, self._push_op(op))
                summary.pushed += 1
            except ConflictError as e:
                self.store.clear_op(op.id)
                log.warning(
                    "“%s” changed on the server meanwhile: your %s was dropped"
                    " (conflict: %s; server version kept)",
                    event.summary,
                    "deletion" if op.kind == "delete" else "change",
                    e,
                )
                summary.conflicts.append(event.summary)

    def _push_op(self, op: PendingOp) -> Event | None:
        """Send ``op``; returns the event as the server has it now (None: deleted)."""
        event, bases = op.event, self.store.bases(op.event.uid)
        if op.kind != "delete":
            self.store.record_attempt(event)
        try:
            if op.kind != "create" and event.etag is None:
                raise ConflictError("etag unknown")  # check before overwriting
            return self._send(op.kind, event)
        except ConflictError:
            current = self.provider.fetch_event(event)
            if current is None and op.kind == "delete":
                return None
            if current is None:
                raise
            if op.kind != "delete" and ics.same_content(current.raw, event.raw):
                return replace(current, calendar_id=event.calendar_id)
            if not any(ics.same_content(current.raw, b) for b in bases):
                raise
            kind: OpKind = "delete" if op.kind == "delete" else "update"
            return self._send(kind, replace(event, href=current.href, etag=current.etag))

    def _send(self, kind: OpKind, event: Event) -> Event | None:
        if kind == "delete":
            self.provider.delete_event(event)
            return None
        if kind == "create":
            return self.provider.create_event(event)
        return self.provider.update_event(event)

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
                log.warning("could not fetch subscription “%s”: %s", cal.name, e)
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
