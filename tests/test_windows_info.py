"""Windows settings probe (stage 10a): parsers and derived facts on fixture data, no OS calls."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from wzce.core.system_info import SystemInfo, apply_cim_json
from wzce.core.windows_info import (
    BALANCED_SCHEME,
    AntivirusProduct,
    BackgroundApp,
    NetworkLink,
    PageFile,
    WindowsInfo,
    apply_windows_cim,
    decode_av_state,
    decode_tpm_manufacturer,
    dx_flag,
    effective_overlay,
    find_game_value,
    has_compat_flag,
    match_background_apps,
    network_kind,
    parse_dx_settings,
    parse_fsutil_trim,
    parse_gpu_preference,
    parse_microcode,
    parse_partition_style,
    parse_smart_app_control,
    probe_native,
    probe_processes,
    probe_registry,
    probe_storage,
)

FIXTURE = Path(__file__).parent / "fixtures" / "windows_cim.json"
GAME_EXE = r"G:\SteamLibrary\steamapps\common\Call of Duty HQ\cod.exe"


def _win() -> WindowsInfo:
    win = WindowsInfo()
    apply_windows_cim(win, json.loads(FIXTURE.read_text(encoding="utf-8")))
    return win


# ------------------------------------------------------------------- CIM


def test_cim_section_on_the_users_pc() -> None:
    win = _win()
    assert win.hypervisor_present is False and win.virtualization_firmware is False
    assert win.svm_disabled_in_firmware is True
    assert win.vbs_status == 1 and win.vbs_services_running == [] and win.hvci_running is False
    assert win.enabled_vm_features == [
        "VirtualMachinePlatform",
        "Microsoft-Windows-Subsystem-Linux",
    ]
    assert win.antivirus == [
        AntivirusProduct("Norton 360", enabled=True, up_to_date=True),
        AntivirusProduct("Windows Defender", enabled=False, up_to_date=True),  # passive
    ]
    assert [av.name for av in win.third_party_antivirus] == ["Norton 360"]
    assert (win.defender_realtime, win.defender_mode) == (False, "Passive Mode")
    assert win.pagefile_auto is False
    assert win.pagefiles == [PageFile(r"C:\pagefile.sys", 131072)]  # single object, not a list
    assert win.system_disk_gpt is True
    # The disconnected Wi-Fi card is ignored.
    assert win.network == [NetworkLink("Realtek PCIe 2.5GbE Family Controller", "ethernet", 1000)]
    assert win.wired_network is True


def test_cim_json_feeds_system_info() -> None:
    info = SystemInfo()
    apply_cim_json(info, json.loads(FIXTURE.read_text(encoding="utf-8")))
    assert info.windows.system_disk_gpt is True
    assert info.cpu_name.startswith("AMD Ryzen 7 9800X3D")


def test_missing_sections_mean_unknown() -> None:
    win = WindowsInfo()
    apply_windows_cim(win, {})
    assert win.hypervisor_present is None and win.svm_disabled_in_firmware is None
    assert win.hvci_running is None and win.system_disk_gpt is None
    assert win.antivirus == [] and win.network == [] and win.wired_network is None
    assert SystemInfo().windows == WindowsInfo()  # always present, empty by default


@pytest.mark.parametrize(
    ("hypervisor", "firmware", "disabled"),
    [
        (False, False, True),  # nothing runs and the flag is off: SVM/VT-x off in BIOS
        (False, True, False),
        (True, False, False),  # Windows hides the flag while its hypervisor runs
        (None, False, None),
    ],
)
def test_svm_disabled_in_firmware(hypervisor, firmware, disabled) -> None:
    win = WindowsInfo(hypervisor_present=hypervisor, virtualization_firmware=firmware)
    assert win.svm_disabled_in_firmware is disabled


def test_hvci_running_from_security_services() -> None:
    assert WindowsInfo(vbs_status=2, vbs_services_running=[2]).hvci_running is True
    assert WindowsInfo(vbs_status=2, vbs_services_running=[1]).hvci_running is False


@pytest.mark.parametrize(
    ("value", "gpt"),
    [("GPT", True), ("MBR", False), (2, True), (1, False), (0, None), ("RAW", None), (None, None)],
)
def test_parse_partition_style(value, gpt) -> None:
    assert parse_partition_style(value) is gpt


@pytest.mark.parametrize(
    ("state", "decoded"),
    [
        (266240, (True, True)),  # 0x041000 Norton: on, current
        (393472, (False, True)),  # 0x060100 Defender in passive mode
        (0x041010, (True, False)),  # definitions out of date
        (397568, (True, True)),  # 0x061100 Defender active
        ("x", None),
    ],
)
def test_decode_av_state(state, decoded) -> None:
    assert decode_av_state(state) == decoded


@pytest.mark.parametrize(
    ("medium", "kind"), [(14, "ethernet"), (9, "wifi"), (1, "wifi"), (8, "mobile"), (0, "other")]
)
def test_network_kind(medium, kind) -> None:
    assert network_kind(medium) == kind


# -------------------------------------------------------------- registry


def test_dx_settings_and_defaults() -> None:
    settings = parse_dx_settings("SwapEffectUpgradeEnable=1;AutoHDREnable=1;")
    assert settings == {"SwapEffectUpgradeEnable": "1", "AutoHDREnable": "1"}
    assert dx_flag(settings, "AutoHDREnable", default=False) is True
    assert dx_flag(settings, "VRROptimizeEnable", default=True) is True  # absent = default
    assert dx_flag({"VRROptimizeEnable": "0"}, "VRROptimizeEnable", default=True) is False
    assert parse_dx_settings(None) == {} and parse_dx_settings("garbage;=1;") == {}


def test_game_gpu_preference_and_fso_flag() -> None:
    gpu_values = {
        "DirectXUserGlobalSettings": "SwapEffectUpgradeEnable=1;",
        r"C:\Games\other.exe": "GpuPreference=1;",
        GAME_EXE: "AppStatus=4096;",
    }
    assert find_game_value(gpu_values) == "AppStatus=4096;"
    assert parse_gpu_preference(find_game_value(gpu_values)) == 0  # no preference = Windows
    assert parse_gpu_preference("AppStatus=4096;GpuPreference=2;") == 2
    assert parse_gpu_preference(None) == 0
    assert parse_gpu_preference("GpuPreference=x;") is None
    assert find_game_value({r"C:\x\notcod.exe": "1"}) is None

    layers = {GAME_EXE.upper(): "~ DISABLEDXMAXIMIZEDWINDOWEDMODE "}  # paths compare case-blind
    assert has_compat_flag(find_game_value(layers), "DISABLEDXMAXIMIZEDWINDOWEDMODE")
    assert not has_compat_flag("~ RUNASADMIN", "DISABLEDXMAXIMIZEDWINDOWEDMODE")
    assert not has_compat_flag(None, "DISABLEDXMAXIMIZEDWINDOWEDMODE")


@pytest.mark.parametrize(
    ("value", "name"),
    [(0x414D4400, "AMD"), (0x494E5443, "INTC"), (0x4D534654, "MSFT"), (0, None), (None, None)],
)
def test_decode_tpm_manufacturer(value, name) -> None:
    assert decode_tpm_manufacturer(value) == name


def test_parse_microcode() -> None:
    assert parse_microcode(b"5@@\x0b", "AuthenticAMD") == 0x0B404035  # the user's 9800X3D
    intel = (0).to_bytes(4, "little") + (0x12B).to_bytes(4, "little")
    assert parse_microcode(intel, "GenuineIntel") == 0x12B
    assert parse_microcode(b"\x00\x00", "AuthenticAMD") is None
    assert parse_microcode(None, None) is None


def test_smart_app_control_and_power_overlay() -> None:
    assert [parse_smart_app_control(v) for v in (0, 1, 2, 7, None)] == [
        "off", "on", "evaluation", None, None,
    ]  # fmt: skip
    zero = "00000000-0000-0000-0000-000000000000"
    assert effective_overlay(BALANCED_SCHEME, zero) == "balanced"
    assert (
        effective_overlay(BALANCED_SCHEME.upper(), "DED574B5-45A0-4F42-8737-46345C09C238")
        == "best_performance"
    )
    assert effective_overlay(BALANCED_SCHEME, "11111111-2222-3333-4444-555555555555") == "custom"
    # High performance plan: Windows still answers with zeros, but no overlay applies.
    assert effective_overlay("8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c", zero) is None


# ------------------------------------------------------- other probes


def test_parse_fsutil_trim() -> None:
    on = "NTFS DisableDeleteNotify = 0  (Allows TRIM operations to be sent to the storage device)"
    assert parse_fsutil_trim(on + "\nReFS DisableDeleteNotify = 0") is True
    assert parse_fsutil_trim("NTFS DisableDeleteNotify = 1  (Disallows TRIM)") is False
    assert parse_fsutil_trim("Access is denied.") is None


def test_match_background_apps() -> None:
    names = ["Discord.exe", "Discord.exe", "RTSS.exe", "lghub_agent.exe", "explorer.exe",
             "reWASDEngine.exe", "reWASDService.exe"]  # fmt: skip
    assert match_background_apps(names) == [
        BackgroundApp("rewasd", "input_remap"),
        BackgroundApp("discord", "overlay"),
        BackgroundApp("rtss", "overlay"),
        BackgroundApp("logitech_ghub", "peripherals"),
    ]
    assert match_background_apps([]) == []


def test_build_text() -> None:
    assert WindowsInfo(build=26200, ubr=9711).build_text == "26200.9711"
    assert WindowsInfo(build=26100).build_text == "26100"
    assert WindowsInfo().build_text is None


@pytest.mark.skipif(sys.platform != "win32", reason="Windows APIs")
def test_live_probes_do_not_raise() -> None:
    """Read-only probes on the test machine: types only, values depend on the PC."""
    win = WindowsInfo()
    for probe in (probe_registry, probe_native, probe_processes, probe_storage):
        probe(win)
    assert isinstance(win.build, int) and win.build >= 10240
    assert win.firmware_uefi in (True, False, None)
    assert win.tpm_version in ("2.0", "1.2", "", None)
    assert isinstance(win.background_apps, list)
