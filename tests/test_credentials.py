import pytest

from tcal.config import AccountConfig
from tcal.credentials import CredentialsError, get_password, store_password

ACCOUNT = AccountConfig("me@icloud.com", "https://caldav.icloud.com", "")


def test_keyring_first(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TCAL_PASSWORD", "from-env")
    store_password("me@icloud.com", "from-keyring")
    assert get_password(ACCOUNT) == "from-keyring"


def test_then_password_cmd_then_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TCAL_PASSWORD", "from-env")
    with_cmd = AccountConfig("me@icloud.com", "", "echo from-cmd")
    assert get_password(with_cmd) == "from-cmd"
    assert get_password(ACCOUNT) == "from-env"
    monkeypatch.delenv("TCAL_PASSWORD")
    assert get_password(ACCOUNT) is None


def test_failing_password_cmd() -> None:
    with pytest.raises(CredentialsError, match="password_cmd failed"):
        get_password(AccountConfig("me@icloud.com", "", "echo nope >&2; exit 1"))
