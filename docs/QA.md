# QA pass — `tcal --demo` (2026-11-21)

Driven with a Textual pilot at 200x55 and 100x35 (demo data, today = Sat 21 Nov 2026,
default config: week view, fitted zoom, nord). Every `[keys]` action was pressed in each view,
the sidebar (minical, calendar list) and every modal (detail, form, confirm, goto, search,
help); mouse: minical days and ‹ ›, calendar checkboxes, Today/‹/› and view tabs, timed and
all-day events, empty slots, wheel scroll; resize 200x55 ↔ 100x35. Compared with Google Calendar web.

Nothing was fixed. Ordered by importance; tag = **bug** / **UX** / **visual**.

## High

1. **bug — New events start at odd times (09:10, 15:40, 15:15).** At the fitted zoom
   (fractional rows/hour, D5) a slot is ~23 min, so slot starts are not on :00/:15/:30.
   Repro 200x55 week: click the row whose axis label reads `16:00` in Tue 17 → the label turns
   into `15:40` and enter opens the form with *From 15:40 – 16:40*; or press `a` right after
   start (cursor on the now-line at 09:28) → *09:10 – 10:10*. Expected: slots snap to
   15/30-min boundaries and clicking next to "16:00" gives 16:00 (Google: 15-min grid).
2. **bug — Overlap layout wastes columns: back-to-back events don't share a column.**
   Repro day view, Sat 21: Design review 10:00–11:30, 1:1 10:30–11:00, Dentist 11:00–12:00 are
   drawn in 3 columns of 1/3 width. 1:1 ends when Dentist starts, so they should stack in
   column 2 (2 columns, each 1/2). In the week view at 200x55 this squeezes "Design review" to
   `Desig` / `10:00` / `Room`. Expected: Google-style packing (end == start is no overlap) and
   events expand into free columns to their right.
3. **bug — Week view at 100x35: overlapping events become garbage.** Repro 100x35 week, Sat 21
   10:00–12:00 reads `De1:` / `1010 Den` / `Ro   11:` / `Dr.` — 2–3-char columns with no gap,
   titles and times of neighbours run together. Expected: at least the first letters of each
   title with a 1-col gap, or a single "3 events" block / `+2` marker that opens the detail.
4. **UX — Uneven hour spacing and imprecise placement at the fitted zoom.** Hour lines alternate
   2 and 3 rows apart (200x55: 07→08 = 2 rows, 08→09 = 3, 13→14 = 2, 14→15 = 3); at 100x35
   (~1.5 rows/h) "Design review 10:00–11:30" visually spans 10:00–12:00, Dentist (11:00) starts a
   row below the 11:00 label, and Haircut 08:00–08:45 / Standup 09:00 (Mon 23) are drawn side by
   side as if they overlapped. Expected: whole rows per hour (e.g. 2 or 3) with scrolling, like
   Google; or make the fit an option, not the default.
5. **UX — Zoom can't return to the default fit.** Repro 100x35 week: press `+` five times, then
   `-` seven times → it stops at 2 rows/h showing 00:00–12:00 only; the initial
   06:30–24:00 view is unreachable without restarting. Expected: the fit level is one stop on the
   zoom ladder (or `-` at the bottom returns to it).
6. **UX — Events before `day_start` are invisible with no hint.** Repro week view: "Early run"
   (Sat 21, 05:45–06:30) is not visible and nothing indicates it; you only find it with `k`/wheel
   or `n`. Expected: a `▲ 1 earlier` marker in the column/axis top (Google scrolls but shows the
   full day; tcal hides by default, so it needs an indicator).
7. **visual — Year view doesn't fit the terminal.** 200x55: 12 tiny months centred with huge
   empty margins (≈60% of the panel unused). 100x35: only Apr–Dec are shown (Jan–Mar cut off;
   after `g 2026-02-10` Jan–Sep show and Oct–Dec are cut), no scrollbar, and a 6-week month
   (March, August) touches the next title (`30 31` directly above `June`). Expected: all 12
   months visible (4x3 / 3x4 / 2x6 depending on size) with a blank line between rows, scaled to
   use the space (Google's year view fills the page).
8. **visual — Now-line is drawn over event text.** Repro: create an event over the current time
   (`a`, ctrl+s) in week view → the block reads `QA we────────────────`. Expected: the line
   passes behind/under the event (or only the `●` marker on the event edge), title stays readable.

## Medium

9. **UX — Month view has no event cursor.** `e`/`x` in month (and year) view only say
   "No event selected"; events there are reachable only by mouse. Expected: `n`/`p` (or
   `j`/`k` inside a day) select chips in the month cell, enter opens the detail.
10. **visual — Month grid doesn't fill the height at 100x35.** Repro 100x35 `m`: 4 empty rows
    under the last week, while cells show `+2 more`/`+4 more`/`+6 more`. Expected: rows share the
    full height. Also the week separators start with a space (` ─────┼`) and the Sunday column is
    1 col narrower (`Ski tri` vs `Ski trip`).
11. **visual — Multi-day all-day events in month view are separate per-day bars.** "Conference"
    (Wed–Fri) and "Ski trip" repeat the title in every cell with gaps at the column borders.
    Expected (Google): one continuous bar per week row, title once.
12. **UX — Editing one instance of a recurring event always edits the whole series.**
    Repro: select Standup on Thu 19, `e` → the form opens on the series (`edit_occurrence` passes
    `occ.event`), so any change moves every weekday. Known
    v1 decision (D4), but the form doesn't say so. Expected: ask "This event / All events" like
    delete does, or at least show "Editing the whole series" in the form title.
13. **UX — Clicking a minical day keeps focus in the minical.** Repro: click 25 in the minical,
    then press `l`/`j` → the minical cursor moves, not the main view (and `h/j/k/l` there only
    move the cursor until enter). Expected: a click jumps and focuses the main view (Google:
    click = navigate).
14. **UX — Delete has no undo.** `x` → `y` deletes immediately. Expected: a toast
    "Deleted "Sprint planning" · u undo" (Google shows Undo).
15. **UX — Sidebar never collapses.** At 100x35 the fixed 28-col sidebar takes 28% of the width
    and the week columns are 8 chars (`Standup`/`09:00–0`). Expected: hide the sidebar below
    ~120 cols or toggle it with a key (Google's hamburger menu).

## Low

16. **bug — Form error stays after it's fixed.** Repro: `a`, ctrl+s with empty title →
    "Title is required"; type a title → the message stays until the next save. Expected: clear
    the error on input change.
17. **UX — `a` creates different things depending on focus.** In the time grid `a` makes a 1 h
    event at the cursor; with the minical/calendar list focused (or month/year view) it makes an
    all-day event on the selected day. Expected: same result regardless of the focused pane (a
    timed event at the next round hour, like Google's "Create").
18. **bug (doc) — Goto weekdays are relative to the selected day, not today.** Repro: `g
    2026-02-10` enter, `g fri` enter → Fri 13 Feb 2026. PLAN G1 says "the next one after today"
    (would be Fri 27 Nov). Pick one and align doc/hint.
19. **visual — View tabs switch between full and initial labels per view.** 100x35: week shows
    `Day │ Week │ Month │ Year`, day view (longer title) shows `D │ W │ M │ Y`. Expected: stable
    tabs; shorten the title (`Sat 21 Nov 2026`) instead.
20. **visual — Help modal looks different from the other modals.** Title "Key Bindings" is a
    filled badge (others use `─ Search ─` border titles) and the `j/k scroll · esc close` hint
    sits outside the box border. `save`/`cancel` appear under "Other" instead of an "Event form"
    group.
21. **visual — Minical marks are ambiguous.** Underline = "day has events", and the shown week
    has only a faint background; at a glance 16–30 all look the same. Expected: event dots or a
    dimmer marker, and a clearer week band (Google: light pill on the displayed week).
22. **UX — Read-only notices are worded inconsistently.** `x` → "Holidays is read-only",
    `e` → "This calendar is read-only". Use one form (with the calendar name).

## Checked and OK

h/j/k/l, H/L, t, d/w/m/y in all views; n/p cycle incl. all-day; enter on event/slot; detail
e/x/esc/q; confirm delete o/s/n and y/n (occurrence and series removal verified in month view);
read-only notices; goto (ISO, `fri`, invalid → "not a date"); search (series listed once, pick
opens day view with the event selected); help scroll; c/space/enter and checkbox clicks hide and
show calendars; tab cycles view → minical → list; r sync status; minical ‹ › and day clicks;
Today/‹/› and tab clicks; wheel scroll reveals 00:00–06:30; resize re-fits the grid.
