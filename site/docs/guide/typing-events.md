# Typing events

`a` (or `i`) asks for a new event: one line, in which the pieces may come in any
order. What is not a date, time, place or the like is the title.

![The event prompt](/screenshots/prompt.svg)

The card under the line is the event as it will be saved, updated with every
letter. What you typed is bright, what is filled in for you is dim. `enter`
saves, `esc` cancels.

## What is filled in

| You leave out | You get |
| --- | --- |
| Date or time, in the week | Right after the selected event, or the slot in [grid mode](/guide/modes#grid-mode) |
| Date or time, elsewhere or with no event selected | The selected day, at the next full hour |
| The end | One hour after the start |
| The calendar | The first one that is shown and writable |

## The language

| | |
| --- | --- |
| **Date** | `today` `tomorrow` `fri` `next mon` `in 3d` `in 2 weeks` `+3d` `24.12.` `24/12` `1.1.27` `dec 24` `24 dec` `2026-12-24` |
| **Several days** | `dec 3-5` `mon-fri` `dec 30 - jan 2` |
| **Time** | `14:00` `1pm` `1:30pm` `13h` `13.30` `noon` `midnight` `at 13` |
| **From – to** | `12:30-13:30` `10-11:30` `1-2pm` `1pm-3` |
| **Length** | `for 2h` `2h` `90m` `1h30` |
| **All day** | `all day` |
| **Repeat** | `daily` `every week` `every mon, wed` `every weekday` `every 2 weeks` |
| **Repeat until** | `until 24.12.` `until dec` `10 times` |
| **Place** | `@Cafe Central` |
| **Calendar** | `#personal` |
| **Notes** | `// everything after it` |
| **As typed** | `"Issue #12 at 9:00"` |

Upper and lower case make no difference. Dates can be shortened: `tod`, `tom`,
`tmr`, `yest`, and weekdays down to two letters (`fr`).

### Dates

Dates are relative to the real today, not to the selected day. A weekday is the
next one after today, `next fri` the Friday of next week, and a date without a
year is this year's. Dates with slashes are day/month, and only read as dates when the day is above
12 (`24/12`): `5/12` could be either, so it stays text.

A range of days without a time is an all-day event. With one it goes from that time
on the first day to the last.

### Times

Right after a date a bare number is an hour: `tom 9`, `fri 1330`. Elsewhere it
needs to look like a time (`9:00`, `9am`, `9h`), or follow `at` at the end of the
title: `Lunch at 13 @Cafe`. An end before the start is on the next day.

### Repeats

![A repeating event](/screenshots/prompt-repeat.svg)

The first event is on the first matching day, on or after the date. `until dec`
runs through the end of December. A repeat word that starts the line belongs to
the title, so `Weekly review fri 9:00` is one event.

### Calendar

The start of the name is enough (`#pers`), and `tab` completes it; again for the
next one that matches. Names with spaces work once they are complete.

### Place and notes

After `@` comes the place: the rest of the line, once the other pieces are taken
out, so the title goes before it. After `//` everything is notes.

## Words that could be either

`tom`, `tod`, the two-letter weekdays and `24/12` could also be a name, a word or
a fraction. They count as dates only where one is expected: before a time
(`tom at 1pm lunch`), where the title ends (`Dentist fr @Praxis`), before *with*
(`Lunch tom with Anna`) or after `on` — and not if the line has another date.

So these keep their titles: *Meeting with Tom*, *Call Tom 1pm*, *How are we*,
*Support 24/7*. `tmr`, `mon` and `24.12.` are always dates. Put anything that
is still taken the wrong way in quotes.

## When something is wrong

![Warnings in the prompt](/screenshots/prompt-warning.svg)

Things that look like a time or a date but are not understood stay in the title,
and the card says so. That doesn't keep you from saving; an unknown or
read-only calendar, or a missing title, does.

## Examples

| Line | Event |
| --- | --- |
| `Dentist tom 9` | Tomorrow 09:00 – 10:00 |
| `Lunch with Anna fri 12:30-13:30 @Cafe #personal` | Friday, with a place, in Personal |
| `Offsite dec 3-5 @Graz` | All day, 3 to 5 December |
| `Gym every tue, thu 18:00 for 90m` | Every Tuesday and Thursday |
| `Standup every weekday 9:00 15m until dec` | Monday to Friday, through December |
| `Night shift sat 22:00-6:00` | Into Sunday morning |
