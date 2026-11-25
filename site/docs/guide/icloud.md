# iCloud setup

tcal talks to iCloud over CalDAV with an **app-specific password**. Your normal
Apple ID password does not work and is never needed, and there is no two-factor
prompt.

## Logging in

1. Create an app-specific password at
   [appleid.apple.com](https://appleid.apple.com) → *Sign-In and Security* →
   *App-Specific Passwords*. It looks like `xxxx-xxxx-xxxx-xxxx`.
2. Run `tcal login` and enter your Apple ID e-mail and that password.

```
$ tcal login
Apple ID: you@icloud.com
App-specific password (appleid.apple.com):
Logged in as you@icloud.com: 6 calendars.
```

tcal checks them against the server before it saves anything: the Apple ID goes
into the [config file](/reference/configuration#account), the password into the
system keyring (on macOS the Keychain, service `tcal`).

Then start `tcal`. The first sync fetches the last 3 and the next 12 months;
[how much](/reference/configuration#sync) is a setting.

## Checking the setup

```bash
tcal doctor
```

goes through the setup step by step — account, password, sign-in, calendar home,
calendars, this week's events, write access — and stops at the first step that
fails, saying what to do about it. It only reads, and never prints the password.

`tcal calendars` lists the account's calendars with their colours and read-only
marks.

## Where the password comes from

It is looked up in this order:

1. the system keyring, where `tcal login` put it
2. `password_cmd` in the config: a shell command that prints it

   ```toml
   [account]
   apple_id = "you@icloud.com"
   password_cmd = "pass show icloud/tcal"   # or: op read op://Private/iCloud/tcal
   ```

3. the `TCAL_PASSWORD` environment variable

On a machine without a usable keyring `tcal login` still works, but warns that
the password was not stored; use one of the other two there.

## What you get

- Calendars in the names, colours and order iCloud gives them. Reminders lists
  are left out.
- Shared calendars you may not write to are read-only: their events open, but
  cannot be edited.
- Guests, alarms, time zones and everything else tcal does not show are kept
  when you edit an event.

Calendars are created and recoloured in Apple's Calendar or on iCloud.com; tcal
follows at the next sync.
