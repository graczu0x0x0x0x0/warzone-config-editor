"""Detailed, read-only system specification for the "Your hardware" bar and system checks.

Collected without admin rights, in three independent probes so one failing never
hides the others:

* one PowerShell call returning JSON (CIM/WMI: CPU, RAM modules, GPUs, board, BIOS,
  OS, monitors from EDID, VBS/HVCI, drive letter -> physical disk type)
* registry reads in Python (HAGS, Game Mode, background recording, windowed-game
  optimizations, Windows display version, game install location)
* ``nvidia-smi`` when present (PCIe link, Resizable BAR via BAR1 size, power limit)

Collection takes 2-4 s (WMI is slow), so the UI runs ``collect_system_info`` in a
background thread. Every parser is a pure function over plain data so it can be
tested with fixtures; ``collect_system_info`` is the only part that touches the OS.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Text describing the queries lives here so the probe stays a single process start.
_POWERSHELL_SCRIPT = r"""
$ErrorActionPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$r = [ordered]@{}
$r.cpu = Get-CimInstance Win32_Processor | Select-Object -First 1 Name, NumberOfCores, NumberOfLogicalProcessors, MaxClockSpeed, L2CacheSize, L3CacheSize, SocketDesignation
$r.memory = @(Get-CimInstance Win32_PhysicalMemory | Select-Object BankLabel, DeviceLocator, Manufacturer, PartNumber, Capacity, Speed, ConfiguredClockSpeed, ConfiguredVoltage, SMBIOSMemoryType)
$r.memory_slots = (Get-CimInstance Win32_PhysicalMemoryArray | Measure-Object -Property MemoryDevices -Sum).Sum
$r.gpus = @(Get-CimInstance Win32_VideoController | Select-Object Name, DriverVersion, @{n='DriverDate';e={ if ($_.DriverDate) { $_.DriverDate.ToString('yyyy-MM-dd') } }}, CurrentHorizontalResolution, CurrentVerticalResolution, CurrentRefreshRate, MaxRefreshRate)
$r.board = Get-CimInstance Win32_BaseBoard | Select-Object -First 1 Manufacturer, Product
$r.bios = Get-CimInstance Win32_BIOS | Select-Object -First 1 SMBIOSBIOSVersion, @{n='ReleaseDate';e={ if ($_.ReleaseDate) { $_.ReleaseDate.ToString('yyyy-MM-dd') } }}
$r.os = Get-CimInstance Win32_OperatingSystem | Select-Object -First 1 Caption, BuildNumber
$r.monitors = @(Get-CimInstance -Namespace root\wmi -ClassName WmiMonitorID | ForEach-Object {
    [ordered]@{
        manufacturer = (($_.ManufacturerName | Where-Object { $_ }) | ForEach-Object { [char]$_ }) -join ''
        name = (($_.UserFriendlyName | Where-Object { $_ }) | ForEach-Object { [char]$_ }) -join ''
        year = $_.YearOfManufacture
    } })
$dg = Get-CimInstance -Namespace root\Microsoft\Windows\DeviceGuard -ClassName Win32_DeviceGuard
if ($dg) { $r.vbs = [ordered]@{ status = $dg.VirtualizationBasedSecurityStatus; running = @($dg.SecurityServicesRunning) } }
$disks = @(Get-PhysicalDisk)
$r.drives = @(Get-Partition | Where-Object { $_.DriveLetter } | ForEach-Object {
    $p = $_
    $d = $disks | Where-Object { $_.DeviceId -eq [string]$p.DiskNumber } | Select-Object -First 1
    [ordered]@{ letter = [string]$p.DriveLetter; disk = $d.FriendlyName; media = [string]$d.MediaType; bus = [string]$d.BusType }
})
$r | ConvertTo-Json -Depth 5 -Compress
"""

POWERSHELL_TIMEOUT_S = 25
NVIDIA_SMI_TIMEOUT_S = 8
STEAM_APP_ID = "1938090"  # Call of Duty HQ on Steam

# SMBIOS memory type codes (SMBIOS spec, table "Memory Device - Type").
MEMORY_TYPES = {20: "DDR", 21: "DDR2", 24: "DDR3", 26: "DDR4", 34: "DDR5", 35: "LPDDR5"}
# Highest JEDEC (non-overclocked) speed and the standard voltage per type.
JEDEC_MAX_SPEED = {"DDR4": 3200, "DDR5": 5600}
JEDEC_VOLTAGE_MV = {"DDR4": 1200, "DDR5": 1100}

# Windows built-in power plans (GUIDs are fixed; names are localized, so match GUIDs).
POWER_PLANS = {
    "381b4222-f694-41f0-9685-ff5bb260df2e": "balanced",
    "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c": "high_performance",
    "a1841308-3541-4fab-bc81-f71556f20b4a": "power_saver",
    "e9a42b02-d5df-448d-aa00-03f14749eb61": "ultimate",
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MemoryModule:
    slot: str  # "P0 CHANNEL A / DIMM 1"
    channel: str | None  # "A", "B"... when it can be read from the slot labels
    manufacturer: str
    part_number: str
    capacity_gb: float
    type: str | None  # "DDR5"
    speed_mts: int | None  # configured (actual) speed in MT/s
    voltage_mv: int | None
    rated_speed_mts: int | None  # from the part number, if it can be decoded
    rated_cl: int | None


@dataclass(frozen=True, slots=True)
class GpuInfo:
    name: str
    driver_version: str
    driver_date: str | None
    is_integrated: bool


@dataclass(frozen=True, slots=True)
class NvidiaInfo:
    name: str
    driver_version: str
    vram_mb: int | None
    pcie_gen: int | None
    pcie_gen_max: int | None
    pcie_width: int | None
    pcie_width_max: int | None
    power_limit_w: float | None
    temperature_c: int | None
    bar1_mb: int | None

    @property
    def rebar_enabled(self) -> bool | None:
        """Resizable BAR is on when the BAR1 aperture covers (almost) the whole VRAM."""
        if not self.bar1_mb or not self.vram_mb:
            return None
        return self.bar1_mb >= self.vram_mb * 0.9


@dataclass(frozen=True, slots=True)
class DriveInfo:
    letter: str
    disk: str
    media: str  # "SSD", "HDD", "Unspecified"
    bus: str  # "NVMe", "SATA", "USB", "RAID"...

    @property
    def kind(self) -> str:
        """Simplified class used by the checks: nvme / ssd / hdd / unknown."""
        if self.bus.upper() == "NVME":
            return "nvme"
        if self.media.upper() == "HDD":
            return "hdd"
        if self.media.upper() == "SSD":
            return "ssd"
        return "unknown"


@dataclass(frozen=True, slots=True)
class GameInstall:
    path: str
    drive: DriveInfo | None
    free_gb: float | None


@dataclass(slots=True)
class SystemInfo:
    cpu_name: str | None = None
    cpu_cores: int | None = None
    cpu_threads: int | None = None
    cpu_base_mhz: int | None = None
    cpu_l2_kb: int | None = None
    cpu_l3_kb: int | None = None
    cpu_socket: str | None = None
    memory: list[MemoryModule] = field(default_factory=list)
    memory_slots: int | None = None
    gpus: list[GpuInfo] = field(default_factory=list)
    nvidia: NvidiaInfo | None = None
    monitors: list[str] = field(default_factory=list)
    board: str | None = None
    bios_version: str | None = None
    bios_date: str | None = None
    os_name: str | None = None
    os_build: str | None = None
    os_display_version: str | None = None  # "25H2"
    power_plan: str | None = None  # key of POWER_PLANS or "custom"
    hags: bool | None = None
    game_mode: bool | None = None
    background_recording: bool | None = None
    windowed_optimizations: bool | None = None
    vbs_running: bool | None = None
    hvci_running: bool | None = None
    drives: list[DriveInfo] = field(default_factory=list)
    game_install: GameInstall | None = None
    errors: list[str] = field(default_factory=list)  # probes that failed (diagnostics)

    # ------------------------------------------------------------ derived facts
    @property
    def memory_total_gb(self) -> float | None:
        return round(sum(m.capacity_gb for m in self.memory), 1) if self.memory else None

    @property
    def memory_type(self) -> str | None:
        types = {m.type for m in self.memory if m.type}
        return types.pop() if len(types) == 1 else None

    @property
    def memory_speed_mts(self) -> int | None:
        speeds = [m.speed_mts for m in self.memory if m.speed_mts]
        return min(speeds) if speeds else None

    @property
    def memory_channels(self) -> int | None:
        """Number of populated memory channels; None when the labels do not say."""
        channels = {m.channel for m in self.memory}
        if not self.memory or None in channels:
            return None
        return len(channels)

    @property
    def expo_xmp(self) -> str:
        """'on', 'off' or 'unknown' - heuristic, see ``expo_state``."""
        return expo_state(self.memory)

    @property
    def dedicated_gpu(self) -> GpuInfo | None:
        return next((g for g in self.gpus if not g.is_integrated), None)

    @property
    def has_integrated_gpu(self) -> bool:
        return any(g.is_integrated for g in self.gpus) and self.dedicated_gpu is not None

    @property
    def x3d_cache(self) -> bool:
        return bool(self.cpu_name and "X3D" in self.cpu_name.upper())


# ---------------------------------------------------------------------------
# Pure parsing / analysis helpers
# ---------------------------------------------------------------------------

_CHANNEL_RE = re.compile(r"CHANNEL\s*([A-H])|CHANNEL([A-H])|CH\s*([A-H])\b", re.IGNORECASE)
_SPEED_RE = re.compile(r"(?<!\d)(2[1-9]\d{2}|[3-9]\d{3})(?!\d)")  # 2100..9999 MT/s
# Brand-specific part-number patterns: (regex, speed group, speed multiplier, CL group)
_PART_PATTERNS: tuple[tuple[re.Pattern[str], int, int, int | None], ...] = (
    (re.compile(r"^F[345]-(\d{4})[A-Z](\d{2})", re.IGNORECASE), 1, 1, 2),  # G.Skill F5-6000J3038
    # Kingston FURY: KF + DDR generation + speed/100 + C + CL, e.g. KF560C30 = DDR5-6000 CL30
    (re.compile(r"^KF[345](\d{2})C(\d{2})", re.IGNORECASE), 1, 100, 2),
    (re.compile(r"^CM\w+?(\d{4})C(\d{2})", re.IGNORECASE), 1, 1, 2),  # Corsair ...6000C30
    (re.compile(r"(\d{4})H?C(\d{2})", re.IGNORECASE), 1, 1, 2),  # TeamGroup 6000HC38, generic
)


def parse_channel(*labels: str) -> str | None:
    """Channel letter from slot labels like 'P0 CHANNEL A' or 'Controller0-ChannelB-DIMM1'."""
    for label in labels:
        match = _CHANNEL_RE.search(label or "")
        if match:
            return next(g for g in match.groups() if g).upper()
    return None


def decode_part_number(part: str) -> tuple[int | None, int | None]:
    """Rated ``(speed MT/s, CL)`` encoded in a RAM part number, best effort."""
    text = (part or "").strip()
    for pattern, speed_group, multiplier, cl_group in _PART_PATTERNS:
        match = pattern.search(text)
        if match:
            speed = int(match.group(speed_group)) * multiplier
            cl = int(match.group(cl_group)) if cl_group else None
            if 2100 <= speed <= 12000:
                return speed, cl
    match = _SPEED_RE.search(text)  # e.g. Patriot "6400 Series"
    return (int(match.group(1)), None) if match else (None, None)


def expo_state(modules: list[MemoryModule]) -> str:
    """Is an XMP/EXPO profile active? 'on' / 'off' / 'unknown'.

    There is no Windows API for it; the evidence used:
    * running above the highest JEDEC speed -> a profile (or manual OC) is active
    * running at a JEDEC speed with standard voltage while the part number says the
      kit is rated faster -> profile is off
    """
    if not modules:
        return "unknown"
    mem_type = modules[0].type
    speed = min((m.speed_mts for m in modules if m.speed_mts), default=None)
    if mem_type not in JEDEC_MAX_SPEED or speed is None:
        return "unknown"
    if speed > JEDEC_MAX_SPEED[mem_type]:
        return "on"
    rated = max((m.rated_speed_mts for m in modules if m.rated_speed_mts), default=None)
    voltage = max((m.voltage_mv for m in modules if m.voltage_mv), default=None)
    standard_voltage = voltage is None or voltage <= JEDEC_VOLTAGE_MV[mem_type]
    if rated and rated > speed + 100 and standard_voltage:
        return "off"
    return "unknown"


def parse_memory(rows: list[dict]) -> list[MemoryModule]:
    modules = []
    for row in rows or []:
        bank, locator = str(row.get("BankLabel") or ""), str(row.get("DeviceLocator") or "")
        part = str(row.get("PartNumber") or "").strip()
        rated_speed, rated_cl = decode_part_number(part)
        configured = row.get("ConfiguredClockSpeed") or row.get("Speed")
        modules.append(
            MemoryModule(
                slot=" / ".join(x for x in (bank.strip(), locator.strip()) if x),
                channel=parse_channel(bank, locator),
                manufacturer=str(row.get("Manufacturer") or "").strip(),
                part_number=part,
                capacity_gb=round(int(row.get("Capacity") or 0) / 1024**3, 1),
                type=MEMORY_TYPES.get(int(row.get("SMBIOSMemoryType") or 0)),
                speed_mts=int(configured) if configured else None,
                voltage_mv=int(row["ConfiguredVoltage"]) if row.get("ConfiguredVoltage") else None,
                rated_speed_mts=rated_speed,
                rated_cl=rated_cl,
            )
        )
    return modules


_INTEGRATED_HINTS = (
    "radeon(tm) graphics",
    "radeon graphics",
    "uhd graphics",
    "iris",
    "intel(r) graphics",
    "vega",
)


def parse_gpus(rows: list[dict]) -> list[GpuInfo]:
    gpus = []
    for row in rows or []:
        name = str(row.get("Name") or "").strip()
        if not name or "basic display" in name.lower() or "remote" in name.lower():
            continue
        lowered = name.lower()
        gpus.append(
            GpuInfo(
                name=name,
                driver_version=str(row.get("DriverVersion") or ""),
                driver_date=row.get("DriverDate"),
                is_integrated=any(hint in lowered for hint in _INTEGRATED_HINTS),
            )
        )
    return gpus


def parse_nvidia_csv(line: str, bar1_mb: int | None) -> NvidiaInfo | None:
    """One ``nvidia-smi --query-gpu=... --format=csv,noheader,nounits`` line."""
    parts = [p.strip() for p in line.split(",")]
    if len(parts) < 9:
        return None

    def number(text: str, cast=int):
        try:
            return cast(float(text))
        except ValueError:
            return None  # "[N/A]" or "[Not Supported]"

    return NvidiaInfo(
        name=parts[0],
        driver_version=parts[1],
        vram_mb=number(parts[2]),
        pcie_gen=number(parts[3]),
        pcie_gen_max=number(parts[4]),
        pcie_width=number(parts[5]),
        pcie_width_max=number(parts[6]),
        power_limit_w=number(parts[7], float),
        temperature_c=number(parts[8]),
        bar1_mb=bar1_mb,
    )


def parse_bar1_total(text: str) -> int | None:
    """Total BAR1 size (MiB) from ``nvidia-smi -q -d MEMORY`` output."""
    match = re.search(r"BAR1 Memory Usage\s*\n\s*Total\s*:\s*(\d+)\s*MiB", text)
    return int(match.group(1)) if match else None


def parse_power_plan(text: str) -> str | None:
    """Key of POWER_PLANS (or 'custom') from ``powercfg /getactivescheme`` output."""
    match = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", text, re.I)
    if not match:
        return None
    return POWER_PLANS.get(match.group(1).lower(), "custom")


def parse_vdf_library_paths(text: str) -> list[str]:
    """Library folders listed in Steam's ``libraryfolders.vdf``."""
    return [p.replace("\\\\", "\\") for p in re.findall(r'"path"\s+"([^"]+)"', text)]


def parse_acf_installdir(text: str) -> str | None:
    match = re.search(r'"installdir"\s+"([^"]+)"', text)
    return match.group(1) if match else None


def apply_cim_json(info: SystemInfo, data: dict) -> None:
    """Fill ``info`` from the PowerShell JSON (tolerates missing parts)."""
    cpu = data.get("cpu") or {}
    info.cpu_name = (cpu.get("Name") or "").strip() or None
    info.cpu_cores = cpu.get("NumberOfCores")
    info.cpu_threads = cpu.get("NumberOfLogicalProcessors")
    info.cpu_base_mhz = cpu.get("MaxClockSpeed")
    info.cpu_l2_kb = cpu.get("L2CacheSize")
    info.cpu_l3_kb = cpu.get("L3CacheSize")
    info.cpu_socket = cpu.get("SocketDesignation")
    info.memory = parse_memory(_as_list(data.get("memory")))
    info.memory_slots = data.get("memory_slots")
    info.gpus = parse_gpus(_as_list(data.get("gpus")))
    board = data.get("board") or {}
    name = " ".join(x for x in (board.get("Manufacturer"), board.get("Product")) if x)
    info.board = name.replace("Technology Co., Ltd.", "").replace("  ", " ").strip() or None
    bios = data.get("bios") or {}
    info.bios_version = bios.get("SMBIOSBIOSVersion")
    info.bios_date = bios.get("ReleaseDate")
    os_info = data.get("os") or {}
    info.os_name = os_info.get("Caption")
    info.os_build = str(os_info.get("BuildNumber") or "") or None
    info.monitors = [
        " ".join(x for x in (m.get("name"), f"({m['year']})" if m.get("year") else "") if x)
        for m in _as_list(data.get("monitors"))
        if m.get("name")
    ]
    vbs = data.get("vbs")
    if vbs:
        info.vbs_running = vbs.get("status") == 2
        info.hvci_running = 2 in _as_list(vbs.get("running"))
    info.drives = [
        DriveInfo(
            letter=str(d.get("letter") or "").upper(),
            disk=str(d.get("disk") or ""),
            media=str(d.get("media") or ""),
            bus=str(d.get("bus") or ""),
        )
        for d in _as_list(data.get("drives"))
        if d.get("letter")
    ]


def _as_list(value: object) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


# ---------------------------------------------------------------------------
# OS probes
# ---------------------------------------------------------------------------


def _run(command: list[str], timeout: float) -> str:
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0  # no console flash
    result = subprocess.run(
        command, capture_output=True, timeout=timeout, check=False, creationflags=flags
    )
    return result.stdout.decode("utf-8", errors="replace")


def _probe_cim(info: SystemInfo) -> None:
    output = _run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-Command", _POWERSHELL_SCRIPT],
        POWERSHELL_TIMEOUT_S,
    )  # fmt: skip
    start = output.find("{")
    apply_cim_json(info, json.loads(output[start:]))


def _probe_nvidia(info: SystemInfo) -> None:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return
    fields = (
        "name,driver_version,memory.total,pcie.link.gen.current,pcie.link.gen.max,"
        "pcie.link.width.current,pcie.link.width.max,power.limit,temperature.gpu"
    )
    csv = _run(
        [exe, f"--query-gpu={fields}", "--format=csv,noheader,nounits"], NVIDIA_SMI_TIMEOUT_S
    )
    memory = _run([exe, "-q", "-d", "MEMORY"], NVIDIA_SMI_TIMEOUT_S)
    first = csv.strip().splitlines()[0] if csv.strip() else ""
    info.nvidia = parse_nvidia_csv(first, parse_bar1_total(memory))


def _registry_value(root: int, path: str, name: str) -> object | None:
    import winreg

    try:
        with winreg.OpenKey(root, path) as key:
            return winreg.QueryValueEx(key, name)[0]
    except OSError:
        return None


def _probe_registry(info: SystemInfo) -> None:
    import winreg

    hklm, hkcu = winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER
    hags = _registry_value(hklm, r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers", "HwSchMode")
    info.hags = None if hags is None else hags == 2
    game_mode = _registry_value(hkcu, r"Software\Microsoft\GameBar", "AutoGameModeEnabled")
    info.game_mode = True if game_mode is None else bool(game_mode)  # Windows 11 default: on
    recording = _registry_value(
        hkcu, r"Software\Microsoft\Windows\CurrentVersion\GameDVR", "HistoricalCaptureEnabled"
    )
    info.background_recording = bool(recording) if recording is not None else False
    dx = _registry_value(
        hkcu, r"Software\Microsoft\DirectX\UserGpuPreferences", "DirectXUserGlobalSettings"
    )
    info.windowed_optimizations = "SwapEffectUpgradeEnable=1" in str(dx or "")
    info.os_display_version = _registry_value(
        hklm, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion", "DisplayVersion"
    )  # type: ignore[assignment]


def _probe_power_plan(info: SystemInfo) -> None:
    info.power_plan = parse_power_plan(_run(["powercfg", "/getactivescheme"], 10))


def find_game_install() -> str | None:
    """Install folder of Call of Duty (HQ): uninstall entries first, then Steam libraries."""
    import winreg

    roots = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
        ),
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    for root, path in roots:
        try:
            with winreg.OpenKey(root, path) as key:
                index = 0
                while True:
                    try:
                        sub = winreg.EnumKey(key, index)
                    except OSError:
                        break
                    index += 1
                    name = _registry_value(root, f"{path}\\{sub}", "DisplayName")
                    if not isinstance(name, str) or not name.startswith("Call of Duty"):
                        continue
                    if "beta" in name.lower():
                        continue  # betas live elsewhere and are short-lived
                    location = _registry_value(root, f"{path}\\{sub}", "InstallLocation")
                    if isinstance(location, str) and location.strip():
                        return location.strip()
        except OSError:
            continue
    steam = _registry_value(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath")
    if isinstance(steam, str):
        vdf = Path(steam) / "steamapps" / "libraryfolders.vdf"
        if vdf.exists():
            for library in parse_vdf_library_paths(
                vdf.read_text(encoding="utf-8", errors="replace")
            ):
                manifest = Path(library) / "steamapps" / f"appmanifest_{STEAM_APP_ID}.acf"
                if manifest.exists():
                    folder = parse_acf_installdir(
                        manifest.read_text(encoding="utf-8", errors="replace")
                    )
                    return str(Path(library) / "steamapps" / "common" / (folder or ""))
    return None


def _probe_game_install(info: SystemInfo) -> None:
    path = find_game_install()
    if not path:
        return
    letter = path[:1].upper()
    drive = next((d for d in info.drives if d.letter == letter), None)
    try:
        free_gb = round(shutil.disk_usage(f"{letter}:\\").free / 1024**3, 1)
    except OSError:
        free_gb = None
    info.game_install = GameInstall(path=path, drive=drive, free_gb=free_gb)


def collect_system_info() -> SystemInfo:
    """Run every probe; never raises. Failed probes are listed in ``errors``."""
    info = SystemInfo()
    if sys.platform != "win32":
        info.errors.append("not windows")
        return info
    # Order matters: the game-install probe needs the drive list from the CIM probe.
    for name, probe in (
        ("cim", _probe_cim),
        ("registry", _probe_registry),
        ("power", _probe_power_plan),
        ("nvidia", _probe_nvidia),
        ("game", _probe_game_install),
    ):
        try:
            probe(info)
        except Exception as exc:  # each probe is optional
            info.errors.append(f"{name}: {exc}")
    return info
