# Configuration

The config file is TOML: `~/.config/tcal/config.toml` (also on macOS), or
`config.toml` in `$TCAL_HOME`. It is laid over the defaults, so write only what
you change:

```toml
[view]
day_start = "08:00"
rows_per_hour = 4

[theme]
name = "nord"
```

`tcal config edit` opens it, and the first time creates it with every default
commented out. `tcal config check` validates it. Settings tcal does not know are
errors, since they are usually typos. Changes take effect the next time tcal
starts.

## `[account]`

| Setting | Default | |
| --- | --- | --- |
| `apple_id` | `""` | Your Apple ID e-mail; `tcal login` writes it |
| `caldav_url` | `"https://caldav.icloud.com"` | The CalDAV server |
| `password_cmd` | `""` | A shell command that prints the app-specific password, see [iCloud setup](/guide/icloud#where-the-password-comes-from) |

## `[view]`

| Setting | Default | |
| --- | --- | --- |
| `day_start` | `"06:30"` | First time shown in the week view; scroll for earlier |
| `day_end` | `"24:00"` | Last time shown |
| `rows_per_hour` | `0` | Zoom of the week view, `1` to `8`; `0` fits `day_start` to `day_end` into the terminal's height |
| `grid_step` | `60` | [Grid mode](/guide/modes#grid-mode) and flash: minutes per slot, `15`, `30` or `60` |
| `week_start` | `"monday"` | `"monday"` … `"sunday"` |
| `default_view` | `"week"` | `"week"`, `"month"`, `"year"` or `"schedule"` |

## `[sync]`

| Setting | Default | |
| --- | --- | --- |
| `interval` | `300` | Seconds between background syncs |
| `past_months` | `3` | How far back events are fetched |
| `future_months` | `12` | How far ahead |

## `[theme]`

| Setting | Default | |
| --- | --- | --- |
| `name` | `"tokyo-night"` | One of the [themes](/reference/themes) |

## `[[subscription]]`

A read-only calendar feed; repeat the block for each. See
[Subscriptions](/guide/subscriptions).

| Setting | |
| --- | --- |
| `name` | Required |
| `url` | Required; `webcal://`, `https://` or `http://` |
| `color` | `"#RRGGBB"`, optional |

Apple's calendar colours, which feeds without one take in turn:
`#FF2968` red, `#FF9500` orange, `#FFCC00` yellow, `#63DA38` green, `#1BADF8`
blue, `#CC73E1` purple, `#A2845E` brown.

## `[keys]`

Each entry is an action with its list of keys. A list replaces all of that
action's defaults:

```toml
[keys]
quit = ["q", "ctrl+q"]
move_left = ["less_than_sign"]
```

Keys have Textual's names: letters as they are (`"H"` is shift+h), `"enter"`,
`"escape"`, `"space"`, `"tab"`, `"left"`, `"ctrl+s"`, and for symbols `"plus"`,
`"minus"`, `"slash"`, `"question_mark"`, `"less_than_sign"`,
`"greater_than_sign"`.

| Action | Default | |
| --- | --- | --- |
| `cursor_left` | `h` `left` | Previous day (time grid: its nearest event) / move left |
| `cursor_down` | `j` `down` | Down (time grid: next event, grid mode: later slot) |
| `cursor_up` | `k` `up` | Up (time grid: previous event, grid mode: earlier slot) |
| `cursor_right` | `l` `right` | Next day (time grid: its nearest event) / move right |
| `prev_period` | `H` | Previous week/month/year (schedule: 2 weeks) |
| `next_period` | `L` | Next week/month/year (schedule: 2 weeks) |
| `today` | `t` | Jump to today |
| `view_week` | `w` | Week view |
| `view_month` | `m` | Month view |
| `view_year` | `Y` | Year view |
| `view_schedule` | `s` | Schedule view (upcoming events) |
| `zoom_in` | `plus` | Zoom in (time grid) |
| `zoom_out` | `minus` | Zoom out (time grid) |
| `open` | `enter` | Open event / else a new event |
| `new_event` | `a` `i` | New event (time grid: after the selected event / at the grid slot) |
| `quick_add` | `A` | New event (same) |
| `edit_event` | `e` | Edit event |
| `delete_event` | `d` | Delete event |
| `undo` | `u` | Undo the last change |
| `redo` | `ctrl+r` | Redo the last undone change |
| `yank` | `y` | Copy (yank) event, or all marked events |
| `paste` | `p` | Paste at the selected event / grid slot / day (several: from that day on) |
| `toggle_mark` | `tab` | Mark / unmark event (several: y copies all, esc clears) |
| `duplicate` | `D` | Duplicate event to the next day |
| `grid_mode` | `v` | Grid mode: cursor keys move a slot cursor (again / esc: back) |
| `move_down` | `J` `ctrl+j` | Move event 15 min later (time grid) |
| `move_up` | `K` `ctrl+k` | Move event 15 min earlier (time grid) |
| `move_left` | `less_than_sign` `ctrl+h` | Move event one day earlier |
| `move_right` | `greater_than_sign` `ctrl+l` | Move event one day later |
| `resize_mode` | `o` | Resize mode: up/down move the end, again: the start (esc: back) |
| `flash` | `f` | Flash jump: type a label to jump to an event or slot (time grid) |
| `goto_date` | `g` | Go to date |
| `search` | `slash` | Search events |
| `sync` | `r` | Sync now |
| `sync_log` | `R` | Sync log (recent warnings and errors) |
| `focus_calendars` | `c` | Focus the calendar list |
| `focus_minical` | `M` | Focus the mini month (enter jumps to the day) |
| `toggle_calendar` | `space` | Show/hide calendar (in the list) |
| `toggle_sidebar` | `b` | Show/hide the sidebar |
| `help` | `question_mark` | This help |
| `quit` | `q` | Quit |
| `save` | `ctrl+s` | Save (as enter; in the form's notes enter is a new line) |
| `cancel` | `escape` | Cancel / close dialog / leave resize, grid mode / clear marks |

What each key does is explained on [Keybindings](/guide/keybindings).

## The defaults

The whole default file, as `tcal` ships it:

<<< ../../../tcal/default_config.toml
