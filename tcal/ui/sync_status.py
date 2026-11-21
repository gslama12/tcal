"""``SyncStatus``: what the status bar says about background syncing."""

from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum


class SyncState(Enum):
    OFF = "off"  # no account: nothing to sync
    SYNCING = "syncing"
    SYNCED = "synced"
    OFFLINE = "offline"  # network unreachable
    FAILED = "failed"  # any other error


@dataclass(frozen=True)
class SyncStatus:
    state: SyncState = SyncState.OFF
    last_sync: datetime | None = None  # last successful sync
    error: str = ""

    def started(self) -> "SyncStatus":
        return replace(self, state=SyncState.SYNCING, error="")

    def succeeded(self, at: datetime) -> "SyncStatus":
        return SyncStatus(SyncState.SYNCED, at)

    def failed(self, error: BaseException | None) -> "SyncStatus":
        # Connection errors (socket, requests/niquests, timeouts) are all OSErrors.
        state = SyncState.OFFLINE if isinstance(error, OSError) else SyncState.FAILED
        return replace(self, state=state, error=str(error or "unknown error"))
