from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from tcal.ics import from_ics, to_ics, without_instance
from tcal.model import Event
from tcal.tz import local_midnight

VIENNA = ZoneInfo("Europe/Vienna")

SERIES = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Apple Inc.//iCloud//EN
BEGIN:VEVENT
UID:series-1
DTSTAMP:20261101T000000Z
DTSTART;TZID=Europe/Vienna:20261102T090000
DTEND;TZID=Europe/Vienna:20261102T100000
SUMMARY:Weekly
RRULE:FREQ=WEEKLY;BYDAY=MO
EXDATE;TZID=Europe/Vienna:20261109T090000
BEGIN:VALARM
ACTION:DISPLAY
TRIGGER:-PT15M
END:VALARM
END:VEVENT
BEGIN:VEVENT
UID:series-1
DTSTAMP:20261101T000000Z
RECURRENCE-ID;TZID=Europe/Vienna:20261116T090000
DTSTART;TZID=Europe/Vienna:20261116T140000
DTEND;TZID=Europe/Vienna:20261116T150000
SUMMARY:Weekly (moved)
END:VEVENT
END:VCALENDAR
"""


def test_roundtrip_timed_series() -> None:
    start = datetime(2026, 11, 16, 9, 0, tzinfo=VIENNA)
    event = Event(
        "u1",
        "cal",
        "Standup",
        start,
        start + timedelta(minutes=15),
        location="Room 4",
        description="Daily\nsync",
        rrule="FREQ=WEEKLY;BYDAY=MO,WE",
        exdates=(start + timedelta(days=7),),
    )
    assert from_ics(to_ics(event), "cal") == [event]


def test_roundtrip_all_day_multi_day() -> None:
    event = Event(
        "u2",
        "cal",
        "Trip",
        local_midnight(datetime(2026, 12, 1).date()),
        local_midnight(datetime(2026, 12, 4).date()),
        all_day=True,
    )
    text = to_ics(event)
    assert "DTSTART;VALUE=DATE:20261201" in text and "DTEND;VALUE=DATE:20261204" in text
    assert from_ics(text, "cal") == [event]


def test_fixed_offset_times_become_named_or_utc() -> None:
    fixed = datetime(2026, 11, 18, 10, 0).astimezone()  # tzinfo is a fixed offset
    event = Event("u3", "cal", "Call", fixed, fixed + timedelta(hours=1))
    back = from_ics(to_ics(event), "cal")[0]
    assert back.start == fixed and back.end - back.start == timedelta(hours=1)


def test_parse_series_with_override_keeps_raw() -> None:
    master, override = from_ics(SERIES, "cal", href="https://x/1.ics", etag='"e1"')
    assert master.rrule == "FREQ=WEEKLY;BYDAY=MO"
    assert master.exdates == (datetime(2026, 11, 9, 9, 0, tzinfo=VIENNA),)
    assert override.recurrence_id == datetime(2026, 11, 16, 9, 0, tzinfo=VIENNA)
    assert override.start.hour == 14
    assert master.href == "https://x/1.ics" and master.etag == '"e1"' and master.raw == SERIES


def test_edit_preserves_unmodelled_properties_and_overrides() -> None:
    master, _ = from_ics(SERIES, "cal")
    master.summary = "Weekly sync"
    text = to_ics(master)
    assert "VALARM" in text and "TRIGGER:-PT15M" in text
    events = from_ics(text, "cal")
    assert [e.summary for e in events] == ["Weekly sync", "Weekly (moved)"]


def test_without_instance_drops_the_override() -> None:
    master, override = from_ics(SERIES, "cal")
    assert override.recurrence_id
    trimmed = without_instance(master, override.recurrence_id)
    assert [e.summary for e in from_ics(trimmed.raw or "", "cal")] == ["Weekly"]


def test_date_only_and_floating_values() -> None:
    text = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:x
BEGIN:VEVENT
UID:a
DTSTART;VALUE=DATE:20261118
SUMMARY:No end
END:VEVENT
BEGIN:VEVENT
UID:b
DTSTART:20261118T080000
DURATION:PT30M
SUMMARY:Floating
END:VEVENT
END:VCALENDAR
"""
    no_end, floating = from_ics(text, "cal")
    assert no_end.all_day and no_end.end - no_end.start == timedelta(days=1)
    assert floating.start.tzinfo is not None
    assert floating.end - floating.start == timedelta(minutes=30)
