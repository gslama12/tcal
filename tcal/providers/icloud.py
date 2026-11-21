"""iCloud (or any CalDAV server) as a Provider, via the ``caldav`` library's client.

Discovery is left to ``caldav``: PROPFIND current-user-principal on
caldav.icloud.com, then the calendar-home-set, which on iCloud lives on the
account's partition host (``https://pNN-caldav.icloud.com:443/<dsid>/calendars/``).
The requests themselves are plain WebDAV so etags are under our control: PUT
with If-None-Match/If-Match, DELETE with If-Match, and a 412 answer becomes a
ConflictError. Calendar ids and event hrefs are absolute URLs on the home's
host (iCloud sometimes answers with hrefs on caldav.icloud.com; they are
rebased so ids stay stable). See docs/PLAN.md "iCloud notes".
"""

import logging
import re
from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import datetime, timedelta
from functools import partial
from typing import Any, TypeVar
from urllib.parse import quote, urljoin, urlsplit

from caldav.davclient import DAVClient
from caldav.lib.error import AuthorizationError, DAVError
from lxml import etree

from tcal import ics
from tcal.model import Calendar, Event
from tcal.providers.base import AuthError, ConflictError, ProviderError
from tcal.tz import utc_stamp

log = logging.getLogger(__name__)

ICLOUD_URL = "https://caldav.icloud.com"
DEFAULT_COLOR = "#5E81AC"
TIMEOUT = 60  # seconds; caldav's default of 10 is short for a big calendar's REPORT
CHUNK = timedelta(days=92)  # one REPORT per ~quarter keeps answers of large calendars small
NS = {"d": "DAV:", "c": "urn:ietf:params:xml:ns:caldav", "a": "http://apple.com/ns/ical/"}
WRITE_PRIVILEGES = {"{DAV:}write", "{DAV:}write-content", "{DAV:}all"}
_COLOR = re.compile(r"#([0-9a-fA-F]{6})([0-9a-fA-F]{2})?|#([0-9a-fA-F]{3})")

PROPFIND_CALENDARS = """<?xml version="1.0" encoding="utf-8"?>
<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"
            xmlns:a="http://apple.com/ns/ical/">
  <d:prop>
    <d:resourcetype/><d:displayname/><d:current-user-privilege-set/>
    <c:supported-calendar-component-set/><a:calendar-color/><a:calendar-order/>
  </d:prop>
</d:propfind>"""

PROPFIND_ETAG = """<?xml version="1.0" encoding="utf-8"?>
<d:propfind xmlns:d="DAV:"><d:prop><d:getetag/></d:prop></d:propfind>"""

REPORT_EVENTS = """<?xml version="1.0" encoding="utf-8"?>
<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
  <d:prop><d:getetag/><c:calendar-data/></d:prop>
  <c:filter>
    <c:comp-filter name="VCALENDAR">
      <c:comp-filter name="VEVENT"><c:time-range start="{start}" end="{end}"/></c:comp-filter>
    </c:comp-filter>
  </c:filter>
</c:calendar-query>"""

T = TypeVar("T")


class ICloudProvider:
    def __init__(self, client: Any, home_url: str | None = None) -> None:
        """``client``: a ``caldav.DAVClient`` (or a test double with the same
        principal/propfind/report/put/delete); ``home_url`` is discovered when omitted."""
        self.client = client
        self._home_url = home_url

    @classmethod
    def connect(cls, apple_id: str, password: str, url: str = ICLOUD_URL) -> "ICloudProvider":
        """No network yet: the first request discovers the calendar home."""
        return cls(DAVClient(url=url, username=apple_id, password=password, timeout=TIMEOUT))

    @property
    def principal_url(self) -> str:
        """The signed-in user's principal (the first request, so it checks the login)."""
        return str(_call("principal discovery", lambda: self.client.principal().url))

    @property
    def home_url(self) -> str:
        """The calendar home (discovered once: principal -> calendar-home-set)."""
        if self._home_url is None:
            home = _call("discovery", lambda: self.client.principal().calendar_home_set.url)
            self._home_url = _normalize(str(home).rstrip("/") + "/")
        return self._home_url

    def list_calendars(self) -> list[Calendar]:
        home = self.home_url
        response = _call("PROPFIND", lambda: self.client.propfind(home, PROPFIND_CALENDARS, 1))
        _check(response, "PROPFIND", home, ok=(207,))
        found = [
            c for resp in response.tree.iterfind("d:response", NS) if (c := self._calendar(resp))
        ]
        found.sort(key=lambda c: c[0])  # stable: unordered ones keep server order
        return [calendar for _, calendar in found]

    def _calendar(self, resp: Any) -> tuple[tuple[int, int], Calendar] | None:
        """(sort key from calendar-order, calendar) of a PROPFIND <response>, or None
        for collections that aren't event calendars."""
        prop = _props(resp)
        if prop.find("d:resourcetype/c:calendar", NS) is None:
            return None  # the home itself, inbox/outbox, notifications, subscriptions
        comps = {
            c.get("name") for c in prop.iterfind("c:supported-calendar-component-set/c:comp", NS)
        }
        if comps and "VEVENT" not in comps:
            return None  # reminders lists
        href = self._url(resp.findtext("d:href", "", NS))
        privileges = {
            p.tag for p in prop.iterfind("d:current-user-privilege-set/d:privilege/*", NS)
        }
        calendar = Calendar(
            id=href,
            name=(prop.findtext("d:displayname", "", NS) or "").strip()
            or href.rstrip("/").rsplit("/", 1)[-1],
            color=_color(prop.findtext("a:calendar-color", "", NS)),
            readonly=bool(privileges) and not privileges & WRITE_PRIVILEGES,
        )
        order = (prop.findtext("a:calendar-order", "", NS) or "").strip()
        return ((0, int(order)) if order.isdigit() else (1, 0)), calendar

    def fetch_events(self, calendar: Calendar, start: datetime, end: datetime) -> list[Event]:
        """Every resource with an instance in [start, end), queried one quarter at a time.

        No <c:expand>: the server returns whole resources (master + overrides),
        which ``recurrence.expand`` expands; a series met in several quarters is kept once.
        """
        seen: dict[str, list[Event]] = {}
        for lo, hi in _chunks(start, end):
            query = REPORT_EVENTS.format(start=utc_stamp(lo), end=utc_stamp(hi))
            response = _call("REPORT", partial(self.client.report, calendar.id, query, 1))
            _check(response, "REPORT", calendar.id, ok=(207,))
            for resp in response.tree.iterfind("d:response", NS):
                href = self._url(resp.findtext("d:href", "", NS))
                prop = _props(resp)
                data = prop.findtext("c:calendar-data", "", NS)
                if href in seen or not data or not data.strip():
                    continue  # already read, the collection itself, or a 404
                try:
                    seen[href] = ics.from_ics(data, calendar.id, href, _etag(prop))
                except Exception as e:  # one unreadable resource must not stop the sync
                    log.warning("skipping unreadable event %s: %s", href, e)
        return [event for events in seen.values() for event in events]

    def create_event(self, event: Event) -> Event:
        href = urljoin(event.calendar_id.rstrip("/") + "/", quote(event.uid, safe="") + ".ics")
        return self._put(replace(event, href=href), {"If-None-Match": "*"})

    def update_event(self, event: Event) -> Event:
        return self._put(event, {"If-Match": event.etag} if event.etag else {})

    def delete_event(self, event: Event) -> None:
        if not event.href:
            return
        href = event.href
        headers = {"If-Match": event.etag} if event.etag else {}
        response = _call("DELETE", lambda: self.client.delete(href, headers=headers))
        if response.status != 404:  # already gone is fine
            _check(response, "DELETE", href, ok=(200, 204))

    def _put(self, event: Event, headers: dict[str, str]) -> Event:
        href = event.href
        assert href
        data = ics.to_ics(event)
        headers = {"Content-Type": "text/calendar; charset=utf-8", **headers}
        response = _call("PUT", lambda: self.client.put(href, data, headers=headers))
        _check(response, "PUT", href, ok=(200, 201, 204))
        etag = response.headers.get("ETag") or self._etag(href)
        return replace(event, etag=etag, raw=data)

    def _etag(self, href: str) -> str | None:
        """The resource's etag, for servers that send none with the PUT answer."""
        try:
            response = self.client.propfind(href, PROPFIND_ETAG, 0)
        except (DAVError, OSError) as e:
            log.warning("no etag for %s: %s", href, e)
            return None
        if response.status != 207:
            return None
        resp = response.tree.find("d:response", NS)
        return _etag(_props(resp)) if resp is not None else None

    def _url(self, href: str) -> str:
        """``href`` as an absolute URL on the home's host (see module doc)."""
        parts = urlsplit(href.strip())
        return urljoin(self.home_url, parts.path)


def _call(what: str, request: Callable[[], T]) -> T:
    """Run a request; caldav's errors become ProviderErrors (network errors stay OSErrors)."""
    try:
        return request()
    except AuthorizationError as e:
        raise AuthError(
            f"{what}: authentication failed (HTTP {e.status or 401}) - use your Apple ID "
            "e-mail and an app-specific password from appleid.apple.com"
        ) from e
    except DAVError as e:
        raise ProviderError(f"{what}: {e}") from e


def _check(response: Any, method: str, url: str, ok: tuple[int, ...]) -> None:
    if response.status == 412:
        raise ConflictError(f"{method} {url}: precondition failed (etag)")
    if response.status not in ok:
        raise ProviderError(f"{method} {url}: HTTP {response.status}")


def _props(resp: Any) -> Any:
    """The properties of a <response> found with a 200 status, merged into one <prop>.

    (Missing ones come in a 404 propstat, as empty elements.) Moves them out of ``resp``.
    """
    merged = etree.Element("prop")
    for propstat in resp.iterfind("d:propstat", NS):
        if " 200" in (propstat.findtext("d:status", "", NS) or " 200"):
            for prop in propstat.iterfind("d:prop", NS):
                merged.extend(prop)
    return merged


def _etag(prop: Any) -> str | None:
    return (prop.findtext("d:getetag", "", NS) or "").strip() or None


def _color(text: str | None) -> str:
    """Apple's "#RRGGBBAA" (or "#RRGGBB", "#RGB") as "#RRGGBB"."""
    m = _COLOR.fullmatch((text or "").strip())
    if not m:
        return DEFAULT_COLOR
    rgb = m.group(1) or "".join(c * 2 for c in m.group(3))
    return "#" + rgb.upper()


def _normalize(url: str) -> str:
    """Drop the default port iCloud puts in the home-set (":443")."""
    parts = urlsplit(url)
    netloc = parts.netloc.removesuffix(":443") if parts.scheme == "https" else parts.netloc
    return parts._replace(netloc=netloc).geturl()


def _chunks(start: datetime, end: datetime) -> Iterator[tuple[datetime, datetime]]:
    """[start, end) in CHUNK-sized pieces (at least one, even if empty)."""
    lo = start
    while True:
        yield lo, min(lo + CHUNK, end)
        lo += CHUNK
        if lo >= end:
            return
