"""Hardware facts used for filtering and (later, stage 6) recommendations.

For now only the GPU vendor, which the game itself records in the settings file
(``GPUName@0`` / ``LastUsedGPU@0``) - no extra system queries needed.
"""

from __future__ import annotations

from .document import ConfigDocument

# Checked in order; the first vendor whose keyword appears in the name wins.
_VENDOR_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("nvidia", ("nvidia", "geforce", "rtx", "gtx", "quadro")),
    ("amd", ("amd", "radeon")),
    ("intel", ("intel", " arc", "iris", "uhd graphics")),
)
_GPU_NAME_IDS = ("GPUName@0", "LastUsedGPU@0")


def gpu_vendor_from_name(name: str) -> str | None:
    """``"NVIDIA GeForce RTX 5090"`` -> ``"nvidia"``; ``None`` when unrecognized."""
    lowered = f" {name.lower()}"
    for vendor, keywords in _VENDOR_KEYWORDS:
        if any(k in lowered for k in keywords):
            return vendor
    return None


def detect_gpu_vendor(document: ConfigDocument) -> str | None:
    """GPU vendor recorded by the game in the settings file, if any."""
    for setting_id in _GPU_NAME_IDS:
        if setting_id in document:
            vendor = gpu_vendor_from_name(document.get(setting_id).raw_value)
            if vendor:
                return vendor
    return None
