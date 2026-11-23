from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta

import pytest
from conftest import TODAY

from tcal.model import Calendar, Event
from tcal.quickadd import apply, parse, title_end, to_text
from tcal.tz import local_midnight, local_zone

# TODAY is Wednesday 2026-11-18
NAMES = ["Work", "Personal", "Family"]


def at(day: date, h: int, m: int = 0) -> datetime:
    return datetime.combine(day, time(h, m), local_zone())


def test_full_example() -> None:
    q = parse("Lunch with Anna tomorrow 12:30-13:30 @Cafe Central #Personal", TODAY, NAMES)
    tomorrow = TODAY + timedelta(days=1)
    assert (q.summary, q.location, q.calendar) == ("Lunch with Anna", "Cafe Central", "Personal")
    assert (q.start, q.end, q.all_day) == (at(tomorrow, 12, 30), at(tomorrow, 13, 30), False)


@pytest.mark.parametrize(
    ("text", "start", "end"),
    [
        ("Call 12:30", (12, 30), (13, 30)),
        ("Call 12-13", (12, 0), (13, 0)),
        ("Call 9am", (9, 0), (10, 0)),
        ("Call at 9pm", (21, 0), (22, 0)),
        ("Call 18h", (18, 0), (19, 0)),
        ("Call 18h for 2h", (18, 0), (20, 0)),
        ("Call for 90 min at 10:00", (10, 0), (11, 30)),
        ("Call for 1h30 at 10:00", (10, 0), (11, 30)),
        ("Call from 9-11am", (9, 0), (11, 0)),
        ("Call 11-1pm", (11, 0), (13, 0)),
        ("Call 0:00", (0, 0), (1, 0)),
    ],
)
def test_times(text: str, start: tuple[int, int], end: tuple[int, int]) -> None:
    q = parse(text, TODAY, NAMES)
    assert (q.summary, q.all_day) == ("Call", False)
    assert (q.start, q.end) == (at(TODAY, *start), at(TODAY, *end))


def test_end_before_start_is_next_day() -> None:
    q = parse("Party 22-1", TODAY, NAMES)
    assert (q.start, q.end) == (at(TODAY, 22), at(TODAY + timedelta(days=1), 1))


@pytest.mark.parametrize(
    ("text", "day"),
    [
        ("Trip dec 24", date(2026, 12, 24)),
        ("Trip on fri", date(2026, 11, 20)),
        ("Trip 24.12.", date(2026, 12, 24)),
        ("Trip 2026-12-24", date(2026, 12, 24)),
        ("Trip next week", date(2026, 11, 25)),
        ("Trip +2w", date(2026, 12, 2)),
        ("Trip", TODAY),
    ],
)
def test_no_time_is_all_day(text: str, day: date) -> None:
    q = parse(text, TODAY, NAMES)
    assert (q.summary, q.all_day) == ("Trip", True)
    assert (q.start, q.end) == (local_midnight(day), local_midnight(day + timedelta(days=1)))


def test_date_and_time_in_any_order() -> None:
    q = parse("3pm meet on fri", TODAY, NAMES)
    assert (q.summary, q.start) == ("meet", at(date(2026, 11, 20), 15))


def test_calendar_prefix_and_unknown() -> None:
    assert parse("x #fa", TODAY, NAMES).calendar == "Family"
    assert parse("x #WORK", TODAY, NAMES).calendar == "Work"
    q = parse("x #zz", TODAY, NAMES)
    assert (q.calendar, q.error, q.summary) == (None, "No calendar “zz”", "x")
    assert parse("x", TODAY, NAMES).calendar is None


@pytest.mark.parametrize(
    ("text", "first", "last"),
    [
        ("Trip dec 3 - dec 5", date(2026, 12, 3), date(2026, 12, 5)),
        ("Workshop 1.12.-3.12.", date(2026, 12, 1), date(2026, 12, 3)),
        ("Trip dec 30 – jan 2", date(2026, 12, 30), date(2027, 1, 2)),
        ("Trip dec 3-5", date(2026, 12, 3), date(2026, 12, 5)),
        ("Trip 3-5 dec", date(2026, 12, 3), date(2026, 12, 5)),
        ("Trip Mon-Fri", date(2026, 11, 23), date(2026, 11, 27)),
    ],
)
def test_date_range_is_multi_day_all_day(text: str, first: date, last: date) -> None:
    q = parse(text, TODAY, NAMES)
    assert (q.summary, q.all_day) == (text.split()[0], True)
    assert (q.start, q.end) == (local_midnight(first), local_midnight(last + timedelta(1)))


def test_date_range_with_times() -> None:
    q = parse("Conf dec 3 - dec 5 9:00-17:00", TODAY, NAMES)
    assert (q.summary, q.start, q.end) == (
        "Conf",
        at(date(2026, 12, 3), 9),
        at(date(2026, 12, 5), 17),
    )


def test_next_weekday_and_in_n_days() -> None:
    q = parse("Review next friday 10:00", TODAY, NAMES)
    assert (q.summary, q.start) == ("Review", at(date(2026, 11, 27), 10))
    q = parse("Doctor in 2 days 9:00", TODAY, NAMES)
    assert (q.summary, q.start) == ("Doctor", at(date(2026, 11, 20), 9))


def test_plain_words_stay_in_summary() -> None:
    q = parse("mail bob@x.com for the win", TODAY, NAMES)
    assert (q.summary, q.location, q.all_day) == ("mail bob@x.com for the win", "", True)


@pytest.mark.parametrize(
    ("text", "summary", "start", "rrule"),
    [
        ("Yoga every monday 18:00", "Yoga", at(date(2026, 11, 23), 18), "FREQ=WEEKLY;BYDAY=MO"),
        ("Gym every tue 7am", "Gym", at(date(2026, 11, 24), 7), "FREQ=WEEKLY;BYDAY=TU"),
        ("Standup daily 9:00", "Standup", at(TODAY, 9), "FREQ=DAILY"),
        ("Sync weekly 10:00", "Sync", at(TODAY, 10), "FREQ=WEEKLY"),
        ("Bills every month 8:00", "Bills", at(TODAY, 8), "FREQ=MONTHLY"),
        ("Standup every weekday 9", "Standup", at(TODAY, 9), "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"),
        (
            "Run every weekday sat 7:00",
            "Run",
            at(date(2026, 11, 23), 7),
            "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR",
        ),
        ("Standup weekdays 9:00", "Standup", at(TODAY, 9), "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"),
        (
            "Yoga every monday and wednesday 7am",
            "Yoga",
            at(TODAY, 7),
            "FREQ=WEEKLY;BYDAY=MO,WE",
        ),
        (
            "Yoga every mon and wed 7am",
            "Yoga",
            at(TODAY, 7),
            "FREQ=WEEKLY;BYDAY=MO,WE",
        ),
        ("Gym every tue, thu 18:00", "Gym", at(date(2026, 11, 19), 18), "FREQ=WEEKLY;BYDAY=TU,TH"),
    ],
)
def test_repeats(text: str, summary: str, start: datetime, rrule: str) -> None:
    q = parse(text, TODAY, NAMES)
    assert (q.summary, q.start, q.rrule) == (summary, start, rrule)


@pytest.mark.parametrize(
    ("text", "summary"),
    [
        ("Daily standup 9:00", "Daily standup"),
        ("Weekly review fri 16:00", "Weekly review"),
        ("Monthly report dec 1", "Monthly report"),
        ("Every day counts", "Every day counts"),
    ],
)
def test_a_leading_repeat_word_is_the_title(text: str, summary: str) -> None:
    q = parse(text, TODAY, NAMES)
    assert (q.summary, q.rrule) == (summary, None)


def test_a_repeat_after_a_leading_repeat_word_counts() -> None:
    q = parse("Weekly sync weekly mon 10:00", TODAY, NAMES)
    assert (q.summary, q.start, q.rrule) == (
        "Weekly sync",
        at(date(2026, 11, 23), 10),
        "FREQ=WEEKLY",
    )


def test_tonight_is_today() -> None:
    q = parse("Movie tonight 8pm", TODAY, NAMES)
    assert (q.summary, q.start) == ("Movie", at(TODAY, 20))


def test_every_without_a_unit_stays_in_summary() -> None:
    q = parse("Talk every other thing", TODAY, NAMES)
    assert (q.summary, q.rrule) == ("Talk every other thing", None)
    assert q.warnings == ("“every other” not understood (kept as text)",)


@pytest.mark.parametrize(
    ("text", "summary", "start"),
    [
        ("Meet tomorrow 9", "Meet", at(TODAY + timedelta(1), 9)),
        ("Meet fri at 14", "Meet", at(date(2026, 11, 20), 14)),
        ("Doctor 14.30", "Doctor", at(TODAY, 14, 30)),
        ("Doctor tomorrow 10.10", "Doctor", at(TODAY + timedelta(1), 10, 10)),
        ("Lunch at noon", "Lunch", at(TODAY, 12)),
        ("Release midnight", "Release", at(TODAY, 0)),
    ],
)
def test_more_time_forms(text: str, summary: str, start: datetime) -> None:
    q = parse(text, TODAY, NAMES)
    assert (q.summary, q.start, q.all_day) == (summary, start, False)


def test_ambiguous_dot_and_bare_numbers_stay_dates_or_words() -> None:
    q = parse("Trip 12.11", TODAY, NAMES)
    assert (q.start, q.all_day) == (local_midnight(date(2026, 11, 12)), True)
    assert parse("Read 3 books", TODAY, NAMES).summary == "Read 3 books"


def until(day: date) -> str:
    """UNTIL of a timed series whose last day is ``day``."""
    last = local_midnight(day + timedelta(1)) - timedelta(seconds=1)
    return f"UNTIL={last.astimezone(UTC):%Y%m%dT%H%M%SZ}"


@pytest.mark.parametrize(
    ("text", "rrule"),
    [
        ("x 9:00 every other week", "FREQ=WEEKLY;INTERVAL=2"),
        ("x 9:00 every 2 weeks on mon, wed", "FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,WE"),
        ("x 9:00 every 3 months 5 times", "FREQ=MONTHLY;INTERVAL=3;COUNT=5"),
        ("x 9:00 daily until 24.12.", f"FREQ=DAILY;{until(date(2026, 12, 24))}"),
        ("x 9:00 every week until dec", f"FREQ=WEEKLY;{until(date(2026, 12, 31))}"),
        ("x 9:00 every week until mar 3", f"FREQ=WEEKLY;{until(date(2027, 3, 3))}"),
        ("x every year until 1.1.2030", "FREQ=YEARLY;UNTIL=20300101"),
        ("x 9:00 no repeat", None),
    ],
)
def test_intervals_and_ends(text: str, rrule: str | None) -> None:
    q = parse(text, TODAY, NAMES)
    assert (q.summary, q.rrule, q.error) == ("x", rrule, "")


def test_a_series_cannot_end_before_it_starts() -> None:
    assert parse("x daily until 3.3.2020", TODAY, NAMES).error.startswith("The series can't end")


@pytest.mark.parametrize(
    ("text", "start", "minutes"),
    [
        ("x 2h fri 18:00", 18, 120),
        ("x 18h 2h", 18, 120),
        ("x 9:00 8h", 9, 480),
        ("x 10:00 1.5h", 10, 90),
        ("x 10:00 90m", 10, 90),
        ("x 18h", 18, 60),
    ],
)
def test_a_duration_without_for(text: str, start: int, minutes: int) -> None:
    q = parse(text, TODAY, NAMES)
    assert (q.summary, q.start.hour, q.end - q.start) == ("x", start, timedelta(minutes=minutes))


def test_all_day_notes_and_literals() -> None:
    q = parse("Offsite fri all day // bring #laptop 9:00", TODAY, NAMES)
    assert (q.summary, q.all_day, q.notes) == ("Offsite", True, "bring #laptop 9:00")
    assert parse("see https://x.org 9:00", TODAY, NAMES).notes is None
    q = parse('"Issue #12 at 9:00" fri 10:00 @"Room 5-7"', TODAY, NAMES)
    assert (q.summary, q.start) == ("Issue #12 at 9:00", at(date(2026, 11, 20), 10))
    assert q.location == "Room 5-7"
    assert parse('Read "Dune 12:30" fri', TODAY, NAMES).summary == 'Read "Dune 12:30"'


def test_a_weekday_before_a_date_is_ignored() -> None:
    for text in ("x thu 24 dec", "x thu dec 24", "x thu 24.12."):
        q = parse(text, TODAY, NAMES)
        assert (q.summary, q.start) == ("x", local_midnight(date(2026, 12, 24)))


def test_calendar_names_with_spaces_and_exact_before_prefix() -> None:
    names = ["Workout", "Work", "My Work"]
    assert parse("x #work fri", TODAY, names).calendar == "Work"
    q = parse("x #my work fri", TODAY, names)
    assert (q.calendar, q.summary) == ("My Work", "x")


def test_what_looks_like_a_time_is_reported() -> None:
    q = parse("x 25:00 30.2.", TODAY, NAMES)
    assert q.summary == "x 25:00 30.2."
    assert [w.split("”")[0] for w in q.warnings] == ["“25:00", "“30.2."]


def event(**changes) -> Event:
    return replace(Event("u", "work", "Meet", at(TODAY, 10), at(TODAY, 11, 30)), **changes)


def test_the_draft_fills_in_what_is_left_out() -> None:
    draft = event()
    q = parse("x", TODAY, NAMES, draft)
    assert (q.start, q.end, q.has_date, q.has_time) == (draft.start, draft.end, False, False)
    q = parse("x fri", TODAY, NAMES, draft)
    friday = date(2026, 11, 20)
    assert (q.start, q.end) == (at(friday, 10), at(friday, 11, 30))
    q = parse("x 14:00", TODAY, NAMES, draft)
    assert (q.start, q.end) == (at(TODAY, 14), at(TODAY, 15, 30))
    q = parse("x 2h", TODAY, NAMES, draft)
    assert (q.start, q.end) == (at(TODAY, 10), at(TODAY, 12))
    assert parse("x all day", TODAY, NAMES, draft).all_day
    assert parse("x dec 3-5", TODAY, NAMES, draft).all_day


MIDNIGHT = local_midnight(TODAY)


@pytest.mark.parametrize(
    "changes",
    [
        {},
        {"summary": "Issue #12 at 12:30"},
        {"summary": '"Dune"'},
        {"summary": 'a "b" c fri'},
        {"summary": "Weekly review every day"},
        {"location": "Cafe Central"},
        {"location": "Room 10:30"},
        {"description": "one line // two"},
        {"end": at(TODAY + timedelta(1), 2)},
        {"end": at(TODAY + timedelta(2), 12)},
        {"end": at(TODAY, 10)},
        {"start": at(date(2027, 1, 2), 9), "end": local_midnight(date(2027, 1, 3))},
        {"start": MIDNIGHT, "end": MIDNIGHT + timedelta(1), "all_day": True},
        {"start": MIDNIGHT, "end": MIDNIGHT + timedelta(3), "all_day": True},
        {"rrule": f"FREQ=WEEKLY;BYDAY=MO,WE;{until(date(2026, 12, 31))}"},
        {"rrule": f"FREQ=DAILY;{until(date(2027, 3, 1))}"},
        {"rrule": "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"},
        {"rrule": "FREQ=WEEKLY;INTERVAL=2;BYDAY=WE"},
        {"rrule": "FREQ=YEARLY"},
        {"rrule": "FREQ=MONTHLY;BYDAY=3WE;COUNT=4"},  # no words for it: the draft's
    ],
)
def test_to_text_round_trips(changes: dict) -> None:
    ev = event(**changes)
    text = to_text(ev, TODAY, "Work")
    q = parse(text, TODAY, NAMES, ev)
    assert (q.summary, q.location, q.calendar) == (ev.summary, ev.location, "Work"), text
    assert (q.start, q.end, q.all_day) == (ev.start, ev.end, ev.all_day), text
    assert (q.rrule, q.notes or "") == (ev.rrule, ev.description), text
    assert (q.warnings, q.error) == ((), "")


def test_to_text_wording() -> None:
    ev = event(location="Cafe", rrule="FREQ=WEEKLY;BYDAY=WE;COUNT=5", description="hi")
    line = "Meet wed 18 nov 10:00-11:30 every wed 5 times #Work @Cafe // hi"
    assert to_text(ev, TODAY, "Work") == line
    assert title_end(line, ev) == 4
    quoted = event(summary="Issue #12")
    assert title_end(to_text(quoted, TODAY), quoted) == len('"Issue #12')


def test_apply_keeps_what_the_text_did_not_change() -> None:
    calendars = [Calendar("work", "Work", "#000000"), Calendar("p", "Personal", "#000000")]
    ev = event(
        start=datetime(2026, 11, 18, 9, tzinfo=UTC),
        end=datetime(2026, 11, 18, 10, tzinfo=UTC),
        location="Cafe\nMain St 1",
        description="two\nlines",
        rrule="FREQ=MONTHLY;BYDAY=3WE",
        raw="raw",
    )
    text = to_text(ev, TODAY, "Work")
    shown = parse(text, TODAY, NAMES, ev)
    assert apply(ev, shown, shown, calendars) == ev

    def edit(line: str) -> Event:
        return apply(ev, parse(line, TODAY, NAMES, ev), shown, calendars)

    renamed = edit(text.replace("Meet", "Met"))
    assert renamed == replace(ev, summary="Met") and renamed.start.tzinfo is UTC
    assert renamed.raw == "raw"
    assert edit(text.replace("#Work", "#pers")).calendar_id == "p"
    assert edit(text.replace("#Work", "")).calendar_id == "work"
    assert edit(text + " // one").description == "one"
    assert edit(text + " //").description == ""
    assert edit(text.replace("#Work", "no repeat")).rrule is None
    assert edit(text.replace("#Work", "3 times")).rrule == "FREQ=MONTHLY;BYDAY=3WE;COUNT=3"
    assert edit("Meet").location == ""


def test_an_instance_keeps_its_calendar_and_has_no_rule() -> None:
    ev = event(recurrence_id=at(TODAY, 10))
    shown = parse(to_text(ev, TODAY), TODAY, NAMES, ev)
    q = parse("Meet 12:00 every day #pers", TODAY, NAMES, ev)
    changed = apply(ev, q, shown, [Calendar("p", "Personal", "#000000")])
    assert (changed.calendar_id, changed.rrule, changed.start) == ("work", None, at(TODAY, 12))


@pytest.mark.parametrize(
    "text",
    [
        "x +99999y",
        "x 31.12.9999 - fri every mon",
        "x daily until dec 0000",
        "x daily until +9999y",
        "x for 99999999999h 10:00",
        "x 99999999999 min 10:00",
        "x every 99999999 weeks",
        'x " @ # // "',
        "x ²h 24:00 9-25 13pm",
    ],
)
@pytest.mark.parametrize("draft", [None, event()])
def test_nonsense_never_crashes(text: str, draft: Event | None) -> None:
    q = parse(text, TODAY, NAMES, draft)
    assert q.summary.startswith("x") and q.start.year in (2026, 2027)
