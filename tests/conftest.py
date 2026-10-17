"""Shared fixtures. Tests only ever touch copies in tmp_path, never the live game folder."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

# GUI tests run headless; must be set before pytest-qt creates the QApplication.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from wzce.core import ConfigDocument, SettingsFileSet

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
SNAPSHOT = EXAMPLES / "live_snapshot_2026-10-17"
COD25_TXT0 = EXAMPLES / "s.1.0.cod25.txt0"
COD25_TXT1 = EXAMPLES / "s.1.0.cod25.txt1"
COD25_MARKER = SNAPSHOT / "s.1.0.cod25.m"
COD26_SINGLE = SNAPSHOT / "s.1.0.cod26.txt"
PROFILE_TXT0 = SNAPSHOT / "profile" / "g.cod25.1.0.l.txt0"

ALL_SAMPLE_FILES = sorted(p for p in EXAMPLES.rglob("*") if p.suffix in {".txt0", ".txt1", ".txt"})


@pytest.fixture
def cod25_doc() -> ConfigDocument:
    return ConfigDocument.from_bytes(COD25_TXT0.read_bytes())


@pytest.fixture
def players_dir(tmp_path: Path) -> Path:
    """A fake ``players`` folder with the cod25 A/B pair + marker and the cod26 single file."""
    players = tmp_path / "players"
    players.mkdir()
    for src in (COD25_TXT0, COD25_TXT1, COD25_MARKER, COD26_SINGLE):
        shutil.copy2(src, players / src.name)
    account = players / "76561190000000000"
    account.mkdir()
    for src in (SNAPSHOT / "profile").iterdir():
        shutil.copy2(src, account / src.name)
    return players


@pytest.fixture
def cod25_set(players_dir: Path) -> SettingsFileSet:
    return SettingsFileSet.from_path(players_dir / "s.1.0.cod25.txt0")


@pytest.fixture(autouse=True)
def isolated_app_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect our own data folder (backups etc.) into tmp for every test."""
    data_dir = tmp_path / "appdata"
    monkeypatch.setenv("WZCE_DATA_DIR", str(data_dir))
    return data_dir


def not_running() -> bool:
    return False


def running() -> bool:
    return True
