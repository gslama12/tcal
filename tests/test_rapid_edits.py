"""Our own pushes must never look like someone else's change (false etag conflicts)."""

from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from conftest import TODAY

from tcal import paths
from tcal.config import load_config
from tcal.model import Calendar, Event
from tcal.providers.base import ProviderError
from tcal.providers.fake import FakeProvider
from tcal.source import StoreSource
from tcal.store import Store
from tcal.sync import SyncEngine, SyncSummary, sync_job
from tcal.ui.app import TcalApp

STEP = timedelta(minutes=15)


class BusyProvider(FakeProvider):
    """Runs the hooks (each once) while a request is under way."""

    before: Callable[[], object] | None = None  # the user acts while the request travels
    after: Callable[[], object] | None = None  # ... while the answer does
    pulling: Callable[[], object] | None = None  # ... while a pull runs

    def fetch_events(self, calendar: Calendar, start: datetime, end: datetime) -> list[Event]:
        pulling, self.pulling = self.pulling, None
        if pulling:
            pulling()
        return super().fetch_events(calendar, start, end)

    def _busy(self, request: Callable[[], Event | None]) -> Event | None:
        before, self.before = self.before, None
        if before:
            before()
        answer = request()
        after, self.after = self.after, None
        if after:
            after()
        return answer

    def create_event(self, event: Event) -> Event:
        done = self._busy(lambda: super(BusyProvider, self).create_event(event))
        assert done
        return done

    def update_event(self, event: Event) -> Event:
        done = self._busy(lambda: super(BusyProvider, self).update_event(event))
        assert done
        return done

    def delete_event(self, event: Event) -> None:
        self._busy(lambda: super(BusyProvider, self).delete_event(event))


@pytest.fixture(params=[True, False], ids=["put-etags", "no-put-etags"])
def server(request: pytest.FixtureRequest) -> BusyProvider:
    return BusyProvider(today=TODAY, put_etags=request.param)


@pytest.fixture
def ui(server: BusyProvider, tmp_path: Path) -> Iterator[Store]:
    """The UI's connection to the cache, synced once."""
    with Store(tmp_path / "tcal.db") as store:
        SyncEngine(server, store, today=TODAY).sync()
        yield store


@pytest.fixture
def sync(server: BusyProvider, ui: Store, tmp_path: Path) -> Callable[[], SyncSummary]:
    return sync_job(server, tmp_path / "tcal.db", load_config().sync, today=TODAY)


def _cached(ui: Store, summary: str = "Dentist") -> Event:
    day = timedelta(days=1)
    start = SyncEngine(FakeProvider(demo=False), ui, today=TODAY).window()[0]
    return next(e for e in ui.events_between(start, start + 400 * day) if e.summary == summary)


def _moved(event: Event, steps: int = 1) -> Event:
    return replace(event, start=event.start + steps * STEP, end=event.end + steps * STEP)


def _assert_synced(server: FakeProvider, ui: Store, expected: Event) -> None:
    assert ui.pending_count() == 0
    cached = ui.get_event(expected.uid)
    assert cached and cached.start == expected.start == server.events[expected.uid].start
    assert cached.etag == server.events[expected.uid].etag


def test_moves_synced_one_by_one(server: BusyProvider, ui: Store, sync) -> None:
    event = _cached(ui)
    for _ in range(4):
        event = ui.save_event(_moved(event))  # never re-read: the etag gets staler and staler
        assert sync().conflicts == []
    _assert_synced(server, ui, event)


@pytest.mark.parametrize("when", ["before", "after", "pulling"])
def test_move_while_the_previous_one_is_pushed(
    server: BusyProvider, ui: Store, sync, when: str
) -> None:
    """The reported bug: the UI still held the etag from before the running push."""
    first = ui.save_event(_moved(_cached(ui)))
    setattr(server, when, lambda: ui.save_event(_moved(first)))
    assert sync().conflicts == []
    assert sync().conflicts == []
    _assert_synced(server, ui, _moved(first))


def test_move_after_the_push_was_recorded_but_before_the_ui_reread(
    server: BusyProvider, ui: Store, sync
) -> None:
    first = ui.save_event(_moved(_cached(ui)))
    assert sync().conflicts == []  # recorded and pulled; the UI still shows ``first``
    second = ui.save_event(_moved(first))
    assert sync().conflicts == []
    _assert_synced(server, ui, second)


def test_edit_while_being_created(server: BusyProvider, ui: Store, sync) -> None:
    dentist = _cached(ui)
    new = ui.save_event(Event("new", "work", "New", dentist.start, dentist.end))
    server.after = lambda: ui.save_event(_moved(new))
    for _ in range(2):
        assert sync().conflicts == []
    _assert_synced(server, ui, _moved(new))


def test_delete_while_being_created(server: BusyProvider, ui: Store, sync) -> None:
    dentist = _cached(ui)
    ui.save_event(Event("new", "work", "New", dentist.start, dentist.end))
    server.after = lambda: ui.delete_event("new")
    for _ in range(2):
        assert sync().conflicts == []
    assert "new" not in server.events and ui.get_event("new") is None


def test_change_calendar_while_being_created(server: BusyProvider, ui: Store, sync) -> None:
    dentist = _cached(ui)
    new = ui.save_event(Event("new", "work", "New", dentist.start, dentist.end))
    server.after = lambda: ui.save_event(replace(new, calendar_id="sport"))
    for _ in range(2):
        assert sync().conflicts == []
    assert server.events["new"].calendar_id == "sport"
    _assert_synced(server, ui, new)


def test_delete_while_an_update_is_pushed(server: BusyProvider, ui: Store, sync) -> None:
    event = ui.save_event(_moved(_cached(ui)))
    server.after = lambda: ui.delete_event(event.uid)
    for _ in range(2):
        assert sync().conflicts == []
    assert event.uid not in server.events and ui.pending_count() == 0


def test_undo_while_a_delete_is_pushed(server: BusyProvider, ui: Store, sync) -> None:
    event = _cached(ui)
    rows = ui.delete_event(event.uid)
    server.after = lambda: ui.restore(rows)
    for _ in range(2):
        assert sync().conflicts == []
    _assert_synced(server, ui, event)


def test_undo_a_delete_queued_during_a_push(server: BusyProvider, ui: Store, sync) -> None:
    event = ui.save_event(_moved(_cached(ui)))
    rows: list[Event] = []
    server.after = lambda: rows.extend(ui.delete_event(event.uid))
    SyncEngine(server, ui, today=TODAY)._push(SyncSummary())  # the delete stays queued
    ui.restore(rows)
    assert sync().conflicts == []
    _assert_synced(server, ui, event)


def test_undo_deleting_an_event_whose_calendar_change_is_unpushed(
    server: BusyProvider, ui: Store, sync
) -> None:
    moved = ui.save_event(replace(_cached(ui), calendar_id="sport"))
    ui.restore(ui.delete_event(moved.uid))
    assert [op.kind for op in ui.pending_ops()] == ["delete", "create"]
    assert sync().conflicts == []
    assert server.events[moved.uid].calendar_id == "sport"


def test_new_etag_without_a_change(server: BusyProvider, ui: Store, sync) -> None:
    """The server rewrote the resource: pulled, or not yet pulled; never pushed, or pushed."""
    event = _cached(ui)
    server.touch(event.uid)
    event = ui.save_event(_moved(event))
    assert sync().conflicts == []
    for _ in range(2):  # pulled before the UI's next edit, then not pulled
        server.touch(event.uid)
        sync()
        server.touch(event.uid)
        event = ui.save_event(_moved(event))
        assert sync().conflicts == []
    _assert_synced(server, ui, event)

    server.touch(event.uid)
    ui.delete_event(event.uid)
    assert sync().conflicts == [] and event.uid not in server.events


def test_stale_pull_after_our_push(server: BusyProvider, ui: Store, sync) -> None:
    """The pull still answers with what our push replaced."""
    old = server.events[_cached(ui).uid]
    first = ui.save_event(_moved(_cached(ui)))
    engine = SyncEngine(server, ui, today=TODAY)
    engine._push(SyncSummary())
    ui.upsert_events(old.calendar_id, [old])
    stale = ui.get_event(old.uid)
    assert stale and stale.start == old.start
    again = ui.save_event(_moved(stale, 3))
    assert sync().conflicts == []
    assert again.start != first.start
    _assert_synced(server, ui, again)


def test_answer_lost_after_the_server_stored_the_push(
    server: BusyProvider, ui: Store, sync
) -> None:
    def lost() -> None:
        raise ProviderError("timeout")

    event = ui.save_event(_moved(_cached(ui)))
    new = ui.save_event(Event("new", "work", "New", event.start, event.end))
    for _ in range(2):
        server.after = lost
        with pytest.raises(ProviderError):
            sync()
    assert sync().conflicts == []
    _assert_synced(server, ui, event)
    _assert_synced(server, ui, new)


def test_edit_after_a_lost_answer(server: BusyProvider, ui: Store, sync) -> None:
    def lost() -> None:
        raise ProviderError("timeout")

    event = _cached(ui)
    for _ in range(2):
        event = ui.save_event(_moved(event))
        server.after = lost
        with pytest.raises(ProviderError):
            sync()
    event = ui.save_event(_moved(event))
    assert sync().conflicts == []
    _assert_synced(server, ui, event)


def test_new_etag_pulled_before_the_ui_reread(server: BusyProvider, ui: Store, sync) -> None:
    event = _cached(ui)
    server.touch(event.uid)
    sync()
    event = ui.save_event(_moved(event))  # with the old etag; never edited before
    assert sync().conflicts == []
    _assert_synced(server, ui, event)


# ----- real conflicts ---------------------------------------------------------


@pytest.mark.parametrize("edit", ["summary", "raw"])
@pytest.mark.parametrize("pushed", [0, 1, 2])
@pytest.mark.parametrize("deleting", [False, True])
def test_changed_by_someone_else(
    server: BusyProvider, ui: Store, sync, pushed: int, edit: str, deleting: bool
) -> None:
    """Also a change tcal doesn't model (here a status in the resource text)."""
    event = _cached(ui)
    for _ in range(pushed):
        event = ui.save_event(_moved(event))
        assert sync().conflicts == []
    theirs = server.events[event.uid]
    if edit == "summary":
        theirs = replace(theirs, summary="Theirs")
    else:
        raw = (theirs.raw or "").replace("END:VEVENT", "STATUS:TENTATIVE\r\nEND:VEVENT")
        theirs = replace(theirs, raw=raw)
    theirs = server._store(theirs, theirs.href)
    if deleting:
        ui.delete_event(event.uid)
    else:
        ui.save_event(_moved(event))
    assert sync().conflicts == ["Dentist"]
    _assert_synced(server, ui, theirs)
    cached = ui.get_event(event.uid)
    assert cached and cached.raw == theirs.raw


def test_changed_by_someone_else_and_pulled_before_the_ui_reread(
    server: BusyProvider, ui: Store, sync
) -> None:
    event = ui.save_event(_moved(_cached(ui)))
    sync()
    theirs = replace(server.events[event.uid], summary="Theirs")
    server._store(theirs, theirs.href)
    sync()
    event = ui.save_event(_moved(event))
    ui.save_event(_moved(event))
    assert sync().conflicts == ["Dentist"]
    assert server.events[event.uid].summary == "Theirs"


def test_deleted_by_someone_else(server: BusyProvider, ui: Store, sync) -> None:
    event = _cached(ui)
    del server.events[event.uid]
    ui.save_event(_moved(event))
    assert sync().conflicts == ["Dentist"]
    assert ui.get_event(event.uid) is None and ui.pending_count() == 0


# ----- in the app -------------------------------------------------------------


async def test_moves_in_the_app_during_a_sync(server: BusyProvider) -> None:
    config = load_config()
    with Store(paths.database_file()) as store:
        job = sync_job(server, paths.database_file(), config.sync, today=TODAY)
        app = TcalApp(StoreSource(store), config, today=TODAY, sync=job)

        def move() -> None:
            day = app.occurrences(TODAY, TODAY + timedelta(1))
            app.editor.move(next(o for o in day if o.summary == "Dentist"), STEP)

        async with app.run_test() as pilot:

            async def settle() -> None:
                for _ in range(3):
                    await pilot.pause()
                    await app.workers.wait_for_complete()

            await settle()
            start = _cached(store).start
            uid = _cached(store).uid
            for hook in ("before", "after", "pulling"):
                setattr(server, hook, lambda: app.call_from_thread(move))
                move()
                await settle()
                start += 2 * STEP
                # the move made during a sync is pushed right after it, not at the next interval
                assert store.pending_count() == 0
                assert server.events[uid].start == start
            for _ in range(3):
                move()
            await settle()
            assert server.events[uid].start == start + 3 * STEP
            assert not any("dropped" in str(n.message) for n in app._notifications)
