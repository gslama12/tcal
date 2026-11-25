# Sync & offline

What you see comes from a local cache, so tcal starts and moves at once, network
or not. Syncing runs in the background: at the start, every 5 minutes, after
each edit and when you press `r`. A sync first sends your changes, then fetches
the last 3 and the next 12 months. All of these are
[settings](/reference/configuration#sync).

## The status bar

| | |
| --- | --- |
| `✓ synced 14:02` | Everything is up to date |
| `⠋ syncing…` | A sync is running |
| `↑2 pending` | Two changes not sent yet |
| `offline · last sync 14:02` | iCloud cannot be reached; changes are queued |
| `⚠ synced 14:02 · Feiertage failed` | Fine, except for a [subscription](/guide/subscriptions) |
| `✗ sync failed: …` | Something else is wrong, see [Troubleshooting](/reference/troubleshooting) |

## Offline

Keep working. Every change goes into the cache and into a queue that is kept on
disk, so it survives quitting. The next sync that gets through sends it.

## Conflicts

If an event was changed elsewhere after tcal last saw it, the server's version
wins: your change is dropped, and a message names the event. That is only done
for real changes. iCloud rewriting an event without changing what it says is no
conflict.

## The sync log

`R` lists this session's warnings and errors, newest first: conflicts, feeds
that failed, events that could not be read.

![The sync log](/screenshots/sync-log.svg)

They are also written to a [log file](/reference/data), whose path is shown at the
bottom.

## Quitting during a sync

`q` closes the calendar, and if a sync is still running tcal waits for it in the
terminal:

```
tcal: syncing… (ctrl+c to quit without waiting)
tcal: synced
```

`ctrl+c` leaves at once. Nothing is lost: what was not sent stays queued for the
next start.

## Without the calendar

`tcal sync` syncs once and prints a summary. Handy in a cron job.
