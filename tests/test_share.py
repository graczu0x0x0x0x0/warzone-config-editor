"""Share export (Markdown / JSON): content, ordering, privacy."""

from __future__ import annotations

import json

import pytest

from conftest import COD25_TXT0, PROFILE_TXT0
from wzce.core import ConfigDocument, KnowledgeBase, Translator
from wzce.core.hardware import HardwareInfo
from wzce.core.share_export import (
    DEFAULT_GROUPS,
    build_share,
    hardware_summary,
    to_json,
    to_markdown,
)

HW = HardwareInfo(
    gpu_name="NVIDIA GeForce RTX 5090", vram_mb=32607, refresh_hz=240, max_refresh_hz=240
)


@pytest.fixture(scope="module")
def kb() -> KnowledgeBase:
    return KnowledgeBase.load()


@pytest.fixture
def doc() -> ConfigDocument:
    return ConfigDocument.from_bytes(COD25_TXT0.read_bytes())


def _share(doc, kb, lang="en", **kwargs):
    return build_share(doc, kb, Translator(lang), game="Black Ops 7 / Warzone", title_code="cod25",
                       app="Warzone Config Editor test", **kwargs)  # fmt: skip


def test_default_groups_and_order(doc, kb) -> None:
    export = _share(doc, kb)
    assert [g.id for g in export.groups] == list(DEFAULT_GROUPS)
    display = export.groups[0]
    assert display.name == "Display"
    assert display.rows[0].key == "DisplayMode@0"  # editor order: mode first
    keys = {row.key for group in export.groups for row in group.rows}
    assert {"VSync@0", "NvidiaReflex@0", "ShaderQuality@0", "DLSSModeMP@0"} <= keys
    assert "VoiceVolume@0" not in keys  # audio not selected


def test_values_are_human_readable(doc, kb) -> None:
    rows = {r.key: r for g in _share(doc, kb, lang="pl").groups for r in g.rows}
    assert rows["DisplayMode@0"].value == "Pełny ekran"
    assert rows["DisplayMode@0"].raw == "Fullscreen"
    assert rows["VideoMemoryScaleMP@0"].value == "50 %"
    assert rows["MaxFpsInGame@0"].value == "250 fps"
    assert rows["CapFps@0"].value == "Wył."


def test_privacy_no_hardware_or_managed_values(doc, kb) -> None:
    export = _share(doc, kb, groups=[g.id for g in kb.groups], include_advanced=True)
    keys = {r.key for g in export.groups for r in g.rows}
    forbidden = {"SoundOutputDevice@0", "GPUName@0", "Monitor@0", "WindowX@0",
                 "LastUsedGPU@0", "GPUDriverVersion@0", "DetectedMemoryAmountMB@0"}  # fmt: skip
    assert not keys & forbidden
    text = to_markdown(export, Translator("en")) + to_json(export)
    assert "{0.0.0." not in text  # no audio device GUIDs


def test_basic_only_hides_advanced(doc, kb) -> None:
    basic = {r.key for g in _share(doc, kb).groups for r in g.rows}
    full = {r.key for g in _share(doc, kb, include_advanced=True).groups for r in g.rows}
    assert "PreferredDisplayMode@0" not in basic
    assert "PreferredDisplayMode@0" in full


def test_markdown_layout(doc, kb) -> None:
    hardware = [("gpu", "Graphics", "NVIDIA GeForce RTX 5090 · 32 GB VRAM")]
    text = to_markdown(_share(doc, kb, hardware=hardware), Translator("en"))
    lines = text.splitlines()
    assert lines[0] == "# Call of Duty settings — Black Ops 7 / Warzone"
    assert lines[2].startswith("_Exported ") and lines[2].endswith(
        "with Warzone Config Editor test_"
    )
    assert (
        "## Hardware" in lines and "- **Graphics:** NVIDIA GeForce RTX 5090 · 32 GB VRAM" in lines
    )
    assert "- **Display mode:** Fullscreen `DisplayMode@0`" in lines
    assert "|" not in text  # lists, not tables: Discord does not render tables


def test_json_structure(doc, kb) -> None:
    data = json.loads(to_json(_share(doc, kb, hardware=[("cpu", "Processor", "Ryzen")])))
    assert data["format"] == "wzce-settings-share"
    assert data["game"] == "Black Ops 7 / Warzone" and data["title_code"] == "cod25"
    assert data["hardware"] == {"cpu": "Ryzen"}
    first = data["groups"][0]["settings"][0]
    assert first == {
        "key": "DisplayMode@0",
        "name": "Display mode",
        "value": "Fullscreen",
        "raw": "Fullscreen",
    }


def test_account_file_groups(kb) -> None:
    account = ConfigDocument.from_bytes(PROFILE_TXT0.read_bytes())
    export = _share(account, kb, groups=["aim"])
    rows = {r.key: r for g in export.groups for r in g.rows}
    assert rows["Fov@1"].value == "120 °"
    assert "MouseHorizontalSensibility@0" in rows


def test_hardware_summary_from_system_info() -> None:
    from test_system import _info

    lines = {hw_id: value for hw_id, _, value in hardware_summary(_info(), HW, Translator("pl"))}
    assert lines["cpu"] == "AMD Ryzen 7 9800X3D 8-Core (8C/16T)"
    assert lines["gpu"] == "NVIDIA GeForce RTX 5090 · 32 GB VRAM"
    assert lines["ram"] == "64 GB DDR5 · 4800 MT/s · EXPO/XMP wyłączone"
    assert lines["monitor"] == "MAG 321U X24 · 240 Hz"
    assert all("G:" not in value and "Steam" not in value for value in lines.values())


def test_hardware_summary_without_data() -> None:
    assert hardware_summary(None, None, Translator("en")) == []


def test_other_gpu_vendor_settings_are_left_out(doc, kb) -> None:
    nvidia = {r.key for g in _share(doc, kb, gpu_vendor="nvidia").groups for r in g.rows}
    unknown = {r.key for g in _share(doc, kb).groups for r in g.rows}
    assert "AmdAntilag2@0" not in nvidia and "NvidiaReflex@0" in nvidia
    assert "AmdAntilag2@0" in unknown  # vendor not known: keep everything
