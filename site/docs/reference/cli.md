# CLI

```
tcal [OPTIONS] [COMMAND]
```

With no command, tcal starts the calendar.

## Options

| Option | What it does |
| --- | --- |
| `--demo` | Start with sample data in a throwaway cache; no account needed |
| `--help` | Show help (works for every command) |

## Commands

| Command | What it does |
| --- | --- |
| `tcal login` | Check an Apple ID and app-specific password, and remember them |
| `tcal sync` | Sync once and print a summary |
| `tcal calendars` | List the account's calendars: colour, name, read-only marks |
| `tcal doctor` | Check the iCloud setup step by step (reads only) |
| `tcal config path` | Print where the config file is |
| `tcal config edit` | Open it in `$VISUAL` / `$EDITOR`; a missing file is created with every default, commented out |
| `tcal config check` | Report unknown settings, bad values, an unknown theme, and keys bound twice |

### `login`

Asks for what it needs. `--apple-id` and `--password` give it on the command
line instead (where the shell's history will remember the password). See
[iCloud setup](/guide/icloud).

### `doctor`

Stops at the first step that fails and says what to do about it, with exit code
1. It never writes anything and never prints the password.

### `config check`

Exits with 1 if it finds a problem.

## Environment

| Variable | What it does |
| --- | --- |
| `TCAL_HOME` | Put config and data in this one directory, see [Data & files](/reference/data) |
| `TCAL_PASSWORD` | The app-specific password, if neither the keyring nor `password_cmd` has one |
| `XDG_CONFIG_HOME`, `XDG_DATA_HOME` | Respected, without `TCAL_HOME` |
| `VISUAL`, `EDITOR` | The editor of `tcal config edit` |
| `TZ` | The local time zone, if it is not the system's |
