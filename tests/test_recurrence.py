from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from test_ics import SERIES

from tcal.ics import from_ics
from tcal.model import Event
from tcal.recurrence import expand
from tcal.tz import local_midnight

VIENNA = ZoneInfo("Europe/Vienna")
NOV = (datetime(2026, 11, 1, tzinfo=VIENNA), datetime(2026, 12, 1, tzinfo=VIENNA))


def _starts(events: list[Event], lo: datetime, hi: datetime) -> list[tuple[str, datetime]]:
    return [(o.summary, o.start.astimezone(VIENNA)) for o in expand(events, lo, hi)]


def test_weekly_with_exdate_and_override() -> None:
    at9 = lambda d: datetime(2026, 11, d, 9, 0, tzinfo=VIENNA)  # noqa: E731
    assert _starts(from_ics(SERIES, "cal"), *NOV) == [
        ("Weekly", at9(2)),
        # 9th: EXDATE
        ("Weekly (moved)", datetime(2026, 11, 16, 14, 0, tzinfo=VIENNA)),
        ("Weekly", at9(23)),
        ("Weekly", at9(30)),
    ]


def test_override_moved_into_range_replaces_instance_outside() -> None:
    master, override = from_ics(SERIES, "cal")
    lo = datetime(2026, 11, 16, 12, 0, tzinfo=VIENNA)
    hi = datetime(2026, 11, 17, tzinfo=VIENNA)
    assert _starts([master, override], lo, hi) == [("Weekly (moved)", override.start)]
    # The original 09:00 slot is not drawn even if only it is in range.
    assert expand([master, override], NOV[0].replace(day=16, hour=8), lo) == []


def test_wall_clock_kept_across_dst() -> None:
    start = datetime(2026, 10, 20, 9, 0, tzinfo=VIENNA)  # CEST
    event = Event("d", "cal", "Daily", start, start + timedelta(hours=1), rrule="FREQ=WEEKLY")
    occs = expand([event], start, datetime(2026, 11, 4, tzinfo=VIENNA))
    assert [o.start.astimezone(VIENNA).hour for o in occs] == [9, 9, 9]  # 27 Oct is CET


def test_until_and_count() -> None:
    start = datetime(2026, 11, 2, 9, 0, tzinfo=VIENNA)
    end = start + timedelta(hours=1)
    until_date = Event("a", "cal", "A", start, end, rrule="FREQ=WEEKLY;UNTIL=20261116")
    until_utc = Event("b", "cal", "B", start, end, rrule="FREQ=WEEKLY;UNTIL=20261109T080000Z")
    count = Event("c", "cal", "C", start, end, rrule="FREQ=DAILY;COUNT=3")
    assert len(expand([until_date], *NOV)) == 3  # 2, 9, 16 (the UNTIL day is included)
    assert len(expand([until_utc], *NOV)) == 2
    assert len(expand([count], *NOV)) == 3


def test_all_day_and_multi_day() -> None:
    day = date(2026, 11, 18)
    bday = Event(
        "b",
        "cal",
        "Birthday",
        local_midnight(day),
        local_midnight(day + timedelta(1)),
        all_day=True,
        rrule="FREQ=YEARLY",
    )
    trip = Event(
        "t", "cal", "Trip", local_midnight(day), local_midnight(day + timedelta(3)), all_day=True
    )
    next_year = expand(
        [bday], local_midnight(date(2027, 11, 18)), local_midnight(date(2027, 11, 19))
    )
    assert [o.start for o in next_year] == [local_midnight(date(2027, 11, 18))]
    # A multi-day event shows on its later days, but not the day after it ends.
    third = local_midnight(day + timedelta(2))
    assert [o.summary for o in expand([trip], third, third + timedelta(days=1))] == ["Trip"]
    after = local_midnight(day + timedelta(3))
    assert expand([trip], after, after + timedelta(days=1)) == []


def test_non_recurring_overlap_and_zero_length() -> None:
    start = datetime(2026, 11, 18, 10, 0, tzinfo=VIENNA)
    long = Event("l", "cal", "Long", start - timedelta(days=1), start + timedelta(hours=1))
    point = Event("p", "cal", "Reminder", start, start)
    lo, hi = start, start + timedelta(hours=2)
    assert [o.summary for o in expand([point, long], lo, hi)] == ["Long", "Reminder"]
    assert expand([point], lo - timedelta(hours=1), lo) == []
