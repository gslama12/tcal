# tcal

Terminal calendar (Python ≥3.11 + Textual) syncing with iCloud via CalDAV.
Architecture and decisions: `docs/PLAN.md` (the contract — record deviations there).

## Run & test

```sh
uv sync
uv run tcal --demo             # TUI with sample data (FakeProvider)
TCAL_HOME=.tcal uv run tcal    # isolated instance: config/data/cache under ./.tcal
uv run pytest -q
uv run ruff check && uv run ruff format --check && uv run mypy
```

## Layout

- `tcal/config.py` + `default_config.toml` — TOML defaults merged with the user file;
  typed frozen dataclasses; unknown settings are errors.
- `tcal/paths.py` — XDG dirs, or everything under `$TCAL_HOME`.
- `tcal/model.py` — `Calendar`, `Event`, `Occurrence` (aware datetimes, end exclusive).
- `tcal/providers/` — `Provider` protocol (`base.py`), `fake.py` demo/test data.
- `tcal/source.py` — `EventSource`: the only way the UI gets data
  (`calendars()`, `occurrences(start_day, end_day)`).
- `tcal/ui/app.py` — `TcalApp`: layout, bindings, data seam, state changes.
- `tcal/ui/state.py` — immutable `AppState` (selected `day`, `view`, `hidden_calendars`).
- `tcal/ui/keys.py` — `binding(action)`: every configurable binding has `id == action`
  from `[keys]`; the app applies the user's keys with `set_keymap`.
- `tcal/ui/theme.py`, `styles.tcss` — todooit palettes as Textual themes
  (`$background1..3`, `$foreground1..3`, `$red`… plus `$primary`/`$secondary`).
- `tcal/ui/widgets/` — one widget per module; subclass `TcalWidget`/`CalendarView`
  from `base.py` and redraw in `on_state`.

## Conventions

- Widgets never mutate state directly: call `app.select_date/set_view/toggle_calendar`;
  after a data change call `app.refresh_data()`. Watching `app.state` is the one redraw signal.
- New keybinds: add the action to `[keys]` in `default_config.toml`, declare it with
  `binding("action")`, implement `action_<name>`.
- Tests: pytest + Textual pilot; `conftest.py` isolates `TCAL_HOME` per test; no network,
  no real keyring. Use the `make_app` / `provider` fixtures (fixed date `TODAY`).
- Keep modules small, typed, no dead code.
