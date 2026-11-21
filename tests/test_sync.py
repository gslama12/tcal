import logging
from dataclasses import replace
from datetime import datetime, time, timedelta

import pytest
from conftest import TODAY

from tcal.config import load_config
from tcal.model import Event
from tcal.providers.base import ProviderError
from tcal.providers.fake import FakeProvider
from tcal.store import Store
from tcal.sync import SyncEngine, sync_job
from tcal.tz import local_zone


def _at(hour: int, days: int = 0) -> datetime:
    return datetime.combine(TODAY + timedelta(days=days), time(hour), local_zone())


@pytest.fixture
def engine(provider: FakeProvider, tmp_path) -> SyncEngine:
    return SyncEngine(provider, Store(tmp_path / "tcal.db"), today=TODAY)


def test_pull_fills_cache(engine: SyncEngine, provider: FakeProvider) -> None:
    summary = engine.sync()
    assert summary.calendars == len(provider.calendars)
    assert summary.events == len(provider.events)
    assert {c.id for c in engine.store.calendars()} == {c.id for c in provider.calendars}
    assert "5 calendars" in str(summary)


def test_window(engine: SyncEngine) -> None:
    start, end = engine.window()
    assert start.date() == TODAY.replace(month=8) and end.date() == TODAY.replace(year=2027)


def test_offline_edits_are_pushed_on_next_sync(engine: SyncEngine, provider: FakeProvider) -> None:
    engine.sync()
    store = engine.store
    # Offline: create, edit and delete locally; nothing reaches the server yet.
    store.save_event(Event("new", "work", "Offsite", _at(9, 1), _at(17, 1)))
    dentist = next(e for e in provider.events.values() if e.summary == "Dentist")
    cached = store.get_event(dentist.uid)
    assert cached
    store.save_event(replace(cached, summary="Dentist!"))
    store.delete_event(next(e.uid for e in provider.events.values() if e.summary == "Haircut"))
    assert "new" not in provider.events and len(store.pending_ops()) == 3

    summary = engine.sync()
    assert summary.pushed == 3 and store.pending_ops() == []
    assert provider.events["new"].summary == "Offsite"
    assert provider.events[dentist.uid].summary == "Dentist!"
    assert not any(e.summary == "Haircut" for e in provider.events.values())
    created = store.get_event("new")
    assert created and created.href == "fake://new" and created.etag


def test_conflict_server_wins(engine: SyncEngine, provider: FakeProvider, caplog) -> None:
    engine.sync()
    uid = next(e.uid for e in provider.events.values() if e.summary == "Dentist")
    # Changed on the server (new etag) after our last pull ...
    provider.update_event(replace(provider.events[uid], summary="Server edit"))
    # ... and locally.
    cached = engine.store.get_event(uid)
    assert cached
    engine.store.save_event(replace(cached, summary="Local edit"))

    with caplog.at_level(logging.WARNING, logger="tcal.sync"):
        summary = engine.sync()
    assert summary.conflicts == 1 and summary.pushed == 0
    assert "conflict" in caplog.text
    synced = engine.store.get_event(uid)
    assert synced and synced.summary == "Server edit"
    assert engine.store.pending_ops() == []


class FlakyProvider(FakeProvider):
    online = False

    def create_event(self, event: Event) -> Event:
        if not self.online:
            raise ProviderError("offline")
        return super().create_event(event)


def test_failed_push_keeps_ops_queued(tmp_path) -> None:
    provider = FlakyProvider(today=TODAY)
    engine = SyncEngine(provider, Store(tmp_path / "tcal.db"), today=TODAY)
    engine.sync()
    engine.store.save_event(Event("new", "work", "Offsite", _at(9), _at(10)))
    with pytest.raises(ProviderError):
        engine.sync()
    assert [op.kind for op in engine.store.pending_ops()] == ["create"]
    assert engine.store.get_event("new")  # still shown from the cache
    provider.online = True
    assert engine.sync().pushed == 1


def test_sync_job_uses_its_own_connection(provider: FakeProvider, tmp_path) -> None:
    job = sync_job(provider, tmp_path / "tcal.db", load_config().sync, today=TODAY)
    assert job().events == len(provider.events)
    with Store(tmp_path / "tcal.db") as store:
        assert len(store.calendars()) == len(provider.calendars)
