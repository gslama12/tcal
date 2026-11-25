"""ICloudProvider + a real caldav DAVClient against iCloud-style HTTP answers."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from icloud_http import APPLE_ID, ENTRY, HOME, PASSWORD, WORK, FakeICloud, connect

from tcal.providers.base import AuthError
from tcal.providers.icloud import ICloudProvider
from tcal.recurrence import expand

VIENNA = ZoneInfo("Europe/Vienna")
WEEK = datetime(2026, 11, 16, tzinfo=VIENNA), datetime(2026, 11, 23, tzinfo=VIENNA)


@pytest.fixture
def server() -> FakeICloud:
    return FakeICloud()


@pytest.fixture
def icloud(server: FakeICloud) -> ICloudProvider:
    return connect(server)(APPLE_ID, PASSWORD, ENTRY)


def test_discovery_moves_to_the_partition_host(icloud: ICloudProvider, server) -> None:
    assert icloud.principal_url == ENTRY + "/1234567/principal/"
    assert icloud.home_url == HOME  # ":443" dropped
    icloud.list_calendars()
    assert server.requests[-1] == ("PROPFIND", HOME, "1")


def test_calendars_colors_readonly_and_reminders_skipped(icloud: ICloudProvider) -> None:
    cals = icloud.list_calendars()
    assert [(c.id, c.name, c.color, c.readonly) for c in cals] == [
        (WORK, "Work", "#FF2968", False),
        (HOME + "holidays/", "Holidays", "#CC73E1", True),
    ]


def test_week_of_events(icloud: ICloudProvider) -> None:
    work = icloud.list_calendars()[0]
    events = icloud.fetch_events(work, *WEEK)
    assert {e.href for e in events} == {
        WORK + n + ".ics" for n in ("6F1C-STANDUP", "A1B2-DENTIST", "C3D4-DAYOFF", "E5F6-BIRTHDAY")
    }
    assert {e.etag for e in events} == {'"mk1"', '"mk2"', '"mk3"', '"mk4"'}
    timed = [(o.event.summary, o.start) for o in expand(events, *WEEK) if not o.event.all_day]
    assert timed == [
        ("Standup", datetime(2026, 11, 16, 9, 15, tzinfo=VIENNA)),
        ("Call with NY dentist", datetime(2026, 11, 17, 15, 0, tzinfo=VIENNA)),  # TZID New York
        ("Standup (moved)", datetime(2026, 11, 18, 11, 0, tzinfo=VIENNA)),  # override
    ]  # Friday's standup is an EXDATE
    all_day = {e.summary: e for e in events if e.all_day}
    for summary, day in (("Day off", date(2026, 11, 19)), ("Anna's birthday", date(2026, 11, 21))):
        event = all_day[summary]  # DTEND == DTSTART, and no DTEND: one day each
        assert event.start.date() == day and event.end - event.start == timedelta(days=1)


def test_wrong_password_is_an_auth_error(server: FakeICloud) -> None:
    icloud = connect(server)(APPLE_ID, "my-apple-id-password", ENTRY)
    with pytest.raises(AuthError, match="app-specific password"):
        icloud.list_calendars()
