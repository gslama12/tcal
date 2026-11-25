# Grid & resize mode

In the week view the cursor keys go from event to event. Two modes change what
they do; the badge in the status bar names the mode, and `esc` leaves it.

## Grid mode

`v` gives you a cursor over time slots instead.

![Grid mode](/screenshots/grid.svg)

| Key | What it does |
| --- | --- |
| `j` / `k` | Next / previous slot |
| `h` / `l` | Same time, the day before / after |
| `a` | New event at the slot |
| `p` | Paste at the slot |
| `enter` | Open the event at the slot, or a new one |
| `v` or `esc` | Back; the event under the cursor (or nearest to it) is selected |

It starts at the end of the selected event. An event under the cursor is
selected, so `e`, `d`, `y`, `J` and the rest work on it.

A slot is an hour; [`grid_step`](/reference/configuration#view) makes it 15 or 30
minutes.

## Resize mode

`o` on a timed event takes hold of its end.

![Resize mode](/screenshots/resize.svg)

| Key | What it does |
| --- | --- |
| `j` / `k` | Move the edge 15 minutes later / earlier, to the quarter hours |
| `o` | Switch between the end and the start |
| `u` | Undo one step (and stay in the mode) |
| `esc` | Leave; what you changed is kept |

The edge being moved is drawn bright, with an arrow. An event cannot be made
shorter than 15 minutes. A repeating one asks this event or all events, once.

Other keys do nothing here, except zoom, undo, sync, help and quit. A click in the grid or a
change of view leaves the mode as well.
