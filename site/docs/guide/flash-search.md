# Flash, search & go to

## Flash

`f` in the week view puts a label on every event and every slot on screen. Type
the label and you are there.

![Flash labels](/screenshots/flash.svg)

An event's label selects the event. A slot's label goes to that slot in
[grid mode](/guide/modes#grid-mode), where `a` makes an event and `p` pastes one.

What is nearest gets a single key, the rest two. `backspace` takes the first of
two back; any key that is no label, such as `esc`, puts them away. There is a
label for each [`grid_step`](/reference/configuration#view), by default every hour.

## Search

`/` searches titles, places and notes of the calendars that are shown.

![The search](/screenshots/search.svg)

`↓` / `↑` choose, `enter` goes to the event and opens it, `esc` closes the
search. Upcoming events come first, then past ones, and a repeating event is
listed once with its next date. It covers what is synced: by default the last 3 and the
next 12 months.

## Go to a date

`g` asks for a date.

![Go to date](/screenshots/goto.svg)

| | |
| --- | --- |
| Days | `today` `tom` `yest` `fri` `next fri` `last mon` |
| From today | `+3d` `-1w` `+2m` `+1y` `in 3 days` `in 2 weeks` `next month` |
| Dates | `24.12.` `24.12.2027` `24/12` `dec 24` `24 dec` `2026-12-24` |
| A month or year | `dec` `jan 2027` `2027` |

Everything is relative to the real today, not to the selected day.
