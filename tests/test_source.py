from dataclasses import replace
from datetime import timedelta

from conftest import TODAY

from tcal.providers.fake import FakeProvider
from tcal.source import ProviderSource


def test_demo_data_shape(provider: FakeProvider) -> None:
    events = list(provider.events.values())
    assert len(provider.list_calendars()) >= 4
    assert any(e.rrule for e in events)
    assert any(e.all_day and e.end - e.start > timedelta(days=1) for e in events)
    assert len({e.uid for e in events}) == len(events)


def test_occurrences_expand_recurrence_and_overlap(provider: FakeProvider) -> None:
    occs = ProviderSource(provider).occurrences(TODAY, TODAY + timedelta(days=1))
    names = [o.summary for o in occs]
    assert "Standup" in names  # weekly recurring, today is a weekday
    assert "Anna's birthday" in names
    assert "Conference" in names  # multi-day all-day spanning today
    assert occs == sorted(occs, key=lambda o: (o.start, o.end))

    week = ProviderSource(provider).occurrences(TODAY, TODAY + timedelta(days=14))
    assert sum(o.summary == "Standup" for o in week) == 10


def test_crud_roundtrip(provider: FakeProvider) -> None:
    event = next(iter(provider.events.values()))
    created = provider.create_event(replace(event, uid="new", href=None))
    assert created.href and created.etag
    updated = provider.update_event(replace(created, summary="Renamed"))
    assert provider.events["new"].summary == "Renamed" and updated.etag != created.etag
    provider.delete_event(updated)
    assert "new" not in provider.events
