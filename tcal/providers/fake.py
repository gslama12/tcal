"""In-memory provider with demo data around a given day, for tests and ``tcal --demo``."""

from dataclasses import replace
from datetime import date, datetime, time, timedelta
from itertools import count
from zoneinfo import ZoneInfo

import icalendar

from tcal import colors, ics
from tcal.model import SUBSCRIPTION_PREFIX, Calendar, Event
from tcal.providers.base import ConflictError
from tcal.tz import local_zone

CALENDARS = [
    Calendar("work", "Work", colors.BLUE),
    Calendar("personal", "Personal", colors.GREEN),
    Calendar("family", "Family", colors.ORANGE),
    Calendar("sport", "Sport", colors.PURPLE),
    Calendar("holidays", "Holidays", colors.RED, readonly=True),
]


NEW_YORK = ZoneInfo("America/New_York")
FEED = Calendar(SUBSCRIPTION_PREFIX + "demo", "Team events", colors.BROWN, readonly=True)


class FakeProvider:
    """Behaves like a CalDAV server: events go through iCalendar text, etags are checked."""

    def __init__(self, today: date | None = None, demo: bool = True) -> None:
        self.calendars = [replace(c) for c in CALENDARS]
        self.events: dict[str, Event] = {}
        self._etags = count(1)
        if demo:
            for event in demo_events(today or date.today()):
                self._store(event, f"fake://{event.uid}")

    def list_calendars(self) -> list[Calendar]:
        return list(self.calendars)

    def fetch_events(self, calendar: Calendar, start: datetime, end: datetime) -> list[Event]:
        """Every VEVENT (master and overrides) of the matching resources."""
        return [
            vevent
            for e in self.events.values()
            if e.calendar_id == calendar.id and (e.rrule or (e.start < end and e.end > start))
            for vevent in ics.from_ics(e.raw or ics.to_ics(e), e.calendar_id, e.href, e.etag)
        ]

    def create_event(self, event: Event) -> Event:
        if event.uid in self.events:
            raise ConflictError(f"{event.uid} exists")
        return self._store(event, f"fake://{event.uid}")

    def update_event(self, event: Event) -> Event:
        self._check_etag(event)
        return self._store(event, self.events[event.uid].href)

    def delete_event(self, event: Event) -> None:
        if event.uid in self.events:
            self._check_etag(event)
            del self.events[event.uid]

    def _check_etag(self, event: Event) -> None:
        current = self.events.get(event.uid)
        if current is None or (event.etag and event.etag != current.etag):
            raise ConflictError(f"{event.uid} changed on the server")

    def _store(self, event: Event, href: str | None) -> Event:
        text = ics.to_ics(event)
        stored = ics.from_ics(text, event.calendar_id, href, str(next(self._etags)))[0]
        self.events[event.uid] = stored
        return stored


def demo_feed(today: date | None = None) -> FakeProvider:
    """A read-only "Other calendars" feed for ``tcal --demo`` (no network)."""
    feed = FakeProvider(demo=False)
    feed.calendars = [replace(FEED)]
    day = today or date.today()

    def at(days: int, hour: int) -> datetime:
        return datetime.combine(day + timedelta(days=days), time(hour), local_zone())

    for uid, summary, start, hours, all_day in (
        ("feed-1", "Team lunch", at(1, 12), 1, False),
        ("feed-2", "Office party", at(6, 17), 3, False),
        ("feed-3", "Hackathon", at(8, 0), 48, True),
    ):
        event = Event(uid, FEED.id, summary, start, start + timedelta(hours=hours), all_day=all_day)
        feed._store(event, f"fake://{uid}")
    return feed


def with_extras(
    event: Event,
    organizer: str = "",
    attendees: tuple[tuple[str, str], ...] = (),
    url: str = "",
    alarms: tuple[timedelta, ...] = (),
) -> Event:
    """``event`` with organizer/attendees (name, PARTSTAT), URL and alarms in its ``raw``."""
    cal = icalendar.Calendar.from_ical(ics.to_ics(event))
    comp = next(iter(cal.walk("VEVENT")))
    mail = lambda name: f"mailto:{name.split()[0].lower()}@example.com"  # noqa: E731
    if organizer:
        comp.add("ORGANIZER", mail(organizer), parameters={"CN": organizer})
    for name, status in attendees:
        comp.add("ATTENDEE", mail(name), parameters={"CN": name, "PARTSTAT": status})
    if url:
        comp.add("URL", url)
    for trigger in alarms:
        alarm = icalendar.Alarm()
        alarm.add("ACTION", "DISPLAY")
        alarm.add("TRIGGER", trigger)
        comp.add_component(alarm)
    return replace(event, raw=cal.to_ical().decode())


def demo_events(today: date) -> list[Event]:
    tz = local_zone()
    monday = today - timedelta(days=today.weekday())
    uids = count(1)

    def at(day: date, hhmm: str) -> datetime:
        hours, minutes = map(int, hhmm.split(":"))
        return datetime.combine(day, time(hours, minutes), tz)

    def timed(
        cal: str,
        summary: str,
        day: date,
        start: str,
        end: str,
        location: str = "",
        description: str = "",
        rrule: str | None = None,
    ) -> Event:
        return Event(
            f"demo-{next(uids)}",
            cal,
            summary,
            at(day, start),
            at(day, end),
            location=location,
            description=description,
            rrule=rrule,
        )

    def all_day(cal: str, summary: str, day: date, days: int = 1) -> Event:
        start = at(day, "00:00")
        return Event(
            f"demo-{next(uids)}", cal, summary, start, start + timedelta(days=days), all_day=True
        )

    d = timedelta
    return [
        # recurring
        timed(
            "work", "Standup", monday, "09:00", "09:15", rrule="FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"
        ),
        timed("sport", "Gym", monday + d(1), "18:00", "19:30", rrule="FREQ=WEEKLY;BYDAY=TU,TH"),
        timed("family", "Call mum", monday + d(6), "11:00", "11:30", rrule="FREQ=WEEKLY"),
        # overlapping timed events today
        timed("work", "Design review", today, "10:00", "11:30", location="Room 4"),
        timed("work", "1:1 with Alex", today, "10:30", "11:00"),
        with_extras(
            timed("personal", "Dentist", today, "11:00", "12:00", location="Dr. Huber"),
            alarms=(timedelta(hours=-1),),
        ),
        timed("personal", "Early run", today, "05:45", "06:30"),
        timed("family", "Dinner", today, "19:00", "21:00", description="Book a table"),
        timed("personal", "Late movie", today, "22:30", "23:59"),
        # the rest of the week and around
        timed("work", "Sprint planning", monday, "13:00", "15:00"),
        timed("work", "Release", monday + d(3), "14:00", "16:00"),
        timed("work", "Interview", monday + d(3), "14:30", "15:30"),
        timed("personal", "Haircut", today + d(2), "08:00", "08:45"),
        timed("work", "Quarterly review", today + d(9), "09:30", "12:00"),
        # an invitation, and a call set in another time zone
        with_extras(
            timed("work", "Budget planning", today - d(1), "15:00", "16:00", location="Room 2"),
            organizer="Maria Lang",
            attendees=(
                ("Maria Lang", "ACCEPTED"),
                ("Tom Weber", "TENTATIVE"),
                ("Lisa Brandt", "DECLINED"),
                ("Alex Kim", "NEEDS-ACTION"),
            ),
            url="https://meet.example.com/budget",
            alarms=(timedelta(minutes=-10),),
        ),
        Event(
            f"demo-{next(uids)}",
            "work",
            "Call with New York",
            datetime.combine(today + d(2), time(9), NEW_YORK),
            datetime.combine(today + d(2), time(9, 30), NEW_YORK),
        ),
        timed("family", "Kids' play", today - d(5), "17:00", "18:00"),
        # all-day and multi-day
        all_day("family", "Anna's birthday", today),
        all_day("personal", "Deadline: taxes", today + d(1)),
        all_day("work", "Conference", monday + d(2), days=3),
        all_day("family", "Ski trip", today + d(12), days=5),
        all_day("holidays", "Public holiday", today + d(16)),
    ]
