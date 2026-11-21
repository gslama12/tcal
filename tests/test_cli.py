import pytest
from click.testing import CliRunner

from tcal import __main__ as main
from tcal import paths
from tcal.__main__ import cli
from tcal.config import load_config, save_apple_id
from tcal.credentials import get_password
from tcal.providers.base import ProviderError
from tcal.providers.fake import FakeProvider
from tcal.store import Store


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


@pytest.fixture
def fake_connect(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str | None, str | None]]:
    """Make the CLI talk to a FakeProvider; records the credentials it was given."""
    seen: list[tuple[str | None, str | None]] = []

    def connect(config, apple_id=None, password=None):
        seen.append((apple_id, password))
        return FakeProvider()

    monkeypatch.setattr(main, "connect", connect)
    return seen


def test_login_stores_account_and_password(tcal_home, fake_connect, memory_keyring) -> None:
    result = CliRunner().invoke(cli, ["login"], input="me@icloud.com\nabcd-efgh\n")
    assert result.exit_code == 0, result.output
    assert "Logged in as me@icloud.com: 5 calendars" in result.output
    assert fake_connect == [("me@icloud.com", "abcd-efgh")]
    assert load_config().account.apple_id == "me@icloud.com"
    assert get_password(load_config().account) == "abcd-efgh"


def test_login_connection_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    class Broken(FakeProvider):
        def list_calendars(self):
            raise ProviderError("HTTP 401")

    monkeypatch.setattr(main, "connect", lambda *a, **k: Broken())
    result = CliRunner().invoke(cli, ["login", "--apple-id", "x", "--password", "y"])
    assert result.exit_code != 0 and "could not connect: HTTP 401" in result.output


def test_sync_and_calendars(fake_connect) -> None:
    result = CliRunner().invoke(cli, ["sync"])
    assert result.exit_code == 0, result.output
    assert result.output.startswith("Synced: 5 calendars")
    with Store(paths.database_file()) as store:
        assert len(store.calendars()) == 5
    result = CliRunner().invoke(cli, ["calendars"])
    assert "Holidays  (read-only)" in result.output


def test_without_account_asks_to_login() -> None:
    for args in (["sync"], ["calendars"], []):
        result = CliRunner().invoke(cli, args)
        assert result.exit_code != 0 and "tcal login" in result.output


def test_save_apple_id_keeps_other_settings(write_config, tcal_home) -> None:
    write_config(
        '[view]\ndefault_view = "month"\n\n[account]\napple_id = "old"\n\n[sync]\ninterval = 60\n'
    )
    save_apple_id("new@icloud.com")
    config = load_config()
    assert config.account.apple_id == "new@icloud.com"
    assert config.view.default_view == "month" and config.sync.interval == 60
    (tcal_home / "config.toml").write_text('[account]\npassword_cmd = "x"\n')
    save_apple_id("a@b.c")
    assert load_config().account.apple_id == "a@b.c"
