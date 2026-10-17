"""System information parsing, RAM heuristics and system checks (fixture data, no OS calls)."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from conftest import COD25_TXT0
from wzce.core import ConfigDocument
from wzce.core.hardware import HardwareInfo
from wzce.core.system_checks import Severity, Status, evaluate_checks, warnings
from wzce.core.system_info import (
    DriveInfo,
    GameInstall,
    MemoryModule,
    SystemInfo,
    apply_cim_json,
    decode_part_number,
    expo_state,
    parse_acf_installdir,
    parse_bar1_total,
    parse_channel,
    parse_nvidia_csv,
    parse_power_plan,
    parse_vdf_library_paths,
)

FIXTURE = Path(__file__).parent / "fixtures" / "system_cim.json"
NVIDIA_CSV = "NVIDIA GeForce RTX 5090, 617.42, 32607, 5, 5, 16, 16, 600.00, 41"
NVIDIA_MEMORY = """
    FB Memory Usage
        Total                             : 32607 MiB
    BAR1 Memory Usage
        Total                             : 32768 MiB
        Used                              : 1 MiB
"""
HW = HardwareInfo(refresh_hz=240, max_refresh_hz=240)


def _info() -> SystemInfo:
    info = SystemInfo()
    apply_cim_json(info, json.loads(FIXTURE.read_text(encoding="utf-8")))
    info.nvidia = parse_nvidia_csv(NVIDIA_CSV, parse_bar1_total(NVIDIA_MEMORY))
    info.power_plan, info.hags, info.game_mode = "high_performance", True, True
    info.background_recording, info.windowed_optimizations = False, True
    drive = next(d for d in info.drives if d.letter == "G")
    info.game_install = GameInstall(
        r"G:\SteamLibrary\steamapps\common\Call of Duty HQ", drive, 247.0
    )
    return info


@pytest.fixture
def doc() -> ConfigDocument:
    return ConfigDocument.from_bytes(COD25_TXT0.read_bytes())


# ---------------------------------------------------------------- parsing


def test_cim_json_is_parsed() -> None:
    info = _info()
    assert info.cpu_name == "AMD Ryzen 7 9800X3D 8-Core Processor"
    assert (info.cpu_cores, info.cpu_threads, info.cpu_l3_kb) == (8, 16, 98304)
    assert info.x3d_cache
    assert info.board == "Gigabyte X870E AORUS ELITE WIFI7"
    assert info.monitors == ["MAG 321U X24 (2024)"]
    assert info.vbs_running and not info.hvci_running
    assert info.memory_total_gb == 64
    assert (info.memory_type, info.memory_speed_mts, info.memory_channels) == ("DDR5", 4800, 2)
    assert info.dedicated_gpu.name == "NVIDIA GeForce RTX 5090"
    assert info.has_integrated_gpu


def test_missing_sections_are_tolerated() -> None:
    info = SystemInfo()
    apply_cim_json(info, {"cpu": None, "memory": None})
    assert info.memory == [] and info.memory_total_gb is None and info.cpu_name is None


@pytest.mark.parametrize(
    ("labels", "channel"),
    [
        (("P0 CHANNEL A", "DIMM 1"), "A"),
        (("BANK 0", "Controller0-ChannelB-DIMM1"), "B"),
        (("ChannelA-DIMM0", ""), "A"),
        (("BANK 0", "DIMM 1"), None),
    ],
)
def test_parse_channel(labels, channel) -> None:
    assert parse_channel(*labels) == channel


@pytest.mark.parametrize(
    ("part", "expected"),
    [
        ("F5-6000J3038F16G", (6000, 30)),  # G.Skill
        ("KF560C30BBEK2-32", (6000, 30)),  # Kingston FURY
        ("CMK32GX5M2B6000C30", (6000, 30)),  # Corsair
        ("FF3D532G6000HC38ADC01", (6000, 38)),  # TeamGroup
        ("6400 Series", (6400, None)),  # Patriot (no CL)
        ("M425R1GB4BB0-CQKOL", (None, None)),  # Samsung JEDEC, nothing encoded
        ("", (None, None)),
    ],
)
def test_decode_part_number(part, expected) -> None:
    assert decode_part_number(part) == expected


def _module(speed: int, voltage: int = 1100, rated: int | None = None, kind: str = "DDR5"):
    return MemoryModule("A", "A", "X", "", 16, kind, speed, voltage, rated, None)


@pytest.mark.parametrize(
    ("modules", "state"),
    [
        ([_module(4800, rated=6400)], "off"),  # the user's PC
        ([_module(6000, 1350, rated=6000)], "on"),
        ([_module(5600, rated=None)], "unknown"),  # JEDEC kit, nothing to compare
        ([_module(4800, 1350, rated=6400)], "unknown"),  # raised voltage: manual tuning?
        ([_module(2133, 1200, rated=3600, kind="DDR4")], "off"),
        ([_module(3600, 1350, kind="DDR4")], "on"),
        ([], "unknown"),
    ],
)
def test_expo_state(modules, state) -> None:
    assert expo_state(modules) == state


def test_nvidia_parsing() -> None:
    nv = parse_nvidia_csv(NVIDIA_CSV, 32768)
    assert (nv.pcie_gen, nv.pcie_width, nv.vram_mb, nv.power_limit_w) == (5, 16, 32607, 600.0)
    assert nv.rebar_enabled is True
    assert parse_nvidia_csv(NVIDIA_CSV, 256).rebar_enabled is False  # 256 MB BAR = ReBAR off
    assert parse_nvidia_csv("too, short", None) is None
    assert parse_nvidia_csv(NVIDIA_CSV.replace(" 41", " [N/A]"), None).temperature_c is None


def test_power_plan_vdf_acf_parsing() -> None:
    assert (
        parse_power_plan("GUID: 8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c  (Wysoka)")
        == "high_performance"
    )
    assert parse_power_plan("GUID: 381b4222-f694-41f0-9685-ff5bb260df2e (Balanced)") == "balanced"
    assert parse_power_plan("GUID: 11111111-2222-3333-4444-555555555555 (Mine)") == "custom"
    assert parse_power_plan("nothing") is None
    vdf = '"0" { "path" "C:\\\\Program Files (x86)\\\\Steam" } "1" { "path" "G:\\\\SteamLibrary" }'
    assert parse_vdf_library_paths(vdf) == ["C:\\Program Files (x86)\\Steam", "G:\\SteamLibrary"]
    assert parse_acf_installdir('"installdir"\t\t"Call of Duty HQ"') == "Call of Duty HQ"


def test_drive_kind() -> None:
    assert DriveInfo("C", "x", "SSD", "NVMe").kind == "nvme"
    assert DriveInfo("D", "x", "HDD", "SATA").kind == "hdd"
    assert DriveInfo("G", "x", "SSD", "SATA").kind == "ssd"
    assert DriveInfo("U", "x", "Unspecified", "USB").kind == "unknown"


# ----------------------------------------------------------------- checks


def _by_id(results):
    return {r.id: r for r in results}


def test_checks_on_the_users_pc(doc) -> None:
    results = evaluate_checks(_info(), HW, doc)
    by_id = _by_id(results)
    assert by_id["expo"].status is Status.WARN and by_id["expo"].severity is Severity.HIGH
    assert by_id["expo"].params == {"profile": "EXPO", "speed": 4800, "rated": 6400}
    assert by_id["game_drive"].status is Status.WARN and by_id["game_drive"].variant == "sata"
    assert by_id["igpu"].status is Status.INFO  # game already uses the RTX 5090
    for ok in ("channels", "ram_size", "disk_space", "refresh", "driver", "pcie", "rebar",
               "power_plan", "hags", "game_mode", "recording", "hvci"):  # fmt: skip
        assert by_id[ok].status is Status.OK, ok
    assert [r.id for r in warnings(results)] == ["expo", "game_drive"]  # most severe first


def test_checks_on_a_problem_pc(doc) -> None:
    info = _info()
    info.memory = info.memory[:1]  # one stick
    info.memory[0] = dataclasses.replace(info.memory[0], capacity_gb=8)
    info.drives = [DriveInfo("D", "HDD", "HDD", "SATA")]
    info.game_install = GameInstall("D:\\CoD", info.drives[0], 20.0)
    info.nvidia = parse_nvidia_csv(
        NVIDIA_CSV.replace("617.42", "580.10").replace(" 16, 16", " 8, 16"), 256
    )
    info.power_plan, info.hags, info.game_mode = "balanced", False, False
    info.background_recording, info.hvci_running = True, True
    hw = HardwareInfo(refresh_hz=60, max_refresh_hz=144)
    by_id = _by_id(evaluate_checks(info, hw, doc))

    expected = {
        "channels": (Status.WARN, Severity.HIGH),
        "ram_size": (Status.WARN, Severity.MEDIUM),
        "game_drive": (Status.WARN, Severity.HIGH),
        "disk_space": (Status.WARN, Severity.MEDIUM),
        "refresh": (Status.WARN, Severity.HIGH),
        "driver": (Status.WARN, Severity.MEDIUM),
        "pcie": (Status.WARN, Severity.MEDIUM),
        "rebar": (Status.WARN, Severity.MEDIUM),  # ReBAR off and GPUUploadHeaps=true in file
        "power_plan": (Status.WARN, Severity.LOW),
        "hags": (Status.WARN, Severity.LOW),
        "game_mode": (Status.WARN, Severity.LOW),
        "recording": (Status.WARN, Severity.LOW),
        "hvci": (Status.INFO, None),
    }
    for check_id, (status, severity) in expected.items():
        assert (by_id[check_id].status, by_id[check_id].severity) == (status, severity), check_id
    assert by_id["game_drive"].variant == "hdd"
    assert by_id["rebar"].variant == "heaps" and by_id["rebar"].action == "setting:GPUUploadHeaps@0"
    assert by_id["refresh"].action.startswith("ms-settings:")


def test_wrong_game_gpu_is_reported(doc) -> None:
    doc.set_value("GPUName@0", "AMD Radeon(TM) Graphics")
    result = _by_id(evaluate_checks(_info(), HW, doc))["igpu"]
    assert (result.status, result.variant) == (Status.WARN, "wrong")


def test_checks_without_data_are_unknown() -> None:
    by_id = _by_id(evaluate_checks(SystemInfo()))
    assert all(r.status is Status.UNKNOWN for r in by_id.values()), [
        r.id for r in by_id.values() if r.status is not Status.UNKNOWN
    ]


def test_intel_cpu_says_xmp() -> None:
    info = _info()
    info.cpu_name = "Intel(R) Core(TM) i7-14700K"
    assert _by_id(evaluate_checks(info))["expo"].params["profile"] == "XMP"
