# QA pass 3 — `tcal --demo` (2026-11-21)

Driven with a Textual pilot at 200x55 and 100x35 (demo data, today = Sat 21 Nov 2026 ~14:10,
default config: week view, fitted zoom, nord) plus 140x40 in catppuccin-latte. New this round:
quick add (`A`, incl. tab → form and ~25 parser inputs), yank/paste/duplicate/move
(`y p P D ctrl+h/j/k/l`) in day/week/month/year/schedule, `[[subscription]]` feeds (a local
HTTP feed with organizer, 4 attendees, 2 alarms, URL, America/New_York times, an all-day alarm,
plus a 404 feed) and the detail extras, schedule view, themes. Every `[keys]` action was pressed
in each view, the minical, the calendar list and the modals; mouse: tabs, minical, calendar
list (incl. feeds), events, double-click on empty slot / month cell. Compared with Google
Calendar web. Items from docs/QA.md and docs/QA2.md are not repeated. I didn't fix anything.

Tag = **bug** / **UX** / **visual**; most important first.

## High

1. **bug: After a move, a *different* event is selected.** Repro 100x35: `d`, `N` ×8 until
   Dentist (Sat 11:00) is selected, `ctrl+l` → Dentist moves to Sun 22 11:00, but the selection
   is on **Call mum** (Sun 11:00): `enter` opens Call mum, and `ctrl+h` asks "Move “Call mum”?".
   The next key edits/moves/deletes the wrong event. Expected: the moved event stays selected
   (Y2). `_select_moved` matches the new occurrence correctly, so the view's `select()` probably
   resolves the event by slot/time rather than by identity.
2. **bug: Month view (and all-day bars in week view) drops the selection after paste,
   duplicate or move.** Repro 100x35: `m`, `n` ×4 (Standup Tue 17), `y`, `j`, `p` → copy appears
   on Tue 24 but nothing is selected; `D` / `ctrl+l` → "No event selected". Same: `m`, `n` until
   Sprint planning, `ctrl+l` → moves once, the second `ctrl+l` says "No event selected". Week:
   `g 2026-11-20` enter, `n` (Anna's birthday), `ctrl+l` → moved, selection gone. Expected: the
   copy/moved event stays selected so moves can be repeated (works for timed events in day/week).
   Likely cause: `MonthView.selected` compares whole `Occurrence`s (`occ == picked`), and the
   background sync after the save changes the event's etag.
3. **bug: `ctrl+h` (move left) never fires in most terminals.** Textual maps `\x08` to
   `backspace` (`textual/_ansi_sequences.py`: `"\x08": (Keys.Backspace,)`). So without the
   kitty keyboard protocol (Terminal.app, tmux by default), `ctrl+h` arrives as backspace and does
   nothing. `ctrl+h/j/k/l` are also often taken by tmux/vim-tmux-navigator pane switching.
   I took this from Textual's key table; the pilot sends key names, so it can't reproduce it.
   Expected: a default that works everywhere for all four moves (e.g. `<`/`>` + `alt+j/k`, or
   `ctrl+left/right`), with `ctrl+hjkl` kept as extras.
4. **bug: New events go into a hidden calendar and vanish.** Repro 200x55: `c`, `space` (hide
   Work), `A` `Meeting 16:00` enter → toast "Added “Meeting”" but nothing appears. The preview
   says "· Work". `a` also preselects Work. Expected: default to the first *visible* writable
   calendar, or show the calendar again (or warn) when saving into a hidden one.
5. **UX: Sync problems are invisible in the TUI.** Repro: `[[subscription]]` with a URL that
   returns 404 → status bar "✓ synced 14:10", and the feed is listed under "Other calendars"
   like a working one. `SyncSummary.failed` and `conflicts` (server wins, local edit dropped) only
   go to the log; `on_worker_state_changed` ignores the worker's result. Expected: a status
   like `⚠ synced · Broken feed failed`, a marker on the feed in the list, and a toast when a
   conflict dropped a local change.
6. **visual/bug: The event detail cuts off long content with no way to scroll.** Repro 100x35
   with a subscription event that has an organizer, 4 attendees, 2 alarms and a 3-line
   description: the notes stop after "1. Budget", and the hint line (`esc close`) is not shown.
   `j`/`k`/wheel do nothing (the `#dialog` is a plain `Vertical`, `max-height: 80%`). Expected:
   a scrollable body with the title and hints pinned (Google's detail card scrolls).

## Medium

7. **UX: Each step of moving a recurring instance asks again.** Repro: select Standup Tue 17,
   `ctrl+k` → MoveScope → `o`; `ctrl+k` again → MoveScope again, although the instance is now an
   override, so "this event" is the only sensible scope. Moving it 1 h takes 4 dialogs. Expected:
   no dialog for an override, and remember the choice for a run of moves on the same event.
8. **UX: Quick add can't express ranges or "next …".** `Trip dec 3 - dec 5` → “Trip - dec 5” on
   Thu 3 Dec only; `Workshop 1.12.-3.12.` → the dates become the title, on today;
   `Review next friday 10:00` → title “Review next”; `Doctor in 2 days 9:00` → title
   “Doctor in 2 days”, today. (`g next fri` is also "not a date", while `g next week` works.)
   Expected: date ranges for multi-day all-day events, `next <weekday>`, `in N days`.
9. **UX: Paste and duplicate are silent, and a read-only source lands in a surprise calendar.**
   Repro: open the subscription event (read-only "QA feed"), `esc`, `D` → a copy appears on Sat 21
   15:00 in **Work**, with no toast. `p` also gives no feedback (only `y` toasts). Expected:
   "Duplicated to Sun 22 · Work" / "Pasted …", naming the calendar when it differs from the
   source.
10. **UX: `u` only undoes deletes.** Repro: `n` (Dinner), `ctrl+l` → `u` → "Nothing to undo".
    Moves, pastes, duplicates and form edits can't be undone; a wrong `ctrl+l` on a series ("s")
    shifts every instance and the only way back is moving it again. Expected: `u` undoes the last
    change of any kind (Google's Undo toast appears after moves and edits too).
11. **UX: Quick add calls a read-only calendar unknown.** `A` `Party #Holidays` → preview
    "No calendar “Holidays”", but Holidays is listed in the sidebar. Expected: "Holidays is
    read-only" (the wording `check_writable` already uses).
12. **UX: `e`/`x` in a read-only event's detail close the detail.** Repro: open the QA feed event,
    press `e` → the detail disappears and the toast "QA feed is read-only" shows. The hint only
    offers `esc close`. Expected: keep the detail open (just the toast) or ignore the key.
13. **UX: `n` in month view ignores the selected day.** Repro: `m` (Sat 21 selected), `n` →
    Standup **Mon 16**. In the time grids and schedule, `n` starts after the cursor (QA2 #2).
    Expected: the first event on or after the selected day.
14. **UX: `--demo` doesn't show the new features.** The demo has no event with an organizer,
    attendees, alarms, a URL or a foreign time zone, and no "Other calendars" (subscriptions are
    skipped). A user trying the demo never sees the detail extras or a feed. Expected: one
    invitation-style event, one alarm, one event in another zone, and a read-only feed calendar
    built from the FakeProvider (no network).
15. **UX: The schedule view doesn't show "now".** Today's past events (Early run 05:45, Design
    review 10:00 at 14:10) look like upcoming ones, and there is no now marker. Also `H` from
    Mon 16 → status bar "Thu 5 Nov 2026" while the list starts at Mon 16 (no events in between).
    Expected (Google): dim past events, a now line between events, and the status/title on the
    first day shown.

## Low

16. **visual: Titles don't wrap in tall blocks.** 200x55 week: Design review (4 rows) shows
    `Design r…` / `10:00` / `Room 4`; 100x35 `Desi…` / `10:00` / `Room…`, `Rele…`. Expected: wrap
    the title over the free lines before adding time/location (Google wraps titles).
17. **visual: Month chips are cut without `…`.** 100x35 `m`: `09:00 Standu`, `Anna's birth`,
    `Deadline: tax`, `17:00 Kids'`. The time grid already ends cut titles with `…`.
18. **visual: The "Other calendars" header doesn't match "My calendars".** "My calendars" is the
    panel's border title, while "Other calendars" is a plain text line inside the list, and a
    failing feed looks like a working one (see #5). Expected: the same heading style for both
    groups.
19. **visual: At maximum zoom the `▼ N later` marker covers the cursor/now row.** Repro 100x35
    week, `+` ×7: the last grid row of Sat reads `  ▼ 2 later` where the slot cursor and the
    now-line (14:14) are. Expected: the marker never covers the cursor or now-line (put it in the
    axis).
20. **visual: An alarm related to the end reads as an offset from the start.**
    `TRIGGER;RELATED=END:PT0M` on a 90-minute event shows "Alert: 1 h 30 min after". Expected:
    "At end" ("10 min before end" for `-PT10M`), as Apple Calendar shows it.
21. **visual: The schedule list ends with a header and no events.** 100x35 `s`: the last row is
    `Fri 27 Nov` with its events below the fold. Expected: don't start a day group on the last
    row.
22. **UX: Quick add hard-codes `escape`/`tab`.** `QuickAddScreen.BINDINGS` uses literal keys,
    so a remapped `[keys] cancel` doesn't apply there (the form and other dialogs use
    `binding("cancel")`). Also `esc` after `tab` → form discards the quick-add text without
    asking, because the prefilled form counts as unchanged.

## Checked and OK

Quick add: live preview, `#cal` prefix match, `@location`, `for 90m`, am/pm, `10h`, `24.12.`,
ranges crossing midnight, enter saves (toast), tab → prefilled form (calendar, times, location;
all-day box empty when off). Yank `y` toast; `p`/`P` at the grid cursor and on the selected day
(month/year); `D` → next day; `ctrl+j/k` ±15 min (all-day / non-grid → notice); read-only
sources → "<Calendar> is read-only" for moves. Subscriptions: feed events drawn in the feed
colour, hiding/showing a feed by click and `space`, `j/k` skip the header, detail shows
"(read-only)", the zone line "America/New_York: … 09:00 – 10:30", URL, "Organizer: Boss Person",
attendee replies (accepted/declined/invited/maybe), "Alert: 10 min before", all-day "1 day before
at 09:00". Schedule: `j/k/h/l`, `n/N`, `H/L` (±14 days), `t`, `+`/`-` ignored, Day N/3 for
multi-day. Double-click on an empty slot / month cell opens New event. Help lists the new keys in
groups. Year view fits at both sizes; `Y` switches to it. Latte: grid, detail and modal
backdrop are readable.
