"""Background syncs, and finishing them after the TUI has closed.

``SyncRunner`` runs the app's syncs in daemon threads: unlike asyncio's executor threads
(which the event loop joins silently when it closes) nothing waits for them implicitly.
``finish_sync`` does, telling the user so; leaving early is safe, since ops stay queued
until the server has answered and the store's writes are transactions.
"""

import logging
import threading
from collections.abc import Callable
from concurrent.futures import Future

from tcal.sync import SyncSummary

log = logging.getLogger(__name__)

Job = Callable[[], SyncSummary]


class SyncRunner:
    def __init__(self, job: Job) -> None:
        self.job = job
        self.last: Future[SyncSummary] | None = None  # the sync started last

    def start(self) -> Future[SyncSummary]:
        """Run one sync in a thread of its own."""
        future: Future[SyncSummary] = Future()
        future.set_running_or_notify_cancel()  # from here on it can't be cancelled
        self.last = future
        threading.Thread(target=self._run, args=(future,), name="sync", daemon=True).start()
        return future

    def _run(self, future: Future[SyncSummary]) -> None:
        try:
            result = self.job()
        except BaseException as e:  # like an executor: whoever waits gets it
            future.set_exception(e)
        else:
            future.set_result(result)


def finish_sync(
    runner: SyncRunner, pending_count: Callable[[], int], echo: Callable[[str], object]
) -> None:
    """Wait for the sync still running, if any, and push the edits made meanwhile.

    ``echo`` gets a line before and one after; ctrl+c stops waiting. With no sync running
    it only mentions edits that could not be pushed (e.g. offline), if there are any.
    """
    future = runner.last
    if future is None or future.done():
        if count := pending_count():
            echo(f"tcal: {_queued(count)}")
        return
    try:
        echo("tcal: syncing… (ctrl+c to quit without waiting)")
        problems = future.result().problems()
        if pending_count():  # edited during that sync
            problems += runner.start().result().problems()
    except KeyboardInterrupt:
        count = pending_count()
        left = _queued(count) if count else "the next start syncs again"
        echo(f"\ntcal: sync not finished; {left}")  # the terminal shows ^C on this line
    except Exception as e:
        log.error("sync failed: %s", e)
        error = " ".join(str(e).split()) or type(e).__name__
        count = pending_count()
        echo(f"tcal: sync failed: {error}" + (f"; {_queued(count)}" if count else ""))
    else:
        echo(", ".join(["tcal: synced", *problems]))


def _queued(count: int) -> str:
    changes = "1 change stays" if count == 1 else f"{count} changes stay"
    return f"{changes} queued for the next start"
