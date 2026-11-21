from datetime import date
from pathlib import Path

import pytest

from tcal.config import Config, load_config
from tcal.providers.fake import FakeProvider
from tcal.source import ProviderSource
from tcal.ui.app import TcalApp

TODAY = date(2026, 11, 18)  # a Wednesday


@pytest.fixture(autouse=True)
def tcal_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Every test gets its own empty TCAL_HOME, never the user's real files."""
    home = tmp_path / "tcal-home"
    monkeypatch.setenv("TCAL_HOME", str(home))
    return home


@pytest.fixture
def write_config(tcal_home: Path):
    """Write a user config.toml into the test's TCAL_HOME and load it."""

    def write(text: str) -> Config:
        tcal_home.mkdir(parents=True, exist_ok=True)
        (tcal_home / "config.toml").write_text(text)
        return load_config()

    return write


@pytest.fixture
def provider() -> FakeProvider:
    return FakeProvider(today=TODAY)


@pytest.fixture
def make_app(provider: FakeProvider):
    def make(config: Config | None = None) -> TcalApp:
        return TcalApp(ProviderSource(provider), config or load_config(), today=TODAY)

    return make
