"""Backup creation, listing, integrity-checked restore and pruning."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import not_running, running
from wzce.core import BackupError, BackupManager, GameRunningError, SettingsFileSet
from wzce.core.paths import app_data_dir


def test_default_root_uses_app_data_dir(isolated_app_data: Path) -> None:
    assert app_data_dir() == isolated_app_data
    assert BackupManager().root == isolated_app_data / "backups"


def test_create_copies_whole_set(cod25_set: SettingsFileSet) -> None:
    info = BackupManager().create(cod25_set, reason="test")
    assert sorted(info.files) == ["s.1.0.cod25.m", "s.1.0.cod25.txt0", "s.1.0.cod25.txt1"]
    assert info.reason == "test"
    assert info.matches(cod25_set)
    for src in cod25_set.existing_files():
        assert (info.path / src.name).read_bytes() == src.read_bytes()


def test_list_is_newest_first_and_filtered(cod25_set: SettingsFileSet, players_dir: Path) -> None:
    manager = BackupManager()
    first = manager.create(cod25_set)
    second = manager.create(cod25_set)
    other = manager.create(SettingsFileSet.from_path(players_dir / "s.1.0.cod26.txt"))
    assert [b.id for b in manager.list(cod25_set)] == [second.id, first.id]
    assert {b.id for b in manager.list()} == {first.id, second.id, other.id}


def test_restore_round_trip(cod25_set: SettingsFileSet) -> None:
    manager = BackupManager()
    original = {p.name: p.read_bytes() for p in cod25_set.existing_files()}
    backup = manager.create(cod25_set)

    doc = cod25_set.load().document
    doc.set_value("MaxFpsInGame@0", 60)
    cod25_set.save(doc, game_running=not_running)

    safety = manager.restore(backup, cod25_set, game_running=not_running)
    assert {p.name: p.read_bytes() for p in cod25_set.existing_files()} == original
    # The state we replaced is kept, so the restore can be undone.
    assert (safety.path / "s.1.0.cod25.txt0").read_bytes() == doc.to_bytes()


def test_restore_refuses_while_game_runs(cod25_set: SettingsFileSet) -> None:
    manager = BackupManager()
    backup = manager.create(cod25_set)
    with pytest.raises(GameRunningError):
        manager.restore(backup, cod25_set, game_running=running)


def test_restore_detects_damaged_backup(cod25_set: SettingsFileSet) -> None:
    manager = BackupManager()
    backup = manager.create(cod25_set)
    (backup.path / "s.1.0.cod25.txt0").write_bytes(b"tampered")
    before = cod25_set.slots[0].read_bytes()
    with pytest.raises(BackupError):
        manager.restore(backup, cod25_set, game_running=not_running)
    assert cod25_set.slots[0].read_bytes() == before


def test_restore_rejects_backup_of_other_set(cod25_set: SettingsFileSet, players_dir: Path) -> None:
    manager = BackupManager()
    other = manager.create(SettingsFileSet.from_path(players_dir / "s.1.0.cod26.txt"))
    with pytest.raises(BackupError):
        manager.restore(other, cod25_set, game_running=not_running)


def test_prune_keeps_newest(cod25_set: SettingsFileSet) -> None:
    manager = BackupManager()
    created = [manager.create(cod25_set) for _ in range(5)]
    removed = manager.prune(cod25_set, keep=2)
    assert {b.id for b in removed} == {b.id for b in created[:3]}
    assert [b.id for b in manager.list(cod25_set)] == [created[4].id, created[3].id]


def test_damaged_manifest_is_skipped(cod25_set: SettingsFileSet) -> None:
    manager = BackupManager()
    good = manager.create(cod25_set)
    bad = manager.root / "broken"
    bad.mkdir()
    (bad / "manifest.json").write_text("{not json", encoding="utf-8")
    assert [b.id for b in manager.list()] == [good.id]


def test_nothing_to_back_up(tmp_path: Path) -> None:
    with pytest.raises(BackupError):
        BackupManager().create(SettingsFileSet(tmp_path, "s.1.0.cod25", is_ab=True))
