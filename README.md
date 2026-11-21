# tcal

A minimal, keyboard-based TUI calendar that syncs with iCloud.

Built with [Textual](https://textual.textualize.io/), vim-style keys, a Google-Calendar-like
layout and an offline-first SQLite cache: the UI only reads the cache, sync runs in the background
and edits made offline are queued and pushed later.

```
╭───────────────────────╮╭─ Day  Week  Month  Year ─── 16 – 22 November 2026 ──── Today ─╮
│    November 2026      ││        Mon 16   Tue 17   Wed 18   Thu 19   Fri 20   Sat 21  … │
│ Mo Tu We Th Fr Sa Su  ││ all-day          ████ Conference ████                         │
│                    1  ││ 06:30                                                         │
│  2  3  4  5  6  7  8  ││ 09:00  ██Standup          ██Standup         ██Standup         │
│  …                    ││ 10:00           ██Review                                      │
│ 23 24 25 26 27 28 29  ││ 12:00  ██Lunch                    ██Lunch                     │
╰───────────────────────╯│ ───────────────────────────────────────────── now ─────────── │
╭─ Calendars ───────────╮│ 18:00                    ██Gym                       ██Dinner │
│ [x] ● Home            ││ …                                                             │
│ [x] ● Work            ││ 24:00                                                         │
╰───────────────────────╯╰───────────────────────────────────────────────────────────────╯
 WEEK  Sat 21 Nov 2026  ✓ synced 14:02                                          ? help
```

Day, week, month and year views · mini month and toggleable calendar list · create, edit and
delete events (incl. recurring: this occurrence or whole series) · go to date · search · zoomable
time grid · mouse support · `nord` and `tokyo-night` themes.

## Install & run

Needs Python ≥ 3.11 and [uv](https://docs.astral.sh/uv/).

```sh
uv sync
uv run tcal --demo     # try it with sample data, no account needed
uv run tcal login      # set up your iCloud account (see below)
uv run tcal            # start the calendar
```

For a global `tcal` command: `uv tool install .` (then just `tcal`, `tcal login`, …).

Other commands: `tcal sync` syncs once and prints a summary, `tcal calendars` lists the
account's calendars.

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

## Configuration

The config file is `~/.config/tcal/config.toml` (`$XDG_CONFIG_HOME/tcal/config.toml`, also on
macOS). It is merged over the [defaults](tcal/default_config.toml), so only write what you
change. Unknown settings are reported as errors. Example:

```toml
[view]
day_start = "08:00"        # first time shown in day/week view (scroll for earlier)
day_end = "20:00"          # last time shown
rows_per_hour = 4          # zoom 1..8; 0 = fit the terminal height (default)
week_start = "sunday"
default_view = "month"     # day | week | month | year

[sync]
interval = 120             # seconds between background syncs

[theme]
name = "tokyo-night"       # nord | tokyo-night

[keys]                     # action = list of keys; replaces that action's defaults
quit = ["q", "ctrl+q"]
new_event = ["n"]
next_event = ["ctrl+n"]
```

Keys use Textual key names: `"plus"`, `"minus"`, `"slash"`, `"question_mark"`, `"ctrl+up"`,
`"H"` for shift+h, …

### Default keys

| Action | Keys | |
|---|---|---|
| `cursor_left` / `cursor_down` / `cursor_up` / `cursor_right` | `h` `j` `k` `l`, arrows | move the cursor |
| `prev_period` / `next_period` | `H` / `L` | previous / next day, week, month or year |
| `today` | `t` | jump to today |
| `view_day` / `view_week` / `view_month` / `view_year` | `d` / `w` / `m` / `y` | switch view |
| `zoom_in` / `zoom_out` | `+` `ctrl+up` / `-` `ctrl+down` | time-grid zoom |
| `open` | `enter` | open event / day, or new event on an empty slot |
| `next_event` / `prev_event` | `n` / `p` | cycle through events in view (day/week) |
| `new_event` | `a` `o` | new event |
| `edit_event` | `e` | edit selected event |
| `delete_event` | `x` | delete selected event |
| `goto_date` | `g` | go to date (`tomorrow`, `fri`, `24.12.`, `2026-12-24`, `+2w`, …) |
| `search` | `/` | search events |
| `sync` | `r` | sync now |
| `focus_calendars` | `c` | focus the calendar list |
| `toggle_calendar` | `space` | show/hide calendar (in the calendar list; `enter` works too) |
| `focus_next` | `tab` | cycle focus |
| `toggle_sidebar` | `b` | show/hide the sidebar (auto-hidden below 120 columns) |
| `help` | `?` | list all keys |
| `quit` | `q` | quit |
| `save` | `ctrl+s` | save the event form |
| `cancel` | `escape` | close a form / dialog |

## Files

| | default | with `TCAL_HOME=dir` |
|---|---|---|
| config | `~/.config/tcal/config.toml` | `dir/config.toml` |
| cache (SQLite, incl. queued edits) | `~/.local/share/tcal/tcal.db` | `dir/data/tcal.db` |
| demo cache (recreated each run) | `~/.local/share/tcal/demo.db` | `dir/data/demo.db` |

`XDG_CONFIG_HOME` / `XDG_DATA_HOME` are respected. `TCAL_HOME` gives a fully isolated
instance, e.g. `TCAL_HOME=.tcal uv run tcal`. Deleting the cache is safe once nothing is
pending (`↑N pending` in the status bar); it is rebuilt by the next sync.

## Development

```sh
uv run pytest -q
uv run ruff check && uv run ruff format --check && uv run mypy
```

Tests need no network or keyring. Architecture and design decisions: [docs/PLAN.md](docs/PLAN.md).

## What I need you to test

Everything iCloud-specific is only tested against a fake server; please check with a real
account (ideally `TCAL_HOME=.tcal` first, so a fresh cache is used):

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
- [ ] Delete "this occurrence" and "whole series" of a recurring event; edit a series.
- [ ] Move an event to another calendar (edit → calendar).
- [ ] Conflict: change an event on the iPhone, then change it in tcal before syncing → the
      iPhone version wins and tcal doesn't get stuck.
- [ ] Offline: disable Wi-Fi, create/edit an event (`↑N pending`, status *offline*), reconnect,
      `r` → pushed.
- [ ] Events with alarms or invitees keep them after editing in tcal.
- [ ] Editing in a read-only calendar is refused.
- [ ] `password_cmd` and `TCAL_PASSWORD` work when the keyring entry is absent.
