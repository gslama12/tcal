# tcal

Terminal calendar (Python ≥3.11 + Textual) syncing with iCloud via CalDAV.
Architecture and decisions: `docs/PLAN.md` (the contract — record deviations there).

## Run & test

```sh
uv sync
uv run tcal --demo             # TUI with sample data (FakeProvider)
TCAL_HOME=.tcal uv run tcal    # isolated instance: config and data under ./.tcal
uv run pytest -q
uv run ruff check && uv run ruff format --check && uv run mypy
```

## Layout

- `tcal/config.py` + `default_config.toml` — TOML defaults merged with the user file;
  typed frozen dataclasses; unknown settings are errors.
- `tcal/paths.py` — XDG dirs, or everything under `$TCAL_HOME`.
- `tcal/model.py` — `Calendar`, `Event`, `Occurrence` (aware datetimes, end exclusive).
- `tcal/providers/` — `Provider` protocol + errors (`base.py`), `icloud.py` CalDAV,
  `fake.py` demo/test data (goes through iCalendar text and checks etags, like a server).
- `tcal/ics.py` — iCalendar text <-> `Event` (edits are written into `Event.raw`).
- `tcal/recurrence.py` — `expand(events, start, end)` -> `Occurrence`s; `tcal/tz.py` local zone.
- `tcal/store.py` — SQLite cache + pending-ops queue; `tcal/sync.py` — `SyncEngine`, `sync_job`.
- `tcal/credentials.py` — password: keyring -> `password_cmd` -> `$TCAL_PASSWORD`.
- `tcal/source.py` — `EventSource`/`StoreSource`: the only way the UI gets data
  (`calendars()`, `occurrences(start_day, end_day)`, `save_event`, `delete_event`).
- `tcal/ui/app.py` — `TcalApp`: layout, bindings, data seam (incl. `save_event`/
  `delete_event`/`undo`), sync, state changes, thin `action_*` methods.
- `tcal/ui/editing.py` — `Editor` (`app.editor`): event form, quick add, yank/paste/
  duplicate, moving; `tcal/ui/undo.py` — `UndoHistory` (`app.history`);
  `tcal/ui/clipboard.py` — pure event transforms (`copy_at`, `shifted`, `instance_of`).
- `tcal/ui/state.py` — immutable `AppState` (selected `day`, `view`, `hidden_calendars`).
- `tcal/ui/keys.py` — `binding(action)`: every configurable binding has `id == action`
  from `[keys]`; the app applies the user's keys with `set_keymap`.
- `tcal/ui/theme.py`, `styles.tcss` — todooit palettes as Textual themes
  (`$background1..3`, `$foreground1..3`, `$red`… plus `$primary`/`$secondary`).
- `tcal/ui/timelayout.py` — time-grid geometry (`TimeScale`, blocks, bars, `sub_columns`);
  `tcal/ui/timepaint.py` — pure `paint(GridFrame, w, h)` for Day/Week, on `canvas.Canvas`.
  `tcal/ui/flash.py` — flash jump (`f`): targets, labels, overlay over painted lines.
  `widgets/timegrid.py` keeps cursor/scroll/zoom/selection/mouse/flash keys only.
- `tcal/ui/widgets/` — one widget per module; subclass `TcalWidget`/`CalendarView`
  from `base.py` and redraw in `on_state`.

## Conventions

- Widgets never mutate state directly: call `app.select_date/set_view/toggle_calendar`;
  edit data with `app.save_event/delete_event` (they refresh and sync);
  after other data changes call `app.refresh_data()`. Watching `app.state` is the one redraw signal.
- New keybinds: add the action to `[keys]` in `default_config.toml`, declare it with
  `binding("action")`, implement `action_<name>`.
- Tests: pytest + Textual pilot; `conftest.py` isolates `TCAL_HOME` per test; no network,
  no real keyring (`memory_keyring` fixture). Use the `make_app` / `provider` / `store`
  fixtures (fixed date `TODAY`; `store` is the cache synced once from `provider`).
- Keep modules small, typed, no dead code.
