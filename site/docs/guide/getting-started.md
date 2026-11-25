# Getting started

Not installed yet? [Installation](/guide/installation) is a one-liner. Then:

```bash
tcal --demo     # look around with sample data
tcal login      # or set up your iCloud account
tcal            # and start
```

tcal opens on this week.

![The week view](/screenshots/week.svg)

On the left the mini month and your calendars, on the right the week: all-day
events on top, the hours below, the red line is now. The status bar shows the
view, the selected day and whether everything is synced.

## The keys you need first

| Key | What it does |
| --- | --- |
| `j` / `k` | Next / previous event of the day |
| `h` / `l` | The nearest event on the day before / after |
| `H` / `L` | Last / next week |
| `t` | Back to today |
| `enter` | Open the selected event |
| `?` | **Show every key** |

The arrow keys work wherever `h` `j` `k` `l` do. The mouse works too: click an
event to open it, the tabs to switch views, a day in the mini month to go there.

## Your first event

```
a                                new event
Lunch with Anna fri 12:30 @Cafe  type it as one line
enter                            save
```

The card under the line shows the event as it will be saved. What you leave out
(drawn dim) is filled in for you, see [Typing events](/guide/typing-events).

Then, with the event selected:

```
J        15 minutes later (K: earlier)
>        a day later (<: earlier)
e        edit it
d        delete it
u        undo any of these
```

## See it in action

![tcal in action](/demo.gif)

## Then

- `w` `m` `Y` `s` switch between week, month, year and schedule — see
  [Views & navigation](/guide/views).
- `f` labels everything on screen to jump to, `/` searches, `g` goes to a date —
  see [Flash, search & go to](/guide/flash-search).
- `y` and `p` copy and paste events, `tab` marks several — see
  [Moving & copying](/guide/move-copy).
- `v` moves a cursor over time slots, `o` changes an event's length — see
  [Grid & resize mode](/guide/modes).
- `q` quits. If a sync is still running, tcal finishes it first — see
  [Sync & offline](/guide/sync#quitting-during-a-sync).

The whole list of keys is on [Keybindings](/guide/keybindings), and `?` shows
it in the app.
