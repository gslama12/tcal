# QA pass 5 — `tcal --demo` (2026-11-21)

I drove the demo with a Textual pilot that boots it the same way as the CLI (`FakeProvider` + demo
feed through `sync_job`). Sizes: 200x55 and 100x35, plus 80x24. Themes: nord and
catppuccin-latte. Today was Sat 21 Nov 2026, ~19:30. I read the screens as text and as SVG→PNG.

Every `[keys]` action was pressed in day, week, month, year and schedule, in the minical, in the
calendar list and in every modal: detail, form, the edit/move/delete scope dialogs, quick add,
goto, search, help, sync log and the server-changed dialog.

Mouse: minical days and ‹ ›, the calendar list, the view tabs, Today, clicking events and
double-clicking an empty slot.

Also covered:
- quick add: ~45 inputs, through the UI and `quickadd.parse`
- `y p P D J K < >` and `u`, including a series move
- "Ends after N"
- the feed and the invitation detail
- zoom, `H`/`L`/`t`
- the README example config

Two realistic runs:
- **First run:** empty cache, and a provider raising `OSError("Network is unreachable")`, then
  reconnecting.
- **Long session:** `[sync] interval = 1` while the form, detail or search was open, with the
  "server" renaming or deleting the event.

I also compared the result with Google Calendar web. QA–QA4 items that are fixed are not
repeated. I didn't fix anything.

Tag = **bug** / **UX** / **visual**; most important first.

## High

1. **bug: Switching to day/week doesn't scroll to the selected event, so `enter`/`e`/`x` act on
   something you can't see.** Repro with the README's example config (`day_end = "20:00"`,
   `rows_per_hour = 4`, `default_view = "schedule"`) at 100x35: press `w`. The grid shows
   06:30–13:00, while Dinner (Sat 19:00) is selected and the now line (19:32) is off-screen.
   `enter` then opens Dinner's detail. Expected: when a view opens, scroll so the
   cursor/selection (or the now line) is visible, like Google scrolls to the current time.
2. **bug: Quick add turns a leading "Daily/Weekly/Monthly/Yearly/Every day" into an endless
   series and eats the word.** Repro: `A`, then:

   | Input | Title | Repeat |
   |---|---|---|
   | `Daily standup 9:00` | “standup” | every day, weekends too, no end |
   | `Weekly review fri 16:00` | “review” | `FREQ=WEEKLY` |
   | `Monthly report dec 1` | “report” | monthly |
   | `Every day counts` | “counts” | daily, all day |
   | `Weekly sync weekly mon 10:00` | “sync weekly” | |

   These are common meeting names. Expected: treat a repeat word as the repeat only when it
   isn't the start of the title (or isn't the only title word), and keep the title intact.
3. **bug: Quick add silently creates the wrong event for ranges and multi-day repeats.**

   | Input | Result | Expected |
   |---|---|---|
   | `Trip dec 3-5` | “Trip dec” **today 03:00–05:00** (read as an hour range) | Dec 3–5 all day |
   | `Mon-Fri trip` | all day on Mon 23 only | Mon–Fri |
   | `Yoga every monday and wednesday 7am` | “Yoga and”, Mondays only, starting **Mon 30** (Mon 23 is skipped; it counts from Wed 25) | Mon + Wed from Mon 23 |
   | `Standup weekdays 9:00` | title “Standup weekdays”, no repeat | weekday series |
   | `Movie tonight 8pm` | title “Movie tonight” | “Movie”, today 20:00 |

   Expected: parse the cases in the right-hand column, or leave the ambiguous text in the title
   and don't guess.
4. **visual: In side-by-side events, one event's time is printed next to the other's title, so
   it reads as the wrong time.** Repro 200x55 week, Thu 19: the line reads
   `14:00      Interview`, but 14:00 is Release's start (Interview starts 14:30). Sat 21 reads
   `10:00      1:1 with…` (1:1 is 10:30, Design review is 10:00). At 100x35: `14:00  Inte…`
   and `10:00  1:1…`. Expected: each sub-column's time stays inside its own block, or a narrow
   block drops its time before a neighbour's line can look like its own.
5. **visual: The `▼ N later` / `▲` markers float in the middle of the grid, above visible
   events.** Repro (README config as in #1) at 100x35 week:
   - Mon 16 shows `▼ 1 later` on the 12:45 row, directly above the visible Sprint planning
     (13:00). The hidden event is Kids' play at 17:00.
   - Thu shows `14:00     ▼2`, squeezed onto Release's time line.
   - At 80x24, Sat shows `▼1` on the 18:00 row just above Dinner, for Late movie at 22:30.

   Expected: keep the markers on the edge row (in the axis column or the column header if the
   cells are taken), so they never sit next to an unrelated visible event.
6. **visual: The edit and move scope dialogs look like the delete dialog.** Repro: select
   Standup → `e`, or Gym → `>`. "This event (o)" and "All events (s)" are red error buttons,
   and the focused one is red text on near-black, which is barely readable. The delete dialog
   ("Delete “Standup”?") also doesn't say which instance. Expected: neutral/primary buttons for
   edit and move, red only for delete, and the instance in the question:
   "Delete “Standup” on Mon 23 Nov?" (Google: "Delete recurring event · This event / All
   events").

## Medium

7. **UX: The "changed on the server" dialog names your unsaved title, not the event.** Repro
   `[sync] interval = 1`: select Dinner, `e`. The server renames it "Dinner server", a sync
   runs, then type `X` and `ctrl+s` → "“X” changed on the server." Expected:
   "“Dinner” was changed on the server (now “Dinner server”)", so you can decide between
   overwrite and discard.
8. **UX: `e` followed by typing replaces the whole title.** Repro: select Dinner, `e`, type
   `X` → the title becomes "X", because the Input selects all text on focus. In a vim-style app
   you expect to append. You only notice the loss on the next look. Expected: put the cursor at
   the end of the title (or don't focus the title when editing).
9. **UX: After `u`, nothing is selected, and the cursor stays where the event was moved to.**
   Repro 100x35: select Gym Tue 17, `>`, `s` (all events), then `u` → Gym is back on Tue/Thu,
   but the cursor is on Wed 18 and nothing is selected, so another `>` says "No event
   selected". The same happens in month view after undoing a `<`. Expected: undo selects the
   restored event and moves the cursor to it, the same way a move keeps the selection.
10. **UX: An event created in the form isn't selected after saving.** Repro: on the Sat 19:00
    slot, `a` "QA series" (Every week, ends after 3), `ctrl+s` → toast "Saved", but Dinner stays
    selected. Paste, duplicate and quick add select the new event. Expected: select the saved
    event so `J`/`K`/`y` work on it right away.
11. **UX: Search results don't refresh after a background sync.** Repro `interval = 1`: `/gym`.
    The server renames Gym to "Gym new" and a sync runs, but the list still says
    `Gym · every week on Tue, Thu`. `enter` opens "Gym new". Expected: rerun the query when
    the data changes (the detail already follows syncs).
12. **UX: During a first run without network, the sidebar gives no hint once the toast is
    gone.** Repro: empty cache, provider raising `OSError` → the toast "Couldn't reach iCloud…"
    shows, but "My calendars" is an empty box, and the week and schedule ("No upcoming events")
    say nothing about not having synced. Only the status bar says `offline · never synced`.
    Expected: a placeholder in the calendar list and the empty schedule ("Not synced yet · r
    retry"). Reconnecting and pressing `r` works fine.

## Low

13. **UX: Some event keys do nothing, silently, in some views.** In year view, `D`, `<` and `>`
    give no feedback, while `y` says "No event selected". In the detail, `y` and `D` do nothing,
    so copying a read-only feed event (e.g. Team lunch) means closing the detail first.
    `+`/`-` in month, year and schedule are silent too. Expected: the same "No event selected"
    / "Zoom works in the day/week view" hint everywhere, and `y` in the detail.
14. **UX: Goto doesn't understand month or year jumps, and its placeholder suggests it does.**
    `dec`, `jan 2027`, `2027` and `12/24` all give "not a date". At 100 columns the placeholder
    is cut to `… 24.12., dec`, which reads as if `dec` works. Expected: `dec` (first of the
    month), `jan 2027`, `2027`, or a shorter placeholder that fits.
15. **visual: The form's dates are hard to check.** From/To show `2026-11-21` with no weekday,
    while everything else says "Sat 21 Nov". "Ends: After [3]" has no unit. Expected:
    "Sat 21 Nov 2026" (still typed in any `parse_date` form), and "After 3 times".
16. **visual: The now line is drawn into the gap between side-by-side blocks.** Repro 100x35:
    create "QA series" Sat 19:00–20:00 next to Dinner → that row reads `●▌Din…─ QA s…`. Expected:
    the now line only in the free parts of the column, or only the `●` marker.

## README (read as a new user, followed literally)

1. **Troubleshooting is out of date:** "Logs: there is no log file yet … other sync warnings …
   are not shown anywhere yet". There is now `R` (sync log) and `data/tcal.log`, and the sync
   log dialog even prints the path. The "Files" table doesn't list the log file either.
2. **The quick-add examples fail in the demo the README tells you to start with:**
   `Lunch with Anna tomorrow 12:30-13:30 @Cafe #home` → the preview says "No calendar “home”",
   and enter does nothing. The demo calendars are Work, Personal, Family, Sport and Holidays.
   Expected: use a demo calendar in the examples (`#work`), or add "Home" to the demo (iCloud's
   default calendars are Home/Work).
3. **The ASCII screenshot doesn't match the app:**

   | README mockup | The app |
   |---|---|
   | `[x] ● Home` checkboxes in a "Calendars" box | `■ Work` under "My calendars" / "Other calendars" |
   | `Mo Tu We` | `M  T  W` |
   | view tabs in the border title | `Today ‹ › 16 – 22 November 2026 … Day │ Week │ Month │ Year │ Schedule` |

   A new user can't recognise the panes from the mockup.
4. **`p` `P` are listed as one action**, "Paste copy at cursor slot / selected day", with no
   difference between them. Vim users expect `P` to do something different. Say that both
   paste the same way, or give `P` its own meaning.

## Checked and OK

QA4 fixes hold:
- The schedule now line is one row.
- Year view scrolls at 80x24.
- `esc` leaves the sidebar.
- Search marks series ("· every week on Tue, Thu").
- Help pages with space/G/end.
- A form is saved over a server change asks first.
- The detail follows sync changes and closes with "“X” was deleted on the server".
- Series moves shift BYDAY (Gym Tue/Thu → Wed/Fri), and undo names what it undid ("Undid move
  of all “Gym” events (back to Tue 17 18:00)").
- Saving the form toasts.
- Quick add handles `every tue … for 1h`, bare hours, `noon`, `3.12.-5.12.` and `#cal`.
- "Ends after N" and the series hint in search work.
- A first run offline toasts "Couldn't reach iCloud … · r retry · `tcal doctor`", and `a`/`A`
  say "Not synced yet · r sync".

Also fine:
- yank/paste/duplicate/move with undo in week, month and schedule.
- Moves by time are refused outside the grid with a hint.
- The invitation detail: 4 guests, answers, organizer, URL and the alert.
- The read-only feed detail, with `e`/`x` → "Team events is read-only".
- The sync log (`R`), with errors listed.
- Mouse on the minical, the calendar list (incl. the feed), the tabs, Today, events, and
  double-clicking a slot.
- The rebinding example from the README (`new_event = ["n"]`, `next_event = ["ctrl+n"]`) works,
  and help shows it.
- `tcal config check` accepts the README example, and `tcal sync`/`doctor`/`calendars` without
  an account give clean errors.
- The latte theme is readable in the grid, help and goto.
