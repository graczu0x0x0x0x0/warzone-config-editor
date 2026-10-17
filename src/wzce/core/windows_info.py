"""Read-only state of the Windows settings that matter for gaming (stage 10a).

Covers the game's anti-cheat requirements (UEFI, Secure Boot, GPT, TPM 2.0), the
virtualization / security stack (hypervisor, VBS, VM features, antivirus), DirectX
and display options, power settings, background apps, mouse, network and storage.
Research and sources: ``docs/RAPORT_WINDOWS.md``.

Everything is read without admin rights, as a normal user. ``core/system_info.py``
fills one ``WindowsInfo`` per run:

* ``apply_windows_cim``: the extra CIM queries that share the single PowerShell call
* ``probe_registry``: HKLM/HKCU values
* ``probe_native``: Win32 APIs via ctypes (firmware type, TPM, mouse, power)
* ``probe_processes``: running background apps and services (psutil)
* ``probe_storage``: TRIM state, free space on the system drive

Absent registry values mean "Windows default", never "off". Many of these keys are
undocumented (community research), so every parser tolerates surprises and falls
back to ``None`` (= unknown). The parsers are pure functions so they can be tested
with fixtures; only the ``probe_*`` functions touch the OS.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import PureWindowsPath

from .process import GAME_PROCESS_NAMES

# Windows 11 "Power mode" overlays. They only apply while the Balanced plan is
# active; with any other plan Windows reports the all-zero GUID as well.
BALANCED_SCHEME = "381b4222-f694-41f0-9685-ff5bb260df2e"
POWER_OVERLAYS = {
    "00000000-0000-0000-0000-000000000000": "balanced",
    "ded574b5-45a0-4f42-8737-46345c09c238": "best_performance",
    "961cc777-2547-4f9d-8174-7d86181b8a7a": "best_efficiency",
}

# powrprof subgroup / setting GUIDs (fixed across Windows versions).
SUB_PROCESSOR = "54533251-82be-4824-96c1-47b60b740d00"
PROCESSOR_MIN_STATE = "893dee8e-2bef-41e0-89c6-b55d0929964c"
PROCESSOR_MAX_STATE = "bc5038f7-23e0-4960-96da-33abaf5935ec"
CORE_PARKING_MIN_CORES = "0cc5b647-c1df-4637-891a-dec35c318583"
SUB_USB = "2a737441-1930-4402-8d77-b2bebba308a3"
USB_SELECTIVE_SUSPEND = "48e6b7a6-50f5-4782-a5d4-53bb8f07e226"

# Optional features that start the Windows hypervisor when enabled.
VM_FEATURES = (
    "VirtualMachinePlatform",
    "Microsoft-Windows-Subsystem-Linux",
    "Microsoft-Hyper-V-All",
    "HypervisorPlatform",
    "Containers-DisposableClientVM",
)

# Win32_DeviceGuard.SecurityServicesRunning codes.
VBS_SERVICE_CREDENTIAL_GUARD = 1
VBS_SERVICE_HVCI = 2

# Service installed by the AMD chipset driver; it parks the CCD without V-Cache on
# dual-CCD X3D processors (only active there; stopped on single-CCD chips).
AMD_VCACHE_SERVICE = "amd3dvcacheSvc"

# Background programs worth knowing about while gaming (lower-case process names).
# Categories: overlay (hooks into the game's rendering), recording, monitoring,
# peripherals (RGB / mouse / headset suites), input_remap (flagged by Ricochet),
# tuning (CPU affinity/priority tools).
BACKGROUND_APPS: dict[str, tuple[str, str]] = {
    "discord.exe": ("discord", "overlay"),
    "steam.exe": ("steam", "overlay"),
    "nvidia overlay.exe": ("nvidia_overlay", "overlay"),
    "rtss.exe": ("rtss", "overlay"),
    "overwolf.exe": ("overwolf", "overlay"),
    "medal.exe": ("medal", "recording"),
    "obs64.exe": ("obs", "recording"),
    "msiafterburner.exe": ("afterburner", "monitoring"),
    "hwinfo64.exe": ("hwinfo", "monitoring"),
    "lghub_agent.exe": ("logitech_ghub", "peripherals"),
    "icue.exe": ("corsair_icue", "peripherals"),
    "armourycrate.service.exe": ("asus_armoury_crate", "peripherals"),
    "razerappengine.exe": ("razer_synapse", "peripherals"),
    "steelseriesgg.exe": ("steelseries_gg", "peripherals"),
    "signalrgb.exe": ("signalrgb", "peripherals"),
    "openrgb.exe": ("openrgb", "peripherals"),
    "wallpaper32.exe": ("wallpaper_engine", "other"),
    "wallpaper64.exe": ("wallpaper_engine", "other"),
    "processlasso.exe": ("process_lasso", "tuning"),
    "rewasd.exe": ("rewasd", "input_remap"),
    "rewasdengine.exe": ("rewasd", "input_remap"),
    "rewasdservice.exe": ("rewasd", "input_remap"),
    "zen studio.exe": ("cronus_zen", "input_remap"),
    "zenstudio.exe": ("cronus_zen", "input_remap"),
}

# NDIS_PHYSICAL_MEDIUM values (MSFT_NetAdapter.NdisPhysicalMedium).
_NET_MEDIUM = {14: "ethernet", 1: "wifi", 9: "wifi", 8: "mobile"}

GAMEBAR_PACKAGE = "Microsoft.XboxGamingOverlay_"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AntivirusProduct:
    name: str
    enabled: bool  # real-time protection active (False = off or passive)
    up_to_date: bool


@dataclass(frozen=True, slots=True)
class NetworkLink:
    description: str
    kind: str  # ethernet / wifi / mobile / other
    speed_mbps: int | None


@dataclass(frozen=True, slots=True)
class PageFile:
    path: str
    size_mb: int | None


@dataclass(frozen=True, slots=True)
class BackgroundApp:
    id: str  # stable key for i18n texts, e.g. "rtss"
    category: str


@dataclass(slots=True)
class WindowsInfo:
    # --- version / updates
    build: int | None = None
    ubr: int | None = None  # update revision: 26200.<ubr>
    reboot_pending: bool | None = None

    # --- game requirements (Ricochet: UEFI + GPT + Secure Boot + TPM 2.0)
    firmware_uefi: bool | None = None
    secure_boot: bool | None = None
    system_disk_gpt: bool | None = None
    tpm_version: str | None = None  # "2.0", "1.2"; "" = no TPM; None = unknown
    tpm_manufacturer: str | None = None  # "AMD", "INTC", "MSFT"...
    tpm_firmware: str | None = None  # "6.32.0.6"
    secure_boot_ca2023: str | None = None  # "Updated", "InProgress"... None = not started
    uac_enabled: bool | None = None
    uac_never_notify: bool | None = None

    # --- virtualization and security
    hypervisor_present: bool | None = None
    virtualization_firmware: bool | None = None  # SVM / VT-x as reported by Windows
    vbs_status: int | None = None  # 0 off, 1 enabled but not running, 2 running
    vbs_services_running: list[int] = field(default_factory=list)
    vm_features: dict[str, bool] = field(default_factory=dict)  # feature -> enabled
    driver_blocklist: bool | None = None
    smart_app_control: str | None = None  # off / on / evaluation
    winring0_drivers: list[str] = field(default_factory=list)  # service names
    antivirus: list[AntivirusProduct] = field(default_factory=list)
    defender_realtime: bool | None = None
    defender_mode: str | None = None  # "Normal", "Passive Mode", "EDR Block Mode"...

    # --- graphics (DirectX user settings, DWM)
    auto_hdr: bool | None = None
    vrr_optimizations: bool | None = None
    game_gpu_preference: int | None = None  # 0 Windows decides, 1 power saving, 2 high perf.
    game_fso_disabled: bool | None = None  # "Disable fullscreen optimizations" on cod.exe
    mpo_disabled: bool | None = None  # OverlayTestMode = 5 tweak

    # --- Xbox / Game Bar
    game_dvr_enabled: bool | None = None  # captures allowed at all
    game_bar_installed: bool | None = None

    # --- power and CPU
    power_overlay: str | None = None  # POWER_OVERLAYS key / "custom"; None if plan != Balanced
    processor_min_percent: int | None = None  # active plan, plugged in (AC)
    processor_max_percent: int | None = None
    core_parking_min_cores: int | None = None  # % of cores kept unparked (100 = no parking)
    usb_selective_suspend: bool | None = None
    amd_vcache_service: str | None = None  # "running" / "stopped"; None = not installed
    cpu_vendor: str | None = None  # "AuthenticAMD", "GenuineIntel"
    microcode_revision: int | None = None

    # --- memory, storage, input, network, background
    pagefile_auto: bool | None = None
    pagefiles: list[PageFile] = field(default_factory=list)
    system_drive: str | None = None  # "C"
    system_free_gb: float | None = None
    trim_enabled: bool | None = None
    mouse_acceleration: bool | None = None  # "Enhance pointer precision"
    network: list[NetworkLink] = field(default_factory=list)
    background_apps: list[BackgroundApp] = field(default_factory=list)

    # ------------------------------------------------------------ derived facts
    @property
    def build_text(self) -> str | None:
        if self.build is None:
            return None
        return f"{self.build}.{self.ubr}" if self.ubr is not None else str(self.build)

    @property
    def hvci_running(self) -> bool | None:
        return None if self.vbs_status is None else VBS_SERVICE_HVCI in self.vbs_services_running

    @property
    def svm_disabled_in_firmware(self) -> bool | None:
        """True when CPU virtualization is off in BIOS/UEFI.

        Windows reports the firmware flag as False while its own hypervisor runs,
        so the flag only means something when no hypervisor is present.
        """
        if self.hypervisor_present is None or self.virtualization_firmware is None:
            return None
        if self.hypervisor_present:
            return False
        return not self.virtualization_firmware

    @property
    def enabled_vm_features(self) -> list[str]:
        return [name for name in VM_FEATURES if self.vm_features.get(name)]

    @property
    def third_party_antivirus(self) -> list[AntivirusProduct]:
        return [av for av in self.antivirus if "defender" not in av.name.lower()]

    @property
    def wired_network(self) -> bool | None:
        if not self.network:
            return None
        return any(link.kind == "ethernet" for link in self.network)


# ---------------------------------------------------------------------------
# Pure parsing helpers
# ---------------------------------------------------------------------------


def parse_dx_settings(text: object) -> dict[str, str]:
    """``Key=Val;Key=Val;`` strings from ``HKCU\\...\\DirectX\\UserGpuPreferences``."""
    result: dict[str, str] = {}
    for part in str(text or "").split(";"):
        key, sep, value = part.partition("=")
        if sep and key.strip():
            result[key.strip()] = value.strip()
    return result


def dx_flag(settings: dict[str, str], key: str, default: bool) -> bool:
    value = settings.get(key)
    if value is None:
        return default
    return value == "1"


def is_game_exe(path: str) -> bool:
    """Registry value names under UserGpuPreferences / AppCompatFlags are full exe paths."""
    return PureWindowsPath(path).name.lower() in GAME_PROCESS_NAMES


def find_game_value(values: dict[str, object]) -> object | None:
    """Data of the first value whose name is the game's executable path."""
    return next((data for name, data in values.items() if is_game_exe(name)), None)


def parse_gpu_preference(text: object) -> int | None:
    value = parse_dx_settings(text).get("GpuPreference")
    try:
        return int(value) if value is not None else 0  # absent = let Windows decide
    except ValueError:
        return None


def has_compat_flag(text: object, flag: str) -> bool:
    """AppCompatFlags\\Layers data: ``~ FLAG1 FLAG2`` (``~`` = applies to this exe only)."""
    return flag.upper() in str(text or "").upper().split()


def decode_tpm_manufacturer(value: object) -> str | None:
    """TPM manufacturer id (four ASCII chars packed big-endian, e.g. 0x414D4400 = 'AMD')."""
    if not isinstance(value, int) or value <= 0:
        return None
    text = value.to_bytes(4, "big").rstrip(b"\x00").decode("ascii", errors="replace")
    return text.strip() or None


def parse_microcode(raw: object, vendor: str | None) -> int | None:
    """Microcode from ``CentralProcessor\\0\\Update Revision``.

    Intel keeps the revision in the upper DWORD, AMD in the lower one.
    """
    if not isinstance(raw, bytes | bytearray) or len(raw) < 4:
        return None
    if vendor == "GenuineIntel" and len(raw) >= 8:
        value = int.from_bytes(raw[4:8], "little")
    else:
        value = int.from_bytes(raw[:4], "little")
    return value or None


def decode_av_state(state: object) -> tuple[bool, bool] | None:
    """``AntiVirusProduct.productState`` -> (real-time enabled, definitions up to date).

    Undocumented but stable layout: byte 1 = 0x10/0x11 when real-time protection is
    on (0x00 off, 0x01 snoozed / passive), byte 0 = 0x00 when definitions are current.
    """
    if not isinstance(state, int):
        return None
    realtime = (state >> 8) & 0xFF
    return realtime in (0x10, 0x11), (state & 0xFF) == 0


def parse_smart_app_control(value: object) -> str | None:
    return {0: "off", 1: "on", 2: "evaluation"}.get(value) if isinstance(value, int) else None


def effective_overlay(active_scheme: str, overlay: str) -> str | None:
    """Power mode name, or None when the active plan is not Balanced (no overlay then)."""
    if active_scheme.lower() != BALANCED_SCHEME:
        return None
    return POWER_OVERLAYS.get(overlay.lower(), "custom")


def parse_fsutil_trim(text: str) -> bool | None:
    """``fsutil behavior query DisableDeleteNotify``: TRIM is on when NTFS reports 0."""
    match = re.search(r"NTFS\s+DisableDeleteNotify\s*=\s*(\d)", text)
    return match.group(1) == "0" if match else None


def parse_partition_style(value: object) -> bool | None:
    """MSFT_Disk.PartitionStyle -> GPT?

    A number (1 MBR, 2 GPT, 0 RAW) in a fresh session, but the name ("GPT") once the
    Storage module's type data is loaded - which ``Get-Partition`` in the same script does.
    """
    style = {1: "MBR", 2: "GPT"}.get(value, value) if isinstance(value, int) else value
    if not isinstance(style, str) or style.upper() not in ("MBR", "GPT"):
        return None
    return style.upper() == "GPT"


def network_kind(medium: object) -> str:
    return _NET_MEDIUM.get(medium, "other") if isinstance(medium, int) else "other"


def match_background_apps(process_names: list[str]) -> list[BackgroundApp]:
    found: dict[str, BackgroundApp] = {}
    for name in process_names:
        entry = BACKGROUND_APPS.get(name.lower())
        if entry and entry[0] not in found:
            found[entry[0]] = BackgroundApp(*entry)
    return sorted(found.values(), key=lambda app: (app.category, app.id))


def _as_list(value: object) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _int(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def apply_windows_cim(win: WindowsInfo, data: dict) -> None:
    """Fill ``win`` from the shared PowerShell JSON (``win``, ``vbs`` and ``cpu`` sections)."""
    vbs = data.get("vbs") or {}
    if vbs:
        win.vbs_status = _int(vbs.get("status"))
        win.vbs_services_running = [x for x in map(_int, _as_list(vbs.get("running"))) if x]
    section = data.get("win") or {}
    cs = section.get("cs") or {}
    win.hypervisor_present = cs.get("HypervisorPresent")
    win.pagefile_auto = cs.get("AutomaticManagedPagefile")
    virt = (data.get("cpu") or {}).get("VirtualizationFirmwareEnabled")
    win.virtualization_firmware = virt if isinstance(virt, bool) else None
    win.vm_features = {
        str(f.get("Name")): f.get("InstallState") == 1  # 1 enabled, 2 disabled, 3 absent
        for f in _as_list(section.get("features"))
        if f.get("Name")
    }
    win.antivirus = []
    for product in _as_list(section.get("av")):
        decoded = decode_av_state(product.get("productState"))
        name = str(product.get("displayName") or "").strip()
        if decoded and name:
            win.antivirus.append(AntivirusProduct(name, *decoded))
    defender = section.get("defender") or {}
    if defender:
        win.defender_realtime = defender.get("RealTimeProtectionEnabled")
        win.defender_mode = defender.get("AMRunningMode")
    win.pagefiles = [
        PageFile(str(p.get("Name") or ""), _int(p.get("AllocatedBaseSize")))
        for p in _as_list(section.get("pagefiles"))
        if p.get("Name")
    ]
    win.system_disk_gpt = parse_partition_style(section.get("boot_partition_style"))
    win.network = [
        NetworkLink(
            description=str(n.get("InterfaceDescription") or ""),
            kind=network_kind(n.get("NdisPhysicalMedium")),
            speed_mbps=(_int(n.get("Speed")) or 0) // 1_000_000 or None,
        )
        for n in _as_list(section.get("net"))
        if n.get("MediaConnectState") == 1  # connected
    ]


# Appended to the PowerShell script in ``core/system_info.py`` (one process start).
POWERSHELL_PART = r"""
$w = [ordered]@{}
$w.cs = Get-CimInstance Win32_ComputerSystem | Select-Object -First 1 HypervisorPresent, AutomaticManagedPagefile
$w.features = @(Get-CimInstance Win32_OptionalFeature -Filter "Name='VirtualMachinePlatform' OR Name='Microsoft-Windows-Subsystem-Linux' OR Name='Microsoft-Hyper-V-All' OR Name='HypervisorPlatform' OR Name='Containers-DisposableClientVM'" | Select-Object Name, InstallState)
$w.av = @(Get-CimInstance -Namespace root\SecurityCenter2 -ClassName AntiVirusProduct | Select-Object displayName, productState)
$w.defender = Get-CimInstance -Namespace root\Microsoft\Windows\Defender -ClassName MSFT_MpComputerStatus | Select-Object -First 1 RealTimeProtectionEnabled, AMRunningMode
$w.pagefiles = @(Get-CimInstance Win32_PageFileUsage | Select-Object Name, AllocatedBaseSize)
$w.boot_partition_style = (Get-CimInstance -Namespace root\Microsoft\Windows\Storage -ClassName MSFT_Disk | Where-Object IsBoot | Select-Object -First 1).PartitionStyle
$w.net = @(Get-CimInstance -Namespace root\StandardCimv2 -ClassName MSFT_NetAdapter -Filter "ConnectorPresent=TRUE" | Select-Object InterfaceDescription, NdisPhysicalMedium, Speed, MediaConnectState)
$r.win = $w
"""


# ---------------------------------------------------------------------------
# OS probes (Windows only; each may raise - the caller records the error)
# ---------------------------------------------------------------------------


def _read(root: int, path: str, name: str) -> object | None:
    import winreg

    try:
        with winreg.OpenKey(root, path) as key:
            return winreg.QueryValueEx(key, name)[0]
    except OSError:
        return None


def _key_exists(root: int, path: str) -> bool:
    import winreg

    try:
        winreg.CloseKey(winreg.OpenKey(root, path))
    except OSError:
        return False
    return True


def _values(root: int, path: str) -> dict[str, object]:
    import winreg

    result: dict[str, object] = {}
    try:
        with winreg.OpenKey(root, path) as key:
            index = 0
            while True:
                try:
                    name, data, _type = winreg.EnumValue(key, index)
                except OSError:
                    break
                result[name] = data
                index += 1
    except OSError:
        pass
    return result


def _subkeys(root: int, path: str) -> list[str]:
    import winreg

    names: list[str] = []
    try:
        with winreg.OpenKey(root, path) as key:
            index = 0
            while True:
                try:
                    names.append(winreg.EnumKey(key, index))
                except OSError:
                    break
                index += 1
    except OSError:
        pass
    return names


def probe_registry(win: WindowsInfo) -> None:
    import winreg

    hklm, hkcu = winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER
    nt = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
    win.build = _int(_read(hklm, nt, "CurrentBuild"))
    win.ubr = _int(_read(hklm, nt, "UBR"))
    win.reboot_pending = _key_exists(
        hklm, r"SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired"
    ) or _key_exists(
        hklm, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending"
    )

    secure_boot = r"SYSTEM\CurrentControlSet\Control\SecureBoot"
    enabled = _read(hklm, secure_boot + r"\State", "UEFISecureBootEnabled")
    win.secure_boot = None if enabled is None else enabled == 1
    status = _read(hklm, secure_boot + r"\Servicing", "UEFICA2023Status")
    win.secure_boot_ca2023 = status if isinstance(status, str) and status else None

    # Undocumented provisioning values; readable without admin (Win32_Tpm is not).
    tpm = r"SYSTEM\CurrentControlSet\Services\TPM\WMI"
    win.tpm_manufacturer = decode_tpm_manufacturer(_read(hklm, tpm, "TaskManufacturerId"))
    firmware = _read(hklm, tpm, "TaskFirmwareVersion") or _read(
        hklm, tpm, "FirmwareVersionAtLastProvision"
    )
    win.tpm_firmware = firmware if isinstance(firmware, str) and firmware else None

    policies = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System"
    lua = _read(hklm, policies, "EnableLUA")
    win.uac_enabled = True if lua is None else lua != 0
    consent = _read(hklm, policies, "ConsentPromptBehaviorAdmin")
    win.uac_never_notify = (not win.uac_enabled) or consent == 0

    blocklist = _read(
        hklm, r"SYSTEM\CurrentControlSet\Control\CI\Config", "VulnerableDriverBlocklistEnable"
    )
    win.driver_blocklist = True if blocklist is None else blocklist == 1  # on by default (22H2+)
    win.smart_app_control = parse_smart_app_control(
        _read(
            hklm, r"SYSTEM\CurrentControlSet\Control\CI\Policy", "VerifiedAndReputablePolicyState"
        )
    )
    win.mpo_disabled = _read(hklm, r"SOFTWARE\Microsoft\Windows\Dwm", "OverlayTestMode") == 5

    cpu = r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
    vendor = _read(hklm, cpu, "VendorIdentifier")
    win.cpu_vendor = vendor if isinstance(vendor, str) else None
    win.microcode_revision = parse_microcode(_read(hklm, cpu, "Update Revision"), win.cpu_vendor)

    services = r"SYSTEM\CurrentControlSet\Services"
    names = _subkeys(hklm, services)
    win.winring0_drivers = sorted(
        name
        for name in names
        if "winring0" in str(_read(hklm, f"{services}\\{name}", "ImagePath") or "").lower()
    )

    dx_key = r"Software\Microsoft\DirectX\UserGpuPreferences"
    dx_values = _values(hkcu, dx_key)
    dx = parse_dx_settings(dx_values.get("DirectXUserGlobalSettings"))
    win.auto_hdr = dx_flag(dx, "AutoHDREnable", default=False)
    win.vrr_optimizations = dx_flag(dx, "VRROptimizeEnable", default=True)
    win.game_gpu_preference = parse_gpu_preference(find_game_value(dx_values))
    layers = _values(hkcu, r"Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers")
    win.game_fso_disabled = has_compat_flag(
        find_game_value(layers), "DISABLEDXMAXIMIZEDWINDOWEDMODE"
    )

    dvr = _read(hkcu, r"System\GameConfigStore", "GameDVR_Enabled")
    win.game_dvr_enabled = True if dvr is None else dvr != 0
    packages = (
        r"Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion"
        r"\AppModel\Repository\Packages"
    )
    win.game_bar_installed = any(n.startswith(GAMEBAR_PACKAGE) for n in _subkeys(hkcu, packages))


def _guid_struct():
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", wintypes.DWORD),
            ("Data2", wintypes.WORD),
            ("Data3", wintypes.WORD),
            ("Data4", ctypes.c_ubyte * 8),
        ]

    return GUID


def probe_native(win: WindowsInfo) -> None:
    import ctypes
    import uuid
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32")
    firmware = wintypes.DWORD()
    if kernel32.GetFirmwareType(ctypes.byref(firmware)):
        win.firmware_uefi = {1: False, 2: True}.get(firmware.value)

    win.tpm_version = _tpm_version()

    mouse = (ctypes.c_int * 3)()  # threshold1, threshold2, acceleration
    if ctypes.WinDLL("user32").SystemParametersInfoW(0x0003, 0, mouse, 0):  # SPI_GETMOUSE
        win.mouse_acceleration = mouse[2] != 0

    guid_type = _guid_struct()

    def guid(text: str):
        value = guid_type()
        ctypes.memmove(ctypes.byref(value), uuid.UUID(text).bytes_le, 16)
        return value

    powrprof = ctypes.WinDLL("powrprof")
    active = ctypes.POINTER(guid_type)()
    if powrprof.PowerGetActiveScheme(None, ctypes.byref(active)) != 0:
        return
    try:
        active_guid = str(uuid.UUID(bytes_le=bytes(active.contents)))
        overlay = guid_type()
        if powrprof.PowerGetEffectiveOverlayScheme(ctypes.byref(overlay)) == 0:
            overlay_guid = str(uuid.UUID(bytes_le=bytes(overlay)))
            win.power_overlay = effective_overlay(active_guid, overlay_guid)

        def ac_value(subgroup: str, setting: str) -> int | None:
            value = wintypes.DWORD()
            rc = powrprof.PowerReadACValueIndex(
                None, active, ctypes.byref(guid(subgroup)), ctypes.byref(guid(setting)),
                ctypes.byref(value),
            )  # fmt: skip
            return value.value if rc == 0 else None

        win.processor_min_percent = ac_value(SUB_PROCESSOR, PROCESSOR_MIN_STATE)
        win.processor_max_percent = ac_value(SUB_PROCESSOR, PROCESSOR_MAX_STATE)
        win.core_parking_min_cores = ac_value(SUB_PROCESSOR, CORE_PARKING_MIN_CORES)
        usb = ac_value(SUB_USB, USB_SELECTIVE_SUSPEND)
        win.usb_selective_suspend = None if usb is None else usb != 0
    finally:
        kernel32.LocalFree(active)


def _tpm_version() -> str | None:
    """TPM spec version via TBS (works without admin, unlike Win32_Tpm)."""
    import ctypes
    from ctypes import wintypes

    class TPM_DEVICE_INFO(ctypes.Structure):  # Win32 structure name
        _fields_ = [
            ("structVersion", wintypes.UINT),
            ("tpmVersion", wintypes.UINT),
            ("tpmInterfaceType", wintypes.UINT),
            ("tpmImpRevision", wintypes.UINT),
        ]

    info = TPM_DEVICE_INFO()
    rc = ctypes.WinDLL("tbs").Tbsi_GetDeviceInfo(ctypes.sizeof(info), ctypes.byref(info))
    rc &= 0xFFFFFFFF
    if rc == 0x8028400F:  # TBS_E_TPM_NOT_FOUND
        return ""
    if rc != 0:
        return None
    return {1: "1.2", 2: "2.0"}.get(info.tpmVersion)


def probe_processes(win: WindowsInfo) -> None:
    import psutil

    names = [p.info.get("name") or "" for p in psutil.process_iter(["name"])]
    win.background_apps = match_background_apps(names)
    try:
        win.amd_vcache_service = psutil.win_service_get(AMD_VCACHE_SERVICE).status()
    except psutil.NoSuchProcess:  # psutil raises this for unknown services
        win.amd_vcache_service = None


def probe_storage(win: WindowsInfo) -> None:
    import os

    drive = (os.environ.get("SYSTEMDRIVE") or "C:").rstrip("\\")
    win.system_drive = drive[:1].upper()
    win.system_free_gb = round(shutil.disk_usage(drive + "\\").free / 1024**3, 1)
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    result = subprocess.run(
        ["fsutil", "behavior", "query", "DisableDeleteNotify"],
        capture_output=True, timeout=10, check=False, creationflags=flags,
    )  # fmt: skip
    win.trim_enabled = parse_fsutil_trim(result.stdout.decode("utf-8", errors="replace"))
