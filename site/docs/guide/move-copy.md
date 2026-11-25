# Moving & copying

Everything here works on the selected event, and [`u`](/guide/undo) takes it
back.

## Moving

| Key | What it does |
| --- | --- |
| `K` / `J` | 15 minutes earlier / later (week view, timed events) |
| `<` / `>` | One day earlier / later (week, month and schedule) |

`ctrl+k` `ctrl+j` `ctrl+h` `ctrl+l` do the same, where your terminal (or tmux)
lets them through.

Moving a repeating event asks this event or all events. The answer holds while
you keep moving the same one. Moving all events of a Tue/Thu series by a day
makes it Wed/Fri.

To change how long it lasts, see [Resize mode](/guide/modes#resize-mode); to
move it somewhere else entirely, [edit it](/guide/editing-events) or copy and
paste.

## Copying

| Key | What it does |
| --- | --- |
| `y` | Copy (yank) the event |
| `p` | Paste it |
| `D` | Duplicate it to the next day |

`p` pastes at the time of the selected event, at the slot in
[grid mode](/guide/modes#grid-mode), or else on the selected day at the event's
own time. [Flash](/guide/flash-search#flash) is the quick way there: `y`, `f`,
the label of a slot, `p`.

A copy is a single event of the same length in the same calendar, also when the
original repeats. A copy from a read-only calendar goes to your first writable
one.

## Several events

![Four marked events](/screenshots/marks.svg)

`tab` marks the selected event with a ✓ (again: unmarks it). The status bar
counts them, and they stay marked while you go to other days and views.

1. `tab` on each event
2. `y` copies them all
3. go to another day, `p`

The first lands on the day you are on; the others keep their distance from it,
their times and lengths. So a marked week goes into another week in one go, and one `u`
removes all of it. `esc` clears the marks.
