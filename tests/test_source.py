from dataclasses import replace
from datetime import timedelta

from conftest import TODAY

from tcal.providers.fake import FakeProvider
from tcal.source import StoreSource
from tcal.store import Store


def test_demo_data_shape(provider: FakeProvider) -> None:
    events = list(provider.events.values())
    assert len(provider.list_calendars()) >= 4
    assert any(e.rrule for e in events)
    assert any(e.all_day and e.end - e.start > timedelta(days=1) for e in events)
    assert len({e.uid for e in events}) == len(events)
    assert all(e.href and e.etag for e in events)


def test_occurrences_expand_recurrence_and_overlap(store: Store) -> None:
    source = StoreSource(store)
    occs = source.occurrences(TODAY, TODAY + timedelta(days=1))
    names = [o.summary for o in occs]
    assert "Standup" in names  # weekly recurring, today is a weekday
    assert "Anna's birthday" in names
    assert "Conference" in names  # multi-day all-day spanning today
    assert occs == sorted(occs, key=lambda o: (o.start, o.end))

    week = source.occurrences(TODAY, TODAY + timedelta(days=14))
    assert sum(o.summary == "Standup" for o in week) == 10


def test_save_and_delete_through_source(store: Store) -> None:
    source = StoreSource(store)
    day = (TODAY, TODAY + timedelta(days=1))
    dentist = next(o.event for o in source.occurrences(*day) if o.summary == "Dentist")
    source.save_event(replace(dentist, summary="Dentist (moved)"))
    assert "Dentist (moved)" in [o.summary for o in source.occurrences(*day)]
    source.delete_event(dentist.uid)
    assert not any(o.summary.startswith("Dentist") for o in source.occurrences(*day))


def test_crud_roundtrip(provider: FakeProvider) -> None:
    event = next(iter(provider.events.values()))
    created = provider.create_event(replace(event, uid="new", href=None))
    assert created.href and created.etag
    updated = provider.update_event(replace(created, summary="Renamed"))
    assert provider.events["new"].summary == "Renamed" and updated.etag != created.etag
    provider.delete_event(updated)
    assert "new" not in provider.events
