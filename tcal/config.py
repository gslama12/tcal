"""TOML config: the user's file merged over ``default_config.toml``.

Every section is a frozen dataclass so callers get typed, validated values.
Unknown sections, settings or key actions are errors (they are usually typos).
"""

import json
import re
import tomllib
from dataclasses import dataclass, fields
from importlib import resources
from pathlib import Path
from typing import Any

from tcal import paths

VIEWS = ("day", "week", "month", "year", "schedule")
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class AccountConfig:
    apple_id: str
    caldav_url: str
    password_cmd: str


@dataclass(frozen=True)
class ViewConfig:
    day_start: int  # minutes after midnight
    day_end: int  # minutes after midnight, up to 24 * 60
    rows_per_hour: int  # 0 = fit the terminal height
    week_start: int  # 0 = Monday .. 6 = Sunday (date.weekday())
    default_view: str  # one of VIEWS


@dataclass(frozen=True)
class SyncConfig:
    interval: int  # seconds
    past_months: int
    future_months: int


@dataclass(frozen=True)
class ThemeConfig:
    name: str


@dataclass(frozen=True)
class Config:
    account: AccountConfig
    view: ViewConfig
    sync: SyncConfig
    theme: ThemeConfig
    keys: dict[str, list[str]]  # action -> keys


def parse_hhmm(value: str) -> int:
    """'06:30' -> 390 minutes. '24:00' is allowed as the end of the day."""
    try:
        hours, minutes = (int(part) for part in value.split(":"))
    except ValueError:
        raise ConfigError(f"invalid time {value!r}, expected HH:MM") from None
    total = hours * 60 + minutes
    if not (0 <= minutes < 60 and 0 <= total <= 24 * 60):
        raise ConfigError(f"invalid time {value!r}")
    return total


def default_text() -> str:
    return resources.files("tcal").joinpath("default_config.toml").read_text()


def default_data() -> dict[str, Any]:
    return tomllib.loads(default_text())


def commented_defaults() -> str:
    """The defaults with every setting commented out: a starting point for the user file."""
    lines = default_text().splitlines()
    return "".join(
        f"{line}\n" if not line or line.startswith("#") else f"# {line}\n" for line in lines
    )


def key_conflicts(config: Config) -> dict[str, list[str]]:
    """Keys bound to more than one action: key -> actions (only one of them would fire)."""
    actions: dict[str, list[str]] = {}
    for action, keys in config.keys.items():
        for key in dict.fromkeys(keys):
            actions.setdefault(key, []).append(action)
    return {key: names for key, names in actions.items() if len(names) > 1}


def describe_conflicts(conflicts: dict[str, list[str]]) -> list[str]:
    return [f"key {key!r} is bound to {', '.join(names)}" for key, names in conflicts.items()]


def load_config(path: Path | None = None) -> Config:
    """Load the user config (default: ``paths.config_file()``) over the defaults."""
    path = path or paths.config_file()
    data = default_data()
    if path.exists():
        try:
            user = tomllib.loads(path.read_text())
        except tomllib.TOMLDecodeError as e:
            raise ConfigError(f"{path}: {e}") from None
        _merge(data, user)
    return _build(data)


def _merge(base: dict[str, Any], user: dict[str, Any]) -> None:
    for section, values in user.items():
        if section not in base:
            raise ConfigError(f"unknown config section [{section}]")
        if not isinstance(values, dict):
            raise ConfigError(f"[{section}] must be a table")
        unknown = values.keys() - base[section].keys()
        if unknown:
            raise ConfigError(f"unknown setting(s) in [{section}]: {', '.join(sorted(unknown))}")
        base[section].update(values)


def _section(cls: type, values: dict[str, Any]) -> Any:
    return cls(**{f.name: values[f.name] for f in fields(cls)})


def _build(data: dict[str, Any]) -> Config:
    view = data["view"]
    if view["default_view"] not in VIEWS:
        raise ConfigError(f"default_view must be one of {', '.join(VIEWS)}")
    if view["week_start"] not in WEEKDAYS:
        raise ConfigError(f"week_start must be one of {', '.join(WEEKDAYS)}")
    day_start, day_end = parse_hhmm(view["day_start"]), parse_hhmm(view["day_end"])
    if day_start >= day_end:
        raise ConfigError("day_start must be before day_end")
    if not 0 <= view["rows_per_hour"] <= 8:
        raise ConfigError("rows_per_hour must be between 0 and 8")

    keys = data["keys"]
    for action, value in keys.items():
        if not (isinstance(value, list) and all(isinstance(k, str) for k in value)):
            raise ConfigError(f"[keys] {action} must be a list of key names")

    return Config(
        account=_section(AccountConfig, data["account"]),
        view=ViewConfig(
            day_start=day_start,
            day_end=day_end,
            rows_per_hour=view["rows_per_hour"],
            week_start=WEEKDAYS.index(view["week_start"]),
            default_view=view["default_view"],
        ),
        sync=_section(SyncConfig, data["sync"]),
        theme=_section(ThemeConfig, data["theme"]),
        keys=dict(keys),
    )


def save_apple_id(apple_id: str, path: Path | None = None) -> None:
    """Set ``[account] apple_id`` in the user config, keeping the rest of the file."""
    path = path or paths.config_file()
    text = path.read_text() if path.exists() else ""
    line = f"apple_id = {json.dumps(apple_id)}"  # a JSON string is a valid TOML basic string
    header = re.search(r"^\[account\][ \t]*$", text, re.MULTILINE)
    if header is None:
        text = text.rstrip("\n") + ("\n\n" if text.strip() else "") + f"[account]\n{line}\n"
    else:
        start = header.end()
        nxt = re.compile(r"^\[", re.MULTILINE).search(text, start)
        end = nxt.start() if nxt else len(text)
        body, count = re.subn(
            r"^apple_id[ \t]*=.*$", lambda _: line, text[start:end], count=1, flags=re.MULTILINE
        )
        text = text[:start] + (body if count else f"\n{line}{body}") + text[end:]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
