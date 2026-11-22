# tcal

A minimal, keyboard-based TUI calendar that syncs with iCloud.

Built with [Textual](https://textual.textualize.io/), vim-style keys, a Google-Calendar-like
layout and an offline-first SQLite cache: the UI only reads the cache, sync runs in the background
and edits made offline are queued and pushed later.

```
╭──────────────────────────╮╭──────────────────────────────────────────────────────────────────────────────────────────╮
│ November 2026    ‹ ›     ││  Today    ‹  ›   16 – 22 November 2026             Day │ Week │ Month │ Year │ Schedule  │
│  M  T  W  T  F  S  S     │╰──────────────────────────────────────────────────────────────────────────────────────────╯
│ 26 27 28 29 30 31  1     │╭──────────────────────────────────────────────────────────────────────────────────────────╮
│  2  3  4  5  6  7  8     ││         Mon 16      Tue 17      Wed 18      Thu 19      Fri 20      Sat 21      Sun 22   │
│  9 10 11 12 13 14 15     ││      │           │           │ Conference                        │ Anna's bi…│ Deadline:…│
│ 16 17 18 19 20 21 22     ││──────┼───────────┼───────────┼───────────┼───────────┼───────────┼───────────┼───────────│
│ 23 24 25 26 27 28 29     ││      │           │           │           │           │           │           │           │
│ 30  1  2  3  4  5  6     ││07:00 │           │           │           │           │           │           │           │
╰──────────────────────────╯│08:00 │           │           │           │           │           │           │           │
╭─ My calendars ───────────╮│09:00 │ Standup   │ Standup   │ Standup   │ Standup   │ Standup   │           │           │
│ ■ Work                   ││10:00 │           │           │           │           │           │ Design… +2│           │
│ ■ Personal               ││11:00 │           │           │           │           │           │ 10:00     │ Call mum  │
│ ■ Family                 ││      │           │           │           │           │           │           │           │
│ ■ Sport                  ││12:00 │           │           │           │           │           │           │ Team lunch│
│ ■ Holidays               ││13:00 │ Sprint pl…│           │           │           │           │           │           │
│                          ││14:00 │ 13:00     │           │           │ Release   │           │           │           │
│  Other calendars ─────── ││15:00 │           │           │           │ Interview │ Budget pl…│           │           │
│ ■ Team events            ││16:00 │           │           │           │           │           │           │           │
│                          ││      │           │           │           │           │           │           │           │
│                          ││17:00 │ Kids' play│           │           │           │           │           │           │
│                          ││18:00 │           │ Gym       │           │ Gym       │           │           │           │
│                          ││19:00 │           │ 18:00     │           │ 18:00     │           │▌Dinner    │           │
│                          ││20:00 │           │           │           │           │           ●▌19:00     │           │
╰──────────────────────────╯╰──────────────────────────────────────────────────────────────────────────────────────────╯
 WEEK                                               Sat 21 Nov 2026                               ✓ synced 19:32   ? help
```

## Features

- **Views:** day and week (zoomable time grid, overlapping events stacked as translucent rounded blocks, now line), month (multi-day
  bars, "+N more"), year (12 mini months) and schedule (a scrolling list of upcoming events).
  Sidebar with mini month and a toggleable calendar list; mouse support.
- **Events:** create, edit, delete, incl. recurring events ("this event" or "all events"),
  repeat rules with an end (on a date / after N times), alarms and invitees kept on edit.
  The detail view shows time zone, guests and their answers, alerts and URL.
- **Quick add** (`A`): one line like `Lunch with Anna tomorrow 12:30-13:30 @Cafe #personal`.
- **Yank / paste / duplicate / move** events with the keyboard (`y` `p` `D`, `J` `K` `<` `>`)
  and an **undo** stack (`u`, the last 20 changes).
- **Go to date** (`g`: `fri`, `next fri`, `+2w`, `in 3 days`, `24.12.`, `dec 24`, `dec`, `2027`, `2026-12-24`)
  and **search** (`/`).
- **iCloud sync** in the background, offline edits queued, server wins on conflicts;
  read-only **subscriptions** (holidays, sports, …) from any iCalendar URL.
- **Config** in TOML: every key rebindable, five themes, `tcal config check`, `tcal doctor`.

## Install & run

Needs Python ≥ 3.11 and [uv](https://docs.astral.sh/uv/).

```sh
uv sync
uv run tcal --demo     # try it with sample data, no account needed
uv run tcal login      # set up your iCloud account (see below)
uv run tcal            # start the calendar
```

For a global `tcal` command: `uv tool install .` (then just `tcal`, `tcal login`, …).

| Command | |
|---|---|
| `tcal` | start the calendar (`--demo`: sample data in a throwaway cache) |
| `tcal login` | check and store your Apple ID + app-specific password |
| `tcal sync` | sync once and print a summary |
| `tcal calendars` | list the account's calendars (colour, read-only marks) |
| `tcal doctor` | check the iCloud setup step by step (reads only) |
| `tcal config path` / `edit` / `check` | where the config is / open it in `$VISUAL`/`$EDITOR` / validate it |

## iCloud setup

1. Create an **app-specific password** at [appleid.apple.com](https://appleid.apple.com)
   → *Sign-In and Security* → *App-Specific Passwords*. Your normal Apple ID password won't work
   (and is never needed; no 2FA prompt).
2. Run `tcal login` and enter your Apple ID e-mail and the app-specific password. tcal checks
   them against `https://caldav.icloud.com`, saves the Apple ID to the config file and the
   password in the system keyring (macOS Keychain, service `tcal`).

The password is looked up in this order:

1. the system keyring (written by `tcal login`)
2. `password_cmd` in the config: a shell command that prints the password, e.g.
   ```toml
   [account]
   apple_id = "you@icloud.com"
   password_cmd = "pass show icloud/tcal"    # or: op read op://Private/iCloud/tcal
   ```
3. the `TCAL_PASSWORD` environment variable

The sync window is the last 3 and the next 12 months (`[sync] past_months` / `future_months`),
synced every 5 minutes (`interval`), after each edit and on `r`.

## Subscribed calendars

Read-only iCalendar feeds (holidays, sports fixtures, a shared team calendar, …) are added in
the config file, one `[[subscription]]` block each. They are fetched on every sync, cached for
offline use and listed under **Other calendars** in the sidebar (toggle them like the others;
they cannot be edited). `webcal://` URLs work as they are. A feed that fails keeps its cached
events and gets a ⚠ in the calendar list and the status bar.

```toml
[[subscription]]
name = "US Holidays"
url = "webcal://calendars.icloud.com/holidays/us_en.ics"
color = "#BF616A"          # optional

[[subscription]]
name = "Feiertage"
url = "https://calendars.icloud.com/holidays/at_de.ics"
```

Apple's holiday calendars follow the pattern
`https://calendars.icloud.com/holidays/<country>_<language>.ics` (e.g. `us_en`, `gb_en`,
`de_de`, `at_de`). To copy the URL of any subscription you already have in Calendar.app:
right-click the calendar → *Get Info* → *Subscribed to*.

## Configuration

The config file is `~/.config/tcal/config.toml` (`$XDG_CONFIG_HOME/tcal/config.toml`, also on
macOS). It is merged over the [defaults](tcal/default_config.toml), so only write what you
change. Unknown settings are errors. `tcal config edit` creates the file with every default
commented out; `tcal config check` reports unknown settings/actions, bad values, an unknown theme
and keys bound to more than one action.

```toml
[view]
day_start = "08:00"        # first time shown in day/week view (scroll for earlier)
day_end = "20:00"          # last time shown
rows_per_hour = 4          # zoom 1..8; 0 = fit the terminal height (default)
week_start = "sunday"
default_view = "schedule"  # day | week | month | year | schedule

[sync]
interval = 120             # seconds between background syncs

[theme]
name = "tokyo-night"

[keys]                     # action = list of keys; replaces that action's defaults
quit = ["q", "ctrl+q"]
new_event = ["n"]
next_event = ["ctrl+n"]
```

**Themes:** `tokyo-night` (default, same palette as todooit), `nord`, `gruvbox`,
`catppuccin-mocha` (dark) and `catppuccin-latte` (light). An unknown name falls back to
`tokyo-night` with a warning.

**Keys** use Textual key names: `"plus"`, `"minus"`, `"slash"`, `"question_mark"`,
`"less_than_sign"`, `"ctrl+up"`, `"H"` for shift+h, … Overriding an action replaces its whole
key list. A key bound to two actions only triggers one of them: tcal warns at startup and
`tcal config check` lists the conflicts.

### Default keys

`?` in the app shows the same list with your own bindings. This table is the output of
`uv run python scripts/keys_table.py`.

<!-- keys:start -->
| Keys | Action |
|---|---|
| **Navigation** | |
| `h` `←` | Previous day / move left |
| `l` `→` | Next day / move right |
| `k` `↑` | Up (earlier time / previous week) |
| `j` `↓` | Down (later time / next week) |
| `H` | Previous day/week/month/year (schedule: 2 weeks) |
| `L` | Next day/week/month/year (schedule: 2 weeks) |
| `t` | Jump to today |
| `g` | Go to date |
| `n` | Next event in view |
| `N` | Previous event in view |
| **Views** | |
| `d` | Day view |
| `w` | Week view |
| `m` | Month view |
| `Y` | Year view |
| `s` | Schedule view (upcoming events) |
| `+` `ctrl+up` | Zoom in (time grid) |
| `-` `ctrl+down` | Zoom out (time grid) |
| `c` | Focus the calendar list |
| `M` | Focus the mini month (enter jumps to the day) |
| `space` | Show/hide calendar (in the list) |
| `tab` | Next pane |
| `b` | Show/hide the sidebar |
| **Events** | |
| `⏎` | Open event / new event in empty slot |
| `a` `o` | New event |
| `A` | Quick add (one line) |
| `e` | Edit event |
| `x` | Delete event |
| `u` | Undo the last change |
| `y` | Copy (yank) event |
| `p` `P` | Paste copy at the cursor slot (time grid) or on the selected day |
| `D` | Duplicate event to the next day |
| `K` `ctrl+k` | Move event 15 min earlier (time grid) |
| `J` `ctrl+j` | Move event 15 min later (time grid) |
| `<` `ctrl+h` | Move event one day earlier |
| `>` `ctrl+l` | Move event one day later |
| `/` | Search events |
| **Event form** | |
| `ctrl+s` | Save |
| `esc` | Cancel / close dialog |
| **App** | |
| `r` | Sync now |
| `R` | Sync log (recent warnings and errors) |
| `?` | This help |
| `q` | Quit |
<!-- keys:end -->

`p` and `P` both paste the same way (there is no "paste before"). `j`/`k` scroll the event
detail; in the sidebar (`c` calendar list, `M` mini month) the cursor keys move its own
cursor, esc or a view key returns to the main view. `J`/`K` move timed events in the day/week
grid only. ctrl+h/j/k/l are extra move keys for
terminals that pass them through (many send ctrl+h as backspace; tmux often takes them).
The sidebar hides itself below 120 columns (`b` pins your choice).

## Files

| | default | with `TCAL_HOME=dir` |
|---|---|---|
| config | `~/.config/tcal/config.toml` | `dir/config.toml` |
| cache (SQLite, incl. queued edits) | `~/.local/share/tcal/tcal.db` | `dir/data/tcal.db` |
| log (sync warnings and errors) | `~/.local/share/tcal/tcal.log` | `dir/data/tcal.log` |
| demo cache (recreated each run) | `~/.local/share/tcal/demo.db` | `dir/data/demo.db` |

`XDG_CONFIG_HOME` / `XDG_DATA_HOME` are respected. `TCAL_HOME` gives a fully isolated
instance, e.g. `TCAL_HOME=.tcal uv run tcal`. Deleting the cache is safe once nothing is
pending (`↑N pending` in the status bar); it is rebuilt by the next sync.

## Troubleshooting

- **`tcal doctor`** checks account → password source → sign-in → calendar home → calendars →
  this week's events → write access, stops at the first failing step and says what to fix
  (exit code 1). It never writes and prints no password.
- **Status bar:** `✓ synced 14:02`, `offline` (no network; edits stay queued as `↑N pending`),
  `⚠ … failed` (a subscription feed). `r` syncs now and reports the result as a toast.
- **`tcal sync`** runs one sync in the terminal and prints the error, if any.
- **Sync log:** `R` lists this session's sync warnings and errors (e.g. an unreadable event
  that was skipped, a feed that failed); warnings are also toasted once. Conflicts (the server
  version kept) are named in a toast and counted in `tcal sync`'s summary.
- **Log file:** `tcal` and `tcal sync` also append warnings and errors to `tcal.log` in the
  data directory (see [Files](#files); the sync log dialog prints its path). It rotates at
  256 kB (one backup kept), so it is safe to leave alone and to attach to a bug report.
- **Fresh start:** prefix any command with `TCAL_HOME=.tcal` for a separate config and cache.

## Development

```sh
uv run pytest -q
uv run ruff check && uv run ruff format --check && uv run mypy
uv run python scripts/keys_table.py   # key table above (a test checks it is up to date)
uv run python scripts/bench.py        # ms per keypress with ~5000 events
```

Tests need no network or keyring. Architecture and design decisions: [docs/PLAN.md](docs/PLAN.md).

## What I need you to test

Everything iCloud-specific is only tested against a fake server; please check with a real
account (ideally `TCAL_HOME=.tcal` first, so a fresh cache is used):

- [ ] **First** `tcal login`, then `tcal doctor`: every step shows ✓ (account, password source,
      sign-in, calendar home on `pNN-caldav.icloud.com`, your calendars with colors and
      read-only marks, this week's event count per calendar, write access). It only reads.
      If a step fails, please send me its whole output (it contains no password).
- [ ] `tcal login` succeeds and prints the right number of calendars; the password lands in the
      Keychain (`security find-generic-password -s tcal -a you@icloud.com`); a wrong password
      gives a clean error.
- [ ] `tcal calendars`: names, colors and order match Calendar.app; Reminders lists are
      not shown; shared/subscribed calendars you can't edit are marked read-only.
- [ ] `tcal sync` / starting `tcal`: events from the last 3 and next 12 months appear at the
      right local times, incl. all-day, multi-day and events created in another time zone.
- [ ] Recurring events (weekly, with a deleted instance, with one instance moved on the iPhone)
      show correctly.
- [ ] Create, edit and delete an event in tcal → shows up on the iPhone / iCloud.com, and edits
      there show up in tcal after `r`. Then edit the same event again in tcal (this relies on the
      ETag iCloud returns after a PUT).
- [ ] Delete "this event" and "all events" of a recurring event; edit a series, incl. an end
      date / count ("Ends") → the iPhone shows the same instances.
- [ ] Quick add (`A`) a repeating event (`Gym every tue 18:00 for 1h #home`) → right calendar,
      time and repeat on the iPhone.
- [ ] Move events with `J`/`K`/`<`/`>`: a one-off, one instance of a series ("this event") and a
      whole series ("all events", incl. a weekly one on Tue/Thu moved by one day) → same on
      the iPhone. Then `u` repeatedly undoes each step on the server too.
- [ ] Delete an event, sync (`r`), then `u` → it comes back on the iPhone.
- [ ] Yank/paste (`y`, `p`) and duplicate (`D`) → plain copies on the iPhone.
- [ ] Move an event to another calendar (edit → calendar), then undo it.
- [ ] Conflict: change an event on the iPhone, then change it in tcal before syncing → the
      iPhone version wins and tcal doesn't get stuck. With the event form open while the
      iPhone change syncs in, saving asks "overwrite / discard".
- [ ] Offline: disable Wi-Fi, create/edit an event (`↑N pending`, status *offline*), reconnect,
      `r` → pushed. Starting tcal for the first time without network explains why it's empty.
- [ ] Events with alarms or invitees keep them after editing in tcal; the detail shows guests
      with their answers and the alerts like Calendar.app.
- [ ] Editing in a read-only calendar is refused.
- [ ] A `[[subscription]]` to an Apple holiday feed (e.g. `at_de`) shows under *Other
      calendars*; a wrong URL shows ⚠ and doesn't break the sync.
- [ ] `password_cmd` and `TCAL_PASSWORD` work when the keyring entry is absent.
