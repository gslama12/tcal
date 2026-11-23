"""Benchmark tcal with a big cache: ~5000 events over 3 years in 6 calendars.

    uv run python scripts/bench.py            # timings (ms per keypress)
    uv run python scripts/bench.py --profile  # plus a cProfile of the key presses

Not a test: it times app start, view switches, H/L, j/k, month/year renders and
search on a headless 160x50 terminal, as CPU time per keypress (the pilot's
own idle waits would add ~65 ms of wall time to every key). Target: < 50 ms.
"""

import asyncio
import cProfile
import pstats
import random
import sys
import tempfile
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import median

from tcal.config import load_config
from tcal.model import Calendar, Event
from tcal.source import StoreSource
from tcal.store import Store
from tcal.tz import local_zone
from tcal.ui.app import TcalApp

TODAY = date(2026, 11, 18)
SIZE = (160, 50)
CALENDARS = [
    Calendar(f"cal{i}", f"Calendar {i}", color)
    for i, color in enumerate(["#5E81AC", "#A3BE8C", "#D08770", "#B48EAD", "#BF616A", "#EBCB8B"])
]
RULES = ["FREQ=DAILY", "FREQ=WEEKLY", "FREQ=WEEKLY;BYDAY=MO,WE,FR", "FREQ=MONTHLY", "FREQ=YEARLY"]


def fill(store: Store, n_single: int = 4900, n_series: int = 100) -> None:
    rnd = random.Random(1)
    zone = local_zone()
    first = TODAY - timedelta(days=548)
    events: dict[str, list[Event]] = {c.id: [] for c in CALENDARS}
    for i in range(n_single + n_series):
        cal = rnd.choice(CALENDARS).id
        day = first + timedelta(days=rnd.randrange(3 * 365))
        all_day = rnd.random() < 0.1
        if all_day:
            start = datetime.combine(day, datetime.min.time(), zone)
            end = start + timedelta(days=rnd.choice([1, 1, 1, 2, 3]))
        else:
            start = datetime(day.year, day.month, day.day, rnd.randrange(7, 21), 0, tzinfo=zone)
            start += timedelta(minutes=rnd.choice([0, 15, 30, 45]))
            end = start + timedelta(minutes=rnd.choice([30, 45, 60, 90, 120]))
        rrule = None
        if i >= n_single:
            rrule = rnd.choice(RULES)
            if rnd.random() < 0.5:
                until = start + timedelta(days=rnd.randrange(30, 700))
                rrule += f";UNTIL={until.strftime('%Y%m%d')}"
        events[cal].append(
            Event(
                f"e{i}",
                cal,
                f"Event {i} {rnd.choice(['sync', 'lunch', 'gym'])}",
                start,
                end,
                all_day,
                location="Room 1",
                rrule=rrule,
            )
        )
    store.upsert_calendars(CALENDARS)
    for cal, evs in events.items():
        store.upsert_events(cal, evs)


async def run(store: Store, profile: cProfile.Profile | None) -> dict[str, list[float]]:
    times: dict[str, list[float]] = {}
    t0 = time.process_time()
    app = TcalApp(StoreSource(store), load_config(), today=TODAY)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        times["app start"] = [(time.process_time() - t0) * 1000]
        app.focus_view()
        await pilot.pause()

        async def press(label: str, *keys: str) -> None:
            for key in keys:
                if profile:
                    profile.enable()
                t = time.process_time()  # CPU time: the pilot's idle waits don't count
                await pilot.press(key)
                await pilot.pause()
                times.setdefault(label, []).append((time.process_time() - t) * 1000)
                if profile:
                    profile.disable()

        await press("no-op key (baseline)", *"zzzz")
        await press("view switch d/w/m/y", "d", "w", "m", "y", "w", "d", "m", "w")
        await press("week H/L", *"LLLLHHHHHH")
        await press("week j/k", *"jjjjkkkk")
        await press("week H/L", *"LLLLHHHH")
        await press("week j/k", *"jjjjkkkk")
        await press("month view", "m")
        await press("month H/L", *"LLLHHH")
        await press("month j/k/h/l", *"jjkkhlhl")
        await press("year view", "y")
        await press("year H/L", "L", "H", "H", "L")
        await press("year j/k", *"jjkk")
        await press("search open", "slash")
        await press("search type", *"lunch")
        await press("search close", "escape")
    return times


def main() -> None:
    profile = cProfile.Profile() if "--profile" in sys.argv else None
    with tempfile.TemporaryDirectory() as tmp, Store(Path(tmp) / "bench.db") as store:
        t = time.perf_counter()
        fill(store)
        print(f"fill store: {(time.perf_counter() - t) * 1000:.0f} ms")
        times = asyncio.run(run(store, profile))
    print(f"{'action':22} {'median':>8} {'max':>8}  (ms)")
    for label, ms in times.items():
        flag = "" if label == "app start" or max(ms) < 50 else "  > 50 ms"
        print(f"{label:22} {median(ms):8.1f} {max(ms):8.1f}{flag}")
    if profile:
        pstats.Stats(profile).sort_stats("cumulative").print_stats(35)


if __name__ == "__main__":
    main()
