"""iCloud (or any CalDAV server) as a Provider, via the ``caldav`` library's client.

Discovery (principal -> calendar home, incl. iCloud's per-user host) is left
to ``caldav``; the requests themselves are plain WebDAV so etags are under our
control: PUT with If-None-Match/If-Match, DELETE with If-Match, and a 412
answer becomes a ConflictError. Calendar ids are the collections' URLs.
"""

import logging
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote, urljoin

from caldav.davclient import DAVClient

from tcal import ics
from tcal.model import Calendar, Event
from tcal.providers.base import ConflictError, ProviderError

log = logging.getLogger(__name__)

ICLOUD_URL = "https://caldav.icloud.com"
DEFAULT_COLOR = "#5E81AC"
NS = {"d": "DAV:", "c": "urn:ietf:params:xml:ns:caldav", "a": "http://apple.com/ns/ical/"}
WRITE_PRIVILEGES = {"{DAV:}write", "{DAV:}write-content", "{DAV:}all"}

PROPFIND_CALENDARS = """<?xml version="1.0" encoding="utf-8"?>
<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"
            xmlns:a="http://apple.com/ns/ical/">
  <d:prop>
    <d:resourcetype/><d:displayname/><d:current-user-privilege-set/>
    <c:supported-calendar-component-set/><a:calendar-color/><a:calendar-order/>
  </d:prop>
</d:propfind>"""

REPORT_EVENTS = """<?xml version="1.0" encoding="utf-8"?>
<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
  <d:prop><d:getetag/><c:calendar-data/></d:prop>
  <c:filter>
    <c:comp-filter name="VCALENDAR">
      <c:comp-filter name="VEVENT"><c:time-range start="{start}" end="{end}"/></c:comp-filter>
    </c:comp-filter>
  </c:filter>
</c:calendar-query>"""


class ICloudProvider:
    def __init__(self, client: Any, home_url: str | None = None) -> None:
        """``client``: a ``caldav.DAVClient`` (or a test double with the same
        propfind/report/put/delete); ``home_url`` is discovered when omitted."""
        self.client = client
        self._home_url = home_url

    @classmethod
    def connect(cls, apple_id: str, password: str, url: str = ICLOUD_URL) -> "ICloudProvider":
        """No network yet: the first request discovers the calendar home."""
        return cls(DAVClient(url=url, username=apple_id, password=password))

    @property
    def home_url(self) -> str:
        if self._home_url is None:
            self._home_url = str(self.client.principal().calendar_home_set.url)
        return self._home_url

    def list_calendars(self) -> list[Calendar]:
        response = self.client.propfind(self.home_url, props=PROPFIND_CALENDARS, depth=1)
        _check(response, "PROPFIND", self.home_url, ok=(207,))
        found: list[tuple[int, Calendar]] = []
        for resp in response.tree.iterfind("d:response", NS):
            if resp.find(".//d:resourcetype/c:calendar", NS) is None:
                continue  # the home itself, inbox/outbox, ...
            comps = {
                c.get("name")
                for c in resp.iterfind(".//c:supported-calendar-component-set/c:comp", NS)
            }
            if comps and "VEVENT" not in comps:
                continue  # reminders lists
            href = urljoin(self.home_url, resp.findtext("d:href", "", NS))
            privileges = {
                p.tag for p in resp.iterfind(".//d:current-user-privilege-set/d:privilege/*", NS)
            }
            calendar = Calendar(
                id=href,
                name=resp.findtext(".//d:displayname", "", NS)
                or href.rstrip("/").rsplit("/", 1)[-1],
                color=(resp.findtext(".//a:calendar-color", "", NS) or DEFAULT_COLOR)[:7],
                readonly=bool(privileges) and not privileges & WRITE_PRIVILEGES,
            )
            order = resp.findtext(".//a:calendar-order", "", NS)
            found.append((int(order) if order.isdigit() else len(found), calendar))
        return [c for _, c in sorted(found, key=lambda pair: pair[0])]

    def fetch_events(self, calendar: Calendar, start: datetime, end: datetime) -> list[Event]:
        query = REPORT_EVENTS.format(start=_utc(start), end=_utc(end))
        response = self.client.report(calendar.id, query, depth=1)
        _check(response, "REPORT", calendar.id, ok=(207,))
        events: list[Event] = []
        for resp in response.tree.iterfind("d:response", NS):
            data = resp.findtext(".//c:calendar-data", "", NS)
            if not data:
                continue
            href = urljoin(calendar.id, resp.findtext("d:href", "", NS))
            try:
                events += ics.from_ics(
                    data, calendar.id, href, resp.findtext(".//d:getetag", None, NS)
                )
            except (ValueError, KeyError) as e:
                log.warning("skipping unreadable event %s: %s", href, e)
        return events

    def create_event(self, event: Event) -> Event:
        href = urljoin(event.calendar_id.rstrip("/") + "/", quote(event.uid, safe="") + ".ics")
        return self._put(replace(event, href=href), {"If-None-Match": "*"})

    def update_event(self, event: Event) -> Event:
        return self._put(event, {"If-Match": event.etag} if event.etag else {})

    def delete_event(self, event: Event) -> None:
        if not event.href:
            return
        headers = {"If-Match": event.etag} if event.etag else {}
        response = self.client.delete(event.href, headers=headers)
        if response.status != 404:  # already gone is fine
            _check(response, "DELETE", event.href, ok=(200, 204))

    def _put(self, event: Event, headers: dict[str, str]) -> Event:
        assert event.href
        data = ics.to_ics(event)
        headers = {"Content-Type": "text/calendar; charset=utf-8", **headers}
        response = self.client.put(event.href, data, headers=headers)
        _check(response, "PUT", event.href, ok=(200, 201, 204))
        return replace(event, etag=response.headers.get("ETag"), raw=data)


def _check(response: Any, method: str, url: str, ok: tuple[int, ...]) -> None:
    if response.status == 412:
        raise ConflictError(f"{method} {url}: precondition failed (etag)")
    if response.status not in ok:
        raise ProviderError(f"{method} {url}: HTTP {response.status}")


def _utc(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
