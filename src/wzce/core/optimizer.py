"""Optimizer: turn (goal, bottleneck, detected hardware) into recommended values.

Layers, later ones override earlier ones:

1. the static preset for the goal (knowledge base ``recommend``)
2. hardware rules (knowledge base ``rule`` field):
   * ``physical_cores``   -> RendererWorkerCount = P-cores (hybrid) or physical cores
   * ``vram_fraction``    -> VideoMemoryScaleMP from the VRAM size and goal
   * ``refresh_rate_cap`` -> MaxFpsInGame = refresh - 3 (stays inside VRR range)
3. GPU vendor: anti-aliasing / upscaler that fits the card
4. bottleneck answer (CPU- vs GPU-bound, read from in-game telemetry):
   Reflex boost and GPU Upload Heaps, per the community rule of thumb

Each value carries a ``Reason`` (i18n key + parameters) that the wizard shows
next to the change, so the user sees *why* it is recommended. The result is a
plain ``{id: value}`` dict meant for ``templates.plan_template`` - which still
validates every value against the file and drops hardware/managed settings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from .document import ConfigDocument
from .hardware import HardwareInfo
from .knowledge import KnowledgeBase


class Goal(StrEnum):
    """Same ids as the knowledge-base presets."""

    COMPETITIVE = "competitive"
    BALANCED = "balanced"
    QUALITY = "quality"
    LOW_END = "low_end"


class Bottleneck(StrEnum):
    UNKNOWN = "unknown"
    CPU = "cpu"
    GPU = "gpu"


# (max VRAM in MB, fraction) - first row whose limit is >= the card's VRAM wins.
# Guides: 60-80 %, lower on 8 GB cards; too high competes with Windows/Discord/browser.
VRAM_TABLE: tuple[tuple[int, float], ...] = (
    (4_500, 0.55),
    (6_500, 0.60),
    (8_500, 0.65),
    (12_500, 0.70),
    (16_500, 0.75),
    (10**9, 0.80),
)
VRAM_GOAL_DELTA = {Goal.QUALITY: 0.05, Goal.LOW_END: -0.05}
FPS_CAP_MARGIN = 3  # below refresh rate, keeps G-Sync/FreeSync engaged
FPS_CAP_LIMITS = (30, 300)  # range of MaxFpsInGame in the game file

VENDOR_AA = {"nvidia": "DLSS", "amd": "FSR AA", "intel": "XeSS"}


@dataclass(frozen=True, slots=True)
class Reason:
    key: str  # i18n key, e.g. "optimizer.reason_cores"
    params: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class OptimizerResult:
    values: dict[str, object] = field(default_factory=dict)
    reasons: dict[str, Reason] = field(default_factory=dict)

    def set(self, setting_id: str, value: object, reason: Reason) -> None:
        self.values[setting_id] = value
        self.reasons[setting_id] = reason


def vram_fraction(vram_mb: int, goal: Goal) -> float:
    base = next(fraction for limit, fraction in VRAM_TABLE if vram_mb <= limit)
    return round(min(0.9, max(0.5, base + VRAM_GOAL_DELTA.get(goal, 0.0))), 2)


def recommend(
    knowledge: KnowledgeBase,
    document: ConfigDocument,
    hardware: HardwareInfo,
    goal: Goal,
    bottleneck: Bottleneck = Bottleneck.UNKNOWN,
) -> OptimizerResult:
    result = OptimizerResult()
    preset_reason = Reason("optimizer.reason_preset", {"preset": goal.value})

    # 1. static preset values
    for setting_id, value in knowledge.preset_values(goal.value).items():
        result.set(setting_id, value, preset_reason)

    # 2. hardware rules
    for setting_id, entry in knowledge.entries.items():
        if entry.rule is None or setting_id not in document:
            continue
        setting = document.get(setting_id)
        constraint = setting.constraint
        if entry.rule == "physical_cores" and hardware.worker_cores:
            cores = hardware.worker_cores
            if constraint is not None and constraint.max_value is not None:
                cores = min(cores, int(constraint.max_value))
            key = "optimizer.reason_pcores" if hardware.is_hybrid else "optimizer.reason_cores"
            result.set(setting_id, cores, Reason(key, {"cores": hardware.worker_cores}))
        elif entry.rule == "vram_fraction" and hardware.vram_mb:
            fraction = vram_fraction(hardware.vram_mb, goal)
            gb = round(hardware.vram_mb / 1024)
            result.set(setting_id, fraction, Reason("optimizer.reason_vram", {"gb": gb}))
        elif entry.rule == "refresh_rate_cap" and hardware.best_refresh_hz and goal != Goal.LOW_END:
            low, high = FPS_CAP_LIMITS
            cap = max(low, min(high, hardware.best_refresh_hz - FPS_CAP_MARGIN))
            result.set(
                setting_id,
                cap,
                Reason("optimizer.reason_refresh", {"hz": hardware.best_refresh_hz}),
            )

    # 3. anti-aliasing / upscaler matching the GPU vendor
    vendor = hardware.gpu_vendor
    if vendor in VENDOR_AA and "AATechniquePreferredMP@0" in document:
        result.set(
            "AATechniquePreferredMP@0",
            VENDOR_AA[vendor],
            Reason("optimizer.reason_vendor_aa", {"vendor": vendor.upper()}),
        )

    # 4. bottleneck: Reflex boost + GPU Upload Heaps (JordanTBH rule of thumb)
    if bottleneck is Bottleneck.CPU:
        reason = Reason("optimizer.reason_cpu_bound")
        if vendor in (None, "nvidia"):
            result.set("NvidiaReflex@0", "Enabled + boost", reason)
        result.set("GPUUploadHeaps@0", False, reason)
    elif bottleneck is Bottleneck.GPU:
        reason = Reason("optimizer.reason_gpu_bound")
        if vendor in (None, "nvidia"):
            result.set("NvidiaReflex@0", "Enabled", reason)
        result.set("GPUUploadHeaps@0", True, reason)

    return result
