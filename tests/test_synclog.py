import logging
import threading
from dataclasses import replace
from datetime import datetime, timedelta

from click.testing import CliRunner
from conftest import TODAY
from rich.console import Console

from tcal import paths
from tcal.__main__ import cli
from tcal.config import load_config
from tcal.model import Calendar, Event
from tcal.providers.fake import FakeProvider
from tcal.source import StoreSource
from tcal.store import Store
from tcal.sync import SyncEngine, SyncSummary
from tcal.synclog import LogEntry, collect, log_to_file
from tcal.ui.app import TcalApp
from tcal.ui.screens.help import sections
from tcal.ui.screens.sync_log import EntryList, SyncLogScreen

log = logging.getLogger("tcal.test")


class WarningProvider(FakeProvider):
    """Logs a warning while fetching, like ICloudProvider skipping an unreadable event."""

    def fetch_events(self, calendar: Calendar, start: datetime, end: datetime) -> list[Event]:
        log.warning("skipping unreadable event in %s", calendar.name)
        return super().fetch_events(calendar, start, end)


def test_collect_keeps_this_threads_warnings_only() -> None:
    with collect() as messages:
        log.info("not a warning")
        log.warning("mine")
        other = threading.Thread(target=log.warning, args=("another thread's",))
        other.start()
        other.join()
        log.error("an error")
    log.warning("after")
    assert messages == ["mine", "an error"]


def test_summary_has_conflicts_and_provider_warnings(provider: FakeProvider, store: Store) -> None:
    uid = next(e.uid for e in provider.events.values() if e.summary == "Dentist")
    provider.update_event(replace(provider.events[uid], summary="Server edit"))
    cached = store.get_event(uid)
    assert cached
    store.save_event(replace(cached, summary="Local edit"))

    summary = SyncEngine(provider, store, today=TODAY).sync()
    assert summary.warnings[0].startswith("“Local edit” changed on the server meanwhile")
    assert "server version kept" in summary.warnings[0]

    noisy = WarningProvider(today=TODAY)
    summary = SyncEngine(noisy, Store(":memory:"), today=TODAY).sync()
    assert len(summary.warnings) == len(noisy.calendars)
    assert summary.warnings[0].startswith("skipping unreadable event in")


def test_log_file_gets_warnings_once(tcal_home) -> None:
    file = paths.log_file()
    log_to_file(file)
    log_to_file(file)  # no second handler: one line per message
    log.info("not written")
    log.warning("feed down")
    for handler in logging.getLogger("tcal").handlers:
        handler.flush()
    [line] = file.read_text().splitlines()
    assert line.endswith("WARNING tcal.test: feed down")


def test_cli_sync_prints_warnings_and_logs_them(monkeypatch) -> None:
    from tcal import __main__ as main

    monkeypatch.setattr(main, "connect", lambda config: WarningProvider(today=TODAY))
    result = CliRunner().invoke(cli, ["sync"])
    assert result.exit_code == 0, result.output
    assert "warning: skipping unreadable event in" in result.output
    for handler in logging.getLogger("tcal").handlers:
        handler.flush()
    assert "skipping unreadable event" in paths.log_file().read_text()


def _entries_text(app: TcalApp) -> str:
    console = Console(width=100, record=True)
    console.print(app.screen.query_one(EntryList).render())
    return console.export_text()


def _app(store: Store, summaries: list[SyncSummary]) -> TcalApp:
    def job() -> SyncSummary:
        summary = summaries.pop(0)
        if isinstance(summary, Exception):
            raise summary
        return summary

    return TcalApp(StoreSource(store), load_config(), today=TODAY, sync=job)


async def _sync(app: TcalApp, pilot) -> None:
    app.request_sync()
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause()


def _toasts(app: TcalApp) -> list[str]:
    return [str(n.message) for n in app._notifications if "sync warning" in str(n.message)]


async def test_toast_once_per_new_warnings_and_log_screen(store: Store) -> None:
    feed = "could not fetch subscription “Holidays”: HTTP 500"
    summaries = [
        SyncSummary(warnings=[feed]),
        SyncSummary(warnings=[feed]),  # periodic sync, same problem: no new toast
        SyncSummary(warnings=[feed, "skipping unreadable event x.ics"]),
        OSError("network down"),
    ]
    app = _app(store, summaries)  # type: ignore[arg-type]
    async with app.run_test(size=(120, 40)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert _toasts(app) == [f"1 sync warning: {feed} · R sync log"]
        await _sync(app, pilot)
        assert len(_toasts(app)) == 1
        await _sync(app, pilot)
        assert _toasts(app)[-1] == f"2 sync warnings: {feed} · R sync log"
        await _sync(app, pilot)

        assert [(e.error, e.message) for e in app.sync_log] == [
            (False, feed),
            (False, feed),
            (False, feed),
            (False, "skipping unreadable event x.ics"),
            (True, "network down"),
        ]
        await pilot.press("R")
        screen = app.screen
        assert isinstance(screen, SyncLogScreen)
        text = _entries_text(app)
        rows = text.splitlines()
        assert "✗" in rows[0] and "network down" in rows[0]  # newest first
        assert "⚠" in rows[1] and "skipping unreadable" in rows[1]
        assert rows[0][:8] == app.sync_log[-1].at.strftime("%H:%M:%S")
        await pilot.press("R")
        assert not isinstance(app.screen, SyncLogScreen)


async def test_log_screen_empty_and_older_days(store: Store) -> None:
    app = TcalApp(StoreSource(store), load_config(), today=TODAY)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("R")
        assert "No sync warnings" in _entries_text(app)
        await pilot.press("escape")
        yesterday = datetime.now() - timedelta(days=1)
        app.sync_log.append(LogEntry(yesterday, False, "old"))
        await pilot.press("R")
        text = _entries_text(app)
        assert text.startswith(yesterday.strftime("%a %d %H:%M"))
        assert "tcal.log" in str(app.screen.query_one("#synclog-hint").render())


def test_help_lists_sync_log() -> None:
    rows = dict(row for _, rows in sections(load_config().keys) for row in rows)
    assert rows["R"] == "Sync log (recent warnings and errors)"
