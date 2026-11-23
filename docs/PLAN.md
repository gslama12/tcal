# tcal — implementation plan & decision log

Terminal calendar (Python + Textual) that syncs with iCloud via CalDAV.
Look & feel modelled on todooit; layout modelled on the Google Calendar web app.

> GitHub issues were not available (gh CLI not authenticated), so decisions are
> tracked here instead. Each work package below = one "issue". Notes are a log: a later
> note overrides an earlier one (stale details are marked *superseded*).

## Status (2026-11-21)

- **Done:** all six work packages plus QA rounds 1–4. Day/week/month/year/schedule views,
  sidebar, event CRUD (incl. recurring scopes, repeat ends), detail extras, quick add,
  yank/paste/duplicate/move, undo stack (20), goto, search, help, iCloud CalDAV sync with
  offline queue, subscriptions, `tcal login|sync|calendars|doctor|config`, five themes.
  User docs: README.md (key table from `scripts/keys_table.py`, checked by `tests/test_readme.py`).
- **Not verified:** everything against a real iCloud account (only the fake server in
  `tests/icloud_http.py`) — see README "What I need you to test".
- **Open:** no log file — `logging` warnings from sync (skipped resources) are not visible
  anywhere (H1); no "this and following" edit scope (H2); no drag & drop (D7); one provider
  only (D9).

## Architecture (keep it simple)

```
tcal/
  __main__.py        click CLI: `tcal` (TUI, `--demo`), `tcal login|sync|calendars|doctor`,
                     `tcal config path|edit|check`
  dates.py           pure date helpers: parse_date (goto, quick add, form), add_months
  quickadd.py        quick-add one-line parser
  doctor.py          `tcal doctor` checks
  ics.py             iCalendar text <-> Event (edits written into Event.raw), extras
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
    ics_url.py       read-only `[[subscription]]` feeds (webcal/https)
  sync.py            SyncEngine: push pending ops, then pull window (today -3 months .. +12 months);
                     runs in a Textual worker, periodic (config interval)
  credentials.py     password from: keyring -> `password_cmd` in config -> TCAL_PASSWORD env
  source.py          EventSource / StoreSource: the UI's only data access
  tz.py              local zone
  ui/
    app.py           TcalApp: layout, bindings from config, data seam, sync, actions
    state.py         immutable AppState (day, view, hidden calendars)
    keys.py          binding(action): Binding.id == [keys] action
    editing.py       Editor: form, quick add, yank/paste/duplicate, moves, resizes
    undo.py          UndoHistory (undo + redo); clipboard.py: pure event transforms
    timelayout.py    time-grid geometry; timepaint.py: pure painting; canvas.py; calgrid.py
    sync_status.py   SyncStatus for the status bar
    theme.py         palette (todooit look: dark bg1/bg2/bg3, fg1-3, accent colors), Textual Theme
    styles.tcss
    widgets/
      minical.py     small month calendar (sidebar top)
      calendar_list.py  toggleable calendar list with colors (sidebar)
      view_switcher.py  Day | Week | Month | Year tabs + current range title + "Today"
      timegrid.py    Day & Week views: cursor/scroll/zoom/selection/mouse (drawing: timepaint)
      month_view.py  6x7 grid with event chips, "+N more"
      year_view.py   12 mini-months, days with events highlighted
      schedule_view.py  upcoming events as a list (A1)
      minimonth.py, day_cursor.py, base.py  shared view helpers
      statusbar.py   mode / sync status / hints (todooit-like bar)
    screens/
      main.py        the base screen (no tab focus cycling)
      event_form.py  modal: create/edit (title, calendar, date, start, end, all-day, location, notes)
      event_detail.py  modal: view event, e=edit, x=delete
      help.py        keybinding list
      goto.py        jump to date prompt (parser: `tcal/dates.py`)
      search.py      search events in cache
      quick_add.py   one-line quick add with preview
      prompt.py      the one y/n / scope question box
tests/               pytest + pytest-asyncio, Textual pilot tests, fake provider
```

## Key decisions

- **D1 Stack:** Python ≥3.11, uv, textual, caldav, icalendar, python-dateutil,
  recurring-ical-events, click, keyring, tomllib (stdlib). Dev: pytest, pytest-asyncio, ruff, mypy.
- **D2 iCloud auth:** CalDAV with Apple ID + **app-specific password** (appleid.apple.com).
  No 2FA flow needed. Stored in system keyring via `tcal login`.
- **D3 Offline-first:** UI only reads the SQLite cache; sync runs in the background and
  refreshes the UI on completion. Edits are written to cache + pending-op queue, then pushed.
- **D4 Recurring events:** expanded at read time (recurrence.py). Editing or deleting an
  instance asks "this event" (edit: an override VEVENT with RECURRENCE-ID; delete: EXDATE)
  or "all events" (the series' master). See F4.
- **D5 Time grid:** default visible range 06:30–24:00; zoom changes rows-per-hour (1..8),
  default chosen to fit the terminal height; `day_start`/`day_end` configurable; scrolling
  can reveal 00:00–06:30. The fitted default is a *fractional* rows-per-hour so that
  `day_start`..`day_end` fills the grid exactly (no empty rows below 24:00); its slot times are
  shown rounded up to 5 min. +/- step through the whole zoom levels; zoom-out stops before the
  day gets shorter than the grid.
- **D6 Keybinds:** vim-like, all configurable in `[keys]` of config.toml (action -> list of keys).
  Current defaults (`tcal/default_config.toml`, README table): h/j/k/l move cursor,
  H/L prev/next period, t today, d/w/m/Y/s day/week/month/year/schedule view, +/- zoom,
  enter open, n/N next/prev event, v grid mode (E1), a/i new event, A quick add, e edit,
  x delete, u undo, ctrl+r redo, y yank, p paste, D duplicate, J/K/</> move (ctrl+j/k/h/l too),
  , . end and ; : start earlier/later (R1), f flash
  jump (day/week), g goto date, / search, r sync, c focus calendar list, M focus mini month, space
  toggle calendar, tab mark event (batch copy, B1),
  b sidebar, ? help, q quit, ctrl+s save, esc cancel. (Originally `y` = year view and `dd`
  delete: see S2, Y1.)
- **D7 Mouse:** click date in minical, click calendar checkbox, click view tabs,
  click event to open, click slot to select. No drag & drop.
- **D8 Look:** todooit palette & rounded borders, focused pane gets accent border,
  event blocks use calendar color as background.
- **D9 Multi-provider later:** everything goes through `providers/base.py`.
- **D1a (backend):** recurrence is expanded with python-dateutil (`recurrence.py`), not
  recurring-ical-events (dropped): the cache holds parsed `Event`s, so expanding them
  directly avoids re-parsing iCalendar on every redraw. Series expand in the wall-clock
  time of their own zone (DST-safe); UNTIL in any form is handled.
- Unknown theme (QA2 #1): the TUI falls back to the default theme with a warning notice
  instead of refusing to start; `tcal config check` still reports it as an error.
- Sidebar (QA2 #9/#11): the toggle key pins the user's choice (resizes no longer change it);
  unpinned on a narrow terminal, a sidebar shown by `focus_calendars` hides again when focus
  leaves it. (Text in calendar colours: see "Colour polish".)
- Flash jump (`f`, day/week): `tcal/ui/flash.py` (pure: targets from the `GridFrame`, labels,
  overlay over the painted lines; `timepaint` untouched). todooit's alphabet and red labels, but
  labels mix single keys and pairs (prefix-free) so the targets nearest the cursor get one key;
  targets are events (incl. all-day bars) plus each column's hours, and half hours at ≥2
  rows/hour. While labels are up the grid's `on_key` swallows every key; a non-label key
  cancels and is used up (as in todooit).

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
  `state.add_months` is now public (was `_add_months`; *moved to `tcal/dates.py`*, rev2b).
- **V3 Keys:** new `[keys] toggle_calendar = ["space"]` (calendar list; enter works too).
  MiniCal reuses `cursor_*`/`prev_period`/`next_period`/`open` with its own cursor that
  only commits on enter (click commits at once).
- **V5 Year layout (QA #7):** all 12 months always shown, as 4x3 / 3x4 / 2x6 — whichever
  gives the largest day cells; cells scale up (`mini_month(cell=, row_height=)`) and the gaps
  spread to fill the panel, with ≥ 1 blank line between rows. If no grid fits (e.g. 100x35),
  the weekday initials are dropped first, then the blank lines (no scrolling).
- **V4 Titles:** kept the scaffold's `AppState.title()` format ("16 – 22 November 2026").

### Time grid notes (package 3)

- **T1 Messages:** views post `tcal.ui.messages.EventSelected(occurrence)` (enter / click on an
  event) and `NewEventRequested(start)` (enter on an empty slot, `new_event` key while a grid is
  focused), handled by `TcalApp.on_event_selected` / `on_new_event_requested`.
- **T2 Keys:** new `[keys]` actions `next_event` (n) / `prev_event` (p) cycle through the events
  in view (by day, all-day first, then start time). *Superseded: prev is `N` (Y1).*
- **T3 Zoom:** levels 1, 2, 3, 4, 6, 8 rows/hour (3 = 20-min slots fits ~53-row grids); cursor
  and scroll position are kept in minutes so they survive zoom and resize.
- **T5 Fit (QA #1/#4–6):** a minute belongs to the row whose start is *nearest* (ties: earlier
  row) — event tops/bottoms, hour labels, cursor and now-line all round the same way, so
  back-to-back events never share a row and starts sit on their hour label. Fitted (uneven)
  slots show the roundest :00/:30/:15/:05 minute of the row (15-min snapping while rows are
  ≥ 15 min); zoom levels keep their exact slot starts (e.g. :20 at 3 rows/h). The fit is one stop
  on the `+`/`-` ladder (choosing it re-fits and puts `day_start` on top). Each column shows
  `▲ N earlier` / `▼ N later` (or `▲N`) for timed events scrolled out of view.
- **T6 Overlaps (QA #2/#3/#8), superseded by "Stacked blocks" below:** clusters needing blocks
  narrower than `MIN_WIDTH` (4) in the narrowest day column collapse into one `Block` with `group`
  (its events by start): drawn as "N events" (plus the selected event's title/time), enter/click
  opens the first, n/p cycle through them. The now-line `●` replaces the column's divider.
- **T4 Strip:** all-day events and timed events lasting ≥ 24 h are bars in the all-day strip
  (max 3 lanes, "+N" in the axis for the rest); shorter events crossing midnight are split.

### Help + status bar notes

- **H1 Sync status:** `app.sync_status` is a `tcal.ui.sync_status.SyncStatus` (state off /
  syncing / synced / offline / failed, `last_sync`, `error`), not a string. Errors that are
  `OSError`s (connection, timeout) count as offline. Status bar: view badge · selected date ·
  sync status, `↑N pending` (new `EventSource.pending_count()` / `Store.pending_count()`), help key.
- **H2 Help:** `HelpScreen(config.keys)` lists the active keymap grouped by `help.GROUPS`;
  actions not listed there (new `[keys]` entries) appear under "Other" — add them to GROUPS.
  One column; the box is as wide as its longest line needs (`line_width`), so lines wrap only
  on terminals narrower than that.

### Goto / search notes (package 5)

- **G1 Goto:** `tcal/ui/screens/goto.py` `parse_date(text, today)`; everything is relative to
  the real today, not the selected day (QA #18): dates without a year are in today's year, a
  weekday means the next one after today, `+2w` counts from today; `+Ny` works besides d/w/m.
- **G2 Search:** searches the visible calendars over the sync window (today − past_months ..
  + future_months); a series is listed once (its next instance). `app.show_occurrence(occ)`
  keeps the current view (QA2 #7): goes to `occ`'s day, selects it via `select(occ)`
  (TimeGrid / MonthView / ScheduleView) and opens its detail, like Google.

### Detail notes (package 5, detail)

- **E1 Detail:** `screens/event_detail.py`: `EventDetail(occ)` opens from `on_event_selected`
  (e edit, x delete, esc/q close). `confirm_delete(app, occ)` is the one delete flow (also the
  app's `x`): read-only calendar -> notice; recurring -> o "this event" / s "all events".
- **E2 Selection:** `app.selected_occurrence()` = the focused day/week grid's or month view's
  `selected`; the year view has no event cursor, so `x`/`e` there say "No event selected".
- **E3 Edit hook:** `TcalApp.edit_occurrence(occ)` opens the event form (`edit_event(occ.event)`);
  both `e` in the detail modal and the app's `edit_event` action call it.

### Event form notes (package 5, form)

- **F1 API:** `app.new_event(start)` (datetime → 1 h slot; date → all-day, 09:00–10:00 prefilled
  for unticking) and `app.edit_event(event)` open `screens/event_form.EventForm`; the form
  returns the edited `Event` and the app saves it (`save_event`). Read-only calendar → notice.
  The `edit_event` key edits the focused view's `selected` occurrence (time grids only).
- **F2 Fields:** the end date is always shown (timed events may cross midnight); end follows a
  start change. Unchanged fields keep the event's own values (time zone, custom RRULE).
  Repeat none/daily/weekly/monthly/yearly ↔ `FREQ=…`; disabled for an overridden instance.
- **F3 Keys:** new `[keys] save = ["ctrl+s"]` (priority) and `cancel = ["escape"]`;
  `binding()` gained `priority`. Test apps that record view messages call `prevent_default()`
  so TcalApp's handlers don't also open the form.

### Form fixes (QA #12, #16, #17, #22)

- **F4 Edit scope:** `app.edit_occurrence(occ)` on a recurring event shows `EditScope`
  (o this event / s all events; shares `ScopeDialog` with `ConfirmDelete`). "This event" edits
  `app.instance_of(occ)` — the existing override, or the master copied with `recurrence_id` =
  the instance start (in the master's zone), no RRULE/EXDATEs; `Store.save_event` writes it into
  the resource. The form fixes repeat *and calendar* for an instance. "All events" edits the
  master (new `EventSource.get_event(uid)`). `FakeProvider.fetch_events` now returns every
  VEVENT of a resource (like CalDAV), so overrides survive a sync.
- **F5 New event key:** off the time grids (month/year view, sidebar) `a` makes a 1 h timed
  event at the next round hour (now + 1 h, max 23:00) on the selected day; in a day/week grid it
  uses the cursor slot. `app.new_event(date)` (all-day) stays for callers.
- **F6 Notices:** `app.check_writable(calendar_id)` is the one read-only check
  ("<Calendar> is read-only"), used by edit and delete. Form errors clear on any field change.

### Form/detail fixes (QA2 #6, #13–#16, #19)

- **F7 Vocabulary:** scopes are "This event (o) / All events (s)" for edit and delete; form
  titles "New event" / "Edit event" / "Edit this event" / "Edit all events" (a master with an
  RRULE). The series form keeps the series' dates (no shift-by-delta) and says so in `#note`.
- **F8 Repeat:** `REPEATS` maps choices to RRULEs and adds "Every weekday"
  (`FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR`); other rules show `describe_rrule` as the custom choice.
- **F9 Errors:** `FormError(message, field)`; the error `Static` moves below that field's row,
  the field gets `-invalid` (red border) and focus. Dates parse with goto's `parse_date`.
- **F10 Discard:** esc with changed fields (`values() != shown`) asks `ConfirmDiscard` (y/n).
  Read-only events' detail hints only "esc close". The all-day box is empty when off, ✓ on.

### Month view notes (QA #9–#11)

- **M1 Cursor:** `MonthView.selected` (n/p over the shown chips of the displayed month's days,
  click on a chip); enter opens it, else the Day view; h/j/k/l drop it. Events hidden behind
  "+N more" and days of the adjacent months are skipped (selecting those would switch month).
- **M2 Layout:** `layout_week` packs all-day / ≥24 h events (`timegrid.is_bar`/`layout_bars`)
  into lanes per week row → one bar across the cells and borders, title once (◂/▸ when it
  continues); timed chips follow the day's bars. Week rows share the full height (rows differ
  by ≤1 line); spare columns go to the weekend; no side padding so separators meet the border.

### QA fixes (feat-misc)

- **Q1 Undo delete:** `Store.delete_event` returns the event's rows as they were;
  `Store.restore(rows)` puts them back (cancels an unpushed delete op, else re-creates the
  resource; a deleted instance updates the series again). `EventSource.restore` passes it
  through; `app.delete_event` toasts `Deleted "X" · u undo` and `[keys] undo = ["u"]`
  (`app.undo()`) restores the last delete once. *Superseded by the undo stack (Y4).*

### iCloud hardening (feat-icloud, partial)

- **I1 Review vs caldav 3.7:** discovery (principal → calendar-home-set) and the move to the
  `pNN-caldav.icloud.com` host are done by caldav; tcal drops the home-set's `:443` and rebases
  every href onto the home's host so calendar ids stay stable (iCloud may answer on caldav.icloud.com).
- **I2 Parsing:** only 200 propstats are read (missing props come as empty 404 ones); colors
  `#RRGGBBAA`/`#RRGGBB`/`#RGB` → `#RRGGBB`, anything else → default; etags stripped; a PUT answer
  without `ETag` is followed by a Depth-0 PROPFIND for it.
- **I3 Robustness:** client timeout 60 s (caldav default 10 s); REPORT per ~quarter, resources
  deduped by href; any unreadable resource is skipped with a warning; caldav `AuthorizationError`/
  `DAVError` → `ProviderError` (auth hint mentions the app-specific password).
- **I4 Doctor (feat-doctor):** `tcal doctor` (`tcal/doctor.py`) runs account → password
  (`credentials.find_password` names the source) → sign-in (`ICloudProvider.principal_url`) →
  calendar home → calendars → this week's occurrences per calendar → write access (from the
  privilege set, nothing is written); stops at the first failure with hints, exit 1.
  `providers.base.AuthError(ProviderError)` marks rejected credentials (401/403) so the
  app-specific-password hint can be shown.
- **I5 Fixtures:** `tests/icloud_http.py` is a fake iCloud *below* caldav (patched
  `DAVClient.session.request`, 401 + `WWW-Authenticate` without Basic auth, home-set on
  `p42-caldav.icloud.com:443`, `#RRGGBBAA`, VTODO list, 404 propstats, TZID / EXDATE / override
  / all-day ICS); used by `test_icloud_http.py` and `test_doctor.py`.
- **I6 ics edge cases:** an all-day event without DTEND or with DTEND <= DTSTART lasts one day;
  a timed event ending before it starts is clamped to an instant.

### Performance notes (feat-perf)

- **P1 Bench:** `scripts/bench.py` (5000 events / 3 years / 6 calendars, 100 series) prints CPU ms
  per keypress (headless 160x50). `TcalApp` caches `source.occurrences` per day range until
  `refresh_data()` (so any data change must go through it); `recurrence._rules` caches parsed
  rule sets (dateutil `cache=True`) keyed by (rrule, start, exdates).

### Config notes (feat-config)

- **C1 Config UX:** `tcal config path|edit|check`. `edit` seeds a missing file with
  `commented_defaults()` (every default line commented out). Key conflicts
  (`config.key_conflicts`: one key in several actions' lists) are not errors — they warn
  via `check` (non-zero exit) and a startup toast. Themes: tokyo-night (default,
  todooit's palette), nord, gruvbox, catppuccin-mocha, catppuccin-latte (light: `theme.LIGHT`, `dark=False`);
  timegrid `_readable` now sorts its text colors by luminance so light palettes work.

### Schedule view notes (feat-agenda)

- **A1 Schedule:** `ViewMode.SCHEDULE` (`[keys] view_schedule = ["s"]`, tab "Schedule",
  `default_view = "schedule"` allowed): `widgets/schedule_view.py` lists the days from the
  selected day (header per non-empty day, today accented; events: time range / "All day", colour
  dot, title, dim location). j/k and n/p step through events, h/l jump to the previous/next day's
  first event; the cursor's day becomes `state.day` without restarting the list, any other change
  of `state.day` (H/L = ±14 days, goto, minical, today) restarts it there. Loads `CHUNK_DAYS` (28)
  more when the cursor or the mouse wheel reaches the end (one load scans ≤ 366 days). Own scroll
  offset (no scrollbar), like the time grid. Title: the selected day's month. `selected` works
  with the app's e/x. The view switcher drops the tabs' padding when even the short title does
  not fit (5 tabs at 70 columns).

### UI review notes (feat-revui)

- **R1 Tidy-up (no behaviour change):** the time grid's pure geometry (`TimeScale`, `fit_scale`,
  `pack_*`, `layout_blocks`/`layout_bars`, `is_bar`, `Block`/`Bar`) moved from
  `widgets/timegrid.py` to `tcal/ui/timelayout.py` (the month view uses it too, like `calgrid.py`).
  Views with an event cursor use `keys.EVENT_BINDINGS` (n/p → `action_cycle(step)`, ids unchanged),
  `CalendarView.cursor_style()` and `base.join_lines()`; `app.calendar(id)` is the one lookup.

### Quick add notes (feat-quickadd)

- **QA1 Quick add:** `[keys] quick_add = ["A"]` → `screens/quick_add.QuickAddScreen` (one line +
  live preview; enter saves via `app.save_event`, tab opens `EventForm` prefilled, esc cancels).
  Pure parser `tcal/quickadd.parse(text, today, calendar_names) -> QuickAdd` reuses goto's
  `parse_date` (any run of ≤ 4 words, optional "on"; relative to the real today like G1).
  Pieces are taken out in order `#cal` (name prefix, writable calendars only; unknown → error in
  the preview) → `for 2h|90m|1h30` → time range / single time (needs `:mm`, am/pm or `h`; a bare
  "12" stays text) → date; what's left after a word-initial `@` is the location (so `@` may come
  before the date/time). No time → all-day (a duration is then ignored); end ≤ start → next day.
- **QA3 (feat-g2):** dates also take `next/last <weekday>` (that weekday in the next/previous
  Mon-based week, so on Wed "next fri" is 9 days away) and `in N days|weeks|months|years` (goto
  too). Quick add reads a date range `<date> - <date>` (runs of ≤ 9 words; `dec 30 - jan 2` rolls
  the end into the next year) as a multi-day event. New events default to the first *shown*
  writable calendar; saving into a hidden one (`#work`, the form) shows it again. `#` also
  matches read-only calendars (after the writable ones) to say "Holidays is read-only".
  Quick add's keys are `[keys] cancel` and `focus_next` (tab; a separate key would collide with
  it), shown in its hint; the form opened from it asks "Discard changes?" (`EventForm(edited=True)`).
  Month `n`/`N` without a selection start at the selected day, like the time grids.

### Clipboard & moving (feat-yank)

- **Y1 Keys:** `yank` (y), `paste` (p, P: same action), `duplicate` (D), `move_down/up` (ctrl+j/k,
  ±15 min, timed events in a time grid only) and `move_left/right` (ctrl+h/l, ±1 day, any view
  with a selection). To free y/p: **`view_year` is now `Y`, `prev_event` is `N`** (vim's n/N).
- **Y2 Behaviour:** `tcal/ui/clipboard.py` (`copy_at`, `shifted`). A paste/duplicate is a new
  one-off event (no RRULE/overrides) keeping the duration, in the source calendar or, if that is
  read-only, the first writable one; paste goes to the time grid's cursor slot, else the selected
  day at the event's time of day. Moves check `check_writable`; a series asks `MoveScope`
  (o this event = `instance_of` shifted / s all events = master shifted, EXDATEs along; existing
  overrides keep their RECURRENCE-IDs). The copy / moved event stays selected (`_select_moved`).

- **Y3 QA3 fixes (feat-g1):** views keep their pick by `Occurrence.key` (uid + start) and
  re-resolve it after a reload, so a sync's new etag no longer drops or swaps the selection.
  Default move keys are now **`J`/`K` (±15 min) and `<`/`>` (±1 day)**, `ctrl+j/k/h/l` stay as
  extras (`ctrl+h` arrives as backspace without the kitty protocol, see K5; tmux often takes ctrl+hjkl).
  An override moves without `MoveScope`; the scope answered for a series holds while the same
  occurrence keeps moving (`_move_run`, cleared by any other change). Paste/duplicate toast
  "Pasted “X” to Sun 22 · <calendar if different> · u undo".
- **Y4 Undo stack:** `app.save_event`/`delete_event` push an `UndoStep(uid, rows before, toast)`
  (`EventSource.rows(uid)`; at most `UNDO_DEPTH` = 20); `u` pops one: no rows → delete the
  created event, else `restore(rows)`. `Store.restore` now prefers an unpushed delete's old
  resource (also the one a move to another calendar queued) over the current row's href.

### Subscriptions + detail extras (feat-subs)

- **U1 Subscriptions:** `[[subscription]] name, url, color?` (`Config.subscriptions`, a list of
  tables, so `_merge` passes it through; `webcal://` → `https://`). `providers/ics_url.py`
  `IcsUrlProvider` (urllib, gzip bodies un-gzipped by magic bytes — Apple's holiday feeds) splits
  a feed into one resource per UID (+ the feed's VTIMEZONEs) so `raw` stays small; read-only.
  Calendar id = `model.SUBSCRIPTION_PREFIX + url` and `Calendar.subscribed` is derived from it
  (no store schema change). `SyncEngine(..., subscriptions=)` / `sync_job(..., subscriptions=)`
  pull feeds after the account; a failing feed (ProviderError/OSError) keeps its cache and is
  listed in `SyncSummary.failed`. Not used by `--demo` (no network). `CalendarList` shows feeds
  under "Other calendars".
- **U2 Detail extras:** `ics.extras(event)` → `Extras(organizer, attendees (name, PARTSTAT),
  url)` from `raw`. The detail
  shows `#timezone` (event zone + its times, only when its UTC offset differs from local),
  `#url`, `#people`. Alarms are not shown (the user doesn't use them; `ics.Alarm` and
  `#alarms` were removed); VALARMs stay in `raw` and survive edits.

### Detail, sync status, demo (feat-g3: QA3 #5, #6, #12, #14, #20)

- The detail's `#dialog` is a `VerticalScroll`; `#title`/`#hints` are docked so they stay put;
  `j`/`k` (`cursor_down/up`) scroll, the hints add "j/k scroll" when it overflows. `e`/`x` on a
  read-only event only toast, the detail stays open.
- `SyncStatus.failed_feeds` (from the worker's `SyncSummary`): status bar "⚠ synced 14:10 · X
  failed", a ⚠ after the feed in the calendar list; `conflicts` → a warning toast.
- `--demo` passes `fake.demo_feed()` (read-only "Team events" feed) as subscriptions; demo data
  has an invitation (Budget planning, yesterday), an alarm (Dentist) and a New York call.

### Visual polish (feat-g4, QA3 #15–#19, #21)

- **G4 Schedule:** a red now line (`HH:MM ●───`) sits in today's group before the first timed
  event starting after now (`build_rows(..., current)`, `schedule_view.now()` is the test seam;
  redrawn each minute); today's ended events are dimmed. While the schedule is shown, a list
  (re)start on an empty day moves `state.day` to the first day listed, so status/title match;
  H onto empty days loads earlier days instead of showing the same list again. A day header is
  never drawn on the last row. Time grid: titles word-wrap over the lines the time doesn't need
  (`_wrap`); `▲/▼ N` markers move one row in off the cursor/now row. Month chips/bars end cut
  titles with `…` (`widgets.base.fit`, shared with the grid). "Other calendars" is a rule with
  the title at the border title's column (the failing-feed marker is QA3 #5, not here).

### Structure cleanup (feat-rev2a)

- `app.py` split by responsibility: editing flows → `ui/editing.Editor` (composition,
  `app.editor`; the app keeps `new_event`/`edit_event`/`edit_occurrence` as one-line
  public entry points and the `action_*` methods, since bindings live on the app);
  undo stack + move run → `ui/undo.UndoHistory` (`app.history`); `instance_of` → `clipboard.py`.
- `timegrid.py` split: drawing → `ui/timepaint.py` (pure, takes a `GridFrame` snapshot),
  `Canvas` → `ui/canvas.py`, `sub_columns` → `timelayout.py`; its private `_readable`/`_luma`
  duplicated `theme.text_on`/`luma` and are gone. Behaviour unchanged.

### Tidy-up (feat-rev2b)

- `tcal/dates.py` holds the pure date helpers: `parse_date` (was in `ui/screens/goto.py`),
  `add_months` (was in `ui/state.py`; still importable from there), `WEEKDAYS`/`MONTHS`
  (also used by `config.py`). Quick add and the event form no longer import a UI screen.

### Form/detail vs. sync (feat-h1: QA4 #1, #5, #10, #12, #18)

- **H1 Form:** `#form` is a `VerticalScroll` (title in the border, `#hint` docked), so it
  scrolls to the focused field on short terminals. Saving toasts "Saved “X” · u undo"
  (quick add: "Added …"; `Editor.form_done(event, verb)`).
- **H2 Ends:** a series' "Ends" row (`#ends` never / on date / after + `#ends_value`) maps to
  `UNTIL` (all-day: a DATE; timed: the end of that local day in UTC) / `COUNT`;
  `split_end` / `end_rule` in `event_form.py`; `repeat_of` ignores the end, so
  `FREQ=WEEKLY;COUNT=5` is "Every week" + "After 5". No "this and following" scope (kept simple).
- **H3 Sync interplay:** the detail watches `app.state` and re-resolves its occurrence with
  `app.current_occurrence(occ)` (by key; a one-off also by uid after a move): newer version →
  recompose; gone → close + "“X” was deleted/changed on the server". The form snapshots the
  event's cache rows on mount (etag/href ignored, so our own push isn't a change); if they
  differ at save, `ServerChanged` asks o overwrite (rebased on the current etag/href, or created
  again if deleted) / d discard / esc back. `SyncSummary.conflicts` is now the list of titles,
  named in the toast. (`log.warning` reaching only stderr: fixed in feat-warn.)
- **H4 Detail wording:** durations "10 min" / "1 h" / "1 h 30 min"; people as "4 guests · 1 yes,
  1 maybe, 1 no, 1 awaiting" + one line per guest, the organizer marked, not repeated.

### Time grid fixes (feat-h2, QA4 #6–#8, #16)

- **H2 Cursor slot:** the cursor steps at least 15 min: at 8 rows/hour it covers two rows
  (`TimeGrid._cursor_rows()`, `GridFrame.cursor_rows`), so it never shows 7.5-min times; an
  event under either row is selected. Zooming adopts the shown time only when it is a
  quarter hour, so a level that can't show it (:20/:10 rows) doesn't make the cursor drift.
- Overlaps use `(row, minute)` edges: events overlap if their rows *or* their times do, so a
  30-min overlap that rounds to touching rows is still stacked.
- `timepaint.markers(frame, height)` places the `▲/▼` markers (also used for clicks): on the
  edge row, or the nearest row inwards that is not the cursor/now row and has room beside the
  events. Clicking one selects (and scrolls to) the first hidden event; it doesn't open it.

### QA4 fixes (feat-h3: #2, #9, #13, #15, #19, #20)

- Schedule now line is one row sized to the width (it wrapped, which broke the row arithmetic).
- **V5 amended:** when even the compact year grid is too tall (80x24), `Layout.build(w, h, show=)`
  scrolls so the selected month's row is visible, with ▲/▼ hints at the right edge.
- `widgets/base.SidebarWidget` (MiniCal, CalendarList): the `cancel` key focuses the main view
  (the narrow-terminal sidebar then hides as before). Clicking the minical's ‹ › still focuses it.
- Status bar: when the right side doesn't fit, "↑N pending" → "↑N", then the date is dropped;
  the date also slides left of centre before anything is cut.
- Search rows of a series add "· every week on Tue, Thu" (`describe_rrule`).
- Help: space/shift+space page, home/end and g/G jump (pageup/down already worked).

### Moves, toasts, quick add (feat-h4: QA4 #3, #4, #11, #14, #17)

- **H4:** `clipboard.shifted` shifts plain BYDAY weekdays by the
  days the start moves (an ordinal BYDAY like `2MO` returns None → "Change the days of this
  series in the form"). `app.save_event(event, undo_message)`: moves pass "Undid move of “X”
  (back to Mon 23 11:15)"; deletes toast "Deleted this “X” (Thu 19 09:00)" / "Deleted all “X”
  events". A failed sync toasts "Couldn't reach iCloud: … · r retry" when the sync key asked
  for it or nothing is cached yet (same error once in a row); `r` also toasts "Synced". With
  nothing synced yet, new events say "Not synced yet". Quick add reads repeats (`daily`,
  `every <weekday>`, `every weekday`, …; first day on/after the date), bare hours after a
  date, `14.30` (`H.MM` with MM ≤ 12 only when a date is given elsewhere) and `noon`/`midnight`.

### Sync warnings (feat-warn)

- **W1 Collect:** `tcal/synclog.py`: `collect()` gathers the WARNING+ records the sync's own thread
  logs under the `tcal` logger (so provider warnings like "skipping unreadable event" count too)
  into `SyncSummary.warnings`. Conflict/feed messages are now user-readable sentences.
- **W2 Toast:** after a sync, one line "N sync warning(s): <first> · R sync log" (replaces the
  conflicts toast); repeated only when the warnings change or the sync key asked (a feed failing on
  every periodic sync toasts once).
- **W3 Sync log:** `app.sync_log` (deque of `LogEntry(at, error, message)`, last 200, this session;
  failed syncs added as errors) shown by `SyncLogScreen` newest first. Key: **`R`**, not the
  brief's `L` — `L` is `next_period` (and `l` cursor right); `R` sits next to sync `r`.
- **W4 File:** `log_to_file(paths.log_file())` (`data/tcal.log`, rotating 256 kB, one backup) is
  attached by the CLI (TUI, `--demo`, `tcal sync`); `tcal sync` also prints each warning to stderr.

### Docs (feat-docs)

- README rewritten (features, commands, setup, config/themes, keys, subscriptions,
  troubleshooting, test list). The key table is generated by `scripts/keys_table.py` from the
  default keymap + `help.GROUPS` (so it matches `?`); `tests/test_readme.py` fails when it is
  stale or an action lacks a help description.

### Time grid fixes (feat-k1, QA5 #1, #4, #5, #16)

- A grid scrolls its cursor slot into view when shown or resized (`TimeGrid._show_cursor`):
  views are mounted hidden (no size), so opening week from schedule showed day_start only.
- *Supersedes the feat-h2 marker note:* `▲/▼` markers stay on the edge row (right of its
  events); if that row is the cursor/now row or has no room they go to the right end of the
  column's header line (`Marker.y` = widget line, 0 for the header). Never mid-grid.
- *(Superseded by "Stacked blocks": a covered block's text skips the rows its cover hides.)*
- The now line is not drawn into the 1-col gap beside an event.

### Keys round (ui-keys)

- `focus_minical` (`M`) focuses the mini month (shows the sidebar like `c`); esc / view keys
  return to the main view. The help, sync log and event detail scroll with the configured
  `cursor_up`/`cursor_down` keys (detail hint shows them).
- Personal keymaps live only in the user's local config.

### Stacked blocks (ui-grid; replaces side-by-side overlaps)

- **Cascade:** `timelayout.cascade` takes spans by start (longer first) and puts each one level
  (`Block.depth`) above the deepest earlier span it overlaps; `sub_columns` indents a level by
  `INDENT` = 2 cells (Google-like), so the covered event keeps a 2-cell strip. Of two with the
  same start the shorter goes on top. Only events with identical start *and* end would cover each
  other completely: they share a level side by side (`col`/`cols`, 1-col gap). `layout_blocks`
  returns blocks in drawing order (bottom first); `layout_blocks(..., width)` takes the
  narrowest day column's width and collapses a cluster with a block under `MIN_WIDTH`.
- **Text:** a block's lines go only on rows that no block drawn above it covers, so a covered
  title moves below its cover (one free row: compact "HH:MM title"). Replaces `_place_time`.
- **Look:** fills are the calendar colour at `ALPHA` over the plain grid background (the
  cursor stays hidden under events); a block fully replaces
  a lower one, so overlapping colours never mix (nomix; it used to blend over the lower block); text colours: see "Colour polish". Hour lines (`▔`, see "Cell alignment") show through faintly
  (`HOUR_ALPHA`), the now line clearly (text covers them). *Superseded (ui-colors):* the
  quarter-block rounded corners looked stair-stepped; every event now has a thin accent bar `▎`
  in its calendar colour on its left edge; the left text
  pad is that bar's cell. Corners are plain square: `╭╮╰╯` are thin lines and cannot round a
  filled cell, so a clean rounded look (like the pane borders) is not achievable.
- **Picking:** the cursor selects the deepest block at its slot (side by side: the left one);
  clicks hit the topmost block under the pointer; n/p order is unchanged (by start).

## Colour polish (ui-colors)

- **Calendar colours (apple-colors):** exactly the server's `calendar-color` (alpha byte dropped);
  `app.calendar_color` no longer adapts them to the theme (`harmonize`/`legible`/`text_on` are
  gone). `tcal/colors.py` holds Apple's picker palette (`APPLE_COLORS`): used by the demo
  calendars, iCloud calendars without a colour (blue) and `[[subscription]]`s without one (the
  next of the palette by position, so feeds differ). tcal has no colour picker; the default
  config lists the values. `symbolic-color` is ignored: the hex value is used as sent.
- **One event look (apple-colors, Apple Calendar's):** `theme.event_colors(color, palette,
  selected)` -> (fill, text), shared by timed blocks, all-day bars and month bars. Fill: the colour
  at `ALPHA` over the plain background, with an accent bar `EDGE` in the exact colour. Text:
  `theme.tint`, the colour mixed toward white (light themes: black), further until it has
  `MIN_CONTRAST`; titles (all wrapped lines) bold. Selected: filled with the full colour, no
  bar, white text if that has contrast 3 or more on it (of Apple's: red, brown; see
  `MIN_WHITE_CONTRAST`), else black; the now line through it is drawn in the text colour.
  Month chips: accent bar + tinted text, selected ones filled. Dots and squares (schedule,
  sidebar, search, detail) are the exact colour.
- **Quieter chrome:** hour lines are the divider colour at `LINE_ALPHA` over the background; the
  cursor slot is `primary` at `CURSOR_ALPHA` (not solid); the status bar's help chip is neutral
  (`foreground2` on `background3`), leaving `primary` for the mode chip and active view.

### Batch copy (batch-copy)

- **B1 Marks:** modelled on Apple Calendar (cmd-click several, copy, select a day, paste;
  Google Calendar has no multi-paste). `[keys] toggle_mark = ["tab"]` marks/unmarks the
  selected event in day/week/month/schedule (`AppState.marked`: `Occurrence.key`s, so marks
  survive navigation and syncs); `cancel` (esc) clears them. Both are in `EVENT_BINDINGS`
  (the focused view), so they win over the screen's built-in tab. Marked events get a ✓
  (time grid: a badge in the block's/bar's top-right cell, a post-pass `timepaint._marks`;
  month: before the chip; schedule: instead of the ●); the status bar shows "N selected".
- **B2 Tab:** `focus_next` is now `shift+tab` (described "Cycle panes"; Textual's screen binds
  shift+tab to focus-previous first, which cycles just as well). Quick add's "full form" key
  is a fixed `tab` (it was `[keys] focus_next`; like its fixed enter).
  *`focus_next` is gone, see K2.*
- **B3 Yank/paste:** `y` with marks copies the marked events still shown (by start) and clears
  the marks; `Editor.yanked` is a list. `p` with several: the earliest lands on the selected
  day, the others keep their day offsets, times of day and durations (all-day included); each
  a one-off `copy_at` as for a single paste (also into the source calendar or the first
  writable). Single yank/paste is unchanged. `app.save_events(events, message)` saves them
  as **one undo step**: `UndoStep.changes` is now a list of (uid, rows before).

### Event navigation (event-nav)

- **E1 Modes:** day/week start in **event mode**: `cursor_up/down` select the previous/next
  event of the selected day (all-day bars first, then by start; with none selected the
  first/last; stop at the ends), `cursor_left/right` go to the adjacent day and select its
  event nearest the current one (interval distance to its start minute, earlier on a tie; an
  all-day one goes to the day's first all-day event; empty day: the day only, the minute is
  kept for the next step). Crossing the week edge works as before (`select_date`).
  **Grid mode** (`[keys] grid_mode = ["v"]`, toggles; `cancel`/esc also leaves it, else esc
  clears marks as before) is the old 15-min slot cursor. Leaving selects the event under the
  cursor, else the nearest on that day. The mode is `AppState.grid` (set via
  `app.set_grid_mode`), shared by day and week; the status bar badge reads "WEEK · GRID".
- **E2 Event mode details:** no slot cursor is drawn (`GridFrame.cursor_rows` empty, placed
  at the selected event so flash labels still count from there); the view scrolls the selected
  event's block into view. `a`/`i` (and enter with nothing selected): a new event at the
  selected timed event's end, else at the next full hour; `p`: at the selected timed event's
  start (`TimeGrid.paste_at`), else on the day. Flash: event label selects (mode unchanged),
  slot label switches to grid mode at that slot. Clicks are unchanged in both modes.
  Old grid-cursor tests now call `app.set_grid_mode(True)` first.

### Resizing (resize)

- **R1 Keys:** `end_earlier` (`,`, shift+up), `end_later` (`.`, shift+down), `start_earlier` (`;`)
  and `start_later` (`:`): unshifted / shifted `,` `.` on a German keyboard, no AltGr brackets.
  Like `move_up/down` they need a timed event in a time grid (event or grid mode).
- **R2 Behaviour:** `Editor.resize(occ, edge, step)` goes through the same `_shift` as `move`
  (read-only check, `ResizeScope` for a series with the answer shared with moves via `move_run`,
  one undo step, sync); `clipboard.shifted(event, start_by, end_by)` is a move when both deltas
  are equal. Unlike moves (a plain ±15 min) the edge snaps to the next/previous **quarter hour**
  (`quarter_step`: 23:59 → 24:00). A shrink below `STEP` (15 min) is refused; growing a shorter
  event is fine. A series' start pushed over midnight shifts its BYDAY days as a move does.

### Grid step (grid-step)

- **G1 Slots:** grid mode's cursor is a slot of `[view] grid_step` minutes (15, 30, 60; default
  60; supersedes H2/E1's 15 min): `j`/`k` move by it, the highlight covers it, new events and
  pastes start on it. Only the display snaps (`TimeGrid._slot_of`): `_cursor_min` keeps the exact
  time until the cursor moves, so entering grid mode floors it to the slot (10:50 → 10:00), and
  a flash to a half-hour label lands on its hour. Rows longer than the step (15 min at 2
  rows/hour) are the slots themselves, as before. `GridFrame.cursor_minute` is the axis label.
- **G2** A picked event that starts in the slot stays selected even where its block rounds to
  the next row (10:50 at 2 rows/hour). Event mode keeps 15-min precision (double-click at 07:30
  still makes a 07:30 event) and zooming there no longer rounds the remembered time; moving/resizing events stays at 15 min.

### Keys & redo (zoom-keys)

- **K1 Fewer / other default keys (user request):** zoom is only `+`/`-` (no ctrl+up/down), paste
  only `p` (no `P`), new event `a`/`i` (not `o`).
- **K2 No pane cycling (user request):** the `focus_next` action is removed (a config that still
  sets it gets the usual unknown-setting error) and `screens/main.MainScreen` drops Textual's
  built-in tab / shift+tab; panes have their own keys (`c`, `M`, esc). Dialogs keep tab.
- **K3 Redo:** `[keys] redo = ["ctrl+r"]`, `app.redo()`. `UndoStep` holds both toasts and both
  selections; undoing or redoing a step captures the current rows first (`UndoStep.inverse`) and
  pushes that on the other stack. A new change clears the redo stack.
- **K4 `Store.restore` across calendars:** if the current row is in another calendar than the
  restored one, its resource is deleted and a new one created (before, the push went to the
  old calendar's resource): redoing a calendar move, or undoing one already pushed.
- **K5 ctrl+h:** terminals without the kitty protocol send it as ^H, which Textual reports as
  backspace, so `move_left` did nothing there. `TcalApp.on_event` turns ^H (not DEL, the real
  Backspace key) into `ctrl+h` on the main screen. ctrl+non-ASCII keys (`ctrl+ö`) need the
  kitty protocol.

### Prompts (dialogs)

- **PR1 One prompt:** `screens/prompt.Prompt(question, choices, cancel)` replaces every dialog with
  buttons (`ScopeDialog`/`ConfirmDelete`/`EditScope`/`MoveScope`/`ResizeScope`, `ConfirmDiscard`,
  `ServerChanged`): `scope_prompt(verb, occ)` and `delete_prompt` in `event_detail.py`,
  `discard_prompt` and `server_changed_prompt` in `event_form.py`. A compact box with the question
  and clickable key hints (todooit asks in its bar; a box was requested). Keys are the old ones
  (y, o/s, o/d); enter still takes the first choice (bold), esc and n cancel in all of them.
  Deleting is no longer red. Questions longer than 80 % of the screen's width wrap.

### Cell alignment (align)

- **AL1 Hour lines:** drawn as `▔` on the *top edge* of the hour's first row (was `╌`, mid-row, so a
  block filling its rows stuck out half a row above the line and ended half a row before the
  next). An hour's cell is now exactly the rows between two lines, which a 1-hour block and the
  slot cursor fill; a block's first row shows no line (it is the block's own border).
- **AL2 Ends of the day:** `row_of(24:00)` is always `total_rows` (with a `day_end` before 24:00 at
  an uneven fit, late events left a gap row) and no minute before it is past the last row (a
  23:45 event at 1 row/hour was drawn below the grid). `TimeScale.aligned` rounds ties so that
  `row_of(0)` is 0 (was -1 for e.g. 08:00–24:00 with a tie).
