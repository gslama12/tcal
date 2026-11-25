# Data & files

| What | Where | With `TCAL_HOME=dir` |
| --- | --- | --- |
| Config | `~/.config/tcal/config.toml` | `dir/config.toml` |
| Cache, with the queued changes | `~/.local/share/tcal/tcal.db` | `dir/data/tcal.db` |
| Log of sync warnings and errors | `~/.local/share/tcal/tcal.log` | `dir/data/tcal.log` |
| Cache of `--demo`, new each time | `~/.local/share/tcal/demo.db` | `dir/data/demo.db` |

The paths are the same on macOS and Linux. `XDG_CONFIG_HOME` and `XDG_DATA_HOME`
are respected. `tcal config path` prints the config's.

The password is in none of these: it is in the system keyring, or wherever
[you keep it](/guide/icloud#where-the-password-comes-from).

## One self-contained instance

`TCAL_HOME` moves all of it into one directory, for a second instance that does
not touch the first:

```bash
export TCAL_HOME=~/scratch/tcal
tcal login
tcal
```

The keyring is shared, though: both instances use the same stored password for
the same Apple ID.

## The cache

A SQLite database holding what the last sync fetched, plus your changes that
have not been sent. Deleting it is safe **once nothing is pending** (no
`↑N pending` in the status bar): the next sync fetches it all again.

## The log

Rotates at 256 kB and keeps one older file, so it can be left alone. It contains
titles of events a sync had trouble with — worth a look before attaching it to a
bug report.
