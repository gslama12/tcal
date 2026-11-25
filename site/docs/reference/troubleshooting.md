# Troubleshooting

Start with

```bash
tcal doctor
```

It checks the account, the password and where it comes from, the sign-in, the
calendar home, the calendars, this week's events and write access. It stops at
the first step that fails and says what to do. It only reads, and prints no
password.

## Signing in fails

iCloud wants an **app-specific** password (`xxxx-xxxx-xxxx-xxxx`), not the one of
your Apple ID, and the Apple ID's primary e-mail address as the name. Apple
revokes all app-specific passwords when the Apple ID's password changes: create a
new one and run `tcal login` again.

## No account set up, or no password found

Run `tcal login`. On a machine without a keyring, set
[`password_cmd` or `TCAL_PASSWORD`](/guide/icloud#where-the-password-comes-from)
instead.

## It says `offline`

The server cannot be reached. Changes stay queued and are sent by the next sync
that works; `r` tries again now.

## `✗ sync failed`

`r` syncs again and shows the error. `R` opens the
[sync log](/guide/sync#the-sync-log), and `tcal sync` prints it in the terminal.

## My change is gone

The event was changed somewhere else first, and the server's version
[won](/guide/sync#conflicts). The sync log names it.

## An event is missing

Is its calendar shown (`■`, not `□`, in the sidebar)? Is it inside the
[synced months](/reference/configuration#sync)? An event that cannot be read is
skipped, with a line in the sync log.

## A subscription has a ⚠

Its feed could not be fetched; the reason is in the sync log. It keeps the
events it had.

## The config is not accepted

`tcal config check` says what is wrong. A setting that is not known is an error:
it may have been renamed, or be a typo.

## A key does nothing

- Bound twice? `tcal config check` lists conflicts.
- `ctrl+h/j/k/l` are often taken by tmux; use `J` `K` `<` `>`.
- Most event keys need a selected event, and `J` / `K`, `o`, `f` and `v` the week
  view.
- The badge reads `RESIZE`? `esc` leaves [resize mode](/guide/modes#resize-mode).

## The sidebar is missing

It hides below 120 columns. `b` shows it.

## Starting over

```bash
TCAL_HOME=~/scratch/tcal tcal login
```

tries with a fresh config and cache, and leaves yours alone.
