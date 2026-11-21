# tcal — implementation plan & decision log

Terminal calendar (Python + Textual) that syncs with iCloud via CalDAV.
Look & feel modelled on todooit; layout modelled on the Google Calendar web app.

> GitHub issues were not available (gh CLI not authenticated), so decisions are
> tracked here instead. Each work package below = one "issue".

## Architecture (keep it simple)

```
tcal/
  __main__.py        click CLI: `tcal` (TUI), `tcal login`, `tcal sync`, `tcal --demo`
  paths.py           XDG paths; TCAL_HOME env var relocates config/data/cache into one dir
  config.py          TOML config (~/.config/tcal/config.toml) merged over defaults:
                     account, theme, keybinds, view settings (day_start "06:30", day_end "24:00",
                     row height / zoom, week_start, default view)
  model.py           dataclasses: Calendar(id, name, color, visible, readonly),
                     Event(uid, calendar_id, summary, start, end, all_day, location,
                           description, rrule, recurrence_id, etag, href) ; Occurrence(event, start, end)
  store.py           SQLite cache (stdlib sqlite3): calendars, events (raw ICS + parsed fields),
                     pending ops queue (create/update/delete) for offline edits
  recurrence.py      expand events (RRULE/EXDATE/RECURRENCE-ID) into Occurrences for a date range
  providers/
    base.py          Provider protocol: list_calendars(), fetch_events(cal, start, end),
                     create/update/delete_event(...)
    icloud.py        CalDAV via `caldav` lib, https://caldav.icloud.com, Apple ID + app-specific pw
    fake.py          in-memory provider for tests and `--demo`
  sync.py            SyncEngine: push pending ops, then pull window (today -3 months .. +12 months);
                     runs in a Textual worker, periodic (config interval)
  credentials.py     password from: keyring -> `password_cmd` in config -> TCAL_PASSWORD env
  ui/
    app.py           TcalApp: layout, bindings from config, state (current date, view, cursor)
    theme.py         palette (todooit look: dark bg1/bg2/bg3, fg1-3, accent colors), Textual Theme
    styles.tcss
    widgets/
      minical.py     small month calendar (sidebar top)
      calendar_list.py  toggleable calendar list with colors (sidebar)
      view_switcher.py  Day | Week | Month | Year tabs + current range title + "Today"
      timegrid.py    Day & Week views: time axis, default 06:30–24:00, vertical zoom (+/-),
                     scroll, all-day strip, overlap columns, now-line, slot cursor
      month_view.py  6x7 grid with event chips, "+N more"
      year_view.py   12 mini-months, days with events highlighted
      statusbar.py   mode / sync status / hints (todooit-like bar)
    screens/
      event_form.py  modal: create/edit (title, calendar, date, start, end, all-day, location, notes)
      event_detail.py  modal: view event, e=edit, d=delete
      help.py        keybinding list
      goto.py        jump to date (natural-ish parsing: "tomorrow", "2026-12-24", "fri")
      search.py      search events in cache
tests/               pytest + pytest-asyncio, Textual pilot tests, fake provider
```

## Key decisions

- **D1 Stack:** Python ≥3.11, uv, textual, caldav, icalendar, python-dateutil,
  recurring-ical-events, click, keyring, tomllib (stdlib). Dev: pytest, pytest-asyncio, ruff, mypy.
- **D2 iCloud auth:** CalDAV with Apple ID + **app-specific password** (appleid.apple.com).
  No 2FA flow needed. Stored in system keyring via `tcal login`.
- **D3 Offline-first:** UI only reads the SQLite cache; sync runs in the background and
  refreshes the UI on completion. Edits are written to cache + pending-op queue, then pushed.
- **D4 Recurring events:** expanded at read time (recurrence.py). Editing a recurring
  event edits the whole series (v1); deleting offers "this occurrence" (EXDATE) or "series".
- **D5 Time grid:** default visible range 06:30–24:00; zoom changes rows-per-hour (1..8),
  default chosen to fit the terminal height; `day_start`/`day_end` configurable; scrolling
  can reveal 00:00–06:30.
- **D6 Keybinds:** vim-like, all configurable in `[keys]` of config.toml (action -> list of keys).
  Defaults: h/j/k/l move cursor, H/L prev/next period, t today, d/w/m/y switch view,
  +/- (or ctrl+up/down) zoom, enter open, a/o new event, e edit, x/dd delete, g goto date,
  / search, r sync, c toggle calendar list focus, tab cycle focus, ? help, q quit.
- **D7 Mouse:** click date in minical, click calendar checkbox, click view tabs,
  click event to open, click slot to select. No drag & drop.
- **D8 Look:** todooit palette & rounded borders, focused pane gets accent border,
  event blocks use calendar color as background.
- **D9 Multi-provider later:** everything goes through `providers/base.py`.

## Work packages (≈ issues)

| # | Package | Owner | Branch |
|---|---------|-------|--------|
| 1 | Scaffold: pyproject, package skeleton, paths, config, model, theme, app shell with placeholder panes, fake provider, test infra, CLAUDE.md | agent `scaffold` | feat-scaffold |
| 2 | Backend: store, recurrence, iCloud provider, sync engine, credentials, `tcal login/sync` | agent `backend` | feat-backend |
| 3 | Time grid (day/week) | agent `timegrid` | feat-timegrid |
| 4 | Sidebar (minical, calendar list), view switcher, month & year views | agent `views` | feat-views |
| 5 | Event CRUD screens, detail, goto, search, help, keybind wiring, status bar | agent `crud` | feat-crud |
| 6 | Integration, README, polish, review fixes | orchestrator + agent `review` | feat-polish |

Order: 1 → (2, 3, 4 in parallel) → 5 → 6.
