# Development

```bash
git clone https://github.com/gslama12/tcal
cd tcal
uv sync
uv run tcal --demo
TCAL_HOME=.tcal uv run tcal     # an isolated instance under ./.tcal
```

## Layout

| Path | What is in it |
| --- | --- |
| `tcal/providers/` | Where events come from: iCloud (CalDAV), iCalendar feeds, the demo |
| `tcal/store.py`, `tcal/sync.py` | The SQLite cache with its queue of changes, and the sync |
| `tcal/recurrence.py`, `tcal/ics.py` | Repeating events; iCalendar text to events and back |
| `tcal/quickadd.py`, `tcal/dates.py` | The language of the event prompt |
| `tcal/source.py` | The only way the interface gets at data |
| `tcal/ui/` | The Textual app: screens, widgets, drawing of the week |
| `tcal/default_config.toml` | Every setting and key |
| `tests/` | The test suite |
| `docs/PLAN.md` | Architecture and the log of decisions |
| `site/` | This documentation site |

`CLAUDE.md` has the map in more detail, with the conventions.

## Tests

```bash
uv run pytest -q
uv run ruff check && uv run ruff format --check && uv run mypy
uv run python scripts/bench.py      # ms per keypress with about 5000 events
```

The tests need no network and no keyring. Each gets a `TCAL_HOME` of its own, so
they cannot touch your calendar.

## Docs

The site is [VitePress](https://vitepress.dev/) in `site/`.

```bash
cd site
npm install
npm run docs:dev      # local preview
npm run docs:build    # what CI builds
```

It deploys to GitHub Pages on every push to `main`
(`.github/workflows/docs.yml`).

The table on [Keybindings](/guide/keybindings) is the output of

```bash
uv run python scripts/keys_table.py
```

and a test fails when it is out of date.

### Screenshots

The SVGs in `site/docs/public/screenshots/` are generated; do not edit them by
hand. The script drives the real app through Textual's pilot, headlessly, with
the demo data and the clock set to a fixed time:

```bash
uv run --with "fonttools[woff]" --with time-machine python site/scripts/screenshots.py
```

Names limit it to those: `… screenshots.py week month`. The same code gives the
same files, so a diff shows what really changed.

It needs **JetBrainsMono Nerd Font Mono** installed (`--font-dir <path>` if it
cannot be found). The glyphs each frame draws are embedded in the SVG, because an
`<img>` may not fetch the web font Rich's template points at.

Add a shot by adding a name and the keys that get there to `SCENES`.

### The demo GIF

```bash
uv run --with pillow --with time-machine python site/scripts/demo.py
```

plays the `SCRIPT` in `site/scripts/demo.py` in real time, and takes a frame after every key.
The flash label it types (`FLASH_SLOT`) depends on what is on screen, so a change
to the demo data can move it; `--frames <dir>` writes every frame as a PNG to
check.
