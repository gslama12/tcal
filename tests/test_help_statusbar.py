from datetime import datetime, time, timedelta

from conftest import TODAY

from tcal.model import Event
from tcal.tz import local_zone
from tcal.ui.screens.help import GROUPS, HelpScreen, KeyTable, sections, split_columns
from tcal.ui.state import ViewMode
from tcal.ui.sync_status import SyncState, SyncStatus
from tcal.ui.widgets.statusbar import StatusBar


def bar_text(app) -> str:
    return str(app.query_one(StatusBar).render())


async def test_help_lists_user_overridden_key(make_app, write_config) -> None:
    app = make_app(write_config('[keys]\nsync = ["S"]\nhelp = ["f1"]\n'))
    async with app.run_test() as pilot:
        await pilot.press("f1")
        assert isinstance(app.screen, HelpScreen)
        table = app.screen.query_one(KeyTable)
        rows = dict(row for _, rows in sections(table.keys) for row in rows)
        assert rows["S"] == "Sync now"
        assert "r" not in rows
        await pilot.press("d")  # app keys don't reach the panes behind the modal
        assert app.state.view is ViewMode.WEEK
        await pilot.press("f1")
        assert not isinstance(app.screen, HelpScreen)


async def test_help_closes_with_escape_and_q(make_app) -> None:
    app = make_app()
    async with app.run_test() as pilot:
        for key in ("escape", "q"):
            await pilot.press("question_mark")
            assert isinstance(app.screen, HelpScreen)
            await pilot.press(key)
            assert not isinstance(app.screen, HelpScreen)
        assert app.is_running  # q closed the help, it did not quit


def test_default_keys_are_all_grouped(make_app) -> None:
    titles = [title for title, _ in sections(make_app().config.keys)]
    assert "Event form" in titles and "Other" not in titles


async def test_help_hint_is_inside_the_titled_box(make_app) -> None:
    app = make_app()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.press("question_mark")
        box = app.screen.query_one("#help")
        assert box.border_title == "Key bindings"
        assert app.screen.query_one("#help-hint").parent is box
        assert box.region.bottom <= 30


def test_sections_group_and_keep_unknown_actions() -> None:
    keys = {"today": ["t"], "zoom_in": ["plus", "ctrl+up"], "new_thing": ["z"]}
    assert sections(keys) == [
        ("Navigation", [("t", "Jump to today")]),
        ("Views", [("+ ctrl+up", "Zoom in (time grid)")]),
        ("Other", [("z", "New thing")]),
    ]


async def test_statusbar_shows_view_date_and_help(make_app, write_config) -> None:
    app = make_app(write_config('[keys]\nhelp = ["f1"]\n'))
    async with app.run_test(size=(120, 30)):
        text = bar_text(app)
        assert "WEEK" in text
        assert "Wed 18 Nov 2026" in text
        assert "f1 help" in text
        assert "local only" in text  # no sync job


async def test_statusbar_sync_states(make_app) -> None:
    app = make_app()
    at = datetime(2026, 11, 18, 14, 2)
    async with app.run_test(size=(120, 30)) as pilot:
        bar = app.query_one(StatusBar)
        cases = [
            (SyncStatus().started(), "syncing…"),
            (SyncStatus().succeeded(at), "✓ synced 14:02"),
            (
                SyncStatus().succeeded(at).failed(ConnectionError("no route")),
                "offline · last sync 14:02",
            ),
            (SyncStatus().failed(ValueError("HTTP 500")), "sync failed: HTTP 500 · never synced"),
        ]
        for status, expected in cases:
            app.sync_status = status
            bar.refresh()
            await pilot.pause()
            assert expected in bar_text(app)


def test_offline_vs_failed() -> None:
    assert SyncStatus().failed(TimeoutError()).state is SyncState.OFFLINE
    assert SyncStatus().failed(RuntimeError("x")).state is SyncState.FAILED


async def test_statusbar_shows_pending_count(make_app) -> None:
    app = make_app()
    async with app.run_test(size=(120, 30)) as pilot:
        assert "pending" not in bar_text(app)
        start = datetime.combine(TODAY, time(15), local_zone())
        app.save_event(Event("new", "work", "Coffee", start, start + timedelta(minutes=30)))
        await pilot.pause()
        assert "↑1 pending" in bar_text(app)


async def test_statusbar_shortens_instead_of_cutting_the_help_key(make_app) -> None:
    app = make_app()  # QA4 #15: offline with a pending edit at 100 columns
    async with app.run_test(size=(100, 30)) as pilot:
        app.sync_status = SyncStatus(SyncState.OFFLINE, datetime(2026, 11, 21, 18, 49))
        start = datetime.combine(TODAY, time(15), local_zone())
        app.save_event(Event("new", "work", "Coffee", start, start + timedelta(minutes=30)))
        await pilot.pause()
        text = bar_text(app)
        assert len(text) <= 100 and text.rstrip().endswith("? help")
        assert "↑1" in text and "offline" in text
        await pilot.resize_terminal(60, 30)
        await pilot.pause()
        text = bar_text(app)
        assert len(text) <= 60 and text.rstrip().endswith("? help") and "2026" not in text


async def test_help_pages_and_jumps(make_app) -> None:
    app = make_app()  # QA4 #20
    async with app.run_test(size=(100, 35)) as pilot:
        await pilot.press("question_mark")
        panel = app.screen.query_one("#help-panel")
        assert panel.max_scroll_y > 0
        for key in ("end", "G", "space", "pagedown"):
            await pilot.press("home")
            await pilot.pause(0.3)
            assert panel.scroll_y == 0
            await pilot.press(key)
            await pilot.pause(0.3)
            assert panel.scroll_y > 0, key
        await pilot.press("g")
        await pilot.pause(0.3)
        assert panel.scroll_y == 0


def help_lines(app) -> list[str]:
    table = app.screen.query_one(KeyTable)
    return [table.render_line(y).text for y in range(table.size.height)]


def test_split_columns_balances_and_keeps_order() -> None:
    heights = [14, 14, 21, 4, 6]
    assert split_columns(heights, 1) == [[0, 1, 2, 3, 4]]
    assert split_columns(heights, 2) == [[0, 1], [2, 3, 4]]
    three = split_columns(heights, 3)
    assert sorted(i for column in three for i in column) == [0, 1, 2, 3, 4]
    assert max(sum(heights[i] for i in column) for column in three) == 21
    assert split_columns([5], 2) == [[0], []]


async def test_help_is_one_column_when_narrow(make_app) -> None:
    for width in (70, 80):
        app = make_app()
        async with app.run_test(size=(width, 35)) as pilot:
            await pilot.press("question_mark")
            await pilot.pause()
            assert app.screen.query_one("#help").region.width == width * 9 // 10
            lines = help_lines(app)
            titles = [line.strip() for line in lines if line.strip() in GROUPS]
            assert titles == list(GROUPS)  # each on a line of its own
            panel = app.screen.query_one("#help-panel")
            await pilot.press("j")
            await pilot.pause(0.3)
            assert panel.scroll_y > 0
            await pilot.press("k")
            await pilot.pause(0.3)
            assert panel.scroll_y == 0


async def test_help_uses_columns_when_wide(make_app) -> None:
    for width, count in ((120, 2), (200, 3)):
        app = make_app()
        async with app.run_test(size=(width, 50)) as pilot:
            await pilot.press("question_mark")
            await pilot.pause()
            box = app.screen.query_one("#help")
            assert box.region.width == min(width * 9 // 10, 170)
            lines = help_lines(app)
            titles = [line for line in lines if sum(f" {t} " in f" {line} " for t in GROUPS) > 1]
            assert sum(title in titles[0] for title in GROUPS) == count
            # All of it is visible, nothing is cut off.
            assert app.screen.query_one("#help-panel").max_scroll_y == 0
            words = set(" ".join(lines).split())
            assert all(set(d.split()) <= words for rows in GROUPS.values() for _, d in rows)


async def test_help_relayouts_on_resize(make_app) -> None:
    app = make_app()
    async with app.run_test(size=(200, 35)) as pilot:
        await pilot.press("question_mark")
        await pilot.pause()
        wide = app.screen.query_one(KeyTable).size.height
        await pilot.resize_terminal(80, 35)
        await pilot.pause()
        assert app.screen.query_one(KeyTable).size.height > wide
        assert app.screen.query_one("#help-panel").max_scroll_y > 0
