from click.testing import CliRunner
from conftest import TODAY
from icloud_http import APPLE_ID, PASSWORD, FakeICloud, connect

from tcal import doctor
from tcal.__main__ import cli
from tcal.config import load_config


def _run(server: FakeICloud | None = None) -> tuple[bool, str]:
    lines: list[str] = []
    ok = doctor.run(load_config(), lines.append, connect(server or FakeICloud()), TODAY)
    return ok, "\n".join(lines)


def test_all_steps_pass(write_config, monkeypatch) -> None:
    write_config(f'[account]\napple_id = "{APPLE_ID}"\n')
    monkeypatch.setenv("TCAL_PASSWORD", PASSWORD)
    ok, out = _run()
    assert ok, out
    assert "✓ password: from $TCAL_PASSWORD" in out
    assert "✓ sign-in: principal https://caldav.icloud.com/1234567/principal/" in out
    assert "✓ calendar home: https://p42-caldav.icloud.com/1234567/calendars/" in out
    assert "#FF2968  Work\n" in out and "#CC73E1  Holidays  (read-only)" in out
    assert "Reminders" not in out
    assert "✓ events this week (2026-11-16 – 2026-11-22): 5" in out
    assert "✓ write access (server privileges, nothing written): Work" in out
    assert out.endswith("All checks passed.")


def test_wrong_password_explains_app_specific_passwords(write_config, memory_keyring) -> None:
    write_config(f'[account]\napple_id = "{APPLE_ID}"\n')
    memory_keyring.set_password("tcal", APPLE_ID, "Hunter2!")
    ok, out = _run()
    assert not ok
    assert "✓ password: from system keyring" in out
    assert "! password: doesn't look like an app-specific password" in out
    assert "✗ sign-in: " in out and "App-Specific Passwords" in out
    assert "calendar home" not in out  # stops at the first failure


def test_no_account_or_password() -> None:
    ok, out = _run()
    assert not ok and "✗ account: no Apple ID configured" in out and "tcal login" in out


def test_missing_password(write_config) -> None:
    write_config(f'[account]\napple_id = "{APPLE_ID}"\n')
    ok, out = _run()
    assert not ok and "✗ password: none in the system keyring" in out


def test_cli_exit_code() -> None:
    result = CliRunner().invoke(cli, ["doctor"])
    assert result.exit_code == 1 and "no Apple ID configured" in result.output
