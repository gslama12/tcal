"""Repeat rules (RRULE values): in words (``describe_rrule``) and their ends."""

from datetime import UTC, date, datetime, timedelta

from tcal.dates import WEEKDAYS
from tcal.tz import local_midnight, local_zone, utc_stamp

FREQS = {"DAILY": "day", "WEEKLY": "week", "MONTHLY": "month", "YEARLY": "year"}
DAY_CODES = tuple(name[:2].upper() for name in WEEKDAYS)  # MO .. SU
_DAY_NAMES = {code: name[:3] for code, name in zip(DAY_CODES, WEEKDAYS, strict=True)}
_ENDS = ("COUNT", "UNTIL")


def _parts(rrule: str) -> dict[str, str]:
    return dict(p.split("=", 1) for p in rrule.upper().split(";") if "=" in p)


def describe_rrule(rrule: str) -> str:
    """An RRULE in words, e.g. 'Every 2 weeks on Mon, Fri, until 31 Dec 2026'."""
    parts = _parts(rrule)
    unit = FREQS.get(parts.get("FREQ", ""))
    if unit is None:
        return f"Repeats ({rrule})"
    interval = int(parts.get("INTERVAL", "1"))
    words = f"Every {interval} {unit}s" if interval > 1 else f"Every {unit}"
    if days := parts.get("BYDAY"):
        codes = days.split(",")
        names = [_DAY_NAMES.get(d[-2:], d).capitalize() for d in codes]
        if unit == "week" and tuple(codes) == DAY_CODES[:5]:
            names = ["weekdays"]
        words += " on " + ", ".join(names)
    if count := parts.get("COUNT"):
        words += f", {count} times"
    elif until := parts.get("UNTIL"):
        words += f", until {until_date(until):%-d %b %Y}"
    return words


def until_date(value: str) -> date:
    """The local day of an RRULE UNTIL (a DATE, a UTC ``…Z`` or a floating date-time)."""
    day = date(int(value[:4]), int(value[4:6]), int(value[6:8]))
    if not value.upper().endswith("Z"):
        return day
    stamp = datetime.strptime(value.upper(), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    return stamp.astimezone(local_zone()).date()


def without_end(rrule: str) -> str:
    """``rrule`` without COUNT/UNTIL."""
    parts = rrule.split(";")
    return ";".join(p for p in parts if p and p.split("=")[0].upper() not in _ENDS)


def until_part(day: date, all_day: bool) -> str:
    """The RRULE part ending a series after ``day`` (inclusive)."""
    if all_day:
        return f"UNTIL={day:%Y%m%d}"
    return f"UNTIL={utc_stamp(local_midnight(day + timedelta(days=1)) - timedelta(seconds=1))}"
