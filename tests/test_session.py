"""EditorSession (the UI's model) and GPU vendor detection."""

from __future__ import annotations

import os

import pytest

from conftest import not_running, running
from wzce.core import ConfigDocument, GameRunningError, SettingsFileSet
from wzce.core.hardware import detect_gpu_vendor, gpu_vendor_from_name
from wzce.core.session import EditorSession


@pytest.fixture
def session(cod25_set: SettingsFileSet) -> EditorSession:
    return EditorSession(cod25_set, game_running=not_running)


def test_fresh_session_is_clean(session: EditorSession) -> None:
    assert not session.is_dirty
    assert session.pending_changes() == []
    assert not session.disk_changed()


def test_edit_and_revert(session: EditorSession) -> None:
    session.set_value("MaxFpsInGame@0", 144)
    session.set_value("ShaderQuality@0", "Medium")
    assert session.changed_ids() == {"MaxFpsInGame@0", "ShaderQuality@0"}
    assert session.is_changed("MaxFpsInGame@0")
    assert session.original.get("MaxFpsInGame@0").value == 250  # original untouched

    session.revert("MaxFpsInGame@0")
    assert session.changed_ids() == {"ShaderQuality@0"}
    session.discard_all()
    assert not session.is_dirty


def test_setting_original_value_again_is_not_a_change(session: EditorSession) -> None:
    session.set_value("MaxFpsInGame@0", 144)
    session.set_value("MaxFpsInGame@0", 250)
    assert not session.is_dirty


def test_restore_raw_keeps_non_canonical_text() -> None:
    doc = ConfigDocument.parse("1\nA@0;1;2 = 1 // 0.000000 to 2.000000\n")
    doc.set_value("A@0", 0.5)
    doc.restore_raw("A@0", "1")
    assert doc.to_text() == "1\nA@0;1;2 = 1 // 0.000000 to 2.000000\n"


def test_save_resets_baseline_and_backs_up(session: EditorSession) -> None:
    session.set_value("MaxFpsInGame@0", 144)
    result = session.save()
    assert result.backup is not None
    assert not session.is_dirty
    assert session.original.get("MaxFpsInGame@0").value == 144
    assert session.loaded.slots_in_sync
    assert not session.disk_changed()


def test_save_while_game_runs_keeps_changes(cod25_set: SettingsFileSet) -> None:
    session = EditorSession(cod25_set, game_running=running)
    session.set_value("MaxFpsInGame@0", 144)
    with pytest.raises(GameRunningError):
        session.save()
    assert session.is_dirty  # nothing lost


def test_disk_change_is_detected(session: EditorSession) -> None:
    path = session.fileset.slots[0]
    path.write_bytes(path.read_bytes() + b"\n")
    os.utime(path, ns=(1, 1))
    assert session.disk_changed()
    session.reload()
    assert not session.disk_changed()


def test_gpu_vendor(session: EditorSession) -> None:
    assert session.gpu_vendor == "nvidia"


@pytest.mark.parametrize(
    ("name", "vendor"),
    [
        ("NVIDIA GeForce RTX 5090", "nvidia"),
        ("GeForce GTX 1660", "nvidia"),
        ("AMD Radeon RX 7900 XTX", "amd"),
        ("Radeon(TM) Graphics", "amd"),
        ("Intel(R) Arc(TM) A770 Graphics", "intel"),
        ("Intel(R) UHD Graphics 770", "intel"),
        ("Microsoft Basic Render Driver", None),
        ("", None),
    ],
)
def test_gpu_vendor_from_name(name: str, vendor: str | None) -> None:
    assert gpu_vendor_from_name(name) == vendor


def test_detect_vendor_without_gpu_lines() -> None:
    assert detect_gpu_vendor(ConfigDocument.parse("1\nA@0;1;2 = true\n")) is None
