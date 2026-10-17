"""File discovery in a fake players folder, and document diffing."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from conftest import COD25_TXT0
from wzce.core import (
    ChangeKind,
    ConfigDocument,
    FileKind,
    Scope,
    diff_documents,
    diff_values,
    discover,
)
from wzce.core.diff import same_value
from wzce.core.discovery import classify_stem


def test_discover_finds_machine_and_account_files(players_dir: Path) -> None:
    found = discover([players_dir])
    summary = [(loc.title_code, loc.scope, loc.kind, loc.account_id) for loc in found]
    assert summary == [
        ("cod26", Scope.MACHINE, FileKind.SETTINGS, None),
        ("cod26", Scope.ACCOUNT, FileKind.PROFILE, "76561190000000000"),
        ("cod26", Scope.ACCOUNT, FileKind.PROFILE_PM, "76561190000000000"),
        ("cod25", Scope.MACHINE, FileKind.SETTINGS, None),
        ("cod25", Scope.ACCOUNT, FileKind.PROFILE, "76561190000000000"),
        ("cod25", Scope.ACCOUNT, FileKind.PROFILE_PM, "76561190000000000"),
    ]
    assert found[3].title_name == "Black Ops 7 / Warzone"
    assert found[0].title_name == "cod26"  # unknown titles still listed
    assert found[3].fileset.is_ab and not found[0].fileset.is_ab


def test_discover_ignores_manual_copies_and_steamcloud(players_dir: Path) -> None:
    shutil.copy2(COD25_TXT0, players_dir / "s.1.0.cod25_bu.txt0")
    shutil.copy2(COD25_TXT0, players_dir / "s.1.0.cod25_copy.txt0")
    cloud = players_dir / "76561190000000000" / "SteamCloud"
    cloud.mkdir()
    shutil.copy2(COD25_TXT0, cloud / "g.cod26.1.0.l.txt")
    # Machine-level file inside an account folder is someone's copy, not a real one.
    shutil.copy2(COD25_TXT0, players_dir / "76561190000000000" / "s.1.0.cod25.txt0")

    stems = [loc.fileset.stem for loc in discover([players_dir])]
    assert stems == [
        "s.1.0.cod26", "g.cod26.1.0.l", "g.cod26.pm.1.0.l",
        "s.1.0.cod25", "g.cod25.1.0.l", "g.cod25.pm.1.0.l",
    ]  # fmt: skip


def test_discover_tolerates_missing_dirs(tmp_path: Path) -> None:
    assert discover([tmp_path / "nope"]) == []


def test_diff_documents() -> None:
    before = ConfigDocument.from_bytes(COD25_TXT0.read_bytes())
    after = before.copy()
    after.set_value("MaxFpsInGame@0", 144)
    after.set_value("ShaderQuality@0", "Medium")
    changes = diff_documents(before, after)
    assert [(c.setting_id, c.old_raw, c.new_raw) for c in changes] == [
        ("MaxFpsInGame@0", "250", "144"),
        ("ShaderQuality@0", "Low", "Medium"),
    ]
    assert all(c.kind is ChangeKind.CHANGED for c in changes)


def test_diff_values_added_and_removed() -> None:
    changes = diff_values({"A@0": "1", "Gone@0": "x"}, {"A@0": "1", "New@0": "y"})
    assert [(c.setting_id, c.kind) for c in changes] == [
        ("New@0", ChangeKind.ADDED),
        ("Gone@0", ChangeKind.REMOVED),
    ]


def test_classify_stem() -> None:
    assert classify_stem("s.1.0.cod25") == (Scope.MACHINE, FileKind.SETTINGS, "cod25")
    assert classify_stem("g.cod26.1.0.l") == (Scope.ACCOUNT, FileKind.PROFILE, "cod26")
    assert classify_stem("g.cod25.pm.1.0.l") == (Scope.ACCOUNT, FileKind.PROFILE_PM, "cod25")
    assert classify_stem("s.1.0.cod25_bu") is None


# Float round-off written back by the game (observed in the FOV test, 2026-10-17).
@pytest.mark.parametrize(
    ("a", "b", "same"),
    [
        ("119.900000", "119.900002", True),  # float32 round-trip by the game
        ("0.031623", "0.031623", True),
        ("119.900000", "119.000000", False),
        ("0.850000", "0.860000", False),
        ("250", "251", False),  # integers compare exactly
        ("617.42", "617.420000", True),
        ("true", "false", False),
        ("Low", "Low", True),
        ("Auto", "1.0", False),
    ],
)
def test_same_value(a: str, b: str, same: bool) -> None:
    assert same_value(a, b) is same


def test_diff_ignores_float_round_off() -> None:
    assert diff_values({"Fov@1": "119.900000"}, {"Fov@1": "119.900002"}) == []
