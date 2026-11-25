"""Quitting while a sync runs: the terminal says so after the TUI has closed."""

import asyncio
import threading
import time as clock
from collections.abc import Callable
from concurrent.futures import Future
from datetime import datetime, time, timedelta

import pytest
from click.testing import CliRunner
from conftest import TODAY

from tcal import __main__ as main
from tcal import paths
from tcal.background import SyncRunner, finish_sync
from tcal.config import load_config
from tcal.model import Event
from tcal.providers.base import ProviderError
from tcal.providers.fake import FakeProvider
from tcal.store import Store
from tcal.sync import SyncSummary, sync_job
from tcal.tz import local_zone
from tcal.ui.app import TcalApp

SYNCING = "tcal: syncing… (ctrl+c to quit without waiting)"


class SlowProvider(FakeProvider):
    """Holds each sync's calendar list back until ``released``."""

    def __init__(self) -> None:
        super().__init__(today=TODAY)
        self.started, self.released = threading.Event(), threading.Event()
        self.error: Exception | None = None

    def list_calendars(self):
        self.started.set()
        assert self.released.wait(10)
        if self.error:
            raise self.error
        return super().list_calendars()


def _event(uid: str = "new") -> Event:
    start = datetime.combine(TODAY, time(15), local_zone())
    return Event(uid, "work", "Coffee", start, start + timedelta(minutes=30))


@pytest.fixture
def slow(monkeypatch: pytest.MonkeyPatch) -> SlowProvider:
    provider = SlowProvider()
    monkeypatch.setattr(main, "connect", lambda *a, **k: provider)
    return provider


@pytest.fixture
def tcal(monkeypatch: pytest.MonkeyPatch):
    """Run ``tcal`` headless: ``pilot`` drives the TUI, then q is pressed. Returns the
    terminal's lines."""

    def run(pilot: Callable[[TcalApp], object], closed: Callable[[], object] = bool) -> list[str]:
        original = TcalApp.run

        def headless(app: TcalApp) -> None:
            async def auto_pilot(p) -> None:
                result = pilot(app)
                if asyncio.iscoroutine(result):
                    await result
                await p.pause()
                await p.press("q")

            original(app, headless=True, auto_pilot=auto_pilot)
            closed()

        monkeypatch.setattr(TcalApp, "run", headless)
        result = CliRunner().invoke(main.cli, [])
        assert result.exit_code == 0, result.output
        assert result.stdout == ""
        return result.stderr.splitlines()

    return run


def _pending() -> int:
    with Store(paths.database_file()) as store:
        return store.pending_count()


def test_quitting_during_a_sync_reports_it(slow: SlowProvider, tcal) -> None:
    lines = tcal(
        lambda app: slow.started.wait(5),
        # The TUI closes while the sync still hangs: it doesn't wait for it.
        closed=lambda: threading.Timer(0.2, slow.released.set).start(),
    )
    assert lines == [SYNCING, "tcal: synced"]
    with Store(paths.database_file()) as store:
        assert len(store.calendars()) == len(slow.calendars)


def test_edits_made_during_the_sync_are_pushed(slow: SlowProvider, tcal) -> None:
    def edit(app: TcalApp) -> None:
        slow.started.wait(5)
        app.save_event(_event())

    assert tcal(edit, slow.released.set) == [SYNCING, "tcal: synced"]
    assert slow.events["new"].summary == "Coffee"
    assert _pending() == 0


def test_a_failing_sync_is_reported(slow: SlowProvider, tcal) -> None:
    def edit(app: TcalApp) -> None:
        slow.started.wait(5)
        app.save_event(_event())

    slow.error = ProviderError("HTTP 503\nService unavailable")
    assert tcal(edit, slow.released.set) == [
        SYNCING,
        "tcal: sync failed: HTTP 503 Service unavailable; 1 change stays queued for the next start",
    ]
    assert _pending() == 1


async def _synced(app: TcalApp) -> None:
    await app.workers.wait_for_complete()


def test_nothing_is_printed_when_idle(slow: SlowProvider, tcal) -> None:
    slow.released.set()
    assert tcal(_synced) == []


def test_ctrl_c_leaves_at_once_and_keeps_the_queue(
    slow: SlowProvider, tcal, monkeypatch: pytest.MonkeyPatch
) -> None:
    def edit(app: TcalApp) -> None:
        slow.started.wait(5)
        app.save_event(_event())

    def interrupted(self, timeout=None):
        raise KeyboardInterrupt

    def closed() -> None:
        monkeypatch.setattr(Future, "result", interrupted)

    start = clock.monotonic()
    assert tcal(edit, closed) == [
        SYNCING,
        "",
        "tcal: sync not finished; 1 change stays queued for the next start",
    ]
    assert clock.monotonic() - start < 8  # the sync still hangs
    assert _pending() == 1 and "new" not in slow.events
    monkeypatch.undo()
    slow.released.set()


def test_next_start_pushes_what_ctrl_c_left(store: Store, provider: FakeProvider) -> None:
    """Interrupted with the PUT on the server but not answered: no conflict, no duplicate."""
    event = store.save_event(_event())
    op = store.pending_ops()[0]
    store.record_attempt(op.event)
    provider.create_event(event)
    job = sync_job(provider, paths.database_file(), load_config().sync, today=TODAY)
    assert job().problems() == []
    assert store.pending_count() == 0 and provider.events["new"].summary == "Coffee"


def _finish(summaries: list[SyncSummary], pending: list[int]) -> list[str]:
    """``finish_sync``'s lines for syncs with these results; ``pending``: successive counts."""
    release = threading.Event()
    lines: list[str] = []

    def job() -> SyncSummary:
        release.wait(5)
        return summaries.pop(0)

    def echo(line: str) -> None:
        lines.append(line)
        release.set()

    runner = SyncRunner(job)
    runner.start()
    finish_sync(runner, lambda: pending.pop(0), echo)
    return lines


def test_conflicts_are_summarized_in_one_line() -> None:
    summaries = [SyncSummary(conflicts=["Dinner"]), SyncSummary(failed=["Holidays"])]
    assert _finish(summaries, [1]) == [
        SYNCING,
        "tcal: synced, 1 conflict(s) (server version kept), could not fetch Holidays",
    ]


def test_idle_mentions_only_unsynced_edits() -> None:
    runner = SyncRunner(SyncSummary)
    lines: list[str] = []
    finish_sync(runner, lambda: 0, lines.append)
    runner.start().result()
    finish_sync(runner, lambda: 0, lines.append)
    assert lines == []
    finish_sync(runner, lambda: 2, lines.append)
    assert lines == ["tcal: 2 changes stay queued for the next start"]
