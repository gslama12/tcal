import pytest

from tcal.config import ConfigError, load_config, parse_hhmm


def test_defaults() -> None:
    config = load_config()
    assert config.view.day_start == 6 * 60 + 30
    assert config.view.day_end == 24 * 60
    assert config.view.week_start == 0
    assert config.view.default_view == "week"
    assert config.keys["cursor_down"] == ["j", "down"]
    assert config.theme.name == "tokyo-night"


def test_user_file_merges_over_defaults(write_config) -> None:
    config = write_config(
        '[view]\nday_start = "08:00"\nweek_start = "sunday"\n[keys]\nquit = ["Q"]\n'
    )
    assert config.view.day_start == 480
    assert config.view.week_start == 6
    assert config.view.day_end == 24 * 60  # untouched default
    assert config.keys["quit"] == ["Q"]
    assert config.keys["today"] == ["t"]


@pytest.mark.parametrize(
    "text",
    [
        "[nope]\nx = 1\n",
        "[view]\nday_strat = '08:00'\n",
        "[keys]\nfly = ['f']\n",
        "[keys]\nquit = 'q'\n",
        "[view]\ndefault_view = 'decade'\n",
        "[view]\nday_start = '25:00'\n",
        "[view]\nday_start = '20:00'\nday_end = '08:00'\n",
        "not toml [",
    ],
)
def test_invalid_config(write_config, text: str) -> None:
    with pytest.raises(ConfigError):
        write_config(text)


def test_parse_hhmm() -> None:
    assert parse_hhmm("00:00") == 0
    assert parse_hhmm("24:00") == 1440
    with pytest.raises(ConfigError):
        parse_hhmm("7pm")
