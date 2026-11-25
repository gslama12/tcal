from pathlib import Path

import pytest

from tcal import paths


def test_tcal_home_relocates_everything(tcal_home: Path) -> None:
    assert paths.config_file() == tcal_home / "config.toml"
    assert paths.database_file() == tcal_home / "data" / "tcal.db"


def test_xdg_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TCAL_HOME")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert paths.config_file() == tmp_path / "cfg" / "tcal" / "config.toml"
    assert paths.data_dir() == tmp_path / ".local" / "share" / "tcal"
