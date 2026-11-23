import tomllib

import click
import pytest
from click.testing import CliRunner

from tcal import paths
from tcal.__main__ import cli
from tcal.config import commented_defaults, default_data, key_conflicts, load_config
from tcal.ui.theme import PALETTES, make_theme


def test_defaults_have_no_key_conflicts() -> None:
    assert key_conflicts(load_config()) == {}


def test_key_conflicts(write_config) -> None:
    config = write_config('[keys]\nquit = ["q", "t"]\nsync = ["t", "t"]\n')
    assert set(key_conflicts(config)["t"]) == {"today", "sync", "quit"}


def test_commented_defaults_parse_to_nothing() -> None:
    text = commented_defaults()
    assert tomllib.loads(text) == {}
    assert "# [keys]" in text and "# quit = " in text


def test_config_path() -> None:
    result = CliRunner().invoke(cli, ["config", "path"])
    assert result.output.strip() == str(paths.config_file())


def test_config_edit_creates_file(monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr(click, "edit", lambda filename: opened.append(filename))
    result = CliRunner().invoke(cli, ["config", "edit"])
    assert result.exit_code == 0, result.output
    assert opened == [str(paths.config_file())]
    assert paths.config_file().read_text() == commented_defaults()
    load_config()  # the generated file is valid


def test_config_check(write_config, tcal_home) -> None:
    result = CliRunner().invoke(cli, ["config", "check"])
    assert result.exit_code == 0 and "no config file at" in result.output
    write_config('[view]\nweek_start = "sunday"\n')
    result = CliRunner().invoke(cli, ["config", "check"])
    assert result.exit_code == 0 and result.output.endswith(": OK\n")
    write_config('[keys]\nsync = ["q"]\n')
    result = CliRunner().invoke(cli, ["config", "check"])
    assert result.exit_code != 0 and "key 'q' is bound to sync, quit" in result.output
    (tcal_home / "config.toml").write_text('[keys]\nfly = ["f"]\n')
    result = CliRunner().invoke(cli, ["config", "check"])
    assert result.exit_code != 0 and "unknown setting(s) in [keys]: fly" in result.output
    (tcal_home / "config.toml").write_text('[theme]\nname = "pink"\n')
    result = CliRunner().invoke(cli, ["config", "check"])
    assert result.exit_code != 0 and "unknown theme 'pink'" in result.output


async def test_conflicts_are_shown_at_startup(make_app, write_config) -> None:
    app = make_app(write_config('[keys]\nsync = ["q"]\n'))
    async with app.run_test() as pilot:
        await pilot.pause()
        messages = [n.message for n in app._notifications]
        assert any("key 'q' is bound to sync, quit" in m for m in messages)


async def test_unknown_theme_falls_back_with_a_notice(make_app, write_config) -> None:
    app = make_app(write_config('[theme]\nname = "dracula"\n'))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.theme == f"tcal-{default_data()['theme']['name']}"
        messages = [n.message for n in app._notifications]
        assert any("Unknown theme 'dracula'" in m for m in messages)


def test_default_theme_is_listed() -> None:
    assert default_data()["theme"]["name"] in PALETTES
    assert len(PALETTES) >= 5 and not make_theme("catppuccin-latte").dark


@pytest.mark.parametrize("name", PALETTES)
async def test_theme_renders(name, make_app, write_config, tmp_path) -> None:
    app = make_app(write_config(f'[theme]\nname = "{name}"\n'))
    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        assert app.theme == f"tcal-{name}"
        svg = app.export_screenshot()
        assert PALETTES[name].background1.lower() in svg.lower()
