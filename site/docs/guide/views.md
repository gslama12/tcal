# Views & navigation

Four views, one key each. `H` and `L` page through any of them, `t` returns to
today, and the selected day is kept when you switch.

| Key | View | `H` / `L` move by |
| --- | --- | --- |
| `w` | Week | a week |
| `m` | Month | a month |
| `Y` | Year | a year |
| `s` | Schedule | two weeks |

The view tcal starts with is
[`default_view`](/reference/configuration#view), and the first day of the week
is `week_start`.

## Week

![The week view](/screenshots/week.svg)

Cursor keys step **from event to event**: `j` / `k` to the next and previous one
of the day (all-day events first), `h` / `l` to the nearest one on the day
before or after. Past the edge of the week they go on to the next week.
To move over empty time instead, use [grid mode](/guide/modes#grid-mode).

- Overlapping events are stacked: the later one lies on top, indented.
- All-day events, and those of 24 hours or more, are bars at the top.
- `▲ 1 earlier` / `▼ 2 later` count the events scrolled out of sight. Click one
  to get to them.
- The red line is the time now.

### Zoom

`+` and `-` zoom in and out. tcal starts with the day fitted to the height of
the terminal (by default 06:30 to 24:00); earlier hours are there when you
scroll.

![The week, zoomed in](/screenshots/zoom.svg)

[`day_start`, `day_end` and `rows_per_hour`](/reference/configuration#view) set
where it starts.

## Month

![The month view](/screenshots/month.svg)

`h` `j` `k` `l` move by day and week. `enter` opens the selected day's week.
Days with more events than fit end in `+N more`.

To pick an event here, click it (which opens it); after that its keys (`e`, `d`,
`y`, …) apply to it.

## Year

![The year view](/screenshots/year.svg)

Days with events are bright. `h` `j` `k` `l` move the day and `enter` opens its
week. Click a month's name for the month.

## Schedule

![The schedule view](/screenshots/schedule.svg)

Upcoming events as one list, starting at the selected day; empty days are
skipped. `j` / `k` go through the events, `h` / `l` to the first event of the
previous or next day. More days are loaded as you get to the end.

## The event details

`enter` (or a click) on an event shows all of it: calendar, time, the time in
its own zone if that differs, repeats, place, link, guests with their answers,
and notes.

![An event's details](/screenshots/detail.svg)

`e` edits, `d` deletes, `y` copies, `D` duplicates, `j` / `k` scroll if it is
long, `esc` closes it.

## The sidebar

`b` shows and hides it. On terminals narrower than 120 columns it starts hidden.

![The calendar list with a hidden calendar](/screenshots/calendars.svg)

- `c` goes to the calendar list: `j` / `k` move, `space` (or `enter`) shows and
  hides a calendar. Hidden ones are back the next time tcal starts.
- `M` goes to the mini month: the cursor keys move, `H` / `L` change the month
  and `enter` jumps to the day.
- `esc`, or any view key, returns to the view.

## Mouse

| | |
| --- | --- |
| Click an event | Open it |
| Click a slot or a day | Select it |
| Double-click an empty slot, or a day in the month | New event there (in the month an all-day one) |
| Click `+N more` or a day number in the month | That day's week |
| Wheel | Scroll the week and the schedule |
| Click the tabs, `Today`, `‹` `›` | Switch view, page |
| Click in the mini month or calendar list | Go to a day, show or hide a calendar |
