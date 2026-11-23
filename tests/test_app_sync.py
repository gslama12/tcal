from dataclasses import replace
from datetime import datetime, time, timedelta

from conftest import TODAY
from textual.widgets import Input, Static

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
from tcal.ui.screens.event_detail import EventDetail
from tcal.ui.screens.event_prompt import EventPrompt
from tcal.ui.screens.prompt import Prompt
from tcal.ui.screens.search import ResultList
from tcal.ui.widgets.calendar_list import CalendarList
from tcal.ui.widgets.schedule_view import ScheduleView
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


def _synced_app(provider: FakeProvider, store: Store) -> TcalApp:
    job = sync_job(provider, paths.database_file(), load_config().sync, today=TODAY)
    return TcalApp(StoreSource(store), load_config(), today=TODAY, sync=job)


def _dinner(app: TcalApp):
    return next(o for o in app.occurrences(TODAY, TODAY + timedelta(1)) if o.summary == "Dinner")


async def test_detail_follows_a_server_change_and_closes_when_deleted(
    provider: FakeProvider, store: Store
) -> None:
    app = _synced_app(provider, store)
    async with app.run_test(size=(140, 45)) as pilot:
        await _wait_for_sync(app, pilot)
        occ = _dinner(app)
        app.push_screen(EventDetail(occ))
        await pilot.pause()
        provider.update_event(replace(provider.events[occ.event.uid], location="Pizzeria"))
        app.request_sync()
        await _wait_for_sync(app, pilot)
        assert isinstance(app.screen, EventDetail)
        assert str(app.screen.query_one("#location", Static).render()) == "Pizzeria"

        provider.delete_event(provider.events[occ.event.uid])
        app.request_sync()
        await _wait_for_sync(app, pilot)
        assert not isinstance(app.screen, EventDetail)
        assert any(
            "“Dinner” was deleted on the server" in str(n.message) for n in app._notifications
        )


async def test_search_results_follow_a_sync(provider: FakeProvider, store: Store) -> None:
    app = _synced_app(provider, store)
    async with app.run_test(size=(140, 45)) as pilot:
        await _wait_for_sync(app, pilot)
        uid = _dinner(app).event.uid
        await pilot.press("slash", *"dinner")
        provider.update_event(replace(provider.events[uid], summary="Dinner server"))
        app.request_sync()
        await _wait_for_sync(app, pilot)
        results = app.screen.query_one(ResultList)
        assert results.option_count == 1
        assert "Dinner server" in str(results.get_option_at_index(0).prompt)


async def test_saving_over_a_server_change_asks_first(provider: FakeProvider, store: Store) -> None:
    app = _synced_app(provider, store)
    async with app.run_test(size=(140, 45)) as pilot:
        await _wait_for_sync(app, pilot)
        occ = _dinner(app)
        for choice, title in (("d", "Mine"), ("escape", "Mine"), ("o", "Mine")):
            if not isinstance(app.screen, EventPrompt):
                app.edit_event(_dinner(app).event)
                await pilot.pause()
            line = app.screen.query_one(Input)
            line.value = line.value.replace("Dinner", title)
            uid = occ.event.uid
            provider.update_event(replace(provider.events[uid], location=f"Server {choice}"))
            app.request_sync()
            await _wait_for_sync(app, pilot)
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, Prompt)
            await pilot.press(choice)
            await _wait_for_sync(app, pilot)
            if choice == "escape":
                assert isinstance(app.screen, EventPrompt)  # back to the prompt, input kept
                assert app.screen.query_one(Input).value.startswith("Mine")
            else:
                assert not isinstance(app.screen, (EventPrompt, Prompt))
            if choice == "d":
                assert provider.events[uid].summary == "Dinner"  # the server's version kept
        assert provider.events[uid].summary == "Mine"  # overwritten, not dropped as a conflict
        assert any("Saved “Mine” · u undo" in str(n.message) for n in app._notifications)
        assert not any("dropped" in str(n.message) for n in app._notifications)


async def test_first_run_offline_explains_and_retries() -> None:
    calls = 0

    def unreachable():
        nonlocal calls
        calls += 1
        raise OSError("Network is unreachable")

    def messages(app: TcalApp) -> list[str]:
        return [str(n.message) for n in app._notifications]

    with Store(paths.database_file()) as store:  # empty cache
        app = TcalApp(StoreSource(store), load_config(), today=TODAY, sync=unreachable)
        async with app.run_test() as pilot:
            await _wait_for_sync(app, pilot)
            error = "Couldn't reach iCloud: Network is unreachable · r retry"
            assert sum(m.startswith(error) for m in messages(app)) == 1
            app.request_sync()  # a background retry with the same error: no new toast
            await _wait_for_sync(app, pilot)
            assert sum(m.startswith(error) for m in messages(app)) == 1
            hint = "Not synced yet · r retry"
            assert str(app.query_one(CalendarList).render()) == hint
            schedule = app.query_one(ScheduleView)
            assert str(schedule.render()).strip() == hint
            await pilot.press("a")
            assert hint in messages(app)
            await pilot.press("r")  # the sync key always reports
            await _wait_for_sync(app, pilot)
            assert sum(m.startswith(error) for m in messages(app)) == 2
            assert calls == 3


async def test_background_failure_with_a_cache_stays_quiet(store: Store) -> None:
    def unreachable():
        raise OSError("Network is unreachable")

    app = TcalApp(StoreSource(store), load_config(), today=TODAY, sync=unreachable)
    async with app.run_test() as pilot:
        await _wait_for_sync(app, pilot)
        assert not app._notifications


async def test_server_changed_names_the_event_and_its_new_title(
    provider: FakeProvider, store: Store
) -> None:
    app = _synced_app(provider, store)
    async with app.run_test(size=(140, 45)) as pilot:
        await _wait_for_sync(app, pilot)
        uid = _dinner(app).event.uid
        app.edit_event(_dinner(app).event)
        await pilot.pause()
        provider.update_event(replace(provider.events[uid], summary="Dinner server"))
        app.request_sync()
        await _wait_for_sync(app, pilot)
        app.screen.query_one(Input).value = "X"
        await pilot.press("enter")
        await pilot.pause()
        question = str(app.screen.query_one("#question", Static).render())
        assert question == "“Dinner” was changed on the server (now “Dinner server”)."
