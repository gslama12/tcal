"""The local time zone as a named, DST-aware zone (not a fixed UTC offset)."""

import os
from datetime import date, datetime, time, tzinfo
from functools import cache
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


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
