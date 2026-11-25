"""A fake iCloud at the HTTP layer: a real ``caldav.DAVClient`` whose session answers
from recorded-style multistatus XML and ICS (no network).

Like iCloud: discovery starts on caldav.icloud.com, the calendar-home-set points to the
account's partition host ``p42-caldav.icloud.com:443``, a request without (or with wrong)
Basic auth gets a 401 with ``WWW-Authenticate``, and hrefs are host-relative.
"""

import base64
from typing import Any

from caldav.lib.http_sync import CaseInsensitiveDict, Response

from tcal.providers.icloud import ICloudProvider

APPLE_ID = "me@icloud.com"
PASSWORD = "abcd-efgh-ijkl-mnop"
ENTRY = "https://caldav.icloud.com"
HOME = "https://p42-caldav.icloud.com/1234567/calendars/"
WORK = HOME + "work/"

PRINCIPAL_XML = """<?xml version="1.0" encoding="UTF-8"?>
<multistatus xmlns="DAV:"><response><href>/</href><propstat><prop>
  <current-user-principal><href>/1234567/principal/</href></current-user-principal>
</prop><status>HTTP/1.1 200 OK</status></propstat></response></multistatus>"""

HOME_SET_XML = """<?xml version="1.0" encoding="UTF-8"?>
<multistatus xmlns="DAV:"><response><href>/1234567/principal/</href><propstat><prop>
  <calendar-home-set xmlns="urn:ietf:params:xml:ns:caldav">
    <href xmlns="DAV:">https://p42-caldav.icloud.com:443/1234567/calendars/</href>
  </calendar-home-set>
</prop><status>HTTP/1.1 200 OK</status></propstat></response></multistatus>"""


def _calendar(name: str, display: str, color: str, comp: str, privileges: str) -> str:
    return f"""<response><href>/1234567/calendars/{name}/</href>
  <propstat><prop>
    <resourcetype><collection/><calendar xmlns="urn:ietf:params:xml:ns:caldav"/></resourcetype>
    <displayname>{display}</displayname>
    <calendar-color xmlns="http://apple.com/ns/ical/" symbolic-color="custom">{color}</calendar-color>
    <supported-calendar-component-set xmlns="urn:ietf:params:xml:ns:caldav">
      <comp name="{comp}"/></supported-calendar-component-set>
    <current-user-privilege-set>{privileges}</current-user-privilege-set>
  </prop><status>HTTP/1.1 200 OK</status></propstat>
  <propstat><prop><calendar-order xmlns="http://apple.com/ns/ical/"/></prop>
  <status>HTTP/1.1 404 Not Found</status></propstat></response>"""


WRITE = "<privilege><read/></privilege><privilege><write/></privilege>"
READ = "<privilege><read/></privilege><privilege><read-current-user-privilege-set/></privilege>"
CALENDARS_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<multistatus xmlns="DAV:">
<response><href>/1234567/calendars/</href><propstat><prop>
  <resourcetype><collection/></resourcetype></prop>
  <status>HTTP/1.1 200 OK</status></propstat></response>
{_calendar("work", "Work", "#FF2968FF", "VEVENT", WRITE)}
{_calendar("tasks", "Reminders", "#1BADF8FF", "VTODO", WRITE)}
{_calendar("holidays", "Holidays", "#CC73E1", "VEVENT", READ)}
<response><href>/1234567/calendars/inbox/</href><propstat><prop>
  <resourcetype><collection/><schedule-inbox xmlns="urn:ietf:params:xml:ns:caldav"/></resourcetype>
</prop><status>HTTP/1.1 200 OK</status></propstat></response>
</multistatus>"""

VTIMEZONE = """BEGIN:VTIMEZONE
TZID:Europe/Vienna
BEGIN:DAYLIGHT
TZOFFSETFROM:+0100
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU
DTSTART:19810329T020000
TZNAME:CEST
TZOFFSETTO:+0200
END:DAYLIGHT
BEGIN:STANDARD
TZOFFSETFROM:+0200
RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU
DTSTART:19961027T030000
TZNAME:CET
TZOFFSETTO:+0100
END:STANDARD
END:VTIMEZONE"""


def _ics(*vevents: str) -> str:
    body = "\n".join(f"BEGIN:VEVENT\n{v.strip()}\nEND:VEVENT" for v in vevents)
    text = "BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//Apple Inc.//iCloud 2604B57//EN\n"
    return (text + f"CALSCALE:GREGORIAN\n{VTIMEZONE}\n{body}\nEND:VCALENDAR\n").replace(
        "\n", "\r\n"
    )


STANDUP = _ics(
    """
UID:6F1C-STANDUP
DTSTAMP:20261101T080000Z
CREATED:20261101T080000Z
DTSTART;TZID=Europe/Vienna:20261102T091500
DTEND;TZID=Europe/Vienna:20261102T093000
SUMMARY:Standup
RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR
EXDATE;TZID=Europe/Vienna:20261120T091500
X-APPLE-TRAVEL-ADVISORY-BEHAVIOR:AUTOMATIC
SEQUENCE:0
""",
    """
UID:6F1C-STANDUP
DTSTAMP:20261110T080000Z
RECURRENCE-ID;TZID=Europe/Vienna:20261118T091500
DTSTART;TZID=Europe/Vienna:20261118T110000
DTEND;TZID=Europe/Vienna:20261118T113000
SUMMARY:Standup (moved)
SEQUENCE:1
""",
)
DENTIST = _ics(
    """
UID:A1B2-DENTIST
DTSTAMP:20261101T080000Z
DTSTART;TZID=America/New_York:20261117T090000
DTEND;TZID=America/New_York:20261117T100000
SUMMARY:Call with NY dentist
LOCATION:Phone
"""
)
DAY_OFF = _ics(
    """
UID:C3D4-DAYOFF
DTSTAMP:20261101T080000Z
DTSTART;VALUE=DATE:20261119
DTEND;VALUE=DATE:20261119
SUMMARY:Day off
X-APPLE-UNIVERSAL-ID:c3d4
"""
)
BIRTHDAY = _ics(
    """
UID:E5F6-BIRTHDAY
DTSTAMP:20261101T080000Z
DTSTART;VALUE=DATE:20261121
SUMMARY:Anna's birthday
"""
)


def _resource(name: str, etag: str, ics: str) -> str:
    data = ics.replace("&", "&amp;").replace("<", "&lt;")
    return f"""<response><href>/1234567/calendars/work/{name}.ics</href><propstat><prop>
  <getetag>"{etag}"</getetag>
  <calendar-data xmlns="urn:ietf:params:xml:ns:caldav">{data}</calendar-data>
</prop><status>HTTP/1.1 200 OK</status></propstat></response>"""


WORK_EVENTS_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<multistatus xmlns="DAV:">
{_resource("6F1C-STANDUP", "mk1", STANDUP)}
{_resource("A1B2-DENTIST", "mk2", DENTIST)}
{_resource("C3D4-DAYOFF", "mk3", DAY_OFF)}
{_resource("E5F6-BIRTHDAY", "mk4", BIRTHDAY)}
</multistatus>"""
EMPTY_XML = '<?xml version="1.0" encoding="UTF-8"?><multistatus xmlns="DAV:"/>'

ROUTES = {
    ("PROPFIND", ENTRY): PRINCIPAL_XML,
    ("PROPFIND", ENTRY + "/1234567/principal/"): HOME_SET_XML,
    ("PROPFIND", HOME): CALENDARS_XML,
    ("REPORT", WORK): WORK_EVENTS_XML,
    ("REPORT", HOME + "holidays/"): EMPTY_XML,
}


class FakeICloud:
    """``session.request`` of the DAVClient; records (method, url, Depth) per request."""

    def __init__(self, password: str = PASSWORD) -> None:
        self.password = password
        self.requests: list[tuple[str, str, str | None]] = []

    def __call__(self, method: str, url: str, headers: Any = None, auth: Any = None, **_: Any):
        self.requests.append((method, url, (headers or {}).get("Depth")))
        expected = base64.b64encode(f"{APPLE_ID}:{self.password}".encode()).decode()
        sent = _authorization(auth)
        if sent != f"Basic {expected}":
            return _response(401, "", {"WWW-Authenticate": 'Basic realm="iCloud"'})
        body = ROUTES.get((method, url.removesuffix(":443")))
        if body is None:
            return _response(404, "")
        return _response(207, body, {"Content-Type": "text/xml; charset=utf-8"})


def connect(server: FakeICloud) -> Any:
    """A ``doctor.Connect`` that wires a real ICloudProvider to ``server``."""

    def connect(apple_id: str, password: str, url: str) -> ICloudProvider:
        provider = ICloudProvider.connect(apple_id, password, url)
        provider.client.session.request = server
        return provider

    return connect


def _authorization(auth: Any) -> str | None:
    if auth is None:
        return None
    request = type("R", (), {"headers": {}})()
    auth(request)
    return request.headers.get("Authorization")


def _response(status: int, body: str, headers: dict[str, str] | None = None) -> Response:
    r = Response()
    r.status_code = status
    r.reason = {207: "Multi-Status", 401: "Unauthorized", 404: "Not Found"}[status]
    r.headers = CaseInsensitiveDict(headers or {})
    r._content = body.encode()
    return r
