"""Hardware facts used for filtering and for the optimizer's hardware-dependent rules.

Sources (all read-only, no admin rights needed, Windows only - every probe
degrades to ``None`` elsewhere or on failure, the optimizer then just skips the
rule that needed it):

* GPU vendor/name  - what the game itself recorded in the settings file
                     (``GPUName@0`` / ``LastUsedGPU@0``)
* VRAM            - display adapter class key in the registry
                     (``HardwareInformation.qwMemorySize``, exact even above 4 GB)
* CPU cores       - ``GetLogicalProcessorInformationEx``: one record per physical
                     core with an ``EfficiencyClass``; on Intel hybrid CPUs (12th gen+)
                     the highest class = performance cores (P-cores)
* CPU name        - ``HKLM\\HARDWARE\\DESCRIPTION\\System\\CentralProcessor\\0``
* refresh rate    - ``EnumDisplaySettingsW`` on the primary display (current + max
                     available at the current resolution)
* RAM             - psutil

Parsing is separated from the Win32 calls (``parse_core_efficiency_classes``,
``pick_adapter``) so the logic is unit-testable with synthetic data.
"""

from __future__ import annotations

import ctypes
import struct
import sys
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass

import psutil

from .document import ConfigDocument

# Checked in order; the first vendor whose keyword appears in the name wins.
_VENDOR_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("nvidia", ("nvidia", "geforce", "rtx", "gtx", "quadro")),
    ("amd", ("amd", "radeon")),
    ("intel", ("intel", " arc", "iris", "uhd graphics")),
)
_GPU_NAME_IDS = ("GPUName@0", "LastUsedGPU@0")

_DISPLAY_CLASS_KEY = (
    r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
)
_CPU_KEY = r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
_RELATION_PROCESSOR_CORE = 0


def gpu_vendor_from_name(name: str) -> str | None:
    """``"NVIDIA GeForce RTX 5090"`` -> ``"nvidia"``; ``None`` when unrecognized."""
    lowered = f" {name.lower()}"
    for vendor, keywords in _VENDOR_KEYWORDS:
        if any(k in lowered for k in keywords):
            return vendor
    return None


def gpu_name_from_document(document: ConfigDocument) -> str | None:
    for setting_id in _GPU_NAME_IDS:
        if setting_id in document:
            name = document.get(setting_id).raw_value.strip()
            if name:
                return name
    return None


def detect_gpu_vendor(document: ConfigDocument) -> str | None:
    """GPU vendor recorded by the game in the settings file, if any."""
    for setting_id in _GPU_NAME_IDS:
        if setting_id in document:
            vendor = gpu_vendor_from_name(document.get(setting_id).raw_value)
            if vendor:
                return vendor
    return None


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HardwareInfo:
    cpu_name: str | None = None
    physical_cores: int | None = None
    logical_cores: int | None = None
    performance_cores: int | None = None  # only set on hybrid CPUs (P-cores + E-cores)
    efficiency_cores: int | None = None
    ram_mb: int | None = None
    gpu_name: str | None = None
    gpu_vendor: str | None = None
    vram_mb: int | None = None
    refresh_hz: int | None = None  # current refresh rate of the primary display
    max_refresh_hz: int | None = None  # highest rate available at the current resolution

    @property
    def is_hybrid(self) -> bool:
        return self.performance_cores is not None

    @property
    def worker_cores(self) -> int | None:
        """Cores the community recommends for ``RendererWorkerCount``: P-cores or physical."""
        return self.performance_cores if self.is_hybrid else self.physical_cores

    @property
    def best_refresh_hz(self) -> int | None:
        return self.max_refresh_hz or self.refresh_hz


# ---------------------------------------------------------------------------
# Pure parsing helpers (tested with synthetic data)
# ---------------------------------------------------------------------------


def parse_core_efficiency_classes(buffer: bytes) -> list[int]:
    """EfficiencyClass of each physical core from a ``GetLogicalProcessorInformationEx`` buffer.

    Record layout: DWORD Relationship, DWORD Size, then for RelationProcessorCore a
    PROCESSOR_RELATIONSHIP whose first two bytes are Flags and EfficiencyClass.
    """
    classes: list[int] = []
    offset = 0
    while offset + 8 <= len(buffer):
        relationship, size = struct.unpack_from("<II", buffer, offset)
        if size <= 0:
            break
        if relationship == _RELATION_PROCESSOR_CORE and offset + 10 <= len(buffer):
            _flags, efficiency = struct.unpack_from("<BB", buffer, offset + 8)
            classes.append(efficiency)
        offset += size
    return classes


def split_core_classes(classes: list[int]) -> tuple[int | None, int | None]:
    """``(performance, efficiency)`` core counts; ``(None, None)`` on non-hybrid CPUs."""
    counts = Counter(classes)
    if len(counts) < 2:
        return None, None
    top = max(counts)
    return counts[top], sum(n for cls, n in counts.items() if cls != top)


def pick_adapter(adapters: list[tuple[str, int]], gpu_name: str | None) -> tuple[str, int] | None:
    """Choose the display adapter the game uses: name match first, else the most VRAM.

    ``adapters`` are ``(driver description, VRAM bytes)`` pairs from the registry.
    """
    usable = [a for a in adapters if a[1] > 0]
    if not usable:
        return None
    if gpu_name:
        wanted = gpu_name.lower()
        for adapter in usable:
            if (
                adapter[0].lower() == wanted
                or adapter[0].lower() in wanted
                or wanted in adapter[0].lower()
            ):
                return adapter
    return max(usable, key=lambda a: a[1])


# ---------------------------------------------------------------------------
# Win32 probes (each returns None on any failure)
# ---------------------------------------------------------------------------


def _safe(probe: Callable[[], object]) -> object | None:
    try:
        return probe()
    except Exception:  # hardware probing must never break the app
        return None


def _core_classes() -> list[int] | None:
    if sys.platform != "win32":
        return None
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    length = wintypes.DWORD(0)
    kernel32.GetLogicalProcessorInformationEx(_RELATION_PROCESSOR_CORE, None, ctypes.byref(length))
    if not length.value:
        return None
    buffer = ctypes.create_string_buffer(length.value)
    if not kernel32.GetLogicalProcessorInformationEx(
        _RELATION_PROCESSOR_CORE, buffer, ctypes.byref(length)
    ):
        return None
    return parse_core_efficiency_classes(buffer.raw[: length.value])


def _cpu_name() -> str | None:
    import winreg

    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _CPU_KEY) as key:
        return str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()


def _display_adapters() -> list[tuple[str, int]]:
    import winreg

    adapters: list[tuple[str, int]] = []
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _DISPLAY_CLASS_KEY) as root:
        index = 0
        while True:
            try:
                sub = winreg.EnumKey(root, index)
            except OSError:
                break
            index += 1
            if not sub.isdigit():
                continue
            try:
                with winreg.OpenKey(root, sub) as key:
                    name = str(winreg.QueryValueEx(key, "DriverDesc")[0])
                    adapters.append((name, _adapter_memory(winreg, key)))
            except OSError:
                continue  # access denied / not an adapter
    return adapters


def _adapter_memory(winreg, key) -> int:  # (winreg module, open key handle)
    # qwMemorySize is exact; the older MemorySize DWORD caps at 4 GB.
    for value_name in ("HardwareInformation.qwMemorySize", "HardwareInformation.MemorySize"):
        try:
            value, _kind = winreg.QueryValueEx(key, value_name)
        except OSError:
            continue
        if isinstance(value, bytes):
            value = int.from_bytes(value[:8], "little")
        if isinstance(value, int) and value > 0:
            return value
    return 0


def _refresh_rates() -> tuple[int | None, int | None]:
    if sys.platform != "win32":
        return None, None
    from ctypes import wintypes

    class DEVMODEW(ctypes.Structure):
        _fields_ = [  # Win32 DEVMODEW layout (display variant of the union)
            ("dmDeviceName", wintypes.WCHAR * 32),
            ("dmSpecVersion", wintypes.WORD),
            ("dmDriverVersion", wintypes.WORD),
            ("dmSize", wintypes.WORD),
            ("dmDriverExtra", wintypes.WORD),
            ("dmFields", wintypes.DWORD),
            ("dmPositionX", wintypes.LONG),
            ("dmPositionY", wintypes.LONG),
            ("dmDisplayOrientation", wintypes.DWORD),
            ("dmDisplayFixedOutput", wintypes.DWORD),
            ("dmColor", ctypes.c_short),
            ("dmDuplex", ctypes.c_short),
            ("dmYResolution", ctypes.c_short),
            ("dmTTOption", ctypes.c_short),
            ("dmCollate", ctypes.c_short),
            ("dmFormName", wintypes.WCHAR * 32),
            ("dmLogPixels", wintypes.WORD),
            ("dmBitsPerPel", wintypes.DWORD),
            ("dmPelsWidth", wintypes.DWORD),
            ("dmPelsHeight", wintypes.DWORD),
            ("dmDisplayFlags", wintypes.DWORD),
            ("dmDisplayFrequency", wintypes.DWORD),
            ("dmICMMethod", wintypes.DWORD),
            ("dmICMIntent", wintypes.DWORD),
            ("dmMediaType", wintypes.DWORD),
            ("dmDitherType", wintypes.DWORD),
            ("dmReserved1", wintypes.DWORD),
            ("dmReserved2", wintypes.DWORD),
            ("dmPanningWidth", wintypes.DWORD),
            ("dmPanningHeight", wintypes.DWORD),
        ]

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    current = DEVMODEW()
    current.dmSize = ctypes.sizeof(DEVMODEW)
    if not user32.EnumDisplaySettingsW(None, -1, ctypes.byref(current)):  # ENUM_CURRENT_SETTINGS
        return None, None
    best = current.dmDisplayFrequency
    mode = DEVMODEW()
    mode.dmSize = ctypes.sizeof(DEVMODEW)
    index = 0
    while user32.EnumDisplaySettingsW(None, index, ctypes.byref(mode)):
        same_size = (mode.dmPelsWidth, mode.dmPelsHeight) == (
            current.dmPelsWidth,
            current.dmPelsHeight,
        )
        if same_size and mode.dmDisplayFrequency > best:
            best = mode.dmDisplayFrequency
        index += 1
    # 0 and 1 mean "hardware default" in DEVMODE - not a real rate.
    current_hz = current.dmDisplayFrequency if current.dmDisplayFrequency > 1 else None
    return current_hz, (best if best > 1 else None)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def detect_hardware(document: ConfigDocument | None = None) -> HardwareInfo:
    """Probe this PC. Never raises; unknown facts are ``None``."""
    gpu_name = gpu_name_from_document(document) if document is not None else None
    classes = _safe(_core_classes)
    performance, efficiency = split_core_classes(classes) if classes else (None, None)
    adapters = _safe(_display_adapters) or []
    adapter = pick_adapter(adapters, gpu_name)  # type: ignore[arg-type]
    if gpu_name is None and adapter is not None:
        gpu_name = adapter[0]
    rates = _safe(_refresh_rates) or (None, None)
    memory = _safe(lambda: psutil.virtual_memory().total)
    return HardwareInfo(
        cpu_name=_safe(_cpu_name),  # type: ignore[arg-type]
        physical_cores=_safe(lambda: psutil.cpu_count(logical=False))
        or (len(classes) if classes else None),  # type: ignore[arg-type]
        logical_cores=_safe(lambda: psutil.cpu_count(logical=True)),  # type: ignore[arg-type]
        performance_cores=performance,
        efficiency_cores=efficiency,
        ram_mb=int(memory) // (1024 * 1024) if memory else None,  # type: ignore[arg-type]
        gpu_name=gpu_name,
        gpu_vendor=gpu_vendor_from_name(gpu_name) if gpu_name else None,
        vram_mb=adapter[1] // (1024 * 1024) if adapter else None,
        refresh_hz=rates[0],  # type: ignore[index]
        max_refresh_hz=rates[1],  # type: ignore[index]
    )
