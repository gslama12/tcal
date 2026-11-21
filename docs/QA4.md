# QA pass 4 — `tcal --demo` (2026-11-21)

Driven with a Textual pilot at 200x55 and 100x35, plus 80x24 (the classic default terminal) and
140x40 in catppuccin-latte. Demo data, today = Sat 21 Nov 2026 ~18:40, default config (week view,
fitted zoom, nord). Each `[keys]` action was pressed in day / week / month / year / schedule, the
minical, the calendar list and every modal (detail, form, edit/move/delete scope, quick add, goto,
search, help). Mouse: view tabs, Today/‹/›, minical ‹ › and days, calendar list (incl. the feed),
events, `+N more`, the `▲ earlier` marker. Also covered: quick add (~30 inputs), `y p P D J K < >`
incl. series moves and `u`, the subscription feed and detail extras, all-day/multi-day events,
zoom `+`/`-` up to the limits, `H`/`L`/`t` in every view. Two realistic runs: **first run** (empty
cache, provider raising `OSError`) and **offline with cache** (create/move while offline, then
reconnect); **long session** with `[sync] interval = 2` while the detail or form is open and the
"server" (FakeProvider) changes or deletes the event. Compared with Google Calendar web.
Items fixed since QA.md–QA3.md are not repeated. I didn't fix anything.

Tag = **bug** / **UX** / **visual**; most important first.

## High

1. **bug: The event form doesn't fit or scroll at 80x24.** Repro 80x24: `a` → the dialog is cut
   off after Location; Notes and the `ctrl+s save · esc cancel` hint are off-screen. `tab` ×9
   puts focus in Notes (`TextArea#notes`), which you can't see, so you type blind. Expected: a
   scrollable form body with the title and hints pinned (the detail already scrolls at this
   size), or a compact layout under ~32 rows (date + time on one row, borderless inputs).
2. **bug: The schedule's now line takes 3 rows and breaks the scrolling.** Repro 100x35 `s`:
   the rows read `18:38` / `●──────…` / `─`. `schedule_view.py:331` builds
   `"   HH:MM ●" + "─" * width`, which is longer than the row, so it wraps. Probably because of
   that, the list's row arithmetic is off: (a) `s`, `k` ×10, `j` ×26 → the status bar says
   Thu 26 Nov (Standup Thu 26 selected), but the list ends at Wed 25, so the selection is off
   screen. Each further `j` scrolls only one line. (b) The QA3 #21 trailing header is back: at
   140x40 the list ends with `Fri 27 Nov` and no events, and at 80x24 with `Mon 23 Nov`.
   Expected: a one-row now line (`18:38 ●────` sized to the width), the selection always
   visible, no trailing day header.
3. **bug: Moving a weekday series by a day just drops its first instance.** Repro 200x55: click
   Standup (Thu 19), `esc`, `>`, `s` (All events) → Mon 16's Standup disappears. Tue–Fri are
   unchanged, and next week is still Mon–Fri. `move` shifts DTSTART but not
   `BYDAY=MO,TU,WE,TH,FR`. Gym (`BYDAY=TU,TH`) behaves the same, and `<` has the same problem.
   There's no toast, and `u` is the only way back. Expected: shift the BYDAY days by the same
   delta (MO–FR → TU–SA), or refuse with "Change the days of a series in the form".
4. **UX: A first run without network is a dead end.** Repro: empty cache, provider raising
   `OSError("Network is unreachable")` → status bar `offline · never synced`, "My calendars" is
   an empty box and there's no toast. For the offline state the error text is never shown (only
   `FAILED` shows it). `a`/`A` say "No writable calendar", which is misleading, because nothing
   has synced yet. `r` gives no feedback either. Expected: an empty state in the main panel or a
   toast, e.g. "Couldn't reach iCloud: Network is unreachable · r retry · `tcal doctor`", and
   "Not synced yet" instead of "No writable calendar".
5. **bug: An open detail or form ignores what the background sync did, so edits get lost.**
   Repro with `[sync] interval = 2`:
   (a) `/Dinner` enter (detail open), the server deletes Dinner, the sync runs → the grid no
   longer shows Dinner, but the detail stays. `e` opens a form for the deleted event, `ctrl+s` →
   toast "1 local change(s) conflicted with the server and were dropped", and the event is gone.
   `x` `y` on it says nothing at all.
   (b) Open Dinner's form, the server renames it, the sync pulls the new version (etag 8 → 23)
   while the form is open, then `ctrl+s` → the same anonymous toast, and the typed change is lost.
   tcal already had the newer etag in the store before the save.
   Expected: refresh or close a detail whose event changed or disappeared ("Deleted on the
   server"). At save time, compare with the store's current etag and ask "Changed on the server:
   overwrite / discard". The conflict toast should name the event. Also, the `log.warning`
   lines go to Textual's captured stderr, so they are never visible (there's no log file).
6. **bug: At max zoom the slot cursor and new events land on 7.5-minute times.** Repro 100x35
   week, `+` ×7 → the cursor label reads `18:08` (it was on 18:30 before zooming, so zooming
   also moves it). `a` → From 18:08, To 19:08. Expected: the cursor stays on a 15-min boundary at
   every zoom level (as QA1 #1 does for the fitted zoom), and zooming keeps the cursor's time.

## Medium

7. **visual: Overlaps shorter than a row look like back-to-back events.** Repro 100x35: `a` on
   the 18:30 slot, `ctrl+s` (QA 18:30–19:30), `d` → `18:30 QA` is one full-width row and Dinner
   (19:00–21:00) is full width directly below it. The 30-min overlap doesn't show. At 200x55 the
   two are drawn side by side. Expected: decide columns by the event times, not the rows they
   round to.
8. **visual: Events below the visible range have no `▼ later` marker when the cursor is on
   the last row.** Repro 80x24 week: the grid ends at 20:00, the cursor is on Dinner (Sat
   19:00, last row), and Late movie (Sat 22:30) is hidden with no marker. The QA3 #19 fix
   suppresses the marker instead of moving it. Expected: always show the hint, e.g. in the axis
   column or the row above.
9. **visual: The year view at 80x24 cuts off Oct–Dec, including the current month.** Repro 80x24
   `Y`: Jan–Sep are shown (with no weekday header row), and November isn't visible. There's no
   scroll hint, and `j`/`l` move the selected day out of sight. Expected: all 12 months (4 columns
   × 3 rows, or a compact 2-row-per-week layout), or at least scroll to keep the selected month
   visible.
10. **UX: Saving the form gives no feedback.** `a`, type, `ctrl+s` (or `e` … `ctrl+s`) → no
    toast. Quick add, paste, duplicate and delete all toast with "· u undo". Expected:
    "Saved “QA” · u undo" (Google: "Event saved · Undo").
11. **UX: Quick add can't create recurring events.** `Yoga every monday 18:00` → title
    “Yoga every”, a one-off on Mon 23. `Standup daily 9:00` → title “Standup daily”. Expected:
    `daily`, `weekly`, `every <weekday>` and `every weekday` set the RRULE and show "· weekly" in
    the preview (Google's quick add supports this).
12. **UX: A series can't be ended or split.** The Repeat select only has none, daily,
    weekdays, weekly, monthly and yearly, with no "until" or count. The edit, move and delete
    scopes only offer This event / All events. To stop a weekly meeting you have to delete the
    whole series, including past instances. Expected: "This and following events" in the
    scope dialogs (Google), and an end date in the form.
13. **UX: Esc in the sidebar doesn't return to the view.** Repro 100x35: `c`, `space`, `esc` →
    focus stays in the calendar list, the sidebar stays open, and `j` keeps moving in the list.
    Clicking the minical's ‹ › also leaves focus in the minical, so `h`/`l` move the minical's
    cursor. Expected: `esc` (the `cancel` key) focuses the main view, and the sidebar hides again
    below 120 columns.
14. **UX: Feedback texts are vague or out of date.** After `J J > <`, pressing `u` three times
    toasts "Undid the change to “Dentist”" three times, without saying what was undone. Deleting
    one instance and deleting the whole series both toast "Deleted “Standup”". The help still says
    `u  Undo delete` (`help.py:48`), but undo now covers create, edit, move and paste. Expected:
    "Undid move of “Dentist” (back to Mon 23 11:15)", "Deleted this “Standup” (Thu 19)" /
    "Deleted all “Standup” events", and help text "Undo the last change".

## Low

15. **visual: When offline with pending edits, the status bar overflows at 100 columns.**
    Repro: offline, create an event → `… Sat 21 Nov 2026 offline · last sync 18:49  ↑1 pending   ?`,
    so the help badge is cut to `?`. Expected: shorten (`offline 18:49 · ↑1`) or drop the
    centred date before cutting the right side.
16. **UX: Clicking `▲ 1 earlier` doesn't show the hidden event.** Repro 200x55: click the
    marker in Sat → the cursor moves to 06:30, the marker slides down onto the 07:00 line, and
    Early run (05:45) stays hidden. Expected: a click scrolls up to the earliest hidden event (and
    `▼ later` scrolls down).
17. **UX: Quick add misses common time forms.** `Meet tomorrow 9` → “Meet 9”, all day (a bare
    hour isn't a time). `Doctor 14.30` → “Doctor 14.30”, all day (dot time, common in AT/DE).
    `Lunch at noon` → all day. Expected: a bare hour after a date/weekday, `14.30`, and
    `noon`/`midnight`.
18. **visual: Detail extras are worded inconsistently.** The alerts read "Alert: 10 min before"
    (Budget planning) vs "Alert: 1 hour before" (Dentist). The attendee list has no heading or
    summary, and the organizer is listed twice (`Organizer: Maria Lang`, then
    `Maria Lang · accepted`). Expected: one unit style ("1 h before" / "10 min before") and a
    Google-style "4 guests · 1 yes, 1 maybe, 1 no, 1 awaiting" heading.
19. **UX: Search lists a recurring series once, without saying it repeats.** `/gym` →
    "1 found": `Tue 24 Nov 2026 18:00 Gym`, although Gym is every Tue and Thu. Expected:
    "Gym · every Tue, Thu" on the row, or all upcoming occurrences.
20. **UX: The help dialog only scrolls with `j`/`k`.** `end`, `pagedown`, `G` and `space` do
    nothing, and the long list needs ~25 presses at 100x35. Expected: page and end keys (or
    wheel), like any scrollable dialog.

## Checked and OK

QA3 fixes hold. The moved, pasted and duplicated event stays selected (week timed and all-day,
month). `J`/`K`/`<`/`>` move, and `ctrl+*` remain as extras. New events default to the first
visible calendar. Conflicts reach a toast. The detail scrolls (80x24 too), and read-only `e`/`x`
keep it open. Paste and duplicate toast with the target day, and undo covers moves and series moves.
Month `n` starts at the selected day. Quick add handles ranges (`dec 3 - dec 5`), `next friday`,
`in N days`, `#cal` prefixes and the read-only notice. Titles wrap in tall blocks and month chips
end with `…`. The schedule dims past events, and "Other calendars" is styled like "My calendars".
The `▼ later` marker no longer covers the cursor.

Also fine: offline edits queue (`↑1 pending`, moves coalesce into one op) and push on reconnect,
with the final time correct. A form left open across several interval syncs saves normally when
the server didn't change the event. Edit/move/delete scope dialogs, EXDATE and undo restore
work. "Edit all events" shows the series start with the note and "Every weekday". Goto handles
`next fri`, `in 3 days`, `+2w` and ISO, and `31.2.`/`foo` give "not a date". Search opens the
detail in the current view. `+N more` → day view. View tabs, Today/‹/› and minical ‹ › and days
can all be clicked, and clicking a calendar toggles it (feed too). The tab cycle is
minical → list → view at 200 columns, and at 100 columns the sidebar hides when focus leaves it.
`H`/`L`/`t` work in all views. Latte theme: grid, chips, schedule and quick add are readable.
