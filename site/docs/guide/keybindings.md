# Keybindings

::: tip Press `?`
`?` opens this list inside the app, always matching the keys you actually have —
your own config included. `j` / `k` scroll it, `esc` closes it.
:::

![The help screen](/screenshots/help.svg)

## Default keys

<!-- Generated: uv run python scripts/keys_table.py -->
<!-- keys:start -->
| Keys | Action |
|---|---|
| **Navigation** | |
| `h` `←` | Previous day (time grid: its nearest event) / move left |
| `l` `→` | Next day (time grid: its nearest event) / move right |
| `k` `↑` | Up (time grid: previous event, grid mode: earlier slot) |
| `j` `↓` | Down (time grid: next event, grid mode: later slot) |
| `v` | Grid mode: cursor keys move a slot cursor (again / esc: back) |
| `H` | Previous week/month/year (schedule: 2 weeks) |
| `L` | Next week/month/year (schedule: 2 weeks) |
| `t` | Jump to today |
| `g` | Go to date |
| `f` | Flash jump: type a label to jump to an event or slot (time grid) |
| **Views** | |
| `w` | Week view |
| `m` | Month view |
| `Y` | Year view |
| `s` | Schedule view (upcoming events) |
| `+` | Zoom in (time grid) |
| `-` | Zoom out (time grid) |
| `c` | Focus the calendar list |
| `M` | Focus the mini month (enter jumps to the day) |
| `space` | Show/hide calendar (in the list) |
| `b` | Show/hide the sidebar |
| **Events** | |
| `⏎` | Open event / else a new event |
| `a` `i` | New event (time grid: after the selected event / at the grid slot) |
| `A` | New event (same) |
| `e` | Edit event |
| `d` | Delete event |
| `u` | Undo the last change |
| `ctrl+r` | Redo the last undone change |
| `tab` | Mark / unmark event (several: y copies all, esc clears) |
| `y` | Copy (yank) event, or all marked events |
| `p` | Paste at the selected event / grid slot / day (several: from that day on) |
| `D` | Duplicate event to the next day |
| `K` `ctrl+k` | Move event 15 min earlier (time grid) |
| `J` `ctrl+j` | Move event 15 min later (time grid) |
| `<` `ctrl+h` | Move event one day earlier |
| `>` `ctrl+l` | Move event one day later |
| `o` | Resize mode: up/down move the end, again: the start (esc: back) |
| `/` | Search events |
| **Event prompt / form** | |
| `ctrl+s` | Save (as enter; in the form's notes enter is a new line) |
| `esc` | Cancel / close dialog / leave resize, grid mode / clear marks |
| **App** | |
| `r` | Sync now |
| `R` | Sync log (recent warnings and errors) |
| `?` | This help |
| `q` | Quit |
<!-- keys:end -->

*Time grid* is the week view.

## Keys that depend on where you are

- **Dialogs** show their keys at the bottom or in the question. `esc` always
  closes them, `enter` takes the first choice.
- **Event details:** `e` `d` `y` `D` work on the event, `j` / `k` scroll.
- **Event prompt:** `tab` completes the calendar after a `#`.
- **Event form:** see [Editing events](/guide/editing-events#in-the-form).
- **Sidebar:** the cursor keys move its own cursor; `esc` or a view key returns to
  the view.
- **Resize mode:** only a few keys do anything, see
  [Resize mode](/guide/modes#resize-mode).

## Changing keys

Each key belongs to an action in the `[keys]` section of the
[config](/reference/configuration#keys):

```toml
[keys]
quit = ["q", "ctrl+q"]
new_event = ["n"]
```

A list replaces all of that action's keys. A key bound to two actions only
triggers one of them: tcal warns when it starts, and `tcal config check` lists
the conflicts.

::: info Terminals and ctrl
tmux often takes `ctrl+h/j/k/l` for itself, which is why moving events has
plain keys too. `ctrl` with a letter like `ö` needs a terminal with the kitty
keyboard protocol.
:::
