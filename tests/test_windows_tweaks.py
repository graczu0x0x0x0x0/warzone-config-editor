"""Reversible Windows tweaks (stage 10d) on an in-memory backend - never the real registry."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from test_windows_checks import _users_pc
from wzce.core.check_types import CheckResult, Status
from wzce.core.errors import GameRunningError
from wzce.core.windows_info import BALANCED_SCHEME
from wzce.core.windows_tweaks import (
    BEST_PERFORMANCE_OVERLAY,
    DX_GLOBAL,
    DX_KEY,
    GAME_BAR_KEY,
    GAME_DVR_KEY,
    LAYERS_KEY,
    REG_DWORD,
    REG_SZ,
    TweakError,
    WindowsBackend,
    WindowsTweaks,
    set_compat_flag,
    set_dx_pair,
    tweak_for,
)

GAME_EXE = r"G:\SteamLibrary\steamapps\common\Call of Duty HQ\cod.exe"
HIGH_PERFORMANCE = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
ZERO = "00000000-0000-0000-0000-000000000000"


class FakeBackend:
    """Registry + mouse + power state in dictionaries, shaped like the author's PC."""

    def __init__(self) -> None:
        self.reg: dict[tuple[str, str, str], tuple[object, int]] = {
            ("HKCU", DX_KEY, DX_GLOBAL): ("SwapEffectUpgradeEnable=1;AutoHDREnable=1;", REG_SZ),
            ("HKCU", DX_KEY, GAME_EXE): ("AppStatus=4096;", REG_SZ),
            ("HKCU", LAYERS_KEY, GAME_EXE): ("~ DISABLEDXMAXIMIZEDWINDOWEDMODE ", REG_SZ),
            ("HKCU", GAME_DVR_KEY, "HistoricalCaptureEnabled"): (1, REG_DWORD),
        }
        self.mouse = [6, 10, 1]
        self.scheme, self.overlay = HIGH_PERFORMANCE, ZERO
        self.refuse_overlay = False
        self.calls: list[str] = []

    def reg_get(self, hive, path, name):
        return self.reg.get((hive, path, name))

    def reg_set(self, hive, path, name, value, kind):
        assert hive == "HKCU"
        self.calls.append(f"set {name}")
        self.reg[(hive, path, name)] = (value, kind)

    def reg_delete(self, hive, path, name):
        assert hive == "HKCU"
        self.calls.append(f"delete {name}")
        self.reg.pop((hive, path, name), None)

    def reg_names(self, hive, path):
        return [name for (h, p, name) in self.reg if (h, p) == (hive, path)]

    def mouse_get(self):
        return list(self.mouse)

    def mouse_set(self, values):
        self.mouse = list(values)

    def scheme_get(self):
        return self.scheme

    def scheme_set(self, guid):
        self.scheme = guid
        self.overlay = ZERO  # Windows resets the power mode with the plan

    def overlay_get(self):
        return self.overlay if self.scheme == BALANCED_SCHEME else ZERO

    def overlay_set(self, guid):
        if self.refuse_overlay:
            raise TweakError("Windows refused to change the power mode (error 5)")
        self.overlay = guid


@pytest.fixture
def backend() -> FakeBackend:
    return FakeBackend()


@pytest.fixture
def engine(backend: FakeBackend, tmp_path: Path) -> WindowsTweaks:
    return WindowsTweaks(backend, tmp_path / "windows" / "tweaks.json", game_running=lambda: False)


def _value(backend: FakeBackend, path: str, name: str):
    got = backend.reg.get(("HKCU", path, name))
    return None if got is None else got[0]


# --------------------------------------------------------------- helpers


@pytest.mark.parametrize(
    ("text", "key", "value", "result"),
    [
        ("SwapEffectUpgradeEnable=1;AutoHDREnable=1;", "AutoHDREnable", "0",
         "SwapEffectUpgradeEnable=1;AutoHDREnable=0;"),
        ("AppStatus=4096;", "GpuPreference", "2", "AppStatus=4096;GpuPreference=2;"),
        ("AppStatus=4096;GpuPreference=2;", "GpuPreference", None, "AppStatus=4096;"),
        ("", "GpuPreference", "2", "GpuPreference=2;"),
        ("GpuPreference=2;", "GpuPreference", None, ""),
    ],
)  # fmt: skip
def test_set_dx_pair(text, key, value, result) -> None:
    assert set_dx_pair(text, key, value) == result


@pytest.mark.parametrize(
    ("text", "present", "result"),
    [
        ("~ DISABLEDXMAXIMIZEDWINDOWEDMODE ", False, ""),
        ("~ RUNASADMIN DISABLEDXMAXIMIZEDWINDOWEDMODE", False, "~ RUNASADMIN "),
        ("", True, "~ DISABLEDXMAXIMIZEDWINDOWEDMODE "),
        ("~ RUNASADMIN ", True, "~ RUNASADMIN DISABLEDXMAXIMIZEDWINDOWEDMODE "),
    ],
)
def test_set_compat_flag(text, present, result) -> None:
    assert set_compat_flag(text, "DISABLEDXMAXIMIZEDWINDOWEDMODE", present) == result


# ------------------------------------------------------- apply / restore


def test_dword_tweak_and_restore_of_an_absent_value(engine, backend) -> None:
    entry = engine.apply("game_mode_on", _users_pc())
    assert _value(backend, GAME_BAR_KEY, "AutoGameModeEnabled") == 1
    assert entry.before == [None] and entry.after == [1]
    assert [e.id for e in engine.entries()] == [entry.id]
    engine.restore(entry.id)
    assert _value(backend, GAME_BAR_KEY, "AutoGameModeEnabled") is None  # deleted again
    assert engine.entries() == []


def test_recording_off_restores_previous_value(engine, backend) -> None:
    entry = engine.apply("recording_off", _users_pc())
    assert _value(backend, GAME_DVR_KEY, "HistoricalCaptureEnabled") == 0
    engine.restore(entry.id)
    assert _value(backend, GAME_DVR_KEY, "HistoricalCaptureEnabled") == 1


def test_dx_tweaks_touch_only_their_own_pair(engine, backend) -> None:
    info = _users_pc()
    hdr = engine.apply("auto_hdr_off", info)
    gpu = engine.apply("gpu_high_performance", info)
    assert _value(backend, DX_KEY, DX_GLOBAL) == "SwapEffectUpgradeEnable=1;AutoHDREnable=0;"
    assert _value(backend, DX_KEY, GAME_EXE) == "AppStatus=4096;GpuPreference=2;"
    # Meanwhile the user turns VRR optimizations off in Settings; restoring Auto HDR keeps it.
    backend.reg[("HKCU", DX_KEY, DX_GLOBAL)] = (
        "SwapEffectUpgradeEnable=1;AutoHDREnable=0;VRROptimizeEnable=0;",
        REG_SZ,
    )
    engine.restore(hdr.id)
    assert _value(backend, DX_KEY, DX_GLOBAL) == (
        "SwapEffectUpgradeEnable=1;AutoHDREnable=1;VRROptimizeEnable=0;"
    )
    engine.restore(gpu.id)
    assert _value(backend, DX_KEY, GAME_EXE) == "AppStatus=4096;"  # Windows' own data stays


def test_fso_flag_removed_and_restored(engine, backend) -> None:
    entry = engine.apply("fso_default", _users_pc())
    assert _value(backend, LAYERS_KEY, GAME_EXE) is None  # only flag -> value removed
    engine.restore(entry.id)
    assert _value(backend, LAYERS_KEY, GAME_EXE) == "~ DISABLEDXMAXIMIZEDWINDOWEDMODE "


def test_gpu_preference_without_registry_entry_uses_install_path(engine, backend) -> None:
    backend.reg.pop(("HKCU", DX_KEY, GAME_EXE))
    backend.reg.pop(("HKCU", LAYERS_KEY, GAME_EXE))
    engine.apply("gpu_high_performance", _users_pc())
    assert _value(backend, DX_KEY, GAME_EXE) == "GpuPreference=2;"


def test_mouse_and_power(engine, backend) -> None:
    mouse = engine.apply("mouse_accel_off", _users_pc())
    assert backend.mouse == [0, 0, 0]
    power = engine.apply("power_best_performance", _users_pc())
    assert (backend.scheme, backend.overlay) == (BALANCED_SCHEME, BEST_PERFORMANCE_OVERLAY)
    engine.restore_all()  # newest first: power, then mouse
    assert (backend.scheme, backend.overlay) == (HIGH_PERFORMANCE, ZERO)
    assert backend.mouse == [6, 10, 1]
    assert engine.entries() == [] and power.tweak == "power_best_performance" and mouse.id


def test_failure_rolls_back_and_leaves_no_entry(engine, backend) -> None:
    backend.refuse_overlay = True
    with pytest.raises(TweakError, match="power mode"):
        engine.apply("power_best_performance", _users_pc())
    assert backend.scheme == HIGH_PERFORMANCE  # the plan switch was undone
    assert engine.entries() == []


def test_refused_while_the_game_runs(backend, tmp_path) -> None:
    engine = WindowsTweaks(backend, tmp_path / "t.json", game_running=lambda: True)
    with pytest.raises(GameRunningError):
        engine.apply("game_mode_on", _users_pc())
    assert backend.calls == []


def test_journal_survives_and_tolerates_garbage(engine, tmp_path) -> None:
    entry = engine.apply("game_mode_on", _users_pc())
    data = json.loads(engine.journal.read_text(encoding="utf-8"))
    assert data["format"] == "wzce-windows-tweaks" and data["entries"][0]["tweak"] == "game_mode_on"
    again = WindowsTweaks(engine.backend, engine.journal, game_running=lambda: False)
    assert [e.id for e in again.entries()] == [entry.id]
    engine.journal.write_text("{broken", encoding="utf-8")
    assert engine.entries() == []
    with pytest.raises(TweakError):
        engine.restore(entry.id)


def test_unknown_tweak_and_missing_exe(engine, backend) -> None:
    with pytest.raises(TweakError):
        engine.apply("defender_off", _users_pc())
    backend.reg.clear()
    info = _users_pc()
    info.game_install = None
    with pytest.raises(TweakError, match="executable"):
        engine.apply("fso_default", info)


def test_real_backend_refuses_hklm() -> None:
    with pytest.raises(TweakError, match="HKLM"):
        WindowsBackend().reg_set("HKLM", "SOFTWARE", "x", 1, REG_DWORD)


# ------------------------------------------------------------- mapping


@pytest.mark.parametrize(
    ("check", "tweak"),
    [
        (CheckResult("game_mode", Status.WARN), "game_mode_on"),
        (CheckResult("recording", Status.WARN), "recording_off"),
        (CheckResult("auto_hdr", Status.INFO), "auto_hdr_off"),
        (CheckResult("fso", Status.INFO), "fso_default"),
        (CheckResult("mouse_acceleration", Status.WARN), "mouse_accel_off"),
        (CheckResult("gpu_preference", Status.INFO), "gpu_high_performance"),
        (CheckResult("power_plan", Status.WARN, variant="mode"), "power_best_performance"),
        (CheckResult("power_plan", Status.WARN), "power_best_performance"),  # power saver
        (CheckResult("power_plan", Status.WARN, variant="x3d"), "power_balanced"),
        (CheckResult("game_mode", Status.OK), None),
        (CheckResult("hvci", Status.INFO), None),  # security: never changed by the app
        (CheckResult("secure_boot", Status.WARN), None),
    ],
)
def test_tweak_for(check, tweak) -> None:
    assert tweak_for(check, _users_pc()) == tweak


TWEAKS = ("game_mode_on", "recording_off", "auto_hdr_off", "gpu_high_performance",
          "fso_default", "mouse_accel_off", "power_balanced", "power_best_performance")  # fmt: skip


@pytest.mark.parametrize("lang", ["en", "pl"])
def test_every_tweak_has_texts(lang) -> None:
    from wzce.core.i18n import Translator

    tr = Translator(lang)
    for tweak in TWEAKS:
        for part in ("title", "confirm"):
            assert not tr(f"tweaks.{tweak}.{part}").startswith("tweaks."), (lang, tweak)


def test_every_tweak_can_be_built(engine) -> None:
    from wzce.core.windows_tweaks import build_tweak

    for tweak in TWEAKS:
        assert build_tweak(tweak, engine.backend, _users_pc()).changes
