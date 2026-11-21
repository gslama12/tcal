from click.testing import CliRunner

from tcal.__main__ import cli


def test_help() -> None:
    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "--demo" in result.output


def test_bad_config_is_reported(tcal_home) -> None:
    tcal_home.mkdir()
    (tcal_home / "config.toml").write_text("[nope]\n")
    result = CliRunner().invoke(cli, ["--demo"])
    assert result.exit_code != 0
    assert "unknown config section" in result.output
