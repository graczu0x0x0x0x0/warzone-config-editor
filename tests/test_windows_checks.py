"""Windows-settings checks (stage 10b): rules per PC / CPU, texts for every outcome."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from test_system import NVIDIA_CSV, _info
from wzce.core.i18n import Translator
from wzce.core.system_checks import CheckResult, Severity, Status, evaluate_checks
from wzce.core.system_info import SystemInfo, parse_nvidia_csv
from wzce.core.windows_checks import (
    CHECKS,
    MYTHS,
    Section,
    evaluate_windows_checks,
    tpm_firmware_bad,
)
from wzce.core.windows_info import (
    AntivirusProduct,
    BackgroundApp,
    NetworkLink,
    PageFile,
    apply_windows_cim,
)
from wzce.ui.system_panel import check_text, check_title

FIXTURE = Path(__file__).parent / "fixtures" / "windows_cim.json"
X3D_DUAL = "AMD Ryzen 9 9950X3D 16-Core Processor"
INTEL_14 = "Intel(R) Core(TM) i9-14900K"
ARROW_LAKE = "Intel(R) Core(TM) Ultra 9 285K"


def _users_pc() -> SystemInfo:
    """The author's PC as read on 2026-10-17 (9800X3D, RTX 5090, 25H2)."""
    info = _info()
    win = info.windows
    apply_windows_cim(win, json.loads(FIXTURE.read_text(encoding="utf-8")))
    info.vbs_running, info.hvci_running = False, False
    win.build, win.ubr, win.reboot_pending = 26200, 9711, False
    info.os_display_version = "25H2"
    win.firmware_uefi, win.secure_boot, win.secure_boot_ca2023 = True, True, "Updated"
    win.tpm_version, win.tpm_manufacturer, win.tpm_firmware = "2.0", "AMD", "6.32.0.6"
    win.uac_enabled, win.uac_never_notify, win.driver_blocklist = True, False, True
    win.auto_hdr, win.vrr_optimizations, win.mpo_disabled = True, True, True
    win.game_gpu_preference, win.game_fso_disabled = 0, True
    win.game_dvr_enabled, win.game_bar_installed = True, True
    win.power_overlay, win.amd_vcache_service = None, "stopped"
    win.processor_min_percent, win.processor_max_percent, win.core_parking_min_cores = 0, 100, 100
    win.system_drive, win.system_free_gb, win.trim_enabled = "C", 65.6, True
    win.mouse_acceleration = False
    win.background_apps = [
        BackgroundApp("afterburner", "monitoring"),
        BackgroundApp("discord", "overlay"),
        BackgroundApp("nvidia_overlay", "overlay"),
        BackgroundApp("rtss", "overlay"),
        BackgroundApp("steam", "overlay"),
        BackgroundApp("logitech_ghub", "peripherals"),
    ]
    return info


def _by_id(results: list[CheckResult]) -> dict[str, CheckResult]:
    return {r.id: r for r in results}


def _state(result: CheckResult | None):
    return None if result is None else (result.status, result.severity, result.variant)


# ------------------------------------------------------------ whole PCs


def test_users_pc_has_only_information() -> None:
    by_id = _by_id(evaluate_windows_checks(_users_pc()))
    assert not [r.id for r in by_id.values() if r.status is Status.WARN]
    assert {r.id for r in by_id.values() if r.status is Status.INFO} == {
        "virtualization", "auto_hdr", "mpo", "fso", "processor_state", "overlays",
        "gpu_preference",  # the fixture PC has a Radeon iGPU and no preference for cod.exe
    }  # fmt: skip
    assert by_id["virtualization"].variant == "no_svm"
    assert by_id["virtualization"].params == {"features": "Virtual Machine Platform, WSL"}
    assert by_id["processor_state"].variant == "min"
    assert by_id["overlays"].params["count"] == 4
    assert by_id["tpm"].params["device"] == "AMD fTPM"
    assert by_id["antivirus"].variant == "third_party"
    assert by_id["windows_version"].params == {"version": "25H2", "build": "26200.9711"}
    # Single-CCD X3D on a performance plan: nothing to say about CCD steering.
    assert by_id["power_plan"].status is Status.OK and by_id["power_plan"].variant is None
    for absent in ("x3d_driver", "core_parking", "intel_microcode", "nvidia_hotfix",
                   "input_remap", "winring0", "reboot_pending", "trim"):  # fmt: skip
        assert absent not in by_id, absent


def test_problem_pc() -> None:
    info = _users_pc()
    info.cpu_name, info.cpu_cores = "AMD Ryzen 7 7700X 8-Core Processor", 8
    info.power_plan = "balanced"
    win = info.windows
    win.build, win.ubr = 22621, 4000
    win.firmware_uefi, win.secure_boot, win.system_disk_gpt = False, False, False
    win.tpm_version, win.uac_never_notify = "", True
    win.background_apps = [BackgroundApp("rewasd", "input_remap")]
    win.antivirus, win.defender_realtime = [], False
    win.driver_blocklist, win.winring0_drivers = False, ["WinRing0x64"]
    win.game_bar_installed, win.reboot_pending = False, True
    win.pagefile_auto, win.pagefiles = False, []
    win.system_free_gb, win.trim_enabled, win.mouse_acceleration = 12.0, False, True
    win.network = [NetworkLink("Wi-Fi 7", "wifi", 2400)]
    win.processor_max_percent = 80
    by_id = _by_id(evaluate_windows_checks(info))

    expected = {
        "secure_boot": (Status.WARN, Severity.HIGH, None),
        "boot_mode": (Status.WARN, Severity.HIGH, "legacy"),  # legacy wins over MBR
        "tpm": (Status.WARN, Severity.HIGH, "missing"),
        "uac": (Status.WARN, Severity.MEDIUM, None),
        "input_remap": (Status.WARN, Severity.HIGH, None),
        "antivirus": (Status.WARN, Severity.HIGH, "none"),
        "driver_blocklist": (Status.WARN, Severity.LOW, None),
        "winring0": (Status.WARN, Severity.MEDIUM, None),
        "game_bar": (Status.WARN, Severity.LOW, None),
        "power_plan": (Status.WARN, Severity.LOW, "mode"),
        "processor_state": (Status.WARN, Severity.MEDIUM, "max"),
        "windows_version": (Status.WARN, Severity.MEDIUM, "amd"),
        "reboot_pending": (Status.WARN, Severity.LOW, None),
        "pagefile": (Status.WARN, Severity.HIGH, "off"),
        "system_drive_space": (Status.WARN, Severity.MEDIUM, None),
        "trim": (Status.WARN, Severity.LOW, None),
        "mouse_acceleration": (Status.WARN, Severity.LOW, None),
        "network": (Status.WARN, Severity.LOW, "wifi"),
    }
    for check_id, state in expected.items():
        assert _state(by_id.get(check_id)) == state, check_id
    assert "secure_boot_certs" not in by_id  # nothing to update with Secure Boot off
    assert by_id["input_remap"].params == {"apps": "reWASD"}


def test_empty_probe_gives_unknowns_not_errors() -> None:
    results = evaluate_windows_checks(SystemInfo())
    assert results and all(r.status in (Status.UNKNOWN, Status.OK) for r in results)


def test_merged_into_system_checks_without_duplicates() -> None:
    results = evaluate_checks(_users_pc())
    ids = [r.id for r in results]
    assert len(ids) == len(set(ids))
    assert {"expo", "secure_boot", "power_plan", "hvci"} <= set(ids)
    assert ids.index("virtualization") < ids.index("secure_boot")  # INFO sorts before OK


# ------------------------------------------------------------- CPU rules


def _dual_x3d(plan: str = "balanced") -> SystemInfo:
    info = _users_pc()
    info.cpu_name, info.cpu_cores, info.power_plan = X3D_DUAL, 16, plan
    info.windows.amd_vcache_service = "running"
    info.windows.core_parking_min_cores = 10
    return info


def test_dual_ccd_x3d_rules() -> None:
    by_id = _by_id(evaluate_windows_checks(_dual_x3d()))
    assert _state(by_id["power_plan"]) == (Status.OK, None, "x3d")
    assert _state(by_id["x3d_driver"]) == (Status.OK, None, None)
    assert "core_parking" not in by_id

    info = _dual_x3d("high_performance")
    info.windows.amd_vcache_service = None
    info.windows.core_parking_min_cores = 100
    info.windows.game_bar_installed = False
    by_id = _by_id(evaluate_windows_checks(info))
    assert _state(by_id["power_plan"]) == (Status.WARN, Severity.MEDIUM, "x3d")
    assert _state(by_id["x3d_driver"]) == (Status.WARN, Severity.HIGH, "missing")
    assert _state(by_id["core_parking"]) == (Status.WARN, Severity.MEDIUM, None)
    assert _state(by_id["game_bar"]) == (Status.WARN, Severity.HIGH, "x3d")

    info.windows.amd_vcache_service = "stopped"
    assert _state(_by_id(evaluate_windows_checks(info))["x3d_driver"])[2] == "stopped"


@pytest.mark.parametrize(
    ("plan", "overlay", "state"),
    [
        ("balanced", "best_performance", (Status.OK, None, "mode")),
        ("balanced", "balanced", (Status.WARN, Severity.LOW, "mode")),
        ("power_saver", None, (Status.WARN, Severity.LOW, None)),
        ("ultimate", None, (Status.OK, None, None)),
        ("custom", None, (Status.OK, None, None)),  # e.g. Bitsum Highest Performance
        (None, None, (Status.UNKNOWN, None, None)),
    ],
)
def test_power_plan_on_other_cpus(plan, overlay, state) -> None:
    info = _users_pc()
    info.power_plan, info.windows.power_overlay = plan, overlay
    assert _state(_by_id(evaluate_windows_checks(info))["power_plan"]) == state


@pytest.mark.parametrize(
    ("cpu", "revision", "state"),
    [
        (INTEL_14, 0x129, (Status.WARN, Severity.HIGH, None)),
        (INTEL_14, 0x12B, (Status.OK, None, None)),
        ("Intel(R) Core(TM) i7-13700K", None, (Status.UNKNOWN, None, None)),
        ("Intel(R) Core(TM) i7-12700K", 0x10, None),  # Alder Lake: not affected
        (ARROW_LAKE, 0x10, None),
    ],
)
def test_intel_microcode(cpu, revision, state) -> None:
    info = _users_pc()
    info.cpu_name, info.windows.microcode_revision = cpu, revision
    assert _state(_by_id(evaluate_windows_checks(info)).get("intel_microcode")) == state


@pytest.mark.parametrize(
    ("cpu", "build", "ubr", "variant"),
    [
        ("AMD Ryzen 7 9800X3D 8-Core Processor", 22631, 4000, "amd"),
        ("AMD Ryzen 7 9800X3D 8-Core Processor", 22631, 4112, None),  # KB5041587
        ("AMD Ryzen 5 5600X 6-Core Processor", 26100, 1000, None),
        ("AMD Ryzen 5 3600 6-Core Processor", 22621, 1000, None),  # Zen 2: no fix needed
        (ARROW_LAKE, 26100, 2000, "arrow_lake"),
        (ARROW_LAKE, 26200, 9711, None),
        (INTEL_14, 19045, 5000, "win10"),
    ],
)
def test_windows_version_rules(cpu, build, ubr, variant) -> None:
    info = _users_pc()
    info.cpu_name, info.windows.build, info.windows.ubr = cpu, build, ubr
    result = _by_id(evaluate_windows_checks(info))["windows_version"]
    assert result.variant == variant
    assert result.status is (Status.OK if variant is None else Status.WARN)


@pytest.mark.parametrize(
    ("build", "ubr", "driver", "warn"),
    [
        (26100, 6899, "580.88", True),
        (26200, 9711, "581.80", True),
        (26200, 9711, "581.94", False),
        (26100, 6000, "580.88", False),  # before the regression
        (22631, 9000, "580.88", False),
    ],
)
def test_nvidia_hotfix(build, ubr, driver, warn) -> None:
    info = _users_pc()
    info.windows.build, info.windows.ubr = build, ubr
    info.nvidia = parse_nvidia_csv(NVIDIA_CSV.replace("617.42", driver), 32768)
    assert ("nvidia_hotfix" in _by_id(evaluate_windows_checks(info))) is warn


# ------------------------------------------------------ individual rules


@pytest.mark.parametrize(
    ("manufacturer", "firmware", "bad"),
    [
        ("AMD", "3.92.0.5", True),
        ("AMD", "3.92.5.5", False),
        ("AMD", "6.32.0.6", False),
        ("INTC", "302.12.0.1", True),
        ("INTC", "600.18.0.0", False),
        ("MSFT", "3.1.0.1", False),
        (None, None, False),
    ],
)
def test_tpm_firmware_known_bad(manufacturer, firmware, bad) -> None:
    assert tpm_firmware_bad(manufacturer, firmware) is bad


def test_tpm_firmware_warning() -> None:
    info = _users_pc()
    info.windows.tpm_firmware = "3.92.0.5"
    assert _state(_by_id(evaluate_windows_checks(info))["tpm"]) == (
        Status.WARN, Severity.HIGH, "firmware",
    )  # fmt: skip


def test_antivirus_variants() -> None:
    info = _users_pc()
    win = info.windows
    win.antivirus = [AntivirusProduct("Windows Defender", True, True)]
    assert _state(_by_id(evaluate_windows_checks(info))["antivirus"]) == (Status.OK, None, None)
    win.antivirus = [AntivirusProduct("Windows Defender", True, False)]
    assert _by_id(evaluate_windows_checks(info))["antivirus"].variant == "outdated"


@pytest.mark.parametrize(
    ("auto", "files", "state"),
    [
        (True, [], (Status.OK, None, "auto")),
        (False, [PageFile(r"C:\pagefile.sys", 4096)], (Status.WARN, Severity.MEDIUM, "small")),
        (False, [PageFile(r"C:\pagefile.sys", 131072)], (Status.OK, None, None)),
        (None, [], (Status.UNKNOWN, None, None)),
    ],
)
def test_pagefile(auto, files, state) -> None:
    info = _users_pc()
    info.windows.pagefile_auto, info.windows.pagefiles = auto, files
    assert _state(_by_id(evaluate_windows_checks(info))["pagefile"]) == state


def test_virtualization_variants() -> None:
    info = _users_pc()
    win = info.windows
    win.hypervisor_present, win.virtualization_firmware = True, False
    assert _by_id(evaluate_windows_checks(info))["virtualization"].variant == "features"
    win.vm_features = {}
    assert _state(_by_id(evaluate_windows_checks(info))["virtualization"]) == (
        Status.OK, None, "vbs",
    )  # fmt: skip


def test_gpu_preference_only_with_integrated_graphics() -> None:
    info = _users_pc()  # RTX 5090 + Radeon iGPU
    info.windows.game_gpu_preference = 1
    assert _state(_by_id(evaluate_windows_checks(info))["gpu_preference"]) == (
        Status.WARN, Severity.HIGH, "power_saving",
    )  # fmt: skip
    info.windows.game_gpu_preference = 2
    assert _by_id(evaluate_windows_checks(info))["gpu_preference"].status is Status.OK
    info.gpus = info.gpus[:1]
    assert "gpu_preference" not in _by_id(evaluate_windows_checks(info))


# ---------------------------------------------------------------- texts


def _all_outcomes() -> list[CheckResult]:
    """Results of every scenario in this file, to check that each has texts."""
    infos = [_users_pc(), SystemInfo(), _dual_x3d(), _dual_x3d("high_performance")]
    bad = _users_pc()
    bad.cpu_name = INTEL_14
    bad.windows.microcode_revision = 0x100
    bad.windows.tpm_firmware = "3.92.0.5"
    bad.windows.secure_boot_ca2023 = "InProgress"
    infos.append(bad)
    results = [r for info in infos for r in evaluate_windows_checks(info)]
    variants = {
        "boot_mode": ["legacy", "mbr"],
        "tpm": ["missing", "old", "firmware"],
        "virtualization": ["no_svm", "features"],
        "antivirus": ["none", "outdated"],
        "gpu_preference": ["power_saving"],
        "game_bar": ["x3d"],
        "power_plan": ["mode", "x3d"],
        "processor_state": ["max", "min"],
        "x3d_driver": ["missing", "stopped"],
        "windows_version": ["win10", "amd", "arrow_lake"],
        "pagefile": ["off", "small"],
        "network": ["wifi"],
    }
    for check_id, names in variants.items():
        results += [CheckResult(check_id, Status.WARN, variant=v) for v in names]
    plain_problems = [
        "secure_boot", "uac", "secure_boot_certs", "input_remap", "hvci", "driver_blocklist",
        "winring0", "hags", "gpu_preference", "auto_hdr", "mpo", "fso", "game_mode",
        "recording", "game_bar", "power_plan", "core_parking", "intel_microcode",
        "nvidia_hotfix", "reboot_pending", "system_drive_space", "trim", "overlays",
        "mouse_acceleration",
    ]  # fmt: skip
    results += [CheckResult(i, Status.WARN) for i in plain_problems]
    oks = {"virtualization": ["vbs"], "antivirus": ["third_party"], "pagefile": ["auto"],
           "power_plan": ["mode", "x3d"]}  # fmt: skip
    results += [CheckResult(i, Status.OK) for i in CHECKS]
    results += [CheckResult(i, Status.OK, variant=v) for i, vs in oks.items() for v in vs]
    return results


@pytest.mark.parametrize("lang", ["en", "pl"])
def test_every_outcome_has_texts(lang) -> None:
    tr = Translator(lang)
    for result in _all_outcomes():
        title, text = check_title(result, tr), check_text(result, tr)
        fix = tr(f"checks.{result.id}.fix")
        for value in (title, text, fix):
            assert not value.startswith("checks."), (lang, result.id, result.variant, value)
    for myth in MYTHS:
        for part in ("title", "why"):
            assert not tr(f"myths.{myth}.{part}").startswith("myths."), (lang, myth)


def test_every_check_has_a_section() -> None:
    assert {section for section, _impact in CHECKS.values()} == set(Section)
    produced = {r.id for r in _all_outcomes()}
    assert produced <= set(CHECKS)


def test_params_fill_every_placeholder() -> None:
    tr = Translator("pl")
    for result in evaluate_windows_checks(_users_pc()):
        assert "{" not in check_text(result, tr), result.id
    info = _users_pc()
    info.windows.background_apps = [BackgroundApp("rewasd", "input_remap")]
    remap = _by_id(evaluate_windows_checks(info))["input_remap"]
    assert "reWASD" in check_text(remap, tr)
