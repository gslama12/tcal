# QA pass 2 — `tcal --demo` (2026-11-21)

Driven with a Textual pilot at 200x55 and 100x35 (demo data, today = Sat 21 Nov 2026 ~13:45,
default config: week view, fitted zoom, nord) plus 160x45 for the other themes. Every `[keys]`
action was pressed in day / week / month / year / schedule, the minical, the calendar list and
every modal (detail, form, edit/delete scope, goto, search, help); mouse: minical days and ‹ ›,
calendar checkboxes, Today/‹/› and view tabs, timed and all-day events, empty slots, `+N more`,
double-clicks, wheel; resize 200x55 ↔ 100x35; `tcal doctor` / `sync` / `calendars` /
`config check` without an account; all five themes. Compared with Google Calendar web.
Items fixed since docs/QA.md are not repeated. Nothing was fixed.

Tag = **bug** / **UX** / **visual**; most important first.

## High

1. **bug — Unknown theme crashes the TUI with a traceback.** Repro: `config.toml` with
   `[theme] name = "dracula"`, run `tcal --demo` (or `tcal`) → `ConfigError` escapes `cli`
   (CliRunner: exit 1, uncaught `ConfigError`), i.e. a Python traceback. `load_config()` accepts the
   name, so `tcal doctor` also passes the config and only complains "no Apple ID configured"; only
   `tcal config check` reports it. Expected: `Error: config: unknown theme 'dracula'; one of …`
   at startup, validated in `load_config` like other settings (so doctor/check/app agree).
2. **UX — `n`/`p` ignore the cursor.** Repro week view right after start (cursor Sat 21 13:45):
   `n` → Mon 16 Standup (first event of the week); `h`×4 (Tue 17) then `n` → Mon 16 Standup
   again; `p` from nothing → Sun 22 Deadline. Expected: `n` = the next event after the cursor
   (Sat 21 Dinner 19:00), `p` = the one before (Dentist 11:00), wrapping only at the ends.
3. **visual — `▲ N earlier` / `▼ N later` markers are drawn over events.** Repro 100x35 week,
   `+` ×6 (8 rows/h, ≈11:00–14:00 visible): first grid row of Sat reads `Desig  1:1▲1`, last row of
   Thu reads `R ▼ 2 later` (Release block overwritten), Mon/Tue `╌ ▼ 1 later`. Expected: markers
   never cover event text (put them in the time axis, or skip them in a column whose edge row
   holds an event).
4. **visual — Times are cut mid-number, titles cut without ellipsis.** 200x55 week: `14:00–16:`
   (Release), `14:30–15:3` (Interview), `11:00–12:0` (Dentist), `10:00–11:` (Design review);
   100x35 with sidebar: `13:00–1`, `18:00–1`, `Sprint `; titles `Desig`, `Relea`, `Anna's birt`.
   Expected: drop the end time when the range doesn't fit (`14:00`), never cut digits; end cut
   titles with `…`.
5. **UX — No way to create an event with the mouse.** Double-click on an empty week/day slot or
   on a month cell does nothing (single click only selects); there is no Create button. Google:
   click a slot = quick create, prominent "+ Create". Expected: double-click (or click on the
   already selected slot / empty month cell area) opens New event, and/or a `+` button in the
   toolbar.

## Medium

6. **UX — Editing "All events" from a later instance is confusing.** Repro: click Thu 19
   Standup → `e` → `s` → form titled just "Edit event", From/To **2026-11-16** (series start, not
   the clicked Thu 19), `Repeat: custom` although the detail says "Every week on weekdays".
   Expected: title "Edit series", the rule shown in words, a note that dates are the series start
   (or show the instance date and shift the series by the delta, like Google); offer
   "Every weekday" in Repeat.
7. **UX — Search result switches the view to Day.** Repro week view, `/` `gym` enter → view
   becomes Day (Tue 24). Expected: stay in the current view and select/open the event (Google
   opens the event's detail in place); at least go back to the previous view on esc.
8. **UX — Schedule view can't scroll into the past.** Repro `s`, `k`×10 or wheel up → stays on
   Sat 21's first event; earlier days only via `H` (−14 days) or `g`, and then the list restarts
   there. Expected: `k`/wheel up at the top load earlier days like `j` loads later ones.
9. **visual — Collapsed clusters read `2 ev` at narrow widths; `c` leaves the sidebar open.**
   Repro 100x35 week, `c` (sidebar appears, columns shrink to 8), `tab` back: Sat 10:00 and Thu
   14:00 show `2 ev` with no time or names; the sidebar stays open after focus leaves it, so the
   week stays squeezed until `b`. Expected: a label that fits (`+2`, `2×`, or first title + `+1`),
   and the sidebar auto-hides again when focus leaves it below 120 cols.
10. **UX — Enter in the minical keeps focus there (click doesn't).** Repro `tab`, `l` `l`,
    enter → day jumps, focus stays in MiniCal, next `j`/`l` move the minical cursor instead of the
    view. A click on a minical day moves focus to the view (QA #13 fix). Expected: same as click.
11. **bug — `b` (hide sidebar) is forgotten on resize.** Repro 200x55 `b` → sidebar hidden;
    resize to 100x35 and back to 200x55 → sidebar is shown again. Expected: an explicit toggle
    wins until the user toggles again.
12. **visual — Light theme (catppuccin-latte): chip text with light calendar colours is hard to
    read.** Repro theme catppuccin-latte, `m`: `8:00 Haircut`, `5:45 Early run` (Personal green
    `#a3be8c`) and Sport pink on `#eff1f5`. Expected: darken text colours for light themes (the
    time grid already picks readable text via `_readable`; month/schedule chips don't).

## Low

13. **visual — All-day checkbox looks ticked when it is off.** Repro `a`: the form shows
    `▐X▌ All day` with a grey X for a timed event (Textual default). Expected: empty box when off,
    ✓/filled when on. The Notes box below Location has no label or placeholder.
14. **UX — Read-only event detail still offers edit/delete.** Repro `g 2026-12-07`, `s`, `j`,
    enter → "● Holidays (read-only)" but the footer says `e edit  x delete  esc close`
    (pressing them only toasts "Holidays is read-only"). Expected: footer `esc close` only.
15. **UX — Escape in the event form silently discards input.** Repro `a`, type a title, `tab`,
    esc → form gone, nothing saved, no prompt. Expected: confirm "Discard changes?" when the
    form is dirty (Google asks).
16. **UX — Form errors are far from the field and dates are ISO-only.** Repro `a`, put `09:00`
    in the To *date* → "Invalid date '09:00' (use YYYY-MM-DD)" at the bottom, field not marked;
    the date fields don't accept `tomorrow`, `fri`, `24.12.` like goto does. Expected: highlight
    the invalid field; reuse goto's `parse_date` for the date inputs.
17. **visual — Grid dashes leak into the 1-col gap between side-by-side events.** 200x55 week Sat
    11:00 `╌ Dentist`, Thu 15:00 `╌ 14:30`, day view `╌ Dentist`; at zoom `Room ╌ Denti`.
    Expected: the gap stays blank.
18. **visual — Inconsistent time format.** Month chips `9:00`, `5:45`, `8:00`; week/day grid,
    schedule and detail use `09:00`. Use one format everywhere.
19. **UX — Scope dialogs and titles are worded differently.** Edit: "This event (o) / All events
    (s)", form title "Edit this event"; delete: "This occurrence (o) / Whole series (s)"; series
    form: "Edit event". Pick one vocabulary (Google: "This event / All events").
20. **visual — Day view repeats the date.** Toolbar "Saturday, 21 November 2026" and grid header
    "Saturday, 21 November" directly below. Expected: grid header just "Sat 21" (Google) or none.
21. **UX — Multi-day all-day events in the schedule give no position.** Conference (Wed–Fri) and
    Ski trip (Dec 3–7) are listed identically on every day. Expected: "Day 2/3" or "until Fri"
    (Google shows "Day 2/3").
22. **bug — `tcal config check` says OK for a missing file.** Repro fresh `TCAL_HOME`,
    `tcal config check` → `<home>/config.toml: OK` (file doesn't exist). Expected:
    "no config file at … (defaults are used)".
23. **UX — Goto doesn't know "next week"/"next month".** `g next week` → "not a date"; only
    `+1w` works. Minor; the hint lists the supported forms.

## Checked and OK

Views and keys: h/j/k/l, H/L (schedule ±14 days), t, d/w/m/y/s, +/− incl. the fit stop, enter on
event/slot/`+N more` (→ day view), a/o in every view (next round hour off the grids), e/x with
the scope dialogs (instance override, EXDATE, whole series) and `u` undo (also "Nothing to
undo"), g (ISO, `24.12.`, `dec 24`, `+3d`, `mon`, `tomorrow`, `1.1.2027`; invalid → "not a date"
in the border), `/` (live results, "1 found"), r, c/space/enter in the list, tab cycle, b, ?, q.
Year view: no event cursor (`e`/`x` → "No event selected"), all 12 months fit at both sizes.
Month cursor n/p + enter, multi-day bars, rows fill the height. Form: "Title is required" clears
on typing, "End must be after start", read-only notices use the calendar name. Mouse: tabs,
Today/‹/›, minical ‹ › and days (focus → view), checkboxes, events and all-day bars open the
detail, wheel scrolls to 03:00. Now-line passes behind events. `tcal doctor` without an account:
`✗ account: no Apple ID configured → run tcal login` (exit 1); with an Apple ID but no password:
`✓ account` / `✗ password … → run tcal login`. `sync`/`calendars` without account: clean error.
Key conflicts: `config check` exits 1 with the clash. All themes render; week_start = sunday
works in minical and month.
