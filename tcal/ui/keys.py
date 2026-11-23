"""Bindings whose keys come from config ``[keys]``.

Every configurable binding has ``id == action name`` (the ``[keys]`` entry).
Widgets declare them with ``binding(...)`` using the default keys; the app then
applies the user's config with ``App.set_keymap`` (see ``keymap()``), which
rebinds them wherever they are declared.
"""

from functools import cache

from textual.binding import Binding, BindingType

from tcal.config import Config, default_data


@cache
def default_keys() -> dict[str, list[str]]:
    return default_data()["keys"]


def binding(
    name: str,
    description: str = "",
    action: str | None = None,
    show: bool = False,
    priority: bool = False,
) -> Binding:
    """A Binding for config action ``name``; ``action`` defaults to ``name``."""
    keys = ",".join(default_keys()[name])
    return Binding(keys, action or name, description, show=show, priority=priority, id=name)


def keymap(config: Config) -> dict[str, str]:
    """Textual keymap (binding id -> comma-separated keys) for ``config``."""
    return {name: ",".join(keys) for name, keys in config.keys.items()}


# For the view widgets (Day/Week/Month/Year/Schedule): cursor movement, zoom, open.
VIEW_BINDINGS: list[BindingType] = [
    binding("cursor_left", "Left"),
    binding("cursor_down", "Down"),
    binding("cursor_up", "Up"),
    binding("cursor_right", "Right"),
    binding("open", "Open"),
    binding("zoom_in", "Zoom in"),
    binding("zoom_out", "Zoom out"),
]

# For the views with an event cursor: tab marks the selected event, escape clears the
# marks (here, so they win over the screen's tab).
EVENT_BINDINGS: list[BindingType] = [
    binding("toggle_mark", "Mark", action="app.toggle_mark"),
    binding("cancel", "Clear marks", action="app.clear_marks"),
]
