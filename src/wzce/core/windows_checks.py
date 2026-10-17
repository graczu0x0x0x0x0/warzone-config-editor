"""Windows-settings checks (stage 10b): turn ``SystemInfo.windows`` into advice.

The rules follow ``docs/RAPORT_WINDOWS.md``: the game's anti-cheat requirements
first, then only settings with a measured or documented effect. Several rules
depend on the processor - a dual-CCD Ryzen X3D wants the Balanced plan and core
parking (the AMD driver parks the CCD without V-Cache), Intel 13th/14th gen needs
microcode 0x12B, Zen 3-5 and Arrow Lake need specific Windows builds.

Rules for niche problems return ``None`` when they do not apply or everything is
fine, so the list stays short; the core rows always report a status. Each check id
belongs to a ``Section`` and has an ``Impact`` (how strong the evidence is) for the
UI. Popular tweaks that do nothing or harm are listed in ``MYTHS`` (texts only).

Texts: ``checks.<id>.*`` like the hardware checks, myths: ``myths.<id>.title/why``.
Checks never change anything - they only report.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from enum import StrEnum

from .check_types import CheckResult, Severity, Status
from .system_info import SystemInfo

# URLs and settings pages used as check actions.
ACTIVISION_TPM_URL = (
    "https://support.activision.com/articles/trusted-platform-module-and-secure-boot"
)
AMD_DRIVERS_URL = "https://www.amd.com/en/support/download/drivers.html"
NVIDIA_MPO_URL = "https://nvidia.custhelp.com/app/answers/detail/a_id/5157"
NVIDIA_DRIVERS_URL = "https://www.nvidia.com/Download/index.aspx"
GAME_BAR_STORE_URL = "https://apps.microsoft.com/detail/9nzkpstsnw4p"

# Intel's final Vmin-shift fix for 13th/14th gen desktop CPUs (Sept 2024).
INTEL_MIN_MICROCODE = 0x12B
# Builds (KB) with the AMD Zen 3-5 branch-prediction fix and the Arrow Lake PPM fix.
AMD_FIX_23H2_UBR = 4112  # 22631.4112 = KB5041587
ARROW_LAKE_MIN_UBR = 2161  # 26100.2161 = KB5044384
# KB5066835 (Oct 2025) slowed some games on NVIDIA; fixed by driver 581.94.
NVIDIA_REGRESSION_UBR = 6899
NVIDIA_HOTFIX_DRIVER = (581, 94)
MIN_PAGEFILE_MB = 8192
LOW_SYSTEM_DRIVE_GB = 20


class Section(StrEnum):
    REQUIREMENTS = "requirements"  # the game's anti-cheat (Ricochet)
    SECURITY = "security"
    GRAPHICS = "graphics"
    GAMING = "gaming"  # Game Mode, Xbox Game Bar
    POWER = "power"
    UPDATES = "updates"
    STORAGE = "storage"
    BACKGROUND = "background"
    DEVICES = "devices"  # mouse, network


class Impact(StrEnum):
    REQUIRED = "required"  # the game refuses (some) modes without it
    PROVEN = "proven"  # measured in benchmarks / documented by the vendor
    SITUATIONAL = "situational"  # depends on the PC or the evidence is thin
    NONE = "none"  # no effect on CoD (worth knowing, not worth chasing)


# id -> (section, impact); the order is the display order inside a section.
CHECKS: dict[str, tuple[Section, Impact]] = {
    "secure_boot": (Section.REQUIREMENTS, Impact.REQUIRED),
    "boot_mode": (Section.REQUIREMENTS, Impact.REQUIRED),
    "tpm": (Section.REQUIREMENTS, Impact.REQUIRED),
    "uac": (Section.REQUIREMENTS, Impact.REQUIRED),
    "secure_boot_certs": (Section.REQUIREMENTS, Impact.SITUATIONAL),
    "input_remap": (Section.REQUIREMENTS, Impact.REQUIRED),
    "hvci": (Section.SECURITY, Impact.PROVEN),
    "virtualization": (Section.SECURITY, Impact.SITUATIONAL),
    "antivirus": (Section.SECURITY, Impact.SITUATIONAL),
    "driver_blocklist": (Section.SECURITY, Impact.SITUATIONAL),
    "winring0": (Section.SECURITY, Impact.SITUATIONAL),
    "hags": (Section.GRAPHICS, Impact.SITUATIONAL),
    "gpu_preference": (Section.GRAPHICS, Impact.PROVEN),
    "auto_hdr": (Section.GRAPHICS, Impact.NONE),
    "mpo": (Section.GRAPHICS, Impact.SITUATIONAL),
    "fso": (Section.GRAPHICS, Impact.NONE),
    "game_mode": (Section.GAMING, Impact.SITUATIONAL),
    "recording": (Section.GAMING, Impact.PROVEN),
    "game_bar": (Section.GAMING, Impact.SITUATIONAL),
    "power_plan": (Section.POWER, Impact.SITUATIONAL),
    "processor_state": (Section.POWER, Impact.SITUATIONAL),
    "x3d_driver": (Section.POWER, Impact.PROVEN),
    "core_parking": (Section.POWER, Impact.PROVEN),
    "intel_microcode": (Section.POWER, Impact.PROVEN),
    "windows_version": (Section.UPDATES, Impact.PROVEN),
    "nvidia_hotfix": (Section.UPDATES, Impact.PROVEN),
    "reboot_pending": (Section.UPDATES, Impact.SITUATIONAL),
    "pagefile": (Section.STORAGE, Impact.PROVEN),
    "system_drive_space": (Section.STORAGE, Impact.SITUATIONAL),
    "trim": (Section.STORAGE, Impact.SITUATIONAL),
    "overlays": (Section.BACKGROUND, Impact.SITUATIONAL),
    "mouse_acceleration": (Section.DEVICES, Impact.NONE),
    "network": (Section.DEVICES, Impact.PROVEN),
}

# Popular tweaks that are placebo on Windows 11 or harmful (texts: myths.<id>.*).
MYTHS: tuple[str, ...] = (
    "hpet",
    "timer_resolution",
    "nagle",
    "core_parking",
    "ultimate_plan",
    "services",
    "pagefile_off",
    "usb_suspend",
    "nvme_driver",
    "debloat",
    "security_off",
)

# Display names of background apps (brand names, the same in every language).
APP_NAMES = {
    "discord": "Discord",
    "steam": "Steam",
    "nvidia_overlay": "NVIDIA App",
    "rtss": "RivaTuner (RTSS)",
    "overwolf": "Overwolf",
    "medal": "Medal",
    "obs": "OBS Studio",
    "afterburner": "MSI Afterburner",
    "hwinfo": "HWiNFO",
    "logitech_ghub": "Logitech G HUB",
    "corsair_icue": "Corsair iCUE",
    "asus_armoury_crate": "Armoury Crate",
    "razer_synapse": "Razer Synapse",
    "steelseries_gg": "SteelSeries GG",
    "signalrgb": "SignalRGB",
    "openrgb": "OpenRGB",
    "wallpaper_engine": "Wallpaper Engine",
    "process_lasso": "Process Lasso",
    "rewasd": "reWASD",
    "cronus_zen": "Cronus Zen (Zen Studio)",
}

# Product names of the optional features that start the hypervisor.
VM_FEATURE_NAMES = {
    "VirtualMachinePlatform": "Virtual Machine Platform",
    "Microsoft-Windows-Subsystem-Linux": "WSL",
    "Microsoft-Hyper-V-All": "Hyper-V",
    "HypervisorPlatform": "Windows Hypervisor Platform",
    "Containers-DisposableClientVM": "Windows Sandbox",
}

TPM_NAMES = {"AMD": "AMD fTPM", "INTC": "Intel PTT", "MSFT": "Microsoft Pluton"}

# Firmware TPM versions that fail the game's attestation (Activision support page).
_BAD_TPM_FIRMWARE = {
    "AMD": re.compile(r"^3\.\d+\.0\.\d+$"),  # 3.92.0.5 fails, 3.92.5.5 passes
    "INTC": re.compile(r"^30[23]\.12\."),
}
_RAPTOR_LAKE = re.compile(r"\bi[579]-1[34]\d{3}", re.IGNORECASE)
_ARROW_LAKE = re.compile(r"\bUltra [579] 2\d{2}(?:K|KF|F|T)?\b", re.IGNORECASE)
_RYZEN_ZEN3_PLUS = re.compile(r"\bRyzen [3579] (?:PRO )?[5789]\d{3}", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Processor classification
# ---------------------------------------------------------------------------


def dual_ccd_x3d(info: SystemInfo) -> bool:
    """7900X3D / 7950X3D / 9900X3D / 9950X3D: only one of the two CCDs has V-Cache."""
    return info.x3d_cache and (info.cpu_cores or 0) > 8


def raptor_lake(info: SystemInfo) -> bool:
    return bool(info.cpu_name and _RAPTOR_LAKE.search(info.cpu_name))


def arrow_lake(info: SystemInfo) -> bool:
    return bool(info.cpu_name and _ARROW_LAKE.search(info.cpu_name))


def ryzen_zen3_plus(info: SystemInfo) -> bool:
    return bool(info.cpu_name and _RYZEN_ZEN3_PLUS.search(info.cpu_name))


def _version(text: str | None) -> tuple[int, ...] | None:
    try:
        return tuple(int(part) for part in (text or "").strip().split("."))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def evaluate_windows_checks(info: SystemInfo) -> list[CheckResult]:
    """Windows checks in ``CHECKS`` order; rules that do not apply are left out."""
    rules: list[Callable[[SystemInfo], CheckResult | None]] = [
        _check_secure_boot,
        _check_boot_mode,
        _check_tpm,
        _check_uac,
        _check_secure_boot_certs,
        _check_input_remap,
        _check_hvci,
        _check_virtualization,
        _check_antivirus,
        _check_driver_blocklist,
        _check_winring0,
        _check_hags,
        _check_gpu_preference,
        _check_auto_hdr,
        _check_mpo,
        _check_fso,
        _check_game_mode,
        _check_recording,
        _check_game_bar,
        _check_power_plan,
        _check_processor_state,
        _check_x3d_driver,
        _check_core_parking,
        _check_intel_microcode,
        _check_windows_version,
        _check_nvidia_hotfix,
        _check_reboot_pending,
        _check_pagefile,
        _check_system_drive_space,
        _check_trim,
        _check_overlays,
        _check_mouse_acceleration,
        _check_network,
    ]
    return [result for rule in rules if (result := rule(info)) is not None]


def is_windows_check(check_id: str) -> bool:
    return check_id in CHECKS


# ---------------------------------------------------------------------------
# Game requirements (Ricochet: UEFI + GPT + Secure Boot + TPM 2.0)
# ---------------------------------------------------------------------------


def _check_secure_boot(info: SystemInfo) -> CheckResult:
    on = info.windows.secure_boot
    if on is None:
        return CheckResult("secure_boot", Status.UNKNOWN)
    if not on:
        return CheckResult("secure_boot", Status.WARN, Severity.HIGH, action=ACTIVISION_TPM_URL)
    return CheckResult("secure_boot", Status.OK)


def _check_boot_mode(info: SystemInfo) -> CheckResult:
    win = info.windows
    if win.firmware_uefi is False:
        return CheckResult("boot_mode", Status.WARN, Severity.HIGH, variant="legacy")
    if win.system_disk_gpt is False:
        return CheckResult(
            "boot_mode", Status.WARN, Severity.HIGH, variant="mbr", action=ACTIVISION_TPM_URL
        )
    if win.firmware_uefi and win.system_disk_gpt:
        return CheckResult("boot_mode", Status.OK)
    return CheckResult("boot_mode", Status.UNKNOWN)


def tpm_firmware_bad(manufacturer: str | None, firmware: str | None) -> bool:
    pattern = _BAD_TPM_FIRMWARE.get(manufacturer or "")
    return bool(pattern and firmware and pattern.search(firmware))


def _check_tpm(info: SystemInfo) -> CheckResult:
    win = info.windows
    device = TPM_NAMES.get(win.tpm_manufacturer or "", win.tpm_manufacturer or "TPM")
    params = {"device": device, "firmware": win.tpm_firmware or "?", "version": win.tpm_version}
    if win.tpm_version is None:
        return CheckResult("tpm", Status.UNKNOWN, params=params)
    if win.tpm_version == "":
        return CheckResult("tpm", Status.WARN, Severity.HIGH, params, variant="missing")
    if win.tpm_version != "2.0":
        return CheckResult("tpm", Status.WARN, Severity.HIGH, params, variant="old")
    if tpm_firmware_bad(win.tpm_manufacturer, win.tpm_firmware):
        return CheckResult(
            "tpm", Status.WARN, Severity.HIGH, params, variant="firmware", action=ACTIVISION_TPM_URL
        )
    return CheckResult("tpm", Status.OK, params=params)


def _check_uac(info: SystemInfo) -> CheckResult:
    never = info.windows.uac_never_notify
    if never is None:
        return CheckResult("uac", Status.UNKNOWN)
    if never:
        return CheckResult("uac", Status.WARN, Severity.MEDIUM)
    return CheckResult("uac", Status.OK)


def _check_secure_boot_certs(info: SystemInfo) -> CheckResult | None:
    win = info.windows
    if not win.secure_boot:
        return None  # nothing to update while Secure Boot is off
    if win.secure_boot_ca2023 == "Updated":
        return CheckResult("secure_boot_certs", Status.OK)
    params = {"status": win.secure_boot_ca2023 or "-"}
    return CheckResult(
        "secure_boot_certs", Status.WARN, Severity.LOW, params, action="ms-settings:windowsupdate"
    )


def _check_input_remap(info: SystemInfo) -> CheckResult | None:
    apps = [a for a in info.windows.background_apps if a.category == "input_remap"]
    if not apps:
        return None
    names = ", ".join(APP_NAMES.get(a.id, a.id) for a in apps)
    return CheckResult("input_remap", Status.WARN, Severity.HIGH, {"apps": names})


# ---------------------------------------------------------------------------
# Virtualization and security
# ---------------------------------------------------------------------------


def _check_hvci(info: SystemInfo) -> CheckResult:
    if info.hvci_running is None:
        return CheckResult("hvci", Status.UNKNOWN)
    if info.hvci_running:
        # A security trade-off, so information rather than a warning.
        return CheckResult("hvci", Status.INFO, action="windowsdefender://coreisolation")
    return CheckResult("hvci", Status.OK)


def _check_virtualization(info: SystemInfo) -> CheckResult:
    win = info.windows
    features = ", ".join(VM_FEATURE_NAMES.get(f, f) for f in win.enabled_vm_features)
    params = {"features": features}
    if win.hypervisor_present is None:
        return CheckResult("virtualization", Status.UNKNOWN, params=params)
    if win.svm_disabled_in_firmware and features:
        # Installed but unable to start: no cost now, but WSL2 / Docker are broken.
        return CheckResult(
            "virtualization", Status.INFO, params=params, variant="no_svm",
            action="ms-settings:optionalfeatures",
        )  # fmt: skip
    if win.hypervisor_present and features:
        return CheckResult(
            "virtualization", Status.INFO, params=params, variant="features",
            action="ms-settings:optionalfeatures",
        )  # fmt: skip
    if win.hypervisor_present:
        return CheckResult("virtualization", Status.OK, params=params, variant="vbs")
    return CheckResult("virtualization", Status.OK, params=params)


def _check_antivirus(info: SystemInfo) -> CheckResult:
    win = info.windows
    active = [av for av in win.antivirus if av.enabled]
    if not win.antivirus and win.defender_realtime is None:
        return CheckResult("antivirus", Status.UNKNOWN)
    params = {"names": ", ".join(av.name for av in active)}
    if not active and not win.defender_realtime:
        return CheckResult(
            "antivirus", Status.WARN, Severity.HIGH, params, variant="none",
            action="windowsdefender://threat",
        )  # fmt: skip
    if any(not av.up_to_date for av in active):
        return CheckResult("antivirus", Status.WARN, Severity.LOW, params, variant="outdated")
    if any(av in win.third_party_antivirus for av in active):
        return CheckResult("antivirus", Status.OK, params=params, variant="third_party")
    return CheckResult("antivirus", Status.OK, params=params)


def _check_driver_blocklist(info: SystemInfo) -> CheckResult | None:
    if info.windows.driver_blocklist is not False:
        return None
    return CheckResult(
        "driver_blocklist", Status.WARN, Severity.LOW, action="windowsdefender://coreisolation"
    )


def _check_winring0(info: SystemInfo) -> CheckResult | None:
    drivers = info.windows.winring0_drivers
    if not drivers:
        return None
    return CheckResult("winring0", Status.WARN, Severity.MEDIUM, {"drivers": ", ".join(drivers)})


# ---------------------------------------------------------------------------
# Graphics
# ---------------------------------------------------------------------------


def _check_hags(info: SystemInfo) -> CheckResult:
    if info.hags is None:
        return CheckResult("hags", Status.UNKNOWN)
    if not info.hags:
        return CheckResult(
            "hags", Status.WARN, Severity.LOW, action="ms-settings:display-advancedgraphics"
        )
    return CheckResult("hags", Status.OK)


def _check_gpu_preference(info: SystemInfo) -> CheckResult | None:
    if not info.has_integrated_gpu:
        return None  # one GPU: nothing to choose
    preference = info.windows.game_gpu_preference
    action = "ms-settings:display-advancedgraphics"
    if preference is None:
        return CheckResult("gpu_preference", Status.UNKNOWN)
    if preference == 1:
        return CheckResult(
            "gpu_preference", Status.WARN, Severity.HIGH, variant="power_saving", action=action
        )
    if preference == 0:
        return CheckResult("gpu_preference", Status.INFO, action=action)
    return CheckResult("gpu_preference", Status.OK)


def _check_auto_hdr(info: SystemInfo) -> CheckResult:
    on = info.windows.auto_hdr
    if on is None:
        return CheckResult("auto_hdr", Status.UNKNOWN)
    if on:
        return CheckResult("auto_hdr", Status.INFO, action="ms-settings:display-hdr")
    return CheckResult("auto_hdr", Status.OK)


def _check_mpo(info: SystemInfo) -> CheckResult | None:
    if not info.windows.mpo_disabled:
        return None
    return CheckResult("mpo", Status.INFO, action=NVIDIA_MPO_URL)


def _check_fso(info: SystemInfo) -> CheckResult | None:
    if not info.windows.game_fso_disabled:
        return None
    return CheckResult("fso", Status.INFO)


# ---------------------------------------------------------------------------
# Game Mode, Xbox Game Bar
# ---------------------------------------------------------------------------


def _flag_check(check_id: str, value: bool | None, want: bool, action: str) -> CheckResult:
    if value is None:
        return CheckResult(check_id, Status.UNKNOWN)
    if value != want:
        return CheckResult(check_id, Status.WARN, Severity.LOW, action=action)
    return CheckResult(check_id, Status.OK)


def _check_game_mode(info: SystemInfo) -> CheckResult:
    return _flag_check("game_mode", info.game_mode, True, "ms-settings:gaming-gamemode")


def _check_recording(info: SystemInfo) -> CheckResult:
    return _flag_check("recording", info.background_recording, False, "ms-settings:gaming-gamedvr")


def _check_game_bar(info: SystemInfo) -> CheckResult:
    installed = info.windows.game_bar_installed
    if installed is None:
        return CheckResult("game_bar", Status.UNKNOWN)
    if not installed:
        # Dual-CCD X3D: the AMD driver relies on Game Bar to recognise the game.
        x3d = dual_ccd_x3d(info)
        return CheckResult(
            "game_bar", Status.WARN, Severity.HIGH if x3d else Severity.LOW,
            variant="x3d" if x3d else None, action=GAME_BAR_STORE_URL,
        )  # fmt: skip
    return CheckResult("game_bar", Status.OK)


# ---------------------------------------------------------------------------
# Power and processor
# ---------------------------------------------------------------------------


def _check_power_plan(info: SystemInfo) -> CheckResult:
    plan = info.power_plan
    action = "ms-settings:powersleep"
    if plan is None:
        return CheckResult("power_plan", Status.UNKNOWN)
    params = {"plan": plan}
    if dual_ccd_x3d(info):
        # AMD's V-Cache optimizer needs Balanced; High/Ultimate keep the wrong CCD awake.
        if plan == "balanced":
            return CheckResult("power_plan", Status.OK, params=params, variant="x3d")
        return CheckResult(
            "power_plan", Status.WARN, Severity.MEDIUM, params, variant="x3d", action=action
        )
    if plan == "power_saver":
        return CheckResult("power_plan", Status.WARN, Severity.LOW, params, action=action)
    if plan == "balanced":
        if info.windows.power_overlay == "best_performance":
            return CheckResult("power_plan", Status.OK, params=params, variant="mode")
        return CheckResult(
            "power_plan", Status.WARN, Severity.LOW, params, variant="mode", action=action
        )
    return CheckResult("power_plan", Status.OK, params=params)


def _check_processor_state(info: SystemInfo) -> CheckResult | None:
    win = info.windows
    params = {"min": win.processor_min_percent, "max": win.processor_max_percent}
    if win.processor_max_percent is not None and win.processor_max_percent < 100:
        return CheckResult("processor_state", Status.WARN, Severity.MEDIUM, params, variant="max")
    # High performance ships with 100 %; a lower value means someone edited the plan.
    performance_plan = info.power_plan in ("high_performance", "ultimate")
    lowered = win.processor_min_percent is not None and win.processor_min_percent < 100
    if performance_plan and lowered:
        return CheckResult("processor_state", Status.INFO, params=params, variant="min")
    return None


def _check_x3d_driver(info: SystemInfo) -> CheckResult | None:
    if not dual_ccd_x3d(info):
        return None
    service = info.windows.amd_vcache_service
    if service is None:
        return CheckResult(
            "x3d_driver", Status.WARN, Severity.HIGH, variant="missing", action=AMD_DRIVERS_URL
        )
    if service != "running":
        return CheckResult(
            "x3d_driver", Status.WARN, Severity.MEDIUM, variant="stopped", action=AMD_DRIVERS_URL
        )
    return CheckResult("x3d_driver", Status.OK)


def _check_core_parking(info: SystemInfo) -> CheckResult | None:
    if not dual_ccd_x3d(info) or info.windows.core_parking_min_cores != 100:
        return None
    return CheckResult(
        "core_parking", Status.WARN, Severity.MEDIUM, action="ms-settings:powersleep"
    )


def _check_intel_microcode(info: SystemInfo) -> CheckResult | None:
    if not raptor_lake(info):
        return None
    revision = info.windows.microcode_revision
    if revision is None:
        return CheckResult("intel_microcode", Status.UNKNOWN)
    params = {"revision": f"0x{revision:X}", "required": f"0x{INTEL_MIN_MICROCODE:X}"}
    if revision < INTEL_MIN_MICROCODE:
        return CheckResult("intel_microcode", Status.WARN, Severity.HIGH, params)
    return CheckResult("intel_microcode", Status.OK, params=params)


# ---------------------------------------------------------------------------
# Updates
# ---------------------------------------------------------------------------


def _check_windows_version(info: SystemInfo) -> CheckResult:
    win = info.windows
    if win.build is None:
        return CheckResult("windows_version", Status.UNKNOWN)
    # DisplayVersion ("25H2") is missing on old builds; fall back to the major version.
    version = info.os_display_version or ("11" if win.build >= 22000 else "10")
    params = {"version": version, "build": win.build_text}
    action = "ms-settings:windowsupdate"
    ubr = win.ubr or 0
    if win.build < 22000:
        return CheckResult(
            "windows_version", Status.WARN, Severity.MEDIUM, params, variant="win10", action=action
        )
    amd_fix = win.build >= 26100 or (win.build == 22631 and ubr >= AMD_FIX_23H2_UBR)
    if ryzen_zen3_plus(info) and not amd_fix:
        return CheckResult(
            "windows_version", Status.WARN, Severity.MEDIUM, params, variant="amd", action=action
        )
    # 25H2 (26200) is an enablement package on the 24H2 (26100) branch: same UBRs.
    if arrow_lake(info) and (win.build < 26100 or ubr < ARROW_LAKE_MIN_UBR):
        return CheckResult(
            "windows_version", Status.WARN, Severity.MEDIUM, params, variant="arrow_lake",
            action=action,
        )  # fmt: skip
    return CheckResult("windows_version", Status.OK, params=params)


def _check_nvidia_hotfix(info: SystemInfo) -> CheckResult | None:
    win = info.windows
    if info.nvidia is None or win.build not in (26100, 26200):
        return None
    if (win.ubr or 0) < NVIDIA_REGRESSION_UBR:
        return None
    installed = _version(info.nvidia.driver_version)
    if installed is None or installed >= NVIDIA_HOTFIX_DRIVER:
        return None
    params = {"installed": info.nvidia.driver_version, "required": "581.94"}
    return CheckResult(
        "nvidia_hotfix", Status.WARN, Severity.HIGH, params, action=NVIDIA_DRIVERS_URL
    )


def _check_reboot_pending(info: SystemInfo) -> CheckResult | None:
    if not info.windows.reboot_pending:
        return None
    return CheckResult(
        "reboot_pending", Status.WARN, Severity.LOW, action="ms-settings:windowsupdate"
    )


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


def _check_pagefile(info: SystemInfo) -> CheckResult:
    win = info.windows
    if win.pagefile_auto:
        return CheckResult("pagefile", Status.OK, variant="auto")
    if win.pagefile_auto is None:
        return CheckResult("pagefile", Status.UNKNOWN)
    total_mb = sum(p.size_mb or 0 for p in win.pagefiles)
    params = {"gb": round(total_mb / 1024)}
    if not win.pagefiles:
        return CheckResult("pagefile", Status.WARN, Severity.HIGH, params, variant="off")
    if total_mb < MIN_PAGEFILE_MB:
        return CheckResult("pagefile", Status.WARN, Severity.MEDIUM, params, variant="small")
    return CheckResult("pagefile", Status.OK, params=params)


def _check_system_drive_space(info: SystemInfo) -> CheckResult | None:
    win = info.windows
    if win.system_free_gb is None or win.system_free_gb >= LOW_SYSTEM_DRIVE_GB:
        return None
    params = {"letter": win.system_drive or "C", "gb": round(win.system_free_gb)}
    return CheckResult(
        "system_drive_space",
        Status.WARN,
        Severity.MEDIUM,
        params,
        action="ms-settings:storagesense",
    )


def _check_trim(info: SystemInfo) -> CheckResult | None:
    if info.windows.trim_enabled is not False:
        return None
    return CheckResult("trim", Status.WARN, Severity.LOW)


# ---------------------------------------------------------------------------
# Background apps, mouse, network
# ---------------------------------------------------------------------------


def _check_overlays(info: SystemInfo) -> CheckResult | None:
    apps = [a for a in info.windows.background_apps if a.category in ("overlay", "recording")]
    if len(apps) < 2:
        return None
    names = ", ".join(APP_NAMES.get(a.id, a.id) for a in apps)
    return CheckResult("overlays", Status.INFO, params={"apps": names, "count": len(apps)})


def _check_mouse_acceleration(info: SystemInfo) -> CheckResult:
    on = info.windows.mouse_acceleration
    if on is None:
        return CheckResult("mouse_acceleration", Status.UNKNOWN)
    if on:
        return CheckResult(
            "mouse_acceleration", Status.WARN, Severity.LOW, action="ms-settings:mousetouchpad"
        )
    return CheckResult("mouse_acceleration", Status.OK)


def _check_network(info: SystemInfo) -> CheckResult:
    win = info.windows
    if win.wired_network is None:
        return CheckResult("network", Status.UNKNOWN)
    if not win.wired_network:
        return CheckResult("network", Status.WARN, Severity.LOW, variant="wifi")
    link = next(n for n in win.network if n.kind == "ethernet")
    return CheckResult("network", Status.OK, params={"speed": link.speed_mbps or "?"})
