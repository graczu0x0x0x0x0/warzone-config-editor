"""A/B slot handling, safe saving, read-only attribute, rollback."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from conftest import not_running, running
from wzce.core import (
    BackupManager,
    ConfigDocument,
    GameRunningError,
    SettingsFileSet,
    WzceError,
)
from wzce.core import storage as storage_module

# ------------------------------------------------------------------ fileset


def test_from_path_accepts_any_member(players_dir: Path) -> None:
    names = ["s.1.0.cod25.txt0", "s.1.0.cod25.txt1", "s.1.0.cod25.m"]
    sets = {SettingsFileSet.from_path(players_dir / n) for n in names}
    assert len(sets) == 1
    fs = sets.pop()
    assert fs.is_ab
    assert fs.title_code == "cod25"
    assert [p.name for p in fs.slots] == ["s.1.0.cod25.txt0", "s.1.0.cod25.txt1"]
    assert fs.marker.name == "s.1.0.cod25.m"


def test_single_file_set(players_dir: Path) -> None:
    fs = SettingsFileSet.from_path(players_dir / "s.1.0.cod26.txt")
    assert not fs.is_ab
    assert fs.marker is None
    assert fs.title_code == "cod26"
    assert len(fs.load().document) == 163


def test_from_path_rejects_other_files(tmp_path: Path) -> None:
    with pytest.raises(WzceError):
        SettingsFileSet.from_path(tmp_path / "keybinds.cod25.kb")


# --------------------------------------------------------------- active slot


@pytest.mark.parametrize(("marker", "expected"), [(b"\x00\x00", 0), (b"\x01\x01", 1)])
def test_marker_selects_active_slot(cod25_set: SettingsFileSet, marker: bytes, expected) -> None:
    cod25_set.marker.write_bytes(marker)
    assert cod25_set.active_slot_index() == expected
    assert cod25_set.load().source == cod25_set.slots[expected]


def test_missing_marker_falls_back_to_newest_file(cod25_set: SettingsFileSet) -> None:
    cod25_set.marker.unlink()
    txt0, txt1 = cod25_set.slots
    os.utime(txt0, (1_000_000, 1_000_000))
    os.utime(txt1, (2_000_000, 2_000_000))
    assert cod25_set.active_slot_index() == 1
    os.utime(txt0, (3_000_000, 3_000_000))
    assert cod25_set.active_slot_index() == 0


def test_marker_pointing_at_missing_slot_is_ignored(cod25_set: SettingsFileSet) -> None:
    cod25_set.marker.write_bytes(b"\x01\x01")
    cod25_set.slots[1].unlink()
    assert cod25_set.active_slot_index() == 0


def test_load_reports_slot_differences(cod25_set: SettingsFileSet) -> None:
    loaded = cod25_set.load()  # sample marker = 01 01 -> txt1 (WindowMaximized = true)
    assert loaded.source.name == "s.1.0.cod25.txt1"
    assert not loaded.slots_in_sync
    assert [c.setting_id for c in loaded.slot_differences] == ["WindowMaximized@0"]


# ---------------------------------------------------------------------- save


def _edited(fs: SettingsFileSet) -> ConfigDocument:
    doc = fs.load().document
    doc.set_value("MaxFpsInGame@0", 144)
    return doc


def test_save_writes_identical_bytes_to_both_slots(cod25_set: SettingsFileSet) -> None:
    marker_before = cod25_set.marker.read_bytes()
    doc = _edited(cod25_set)
    result = cod25_set.save(doc, game_running=not_running)

    assert result.written == list(cod25_set.slots)
    expected = doc.to_bytes()
    assert all(p.read_bytes() == expected for p in cod25_set.slots)
    assert cod25_set.marker.read_bytes() == marker_before  # never touched
    assert cod25_set.load().slots_in_sync
    assert not list(cod25_set.directory.glob("*.wzce-tmp"))


def test_save_refuses_while_game_runs(cod25_set: SettingsFileSet) -> None:
    before = [p.read_bytes() for p in cod25_set.slots]
    with pytest.raises(GameRunningError):
        cod25_set.save(_edited(cod25_set), game_running=running)
    assert [p.read_bytes() for p in cod25_set.slots] == before


def test_save_creates_backup_first(cod25_set: SettingsFileSet, tmp_path: Path) -> None:
    originals = {p.name: p.read_bytes() for p in cod25_set.existing_files()}
    manager = BackupManager(tmp_path / "backups")
    result = cod25_set.save(_edited(cod25_set), backup_manager=manager, game_running=not_running)

    assert result.backup is not None
    assert set(result.backup.files) == set(originals)
    for name, data in originals.items():
        assert (result.backup.path / name).read_bytes() == data


def test_save_preserves_read_only_attribute(cod25_set: SettingsFileSet) -> None:
    cod25_set.set_read_only(True)
    assert cod25_set.is_read_only()
    result = cod25_set.save(_edited(cod25_set), game_running=not_running)
    assert cod25_set.is_read_only()
    assert result.read_only_preserved == list(cod25_set.slots)
    assert cod25_set.load().document.get("MaxFpsInGame@0").value == 144
    cod25_set.set_read_only(False)
    assert not cod25_set.is_read_only()


def test_failed_second_slot_rolls_back_first(
    cod25_set: SettingsFileSet, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = [p.read_bytes() for p in cod25_set.slots]
    real_write = storage_module.write_atomic
    calls = {"n": 0}

    def flaky_write(path: Path, data: bytes) -> bool:
        calls["n"] += 1
        if calls["n"] == 2:  # second slot fails (e.g. file locked by antivirus)
            raise PermissionError("locked")
        return real_write(path, data)

    monkeypatch.setattr(storage_module, "write_atomic", flaky_write)
    with pytest.raises(PermissionError):
        cod25_set.save(_edited(cod25_set), game_running=not_running)
    monkeypatch.setattr(storage_module, "write_atomic", real_write)
    assert [p.read_bytes() for p in cod25_set.slots] == before


def test_save_single_file(players_dir: Path) -> None:
    fs = SettingsFileSet.from_path(players_dir / "s.1.0.cod26.txt")
    doc = fs.load().document
    doc.set_value("MaxFpsInGame@0", 165)
    fs.save(doc, game_running=not_running)
    assert fs.load().document.get("MaxFpsInGame@0").value == 165
    assert sorted(p.name for p in players_dir.glob("s.1.0.cod26*")) == ["s.1.0.cod26.txt"]
