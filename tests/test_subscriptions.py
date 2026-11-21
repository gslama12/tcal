"""Read-only iCalendar subscriptions: config, feed provider, sync and the calendar list."""

import gzip
import io
import urllib.error
from datetime import timedelta
from pathlib import Path

import pytest
from conftest import TODAY

from tcal.config import ConfigError, SubscriptionConfig, load_config
from tcal.model import SUBSCRIPTION_PREFIX
from tcal.providers import ics_url
from tcal.providers.base import ProviderError
from tcal.providers.fake import FakeProvider, demo_feed
from tcal.providers.ics_url import IcsUrlProvider
from tcal.source import StoreSource
from tcal.store import Store
from tcal.sync import SyncEngine, SyncSummary
from tcal.ui.app import TcalApp
from tcal.ui.widgets.calendar_list import CalendarList
from tcal.ui.widgets.statusbar import StatusBar

FEED = (Path(__file__).parent / "fixtures" / "holidays.ics").read_bytes()
URL = "https://example.com/holidays.ics"
SUB = SubscriptionConfig("Holidays AT", URL, "#BF616A")
CAL_ID = SUBSCRIPTION_PREFIX + URL


def feeds(body: bytes | Exception = FEED) -> IcsUrlProvider:
    def fetch(url: str) -> bytes:
        assert url == URL
        if isinstance(body, Exception):
            raise body
        return body

    return IcsUrlProvider([SUB], fetch)


def test_config_subscriptions(write_config) -> None:
    config = write_config(
        """
[[subscription]]
name = "Holidays"
url = "webcal://calendars.icloud.com/holidays/us_en.ics"
color = "#bf616a"

[[subscription]]
name = "Team"
url = "https://example.com/team.ics"
"""
    )
    assert config.subscriptions == (
        SubscriptionConfig(
            "Holidays", "https://calendars.icloud.com/holidays/us_en.ics", "#BF616A"
        ),
        SubscriptionConfig("Team", "https://example.com/team.ics", "#8FBCBB"),
    )


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ('name = "x"\nurl = "https://x"\nwhat = 1', "unknown setting"),
        ('name = "x"', "needs a name and a url"),
        ('name = "x"\nurl = "ftp://x"', "url must be"),
        ('name = "x"\nurl = "https://x"\ncolor = "red"', "color must be"),
    ],
)
def test_config_subscription_errors(write_config, body: str, message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        write_config(f"[[subscription]]\n{body}\n")


def test_provider_splits_feed_by_uid_and_window() -> None:
    provider = feeds()
    [cal] = provider.list_calendars()
    assert (cal.id, cal.name, cal.readonly, cal.subscribed) == (CAL_ID, "Holidays AT", True, True)

    events = provider.fetch_events(cal, *_engine().window())
    by_uid = {(e.uid, e.recurrence_id is not None): e for e in events}
    assert sorted(by_uid) == [
        ("market", False),
        ("national-day", False),
        ("new-year", False),
        ("new-year", True),
    ]  # "long-ago" is outside the window
    market = by_uid[("market", False)]
    assert str(market.start.tzinfo) == "Europe/Vienna" and market.start.hour == 18
    assert market.raw is not None and "national-day" not in market.raw  # one UID per resource
    assert "BEGIN:VTIMEZONE" in market.raw

    with pytest.raises(ProviderError):
        provider.create_event(market)


def test_provider_rejects_non_calendar() -> None:
    provider = feeds(b"<html>not found</html>")
    with pytest.raises(ProviderError, match="not an iCalendar feed"):
        provider.fetch_events(provider.list_calendars()[0], *_engine().window())


def test_http_get_ungzips(monkeypatch: pytest.MonkeyPatch) -> None:
    """Apple's holiday feeds come gzip-compressed without saying so."""
    seen = []

    def urlopen(request, timeout):
        seen.append((request.full_url, request.get_header("User-agent"), timeout))
        return io.BytesIO(gzip.compress(FEED))

    monkeypatch.setattr(ics_url.urllib.request, "urlopen", urlopen)
    assert ics_url.http_get(URL) == FEED
    assert seen == [(URL, "tcal", ics_url.TIMEOUT)]


def _engine(store: Store | None = None, subscriptions: IcsUrlProvider | None = None) -> SyncEngine:
    return SyncEngine(
        FakeProvider(today=TODAY),
        store or Store(":memory:"),
        today=TODAY,
        subscriptions=subscriptions,
    )


def test_sync_caches_feed_and_survives_failures() -> None:
    store = Store(":memory:")
    summary = _engine(store, feeds()).sync()
    cals = store.calendars()
    assert cals[-1].id == CAL_ID and cals[-1].readonly
    assert summary.calendars == len(cals) and not summary.failed
    feed_events = [e for e in store.events_between(*_engine().window()) if e.calendar_id == CAL_ID]
    assert len(feed_events) == 4

    # Offline: the feed's cached events stay, the summary names it.
    summary = _engine(store, feeds(urllib.error.URLError("offline"))).sync()
    assert summary.failed == ["Holidays AT"] and "could not fetch Holidays AT" in str(summary)
    assert (
        len([e for e in store.events_between(*_engine().window()) if e.calendar_id == CAL_ID]) == 4
    )

    # Removed from the config: calendar and events are gone.
    _engine(store).sync()
    assert CAL_ID not in [c.id for c in store.calendars()]
    assert not [e for e in store.events_between(*_engine().window()) if e.calendar_id == CAL_ID]


async def test_calendar_list_other_calendars(store: Store) -> None:
    SyncEngine(FakeProvider(today=TODAY), store, today=TODAY, subscriptions=feeds()).sync()
    app = TcalApp(StoreSource(store), load_config(), today=TODAY)
    async with app.run_test(size=(120, 40)) as pilot:
        cal_list = app.query_one(CalendarList)
        lines = str(cal_list.render()).splitlines()
        assert lines[-3] == "" and lines[-1] == "■ Holidays AT"
        assert (
            lines[-2].startswith(" Other calendars ─")
            and len(lines[-2]) == cal_list.content_size.width
        )
        day = TODAY + timedelta(days=1)

        # Click the feed's row (below the heading) to hide it; the heading does nothing.
        gutter = cal_list.gutter
        await pilot.click(CalendarList, offset=(gutter.left + 2, gutter.top + len(lines) - 2))
        assert app.state.hidden_calendars == frozenset()
        await pilot.click(CalendarList, offset=(gutter.left + 2, gutter.top + len(lines) - 1))
        assert app.state.hidden_calendars == {CAL_ID}

        # Keyboard: the cursor reaches the feed after the account's calendars.
        cal_list.focus()
        for _ in lines:
            await pilot.press("j")
        await pilot.press("space")
        assert app.state.hidden_calendars == frozenset()

        # Read-only: no editing from the detail.
        [occ] = [
            o for o in app.occurrences(day, day + timedelta(days=1)) if o.calendar_id == CAL_ID
        ]
        assert occ.summary == "National Day"
        assert not app.check_writable(occ.calendar_id)


async def test_failed_feed_and_conflicts_are_shown(store: Store) -> None:
    def job() -> SyncSummary:  # the cache already has the feed; this sync could not fetch it
        return SyncSummary(failed=["Holidays AT"], conflicts=1)

    SyncEngine(FakeProvider(today=TODAY), store, today=TODAY, subscriptions=feeds()).sync()
    app = TcalApp(StoreSource(store), load_config(), today=TODAY, sync=job)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        bar = str(app.query_one(StatusBar).render())
        assert "⚠ synced" in bar and "Holidays AT failed" in bar
        assert str(app.query_one(CalendarList).render()).splitlines()[-1] == "■ Holidays AT ⚠"
        assert any("1 local change(s) conflicted" in str(n.message) for n in app._notifications)


def test_demo_feed_is_a_read_only_subscription() -> None:
    store = Store(":memory:")
    SyncEngine(FakeProvider(today=TODAY), store, today=TODAY, subscriptions=demo_feed(TODAY)).sync()
    feed = [c for c in store.calendars() if c.subscribed]
    assert [(c.name, c.readonly) for c in feed] == [("Team events", True)]
    events = store.events_between(*_engine().window())
    assert {e.summary for e in events if e.calendar_id == feed[0].id} == {
        "Team lunch",
        "Office party",
        "Hackathon",
    }
