from datetime import datetime, time, timedelta

from conftest import TODAY

from tcal import paths
from tcal.config import load_config
from tcal.model import Event
from tcal.providers.base import ProviderError
from tcal.providers.fake import FakeProvider
from tcal.source import StoreSource
from tcal.store import Store
from tcal.sync import sync_job
from tcal.tz import local_zone
from tcal.ui.app import TcalApp
from tcal.ui.widgets.statusbar import StatusBar


async def _wait_for_sync(app: TcalApp, pilot) -> None:
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause()


async def test_syncs_on_start_and_pushes_edits(provider: FakeProvider) -> None:
    config = load_config()
    with Store(paths.database_file()) as store:  # empty cache: everything comes from the sync
        job = sync_job(provider, paths.database_file(), config.sync, today=TODAY)
        app = TcalApp(StoreSource(store), config, today=TODAY, sync=job)
        async with app.run_test() as pilot:
            await _wait_for_sync(app, pilot)
            assert len(app.calendars()) == len(provider.calendars)
            assert app.occurrences(TODAY, TODAY + timedelta(days=1))
            assert "synced" in str(app.query_one(StatusBar).render())

            start = datetime.combine(TODAY, time(15), local_zone())
            app.save_event(Event("new", "work", "Coffee", start, start + timedelta(minutes=30)))
            assert "Coffee" in [o.summary for o in app.occurrences(TODAY, TODAY + timedelta(1))]
            await _wait_for_sync(app, pilot)
            assert provider.events["new"].summary == "Coffee"

            app.delete_event("new")
            await _wait_for_sync(app, pilot)
            assert "new" not in provider.events


async def test_sync_failure_is_shown(store: Store) -> None:
    def failing():
        raise ProviderError("offline")

    app = TcalApp(StoreSource(store), load_config(), today=TODAY, sync=failing)
    async with app.run_test() as pilot:
        await _wait_for_sync(app, pilot)
        assert "sync failed: offline" in str(app.query_one(StatusBar).render())
        assert app.occurrences(TODAY, TODAY + timedelta(days=1))  # cache still shown
