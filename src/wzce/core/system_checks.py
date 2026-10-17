"""System checks: turn ``SystemInfo`` (+ the game's settings file) into advice.

This module holds the hardware checks (RAM, drives, GPU, monitor); the checks of
Windows settings live in ``core/windows_checks.py`` and are merged in here.

Each check returns a ``CheckResult`` with a status (ok / warn / info / unknown),
a severity for warnings, parameters for the translated texts and an optional
action (a Windows settings URI, a web page, or a setting in the editor).

Texts live in the i18n catalogs under ``checks.<id>.title`` / ``.problem`` /
``.fix`` / ``.ok`` (``.problem_<variant>`` / ``.ok_<variant>`` when a check has
variants). Checks never change anything - they only report.
"""

from __future__ import annotations

from .check_types import CheckResult, Severity, Status
from .document import ConfigDocument
from .hardware import HardwareInfo
from .system_info import SystemInfo
from .windows_checks import evaluate_windows_checks

__all__ = ["CheckResult", "Severity", "Status", "evaluate_checks", "warnings"]

LOW_RAM_GB = 16
LOW_DISK_GB = 50


def _raw(document: ConfigDocument | None, setting_id: str) -> str | None:
    if document is None or setting_id not in document:
        return None
    return document.get(setting_id).raw_value


def _version_tuple(text: str) -> tuple[int, ...] | None:
    try:
        return tuple(int(part) for part in text.strip().split("."))
    except ValueError:
        return None


def evaluate_checks(
    info: SystemInfo,
    hardware: HardwareInfo | None = None,
    document: ConfigDocument | None = None,
) -> list[CheckResult]:
    """All checks, most important first. ``document`` = the game's machine settings file."""
    results = [
        _check_expo(info),
        _check_channels(info),
        _check_ram_size(info),
        _check_game_drive(info),
        _check_disk_space(info),
        _check_refresh(hardware),
        _check_driver(info, document),
        _check_pcie(info),
        _check_rebar(info, document),
        _check_igpu(info, document),
        *evaluate_windows_checks(info),
    ]
    return sorted(results, key=lambda r: r.sort_key)


def warnings(results: list[CheckResult]) -> list[CheckResult]:
    return [r for r in results if r.status is Status.WARN]


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def _check_expo(info: SystemInfo) -> CheckResult:
    state = info.expo_xmp
    profile = "XMP" if (info.cpu_name or "").lower().startswith("intel") else "EXPO"
    rated = max((m.rated_speed_mts or 0 for m in info.memory), default=0) or None
    params = {"profile": profile, "speed": info.memory_speed_mts, "rated": rated}
    if state == "off":
        return CheckResult("expo", Status.WARN, Severity.HIGH, params)
    if state == "on":
        return CheckResult("expo", Status.OK, params=params)
    return CheckResult("expo", Status.UNKNOWN, params=params)


def _check_channels(info: SystemInfo) -> CheckResult:
    channels = info.memory_channels
    params = {"modules": len(info.memory), "channels": channels}
    if channels is None:
        return CheckResult("channels", Status.UNKNOWN, params=params)
    if channels == 1:
        return CheckResult("channels", Status.WARN, Severity.HIGH, params)
    return CheckResult("channels", Status.OK, params=params)


def _check_ram_size(info: SystemInfo) -> CheckResult:
    total = info.memory_total_gb
    if total is None:
        return CheckResult("ram_size", Status.UNKNOWN)
    params = {"gb": round(total), "min": LOW_RAM_GB}
    if total < LOW_RAM_GB - 0.5:
        return CheckResult("ram_size", Status.WARN, Severity.MEDIUM, params)
    return CheckResult("ram_size", Status.OK, params=params)


def _check_game_drive(info: SystemInfo) -> CheckResult:
    install = info.game_install
    if install is None or install.drive is None:
        return CheckResult("game_drive", Status.UNKNOWN)
    drive = install.drive
    params = {"letter": drive.letter, "disk": drive.disk}
    kind = drive.kind
    if kind == "hdd":
        return CheckResult("game_drive", Status.WARN, Severity.HIGH, params, variant="hdd")
    if kind == "ssd" and any(d.kind == "nvme" for d in info.drives):
        return CheckResult("game_drive", Status.WARN, Severity.LOW, params, variant="sata")
    if kind == "unknown":
        return CheckResult("game_drive", Status.UNKNOWN, params=params)
    return CheckResult("game_drive", Status.OK, params=params)


def _check_disk_space(info: SystemInfo) -> CheckResult:
    install = info.game_install
    if install is None or install.free_gb is None:
        return CheckResult("disk_space", Status.UNKNOWN)
    params = {"gb": round(install.free_gb), "min": LOW_DISK_GB}
    if install.free_gb < LOW_DISK_GB:
        return CheckResult("disk_space", Status.WARN, Severity.MEDIUM, params)
    return CheckResult("disk_space", Status.OK, params=params)


def _check_refresh(hardware: HardwareInfo | None) -> CheckResult:
    if hardware is None or not hardware.refresh_hz or not hardware.max_refresh_hz:
        return CheckResult("refresh", Status.UNKNOWN)
    params = {"hz": hardware.refresh_hz, "max": hardware.max_refresh_hz}
    if hardware.refresh_hz < hardware.max_refresh_hz - 1:  # 143.9 vs 144 rounding
        return CheckResult(
            "refresh", Status.WARN, Severity.HIGH, params, action="ms-settings:display-advanced"
        )
    return CheckResult("refresh", Status.OK, params=params)


def _check_driver(info: SystemInfo, document: ConfigDocument | None) -> CheckResult:
    recommended = _raw(document, "DisplayDriverVersionRecommended@0")
    if info.nvidia is None or not recommended:
        return CheckResult("driver", Status.UNKNOWN)
    installed_v = _version_tuple(info.nvidia.driver_version)
    recommended_v = _version_tuple(recommended)
    params = {"installed": info.nvidia.driver_version, "recommended": recommended}
    if installed_v is None or recommended_v is None:
        return CheckResult("driver", Status.UNKNOWN, params=params)
    if installed_v < recommended_v:
        return CheckResult(
            "driver",
            Status.WARN,
            Severity.MEDIUM,
            params,
            action="https://www.nvidia.com/Download/index.aspx",
        )
    return CheckResult("driver", Status.OK, params=params)


def _check_pcie(info: SystemInfo) -> CheckResult:
    nv = info.nvidia
    if nv is None or not nv.pcie_width or not nv.pcie_width_max:
        return CheckResult("pcie", Status.UNKNOWN)
    params = {
        "gen": nv.pcie_gen,
        "gen_max": nv.pcie_gen_max,
        "width": nv.pcie_width,
        "width_max": nv.pcie_width_max,
    }
    # Only the lane count: the PCIe generation drops at idle to save power.
    if nv.pcie_width < nv.pcie_width_max:
        return CheckResult("pcie", Status.WARN, Severity.MEDIUM, params)
    return CheckResult("pcie", Status.OK, params=params)


def _check_rebar(info: SystemInfo, document: ConfigDocument | None) -> CheckResult:
    rebar = info.nvidia.rebar_enabled if info.nvidia else None
    if rebar is None:
        return CheckResult("rebar", Status.UNKNOWN)
    if rebar:
        return CheckResult("rebar", Status.OK)
    if _raw(document, "GPUUploadHeaps@0") == "true":
        return CheckResult(
            "rebar",
            Status.WARN,
            Severity.MEDIUM,
            variant="heaps",
            action="setting:GPUUploadHeaps@0",
        )
    return CheckResult("rebar", Status.WARN, Severity.LOW)


def _check_igpu(info: SystemInfo, document: ConfigDocument | None) -> CheckResult:
    dedicated = info.dedicated_gpu
    if not info.has_integrated_gpu or dedicated is None:
        return CheckResult("igpu", Status.OK if info.gpus else Status.UNKNOWN)
    game_gpu = _raw(document, "GPUName@0")
    params = {"dedicated": dedicated.name, "game_gpu": game_gpu or "?"}
    if game_gpu and game_gpu.strip().lower() != dedicated.name.lower():
        return CheckResult("igpu", Status.WARN, Severity.MEDIUM, params, variant="wrong")
    return CheckResult("igpu", Status.INFO, params=params)
