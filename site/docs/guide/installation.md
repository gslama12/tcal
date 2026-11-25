# Installation

tcal needs Python 3.11 or newer and [uv](https://docs.astral.sh/uv/), and runs
on macOS, Linux and WSL.

```bash
uv tool install git+https://github.com/gslama12/tcal
tcal --demo
```

That puts `tcal` on your `PATH` in an environment of its own. `--demo` starts it
with sample data, no account needed. For your own calendars, go on with
[iCloud setup](/guide/icloud).

::: tip Terminal and font
Any terminal with true colour works. The screenshots on this site are rendered
in [JetBrainsMono Nerd Font](https://www.nerdfonts.com/font-downloads); tcal
draws no icons that need a patched font.

Below 120 columns the sidebar hides itself; `b` shows it and keeps it.
:::

## Updating

```bash
uv tool upgrade tcal
```

## From source

For development, or to try a branch:

```bash
git clone https://github.com/gslama12/tcal
cd tcal
uv sync
uv run tcal --demo
```

`uv tool install .` in the checkout installs that version as the global `tcal`.

## Try it without touching your calendar

Two ways, and neither can change your real data:

```bash
tcal --demo               # sample data in a throwaway cache
TCAL_HOME=~/scratch/tcal tcal   # a separate config and cache
```

The second is a complete instance of its own: it starts without an account, so
`TCAL_HOME=~/scratch/tcal tcal login` comes first. See
[Data & files](/reference/data#one-self-contained-instance).
