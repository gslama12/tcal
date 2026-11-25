"""The local time zone as a named, DST-aware zone (not a fixed UTC offset), and UTC stamps."""

import os
from datetime import UTC, date, datetime, time, tzinfo
from functools import cache
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

UTC_STAMP = "%Y%m%dT%H%M%SZ"  # iCalendar/CalDAV UTC form, e.g. 20261121T090000Z


@cache
def local_zone() -> tzinfo:
    """``$TZ`` or the ``/etc/localtime`` zone; the current fixed offset as a fallback."""
    name = os.environ.get("TZ", "").lstrip(":")
    if not name:
        target = str(Path("/etc/localtime").resolve())
        name = target.split("zoneinfo/", 1)[1] if "zoneinfo/" in target else ""
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return datetime.now().astimezone().tzinfo or ZoneInfo("UTC")


def local_midnight(day: date) -> datetime:
    return datetime.combine(day, time(), local_zone())


def utc_stamp(dt: datetime) -> str:
    """``dt`` in the UTC_STAMP form (sorts chronologically as text)."""
    return dt.astimezone(UTC).strftime(UTC_STAMP)
