"""ICloudProvider against a recorded-style fake DAV client (no network)."""

from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from caldav.response import DAVResponse
from test_ics import SERIES

from tcal.model import Calendar
from tcal.providers.base import ConflictError, ProviderError
from tcal.providers.icloud import ICloudProvider

HOME = "https://p42-caldav.icloud.com/123/calendars/"
VIENNA = ZoneInfo("Europe/Vienna")

CALENDARS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<multistatus xmlns="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav"
             xmlns:A="http://apple.com/ns/ical/">
  <response><href>/123/calendars/</href>
    <propstat><prop><resourcetype><collection/></resourcetype></prop>
    <status>HTTP/1.1 200 OK</status></propstat></response>
  <response><href>/123/calendars/work/</href>
    <propstat><prop>
      <resourcetype><collection/><C:calendar/></resourcetype>
      <displayname>Work</displayname>
      <A:calendar-color>#FF2968FF</A:calendar-color>
      <A:calendar-order>2</A:calendar-order>
      <C:supported-calendar-component-set><C:comp name="VEVENT"/></C:supported-calendar-component-set>
      <current-user-privilege-set><privilege><read/></privilege><privilege><write/></privilege>
      </current-user-privilege-set>
    </prop><status>HTTP/1.1 200 OK</status></propstat></response>
  <response><href>/123/calendars/shared/</href>
    <propstat><prop>
      <resourcetype><collection/><C:calendar/></resourcetype>
      <displayname>Shared</displayname>
      <A:calendar-order>1</A:calendar-order>
      <current-user-privilege-set><privilege><read/></privilege></current-user-privilege-set>
    </prop><status>HTTP/1.1 200 OK</status></propstat></response>
  <response><href>/123/calendars/tasks/</href>
    <propstat><prop>
      <resourcetype><collection/><C:calendar/></resourcetype>
      <displayname>Reminders</displayname>
      <C:supported-calendar-component-set><C:comp name="VTODO"/></C:supported-calendar-component-set>
    </prop><status>HTTP/1.1 200 OK</status></propstat></response>
  <response><href>/123/calendars/inbox/</href>
    <propstat><prop><resourcetype><collection/><C:schedule-inbox/></resourcetype></prop>
    <status>HTTP/1.1 200 OK</status></propstat></response>
</multistatus>"""

EVENTS_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<multistatus xmlns="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">
  <response><href>/123/calendars/work/series-1.ics</href>
    <propstat><prop><getetag>"etag-1"</getetag>
      <C:calendar-data>{SERIES}</C:calendar-data></prop>
    <status>HTTP/1.1 200 OK</status></propstat></response>
  <response><href>/123/calendars/work/broken.ics</href>
    <propstat><prop><getetag>"x"</getetag>
      <C:calendar-data>not ical</C:calendar-data></prop>
    <status>HTTP/1.1 200 OK</status></propstat></response>
</multistatus>"""


class FakeClient:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, dict[str, str], str]] = []
        self.status = 201

    def propfind(self, url: str, props: str = "", depth: int = 0) -> DAVResponse:
        self.requests.append(("PROPFIND", url, {"Depth": str(depth)}, props))
        return DAVResponse.from_bytes(CALENDARS_XML.encode())

    def report(self, url: str, query: str = "", depth: int | None = 0) -> DAVResponse:
        self.requests.append(("REPORT", url, {}, query))
        return DAVResponse.from_bytes(EVENTS_XML.encode())

    def put(self, url: str, body: str, headers: dict[str, str]) -> Any:
        self.requests.append(("PUT", url, headers, body))
        return SimpleNamespace(status=self.status, headers={"ETag": '"new"'})

    def delete(self, url: str, headers: dict[str, str]) -> Any:
        self.requests.append(("DELETE", url, headers, ""))
        return SimpleNamespace(status=self.status, headers={})


@pytest.fixture
def client() -> FakeClient:
    return FakeClient()


@pytest.fixture
def icloud(client: FakeClient) -> ICloudProvider:
    return ICloudProvider(client, home_url=HOME)


WORK = Calendar(HOME + "work/", "Work", "#FF2968")


def test_list_calendars(icloud: ICloudProvider, client: FakeClient) -> None:
    cals = icloud.list_calendars()
    assert [(c.name, c.color, c.readonly) for c in cals] == [
        ("Shared", "#1BADF8", True),
        ("Work", "#FF2968", False),
    ]
    assert cals[1].id == WORK.id
    assert client.requests[0][:3] == ("PROPFIND", HOME, {"Depth": "1"})


def test_fetch_events(icloud: ICloudProvider, client: FakeClient) -> None:
    start, end = datetime(2026, 11, 1, tzinfo=VIENNA), datetime(2026, 12, 1, tzinfo=VIENNA)
    events = icloud.fetch_events(WORK, start, end)
    assert [e.summary for e in events] == ["Weekly", "Weekly (moved)"]  # broken one skipped
    assert events[0].href == WORK.id + "series-1.ics" and events[0].etag == '"etag-1"'
    query = client.requests[0][3]
    assert 'start="20261031T230000Z"' in query and 'end="20261130T230000Z"' in query


def test_create_update_delete_use_etags(icloud: ICloudProvider, client: FakeClient) -> None:
    master = icloud.fetch_events(WORK, datetime.now(VIENNA), datetime.now(VIENNA))[0]
    created = icloud.create_event(replace(master, uid="new id", href=None, etag=None, raw=None))
    method, url, headers, body = client.requests[-1]
    assert (method, url, headers["If-None-Match"]) == ("PUT", WORK.id + "new%20id.ics", "*")
    assert "UID:new id" in body and created.etag == '"new"' and created.href == url

    client.status = 204
    updated = icloud.update_event(replace(master, summary="Renamed"))
    _, url, headers, body = client.requests[-1]
    assert url == master.href and headers["If-Match"] == '"etag-1"'
    assert "SUMMARY:Renamed" in body and "Weekly (moved)" in body  # override kept
    assert updated.etag == '"new"'

    icloud.delete_event(updated)
    assert client.requests[-1][:3] == ("DELETE", master.href, {"If-Match": '"new"'})


def test_errors(icloud: ICloudProvider, client: FakeClient) -> None:
    master = icloud.fetch_events(WORK, datetime.now(VIENNA), datetime.now(VIENNA))[0]
    client.status = 412
    with pytest.raises(ConflictError):
        icloud.update_event(master)
    with pytest.raises(ConflictError):
        icloud.delete_event(master)
    client.status = 404
    icloud.delete_event(master)  # already gone: fine
    client.status = 500
    with pytest.raises(ProviderError):
        icloud.update_event(master)


def test_home_url_is_discovered_lazily(client: FakeClient) -> None:
    calls = []

    def principal() -> Any:
        calls.append(1)
        return SimpleNamespace(calendar_home_set=SimpleNamespace(url=HOME))

    client.principal = principal  # type: ignore[attr-defined]
    provider = ICloudProvider(client)
    assert calls == []
    provider.list_calendars()
    provider.list_calendars()
    assert calls == [1]
