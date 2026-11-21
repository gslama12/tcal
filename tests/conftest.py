from collections.abc import Iterator
from datetime import date
from pathlib import Path

import keyring
import pytest
from keyring.backend import KeyringBackend
from textual.message import Message

from tcal import paths
from tcal.config import Config, load_config
from tcal.providers.fake import FakeProvider
from tcal.source import StoreSource
from tcal.store import Store
from tcal.sync import SyncEngine
from tcal.ui import app as app_module
from tcal.ui.app import TcalApp
from tcal.ui.messages import EventSelected, NewEventRequested

TODAY = date(2026, 11, 18)  # a Wednesday


@pytest.fixture(autouse=True)
def tcal_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Every test gets its own empty TCAL_HOME, never the user's real files."""
    home = tmp_path / "tcal-home"
    monkeypatch.setenv("TCAL_HOME", str(home))
    return home


class MemoryKeyring(KeyringBackend):
    priority = 1

    def __init__(self) -> None:
        super().__init__()
        self.passwords: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.passwords.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.passwords[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self.passwords.pop((service, username), None)


@pytest.fixture(autouse=True)
def memory_keyring() -> Iterator[MemoryKeyring]:
    """Never touch the real system keyring."""
    previous = keyring.get_keyring()
    backend = MemoryKeyring()
    keyring.set_keyring(backend)
    yield backend
    keyring.set_keyring(previous)


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
def store(provider: FakeProvider, tcal_home: Path) -> Iterator[Store]:
    """The SQLite cache in TCAL_HOME, synced once from ``provider``."""
    with Store(paths.database_file()) as store:
        SyncEngine(provider, store, today=TODAY).sync()
        yield store


@pytest.fixture
def make_app(store: Store):
    def make(config: Config | None = None) -> TcalApp:
        return TcalApp(StoreSource(store), config or load_config(), today=TODAY)

    return make


class RecordingApp(TcalApp):
    """TcalApp that records the messages the views post for the CRUD screens
    (instead of opening them)."""

    CSS_PATH = str(Path(app_module.__file__).parent / "styles.tcss")

    def __init__(self, store: Store, config: Config | None = None) -> None:
        super().__init__(StoreSource(store), config or load_config(), today=TODAY)
        self.posted: list[Message] = []

    def on_new_event_requested(self, message: NewEventRequested) -> None:
        message.prevent_default()
        self.posted.append(message)

    def on_event_selected(self, message: EventSelected) -> None:
        message.prevent_default()
        self.posted.append(message)


@pytest.fixture
def app(store: Store) -> RecordingApp:
    return RecordingApp(store)
