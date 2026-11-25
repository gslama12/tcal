"""The event form's fields as text, and back: ``values_of(event)`` -> ``FormValues``;
``build_event(event, shown, values, today)`` puts edited values into the event.

Fields left as shown keep the event's own values (time zone, line breaks, a custom RRULE).
Dates accept goto's forms (``fri``, ``tomorrow``, ``24.12.``, ISO).
"""

import re
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta

from tcal import dates
from tcal.model import Event
from tcal.repeat import until_date, until_part, without_end
from tcal.tz import local_midnight, local_zone

REPEATS: dict[str, str | None] = {  # choice -> RRULE
    "none": None,
    "daily": "FREQ=DAILY",
    "weekdays": "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR",
    "weekly": "FREQ=WEEKLY",
    "monthly": "FREQ=MONTHLY",
    "yearly": "FREQ=YEARLY",
}
CUSTOM = "custom"  # an RRULE the form can't express; kept unless changed
DEFAULT_START, DEFAULT_END = time(9), time(10)
_TIME = re.compile(r"(\d{1,2})[:.]?(\d{2})?")


class FormError(ValueError):
    """Invalid form input; the message is shown below the widget ``field`` (an id)."""

    def __init__(self, message: str, field: str) -> None:
        super().__init__(message)
        self.field = field


@dataclass(frozen=True)
class FormValues:
    """The form's fields as text, as shown to the user (local time)."""

    title: str
    calendar_id: str
    start_date: str
    start_time: str
    end_date: str
    end_time: str
    all_day: bool
    location: str
    notes: str
    repeat: str  # a key of REPEATS or CUSTOM
    ends: str  # "never", "on" or "after"
    ends_value: str  # "on": a date, "after": a number of times

    @property
    def start(self) -> tuple[str, str]:
        return self.start_date.strip(), self.start_time.strip()

    @property
    def end(self) -> tuple[str, str]:
        return self.end_date.strip(), self.end_time.strip()

    @property
    def rule(self) -> tuple[str, str, str, bool]:
        """What the RRULE depends on (UNTIL is a date or a time)."""
        return self.repeat, self.ends, self.ends_value.strip(), self.all_day


def values_of(event: Event) -> FormValues:
    start, end = event.start.astimezone(local_zone()), event.end.astimezone(local_zone())
    if event.all_day:  # end shown inclusive; times prefilled for unticking all-day
        end = datetime.combine(end.date() - timedelta(days=1), DEFAULT_END)
        start = datetime.combine(start.date(), DEFAULT_START)
    ends, ends_value = _end_of(event.rrule or "")
    return FormValues(
        title=_flat(event.summary),
        calendar_id=event.calendar_id,
        start_date=show_date(start.date()),
        start_time=f"{start:%H:%M}",
        end_date=show_date(end.date()),
        end_time=f"{end:%H:%M}",
        all_day=event.all_day,
        location=_flat(event.location),
        notes=event.description,
        repeat=_repeat_of(event.rrule),
        ends=ends,
        ends_value=ends_value,
    )


def _flat(text: str) -> str:
    """``text`` on one line."""
    return ", ".join(line.strip() for line in text.splitlines() if line.strip())


def _repeat_of(rrule: str | None) -> str:
    """The REPEATS choice of ``rrule`` (its end aside), CUSTOM if none matches."""
    if not rrule:
        return "none"
    rule = without_end(rrule).upper()
    return next((r for r, known in REPEATS.items() if known == rule), CUSTOM)


def _end_of(rrule: str) -> tuple[str, str]:
    """The end of a series: the form's choice and its value as shown."""
    for part in rrule.split(";"):
        key, _, value = part.partition("=")
        if key.upper() == "COUNT":
            return "after", value
        if key.upper() == "UNTIL":
            return "on", show_date(until_date(value))
    return "never", ""


def _end_part(values: FormValues, start: datetime, today: date) -> str:
    """The RRULE suffix for the form's "Ends" fields ('' = never)."""
    text = values.ends_value.strip()
    if values.ends == "after":
        if not text.isdecimal() or int(text) < 1:
            raise FormError(f"Not a number of times: {text!r}", "ends_value")
        return f";COUNT={int(text)}"
    if values.ends == "on":
        day = parse_date(text, "ends_value", today)
        if day < start.astimezone(local_zone()).date():
            raise FormError("The series can't end before it starts", "ends_value")
        return f";{until_part(day, values.all_day)}"
    return ""


def show_date(day: date) -> str:
    """A date as the form shows it: 'Sat 21 Nov 2026' (``parse_date`` reads it back)."""
    return f"{day:%a %-d %b %Y}"


def parse_date(text: str, field: str, today: date) -> date:
    if (day := dates.parse_date(text, today)) is None:
        raise FormError(f"Not a date: {text!r} (e.g. 2026-12-24, fri, 24.12.)", field)
    return day


def parse_time(text: str, field: str) -> time:
    """'9', '930', '9:30', '09.30' -> time."""
    match = _TIME.fullmatch(text.strip())
    try:
        if match is None:
            raise ValueError
        return time(int(match[1]), int(match[2] or 0))
    except ValueError:
        raise FormError(f"Not a time: {text!r} (use HH:MM)", field) from None


def build_event(event: Event, shown: FormValues, values: FormValues, today: date) -> Event:
    """``event`` with the form ``values`` applied (``shown`` = the values it was
    opened with); raises FormError on invalid input."""
    title = values.title.strip()
    if not title:
        raise FormError("Title is required", "title")
    start, end = _times(event, shown, values, today)
    rrule = event.rrule
    if values.rule != shown.rule:
        base = without_end(rrule or "") if values.repeat == CUSTOM else REPEATS[values.repeat]
        rrule = base and base + _end_part(values, start, today)
    return replace(
        event,
        summary=event.summary if values.title == shown.title else title,
        calendar_id=values.calendar_id,
        start=start,
        end=end,
        all_day=values.all_day,
        location=event.location if values.location == shown.location else values.location.strip(),
        description=event.description if values.notes == shown.notes else values.notes.strip(),
        rrule=rrule,
    )


def _times(
    event: Event, shown: FormValues, values: FormValues, today: date
) -> tuple[datetime, datetime]:
    """The event's start and end; unchanged ones keep their own zone."""
    same_kind = values.all_day == shown.all_day
    same_start = same_kind and values.start == shown.start
    same_end = same_kind and values.end == shown.end
    if same_start and same_end:
        return event.start, event.end
    start_day = parse_date(values.start_date, "start_date", today)
    end_day = parse_date(values.end_date, "end_date", today)
    if values.all_day:
        start, end = local_midnight(start_day), local_midnight(end_day + timedelta(days=1))
    else:
        zone = local_zone()
        start = datetime.combine(start_day, parse_time(values.start_time, "start_time"), zone)
        end = datetime.combine(end_day, parse_time(values.end_time, "end_time"), zone)
    if end <= start:
        raise FormError("End must be after start", "end_date" if values.all_day else "end_time")
    return event.start if same_start else start, event.end if same_end else end
