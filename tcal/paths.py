"""Where tcal reads and writes.

By default the XDG base directories (also on macOS, so the config lives at
``~/.config/tcal/config.toml``). Setting ``TCAL_HOME`` relocates everything into
one self-contained directory::

    $TCAL_HOME/
        config.toml
        data/       # tcal.db (SQLite cache)
        cache/

Lookups happen at call time, never at import time, so tests can point
``TCAL_HOME`` at a tmp dir.
"""

import os
from pathlib import Path

APP = "tcal"
HOME_ENV_VAR = "TCAL_HOME"


def instance_home() -> Path | None:
    """The instance directory from ``TCAL_HOME``, or None when unset."""
    home = os.environ.get(HOME_ENV_VAR)
    return Path(home).expanduser() if home else None


def _xdg(var: str, fallback: str) -> Path:
    value = os.environ.get(var)
    return (Path(value) if value else Path.home() / fallback) / APP


def config_file() -> Path:
    if home := instance_home():
        return home / "config.toml"
    return _xdg("XDG_CONFIG_HOME", ".config") / "config.toml"


def data_dir() -> Path:
    if home := instance_home():
        return home / "data"
    return _xdg("XDG_DATA_HOME", ".local/share")


def cache_dir() -> Path:
    if home := instance_home():
        return home / "cache"
    return _xdg("XDG_CACHE_HOME", ".cache")


def database_file() -> Path:
    return data_dir() / "tcal.db"
