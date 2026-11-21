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
- **D1a (backend):** recurrence is expanded with python-dateutil (`recurrence.py`), not
  recurring-ical-events (dropped): the cache holds parsed `Event`s, so expanding them
  directly avoids re-parsing iCalendar on every redraw. Series expand in the wall-clock
  time of their own zone (DST-safe); UNTIL in any form is handled.

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

### Scaffold notes (package 1)

- **S1 Data seam:** `tcal/source.py` defines `EventSource` (`calendars()`,
  `occurrences(start_day, end_day)`); `TcalApp` takes one. `ProviderSource` (provider +
  dateutil expansion) backs `--demo` until the backend swaps in store + recurrence.py.
- **S2 Keybinds:** `dd` (delete) is not a default: `d` is the day view and Textual has no
  chords; delete is `x`. Bindings use Textual keymaps (`Binding.id == [keys] action`).
- **S3 State:** `AppState` is frozen; `TcalApp.state` is a reactive (`always_update`), so
  `refresh_data()` re-fires watchers. The selected day field is `day`.
- **S4 Time:** model datetimes are tz-aware; all-day events are local midnight → next
  midnight (exclusive). `Occurrence` times are converted to local time.

### Backend notes (package 2)

- **B1 Model:** `Event` gained `exdates` (deleted instances) and `raw` (the resource's
  iCalendar text, `compare=False`). `ics.to_ics` writes edits into `raw`, so alarms,
  attendees and server-side overrides survive. Times are stored with their named zone;
  `tcal/tz.py` gives the DST-aware local zone (`local_zone()`, `local_midnight()`).
- **B2 Data seam:** `ProviderSource` is gone; `StoreSource(Store)` reads the SQLite cache +
  `recurrence.expand`. `EventSource` gained `save_event` / `delete_event(uid, occurrence)`.
  UI code calls `app.save_event(event)` / `app.delete_event(uid, occurrence)` (cache write,
  redraw, background push). For one instance of a series pass its original start:
  `occ.event.recurrence_id or occ.start`.
- **B3 Sync:** `TcalApp(source, config, sync=sync_job(...))` runs the job in a thread worker on
  start, every `[sync] interval`, on `r` and after edits; `app.sync_status` is shown in the
  status bar. The worker opens its own `Store` connection (SQLite WAL).
  Conflicts (412 / etag mismatch): server wins, logged, op dropped. Other errors abort the
  sync and keep the queue. Moving an event to another calendar = delete there + create here.
- **B4 iCloud:** `ICloudProvider` (plain WebDAV on the caldav client; discovery by caldav).
  Calendar ids are collection URLs; VTODO-only lists are skipped; read-only from
  `current-user-privilege-set`; order from Apple's `calendar-order`.
- **B5 Demo:** `tcal --demo` syncs a `FakeProvider` into `data/demo.db` (recreated each run)
  through the same store/sync path; the real cache is never touched.

### Views notes (package 4)

- **V1 Messages:** `tcal/ui/messages.py` defines `NewEventRequested(start: date | datetime)`
  (a `date` = a whole day, from month/year views) and `EventSelected(occurrence)`. Views post
  them; the app (crud package) handles `on_new_event_requested` / `on_event_selected`.
- **V2 Shared helpers:** `tcal/ui/calgrid.py` (pure month-grid date math, occurrences per
  day), `widgets/minimonth.py` (small month block for MiniCal + YearView),
  `widgets/day_cursor.py` (`DayCursorView`: h/l ±1 day, j/k ±1 week, enter → Day view).
  `state.add_months` is now public (was `_add_months`).
- **V3 Keys:** new `[keys] toggle_calendar = ["space"]` (calendar list; enter works too).
  MiniCal reuses `cursor_*`/`prev_period`/`next_period`/`open` with its own cursor that
  only commits on enter (click commits at once).
- **V4 Titles:** kept the scaffold's `AppState.title()` format ("16 – 22 November 2026").

### Time grid notes (package 3)

- **T1 Messages:** views post `tcal.ui.messages.EventSelected(occurrence)` (enter / click on an
  event) and `NewEventRequested(start)` (enter on an empty slot, `new_event` key while a grid is
  focused). `TcalApp.on_event_selected` / `on_new_event_requested` are placeholders for CRUD.
- **T2 Keys:** new `[keys]` actions `next_event` (n) / `prev_event` (p) cycle through the events
  in view (by day, all-day first, then start time).
- **T3 Zoom:** levels 1, 2, 3, 4, 6, 8 rows/hour (3 = 20-min slots fits ~53-row grids); cursor
  and scroll position are kept in minutes so they survive zoom and resize.
- **T4 Strip:** all-day events and timed events lasting ≥ 24 h are bars in the all-day strip
  (max 3 lanes, "+N" in the axis for the rest); shorter events crossing midnight are split.

### Help + status bar notes

- **H1 Sync status:** `app.sync_status` is a `tcal.ui.sync_status.SyncStatus` (state off /
  syncing / synced / offline / failed, `last_sync`, `error`), not a string. Errors that are
  `OSError`s (connection, timeout) count as offline. Status bar: view badge · selected date ·
  sync status, `↑N pending` (new `EventSource.pending_count()` / `Store.pending_count()`), help key.
- **H2 Help:** `HelpScreen(config.keys)` lists the active keymap grouped by `help.GROUPS`;
  actions not listed there (new `[keys]` entries) appear under "Other" — add them to GROUPS.

### Goto / search notes (package 5)

- **G1 Goto:** `tcal/ui/screens/goto.py` `parse_date(text, today)`; dates without a year are in
  today's year, a weekday means the next one after today; `+Ny` works besides d/w/m.
- **G2 Search:** searches the visible calendars over the sync window (today − past_months ..
  + future_months); a series is listed once (its next instance). `app.show_occurrence(occ)`
  opens the day view with `occ` selected via the new public `TimeGrid.select(occ)`.

### Detail notes (package 5, detail)

- **E1 Detail:** `screens/event_detail.py`: `EventDetail(occ)` opens from `on_event_selected`
  (e edit, x delete, esc/q close). `confirm_delete(app, occ)` is the one delete flow (also the
  app's `x`): read-only calendar -> notice; recurring -> o "this occurrence" / s "whole series".
- **E2 Selection:** `app.selected_occurrence()` = the focused day/week grid's `selected`;
  month/year views have no event cursor, so `x`/`e` there say "No event selected" / do nothing.
- **E3 Edit hook:** `TcalApp.edit_occurrence(occ)` is the placeholder the event form replaces;
  both `e` in the detail modal and the app's `edit_event` action call it.
