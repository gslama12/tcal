"""``tcal doctor``: check the iCloud setup step by step, without writing anything.

Each step prints one ``✓`` line (``!`` for a warning); the first failing step
prints ``✗`` with what to do about it and stops, as later steps depend on it.
"""

import re
from collections.abc import Callable
from datetime import date, timedelta
from functools import partial
from typing import TypeVar

from tcal import paths
from tcal.config import Config
from tcal.credentials import CredentialsError, find_password
from tcal.model import Calendar
from tcal.providers.base import AuthError, ProviderError
from tcal.providers.icloud import ICloudProvider
from tcal.recurrence import expand
from tcal.tz import local_midnight

T = TypeVar("T")
Connect = Callable[[str, str, str], ICloudProvider]
APP_PASSWORD = re.compile(r"[a-z]{4}(-[a-z]{4}){3}")
APP_PASSWORD_HINT = (
    "iCloud needs an app-specific password, not your Apple ID password: create one at "
    "appleid.apple.com → Sign-In and Security → App-Specific Passwords, then run `tcal login`"
)


def calendar_line(cal: Calendar) -> str:
    """'#RRGGBB  Name', with '  (read-only)' if so."""
    return f"{cal.color}  {cal.name}{'  (read-only)' if cal.readonly else ''}"


class Failed(Exception):
    def __init__(self, step: str, problem: str, *hints: str) -> None:
        super().__init__(f"{step}: {problem}")
        self.hints = hints


def run(
    config: Config,
    echo: Callable[[str], object],
    connect: Connect = ICloudProvider.connect,
    today: date | None = None,
) -> bool:
    """Run the checks, printing with ``echo``; True if none failed."""
    try:
        _checks(config, echo, connect, today or date.today())
    except Failed as e:
        echo(f"✗ {e}")
        for hint in e.hints:
            echo(f"    → {hint}")
        return False
    echo("All checks passed.")
    return True


def _checks(config: Config, echo: Callable[[str], object], connect: Connect, today: date) -> None:
    account = config.account
    if not account.apple_id:
        raise Failed("account", "no Apple ID configured", "run `tcal login`")
    echo(f"✓ account: {account.apple_id}")

    try:
        found = find_password(account)
    except CredentialsError as e:
        raise Failed("password", str(e), f"fix password_cmd in {paths.config_file()}") from None
    if found is None:
        raise Failed(
            "password",
            "none in the system keyring, password_cmd or $TCAL_PASSWORD",
            "run `tcal login` to store it in the keyring",
        )
    password, source = found
    echo(f"✓ password: from {source}")
    if not APP_PASSWORD.fullmatch(password):
        echo("! password: doesn't look like an app-specific password (xxxx-xxxx-xxxx-xxxx)")

    provider = connect(account.apple_id, password, account.caldav_url)

    def ask(step: str, request: Callable[[], T]) -> T:
        try:
            return request()
        except AuthError as e:
            raise Failed(
                step,
                str(e),
                APP_PASSWORD_HINT,
                "use the Apple ID's primary e-mail address as the user name",
            ) from None
        except OSError as e:
            raise Failed(
                step,
                f"cannot reach {account.caldav_url}: {e}",
                "check the network connection, and caldav_url if you changed it",
            ) from None
        except ProviderError as e:
            raise Failed(step, str(e)) from None

    echo(f"✓ sign-in: principal {ask('sign-in', lambda: provider.principal_url)}")
    echo(f"✓ calendar home: {ask('calendar home', lambda: provider.home_url)}")

    calendars = ask("calendars", provider.list_calendars)
    if not calendars:
        raise Failed("calendars", "the account has no event calendars", "create one on iCloud.com")
    echo(f"✓ calendars: {len(calendars)}")
    for cal in calendars:
        echo(f"    {calendar_line(cal)}")

    first = today - timedelta(days=(today.weekday() - config.view.week_start) % 7)
    start, end = local_midnight(first), local_midnight(first + timedelta(days=7))
    counts: dict[str, int] = {}
    for cal in calendars:
        events = ask(f"events of {cal.name}", partial(provider.fetch_events, cal, start, end))
        counts[cal.name] = len(expand(events, start, end))
    echo(
        f"✓ events this week ({first:%Y-%m-%d} – {first + timedelta(days=6):%Y-%m-%d}): "
        f"{sum(counts.values())}"
    )
    for name, count in counts.items():
        echo(f"    {count:3}  {name}")

    writable = [c.name for c in calendars if not c.readonly]
    if writable:
        echo(f"✓ write access (server privileges, nothing written): {', '.join(writable)}")
    else:
        echo("! write access: every calendar is read-only, so tcal can't create events")
