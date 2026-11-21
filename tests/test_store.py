from collections.abc import Iterator
from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from test_ics import SERIES

from tcal.ics import from_ics
from tcal.model import Calendar, Event
from tcal.store import Store

VIENNA = ZoneInfo("Europe/Vienna")
START = datetime(2026, 11, 18, 10, 0, tzinfo=VIENNA)


@pytest.fixture
def db(tmp_path) -> Iterator[Store]:
    with Store(tmp_path / "data" / "tcal.db") as store:
        store.upsert_calendars(
            [Calendar("cal", "Cal", "#123456"), Calendar("ro", "RO", "#000000", readonly=True)]
        )
        yield store


def _event(uid: str = "e1", **kw) -> Event:
    return Event(uid, "cal", "Meeting", START, START + timedelta(hours=1), **kw)


def test_calendars_roundtrip_and_replace(db: Store) -> None:
    assert [(c.id, c.readonly) for c in db.calendars()] == [("cal", False), ("ro", True)]
    db.upsert_events("ro", [replace(_event("x"), calendar_id="ro")])
    db.upsert_calendars([Calendar("cal", "Renamed", "#123456")])
    assert [c.name for c in db.calendars()] == ["Renamed"]
    assert db.get_event("x") is None  # vanished calendar takes its events along


def test_events_between_and_fields(db: Store) -> None:
    event = _event(location="Room", description="x", href="h", etag="1", rrule=None)
    db.upsert_events(
        "cal",
        [
            event,
            replace(
                _event("old"), start=START - timedelta(days=30), end=START - timedelta(days=29)
            ),
        ],
    )
    found = db.events_between(START, START + timedelta(days=1))
    assert found == [event] and found[0].start.tzinfo == VIENNA
    assert db.get_event("e1") == event


def test_series_and_overrides_always_returned(db: Store) -> None:
    db.upsert_events("cal", from_ics(SERIES, "cal", "h", "1"))
    far = datetime(2027, 6, 1, tzinfo=VIENNA)
    found = db.events_between(far, far + timedelta(days=1))
    assert sorted(e.summary for e in found) == ["Weekly", "Weekly (moved)"]
    master = db.get_event("series-1")
    assert master and master.recurrence_id is None and master.raw == SERIES
    assert master.exdates == (datetime(2026, 11, 9, 9, 0, tzinfo=VIENNA),)


def test_save_new_event_queues_create_once(db: Store) -> None:
    saved = db.save_event(_event())
    assert saved.raw and "SUMMARY:Meeting" in saved.raw
    db.save_event(replace(saved, summary="Renamed"))
    ops = db.pending_ops()
    assert [(op.kind, op.event.summary) for op in ops] == [("create", "Renamed")]
    db.clear_op(ops[0].id)
    assert db.pending_ops() == []


def test_edit_of_pushed_event_queues_update(db: Store) -> None:
    db.upsert_events("cal", [_event(href="h", etag="1")])
    db.save_event(replace(_event(href="h", etag="1"), summary="Edited"))
    db.save_event(replace(_event(href="h", etag="1"), summary="Edited again"))
    assert [(op.kind, op.event.summary) for op in db.pending_ops()] == [("update", "Edited again")]


def test_delete_unpushed_event_leaves_no_op(db: Store) -> None:
    db.save_event(_event())
    db.delete_event("e1")
    assert db.get_event("e1") is None and db.pending_ops() == []


def test_delete_pushed_event_queues_delete_with_etag(db: Store) -> None:
    db.upsert_events("cal", [_event(href="h", etag="1")])
    db.save_event(replace(_event(href="h", etag="1"), summary="Edited"))
    db.delete_event("e1")
    (op,) = db.pending_ops()
    assert op.kind == "delete" and (op.event.uid, op.event.href, op.event.etag) == ("e1", "h", "1")


def test_delete_one_occurrence_adds_exdate_and_drops_override(db: Store) -> None:
    master, override = from_ics(SERIES, "cal", "h", "1")
    db.upsert_events("cal", [master, override])
    assert override.recurrence_id
    db.delete_event("series-1", override.recurrence_id)
    saved = db.get_event("series-1")
    assert saved and override.recurrence_id in saved.exdates
    assert "Weekly (moved)" not in (saved.raw or "")
    assert [e.summary for e in db.events_between(START, START)] == ["Weekly"]
    assert [op.kind for op in db.pending_ops()] == ["update"]


def test_moving_to_another_calendar_is_delete_plus_create(db: Store) -> None:
    db.upsert_calendars([Calendar("cal", "Cal", "#123456"), Calendar("other", "Other", "#654321")])
    db.upsert_events("cal", [_event(href="h", etag="1")])
    db.save_event(replace(_event(href="h", etag="1"), calendar_id="other"))
    ops = db.pending_ops()
    assert [(op.kind, op.event.calendar_id, op.event.href) for op in ops] == [
        ("delete", "cal", "h"),
        ("create", "other", None),
    ]


def test_pull_keeps_events_with_pending_ops(db: Store) -> None:
    db.upsert_events("cal", [_event("a", href="ha"), _event("b", href="hb")])
    db.save_event(replace(_event("a", href="ha"), summary="Local edit"))
    db.upsert_events("cal", [replace(_event("a", href="ha"), summary="Server")])
    a = db.get_event("a")
    assert a and a.summary == "Local edit"
    assert db.get_event("b") is None  # deleted on the server


def test_restore_cancels_unpushed_delete(db: Store) -> None:
    db.upsert_events("cal", [_event(href="h", etag="1")])
    db.restore(db.delete_event("e1"))
    restored = db.get_event("e1")
    assert restored and (restored.href, restored.etag) == ("h", "1")
    assert [op.kind for op in db.pending_ops()] == ["update"]


def test_restore_after_pushed_delete_creates_again(db: Store) -> None:
    db.upsert_events("cal", [_event(href="h", etag="1")])
    rows = db.delete_event("e1")
    for op in db.pending_ops():
        db.clear_op(op.id)  # the delete reached the server
    db.restore(rows)
    restored = db.get_event("e1")
    assert restored and restored.href is None
    assert [op.kind for op in db.pending_ops()] == ["create"]


def test_restore_one_occurrence_brings_back_override(db: Store) -> None:
    master, override = from_ics(SERIES, "cal", "h", "1")
    db.upsert_events("cal", [master, override])
    assert override.recurrence_id
    db.restore(db.delete_event("series-1", override.recurrence_id))
    saved = db.get_event("series-1")
    assert saved and override.recurrence_id not in saved.exdates
    assert "Weekly (moved)" in (saved.raw or "")
    summaries = {e.summary for e in db.events_between(START, START + timedelta(days=30))}
    assert summaries == {"Weekly", "Weekly (moved)"}
    assert [op.kind for op in db.pending_ops()] == ["update"]
