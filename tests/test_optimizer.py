"""Hardware detection helpers and optimizer rules."""

from __future__ import annotations

import struct

import pytest

from wzce.core import ConfigDocument, KnowledgeBase
from wzce.core.hardware import (
    HardwareInfo,
    detect_hardware,
    parse_core_efficiency_classes,
    pick_adapter,
    split_core_classes,
)
from wzce.core.optimizer import Bottleneck, Goal, recommend, vram_fraction
from wzce.core.templates import SkipReason, plan_template

GB = 1024**3

# The user's actual machine (9800X3D, RTX 5090 32 GB, 240 Hz) - a realistic default.
DESKTOP = HardwareInfo(
    cpu_name="AMD Ryzen 7 9800X3D 8-Core Processor",
    physical_cores=8,
    logical_cores=16,
    gpu_name="NVIDIA GeForce RTX 5090",
    gpu_vendor="nvidia",
    vram_mb=32607,
    refresh_hz=240,
    max_refresh_hz=240,
)
HYBRID = HardwareInfo(physical_cores=24, logical_cores=32, performance_cores=8, efficiency_cores=16)


@pytest.fixture(scope="module")
def kb() -> KnowledgeBase:
    return KnowledgeBase.load()


# ------------------------------------------------------------ CPU parsing


def _core_record(efficiency: int, size: int = 48) -> bytes:
    body = struct.pack("<BB", 0, efficiency) + b"\0" * (size - 10)
    return struct.pack("<II", 0, size) + body


def _other_record(size: int = 32) -> bytes:
    return struct.pack("<II", 2, size) + b"\0" * (size - 8)  # e.g. RelationCache


def test_parse_core_efficiency_classes() -> None:
    buffer = _core_record(1) + _other_record() + _core_record(1) + _core_record(0)
    assert parse_core_efficiency_classes(buffer) == [1, 1, 0]


def test_parse_stops_on_garbage() -> None:
    assert parse_core_efficiency_classes(b"\0" * 8) == []  # size 0 must not loop forever
    assert parse_core_efficiency_classes(b"") == []


@pytest.mark.parametrize(
    ("classes", "expected"),
    [
        ([1] * 8 + [0] * 16, (8, 16)),  # Intel 14900K style
        ([0] * 8, (None, None)),  # classic CPU
        ([], (None, None)),
    ],
)
def test_split_core_classes(classes, expected) -> None:
    assert split_core_classes(classes) == expected


def test_worker_cores() -> None:
    assert DESKTOP.worker_cores == 8 and not DESKTOP.is_hybrid
    assert HYBRID.worker_cores == 8 and HYBRID.is_hybrid


# ---------------------------------------------------------- GPU adapters


def test_pick_adapter_prefers_name_then_vram() -> None:
    adapters = [("Intel(R) UHD Graphics 770", 2 * GB), ("NVIDIA GeForce RTX 4070", 12 * GB)]
    assert pick_adapter(adapters, "Intel(R) UHD Graphics 770")[0].startswith("Intel")
    assert pick_adapter(adapters, None)[0].startswith("NVIDIA")
    assert pick_adapter(adapters, "Unknown GPU")[0].startswith("NVIDIA")
    assert pick_adapter([("Basic Display", 0)], None) is None
    assert pick_adapter([], "x") is None


def test_detect_hardware_never_raises(cod25_doc: ConfigDocument) -> None:
    info = detect_hardware(cod25_doc)
    assert isinstance(info, HardwareInfo)
    assert info.gpu_name == "NVIDIA GeForce RTX 5090"  # from the file
    assert info.gpu_vendor == "nvidia"


# --------------------------------------------------------------- rules


@pytest.mark.parametrize(
    ("vram_mb", "goal", "expected"),
    [
        (4096, Goal.BALANCED, 0.55),
        (8192, Goal.BALANCED, 0.65),
        (8192, Goal.LOW_END, 0.6),
        (12288, Goal.COMPETITIVE, 0.7),
        (16384, Goal.QUALITY, 0.8),
        (32607, Goal.COMPETITIVE, 0.8),
        (32607, Goal.QUALITY, 0.85),
    ],
)
def test_vram_fraction(vram_mb, goal, expected) -> None:
    assert vram_fraction(vram_mb, goal) == pytest.approx(expected)


def test_recommend_competitive_desktop(cod25_doc, kb) -> None:
    result = recommend(kb, cod25_doc, DESKTOP, Goal.COMPETITIVE)
    assert result.values["RendererWorkerCount@0"] == 8
    assert result.reasons["RendererWorkerCount@0"].key == "optimizer.reason_cores"
    assert result.values["VideoMemoryScaleMP@0"] == pytest.approx(0.8)
    assert result.reasons["VideoMemoryScaleMP@0"].params == {"gb": 32}
    assert result.values["MaxFpsInGame@0"] == 237
    assert result.values["AATechniquePreferredMP@0"] == "DLSS"
    assert result.values["ShaderQuality@0"] == "Medium"  # from the preset
    assert result.reasons["ShaderQuality@0"].key == "optimizer.reason_preset"


def test_recommend_hybrid_cpu_and_clamping(cod25_doc, kb) -> None:
    result = recommend(kb, cod25_doc, HYBRID, Goal.BALANCED)
    assert result.values["RendererWorkerCount@0"] == 8
    assert result.reasons["RendererWorkerCount@0"].key == "optimizer.reason_pcores"
    many = HardwareInfo(physical_cores=32)
    assert recommend(kb, cod25_doc, many, Goal.BALANCED).values["RendererWorkerCount@0"] == 16


def test_recommend_refresh_cap_limits(cod25_doc, kb) -> None:
    fast = HardwareInfo(refresh_hz=480, max_refresh_hz=480)
    assert recommend(kb, cod25_doc, fast, Goal.COMPETITIVE).values["MaxFpsInGame@0"] == 300
    low_end = recommend(kb, cod25_doc, DESKTOP, Goal.LOW_END)
    assert low_end.values["MaxFpsInGame@0"] == 60  # preset value, refresh rule not used
    unknown = recommend(kb, cod25_doc, HardwareInfo(), Goal.COMPETITIVE)
    assert "MaxFpsInGame@0" not in unknown.values
    assert "RendererWorkerCount@0" not in unknown.values


@pytest.mark.parametrize(
    ("bottleneck", "reflex", "heaps"),
    [
        (Bottleneck.CPU, "Enabled + boost", False),
        (Bottleneck.GPU, "Enabled", True),
    ],
)
def test_recommend_bottleneck(cod25_doc, kb, bottleneck, reflex, heaps) -> None:
    result = recommend(kb, cod25_doc, DESKTOP, Goal.BALANCED, bottleneck)
    assert result.values["NvidiaReflex@0"] == reflex
    assert result.values["GPUUploadHeaps@0"] is heaps


def test_recommend_amd_card(cod25_doc, kb) -> None:
    amd = HardwareInfo(gpu_vendor="amd", vram_mb=16384)
    result = recommend(kb, cod25_doc, amd, Goal.COMPETITIVE, Bottleneck.CPU)
    assert result.values["AATechniquePreferredMP@0"] == "FSR AA"
    assert result.reasons["NvidiaReflex@0"].key == "optimizer.reason_preset"  # not overridden
    plan = plan_template(cod25_doc, kb, result.values, gpu_vendor="amd")
    assert plan.skipped["NvidiaReflex@0"] is SkipReason.VENDOR


@pytest.mark.parametrize("goal", list(Goal))
def test_every_goal_plans_cleanly(cod25_doc, kb, goal) -> None:
    result = recommend(kb, cod25_doc, DESKTOP, goal, Bottleneck.GPU)
    plan = plan_template(cod25_doc, kb, result.values, gpu_vendor="nvidia")
    invalid = {sid for sid, reason in plan.skipped.items() if reason is SkipReason.INVALID}
    assert invalid == set(), plan.errors
