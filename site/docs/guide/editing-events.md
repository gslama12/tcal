# Editing events

New events are [typed](/guide/typing-events); existing ones are edited field by
field. `e` opens the form, in the views as in the event details.

![The event form](/screenshots/form.svg)

## In the form

| Key | What it does |
| --- | --- |
| `tab` / `shift+tab`, `↓` / `↑` | Next / previous field |
| `h` / `l`, `←` / `→` | On a choice (calendar, repeat, ends): change it |
| `space` | On a choice: open its list (`j` / `k` move, `enter` chooses) |
| `space` | On *All day*: tick it |
| `enter` | Save; in the notes a new line |
| `ctrl+s` | Save, from anywhere |
| `esc` | Cancel; asks before it discards changes |

The keys of the field you are in are shown at the bottom.

Dates are typed as in [Go to date](/guide/flash-search#go-to-a-date) (`fri`,
`24.12.`, `2026-12-24`), times as `9`, `930` or `9:30`. Move the start and the
end follows. If something is not a date or time, the form says so under that
field.

What the form does not show, or you do not change, is kept: the time zone, rules
like "every third Wednesday", guests and alarms.

## Repeating events

Editing one asks first what you mean:

![The question](/screenshots/scope.svg)

- `o` **this event**: only the one selected. Its repeat and calendar are fixed.
- `s` **all events**: the whole series. The form shows the first event's dates,
  and says so.

![The form for a whole series](/screenshots/form-series.svg)

*Repeat* offers every day, weekday, week, month and year; a rule that is none of
these is shown as it is and kept. *Ends* is never, on a date, or after a number
of times. Other rules (`every mon, wed`, `every 2 weeks`) can be
[typed](/guide/typing-events#repeats) when the event is created.

The same question comes up when you [move](/guide/move-copy),
[resize](/guide/modes#resize-mode) or delete one.

## Deleting

`d` deletes the selected event after a `y`; a repeating one asks this event or
all events. [`u`](/guide/undo) brings it back.

## Read-only events

Events of subscriptions and of calendars you may not write to open, but `e` and
`d` only say that the calendar is read-only. You can still copy them: the copy
goes to your first writable calendar.

## If it changed meanwhile

When a sync brings in a new version of the event while its form is open, saving
asks: `o` overwrites the server's version, `d` discards yours, `esc` goes back to
the form.
