# Subscriptions

Read-only iCalendar feeds — holidays, sports fixtures, a shared team calendar —
are added in the [config file](/reference/configuration), one block each:

```toml
[[subscription]]
name = "US Holidays"
url = "webcal://calendars.icloud.com/holidays/us_en.ics"
color = "#FF2968"     # optional

[[subscription]]
name = "Feiertage"
url = "https://calendars.icloud.com/holidays/at_de.ics"
```

They are listed under **Other calendars** in the sidebar, where they can be
shown and hidden like the rest. They are fetched on every sync and cached, so
they are there offline too.

| Setting | |
| --- | --- |
| `name` | What it is called in the calendar list. Required. |
| `url` | `webcal://`, `https://` or `http://`. Required. |
| `color` | `#RRGGBB`. Without one, the next of Apple's calendar colours is used, so feeds differ. |

## Finding a feed

Apple's holiday calendars follow the pattern

```
https://calendars.icloud.com/holidays/<country>_<language>.ics
```

such as `us_en`, `gb_en`, `de_de` or `at_de`. For a subscription you already
have in Calendar.app: right-click the calendar → *Get Info* → *Subscribed to*.

## When a feed fails

It keeps the events it had, gets a ⚠ in the calendar list, and the status bar
names it. The reason is in the [sync log](/guide/sync#the-sync-log). The rest of
the sync is not affected.
