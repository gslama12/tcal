"""Read-only provider for subscribed iCalendar feeds (``[[subscription]]`` in the config).

Each feed is one calendar (id ``SUBSCRIPTION_PREFIX + url``). A feed is a single
file holding many events; it is split into one resource per UID (with the feed's
VTIMEZONEs) so each cached event's ``raw`` stays small.
"""

import gzip
import urllib.request
from collections.abc import Callable, Sequence
from datetime import datetime

import icalendar

from tcal import ics
from tcal.config import SubscriptionConfig
from tcal.model import SUBSCRIPTION_PREFIX, Calendar, Event
from tcal.providers.base import ProviderError

TIMEOUT = 30  # seconds

Fetch = Callable[[str], bytes]


def http_get(url: str) -> bytes:
    """The body of ``url``, un-gzipped (Apple's holiday feeds are gzip without saying so)."""
    request = urllib.request.Request(url, headers={"User-Agent": "tcal", "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        body: bytes = response.read()
    return gzip.decompress(body) if body[:2] == b"\x1f\x8b" else body


class IcsUrlProvider:
    def __init__(
        self, subscriptions: Sequence[SubscriptionConfig], fetch: Fetch = http_get
    ) -> None:
        self.subscriptions = list(subscriptions)
        self.fetch = fetch

    def list_calendars(self) -> list[Calendar]:
        return [
            Calendar(SUBSCRIPTION_PREFIX + s.url, s.name, s.color, readonly=True)
            for s in self.subscriptions
        ]

    def fetch_events(self, calendar: Calendar, start: datetime, end: datetime) -> list[Event]:
        """The feed's events that may occur in [start, end) (series with any of their overrides)."""
        url = calendar.id.removeprefix(SUBSCRIPTION_PREFIX)
        try:
            feed = icalendar.Calendar.from_ical(self.fetch(url))
        except ValueError as e:
            raise ProviderError(f"{calendar.name}: not an iCalendar feed ({e})") from None
        events = []
        for text in split_feed(feed):
            group = ics.from_ics(text, calendar.id)
            if any(e.rrule or e.recurrence_id or (e.start < end and e.end > start) for e in group):
                events.extend(group)
        return events

    def create_event(self, event: Event) -> Event:
        raise ProviderError("subscribed calendars are read-only")

    def update_event(self, event: Event) -> Event:
        raise ProviderError("subscribed calendars are read-only")

    def delete_event(self, event: Event) -> None:
        raise ProviderError("subscribed calendars are read-only")


def split_feed(feed: icalendar.Calendar) -> list[str]:
    """One iCalendar text per UID: its VEVENTs plus the feed's time zones."""
    zones = list(feed.walk("VTIMEZONE"))
    by_uid: dict[str, icalendar.Calendar] = {}
    for vevent in feed.walk("VEVENT"):
        uid = str(vevent.get("UID", ""))
        if not uid or "DTSTART" not in vevent:
            continue
        if uid not in by_uid:
            cal = by_uid[uid] = ics.new_calendar()
            for zone in zones:
                cal.add_component(zone)
        by_uid[uid].add_component(vevent)
    return [cal.to_ical().decode() for cal in by_uid.values()]
