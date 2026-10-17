"""Reversible changes of Windows settings from the Windows optimization tab (stage 10d).

Only "level A" changes: per-user values (HKCU), the mouse acceleration (a per-user
setting applied live through ``SystemParametersInfo``) and the power plan / power
mode (allowed for normal users). Nothing needs admin rights, nothing touches HKLM,
security settings, the BIOS or the game files - see ``docs/RAPORT_WINDOWS.md`` §5.

Every change is a ``Tweak``: a list of (``Target``, wanted state) pairs. Before
writing, the current state of each target is read and stored in a JSON journal
(``<app data>/windows/tweaks.json``) together with the state after writing, so
``restore()`` can put back exactly what was there - including "the value did not
exist". Targets are fine-grained on purpose: one ``Key=Val`` pair inside the
DirectX preference string, one flag inside an AppCompat value - restoring one tweak
never reverts other keys in the same registry value.

The OS is reached through a ``SystemBackend``; ``WindowsBackend`` is the real one,
tests use an in-memory fake, so no test ever writes the real registry.
"""

from __future__ import annotations

import contextlib
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Protocol

from .check_types import CheckResult, Status
from .errors import GameRunningError, WzceError
from .paths import app_data_dir
from .process import GAME_PROCESS_NAMES, is_game_running
from .system_info import SystemInfo
from .windows_info import BALANCED_SCHEME, parse_dx_settings

HKCU = "HKCU"
GAME_BAR_KEY = r"Software\Microsoft\GameBar"
GAME_DVR_KEY = r"Software\Microsoft\Windows\CurrentVersion\GameDVR"
DX_KEY = r"Software\Microsoft\DirectX\UserGpuPreferences"
DX_GLOBAL = "DirectXUserGlobalSettings"
LAYERS_KEY = r"Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers"
FSO_FLAG = "DISABLEDXMAXIMIZEDWINDOWEDMODE"
BEST_PERFORMANCE_OVERLAY = "ded574b5-45a0-4f42-8737-46345c09c238"
JOURNAL_FORMAT = "wzce-windows-tweaks"

REG_SZ, REG_DWORD = 1, 4  # winreg constants, duplicated so tests need no winreg

State = object  # JSON-serialisable state of one target (None = absent)


class TweakError(WzceError):
    """A Windows setting could not be changed or restored."""


class SystemBackend(Protocol):
    """The OS operations the tweaks need; all per-user, none needs admin."""

    def reg_get(self, hive: str, path: str, name: str) -> tuple[object, int] | None: ...
    def reg_set(self, hive: str, path: str, name: str, value: object, kind: int) -> None: ...
    def reg_delete(self, hive: str, path: str, name: str) -> None: ...
    def reg_names(self, hive: str, path: str) -> list[str]: ...
    def mouse_get(self) -> list[int]: ...
    def mouse_set(self, values: list[int]) -> None: ...
    def scheme_get(self) -> str: ...
    def scheme_set(self, guid: str) -> None: ...
    def overlay_get(self) -> str: ...
    def overlay_set(self, guid: str) -> None: ...


# ---------------------------------------------------------------------------
# Targets: one piece of state each, readable and writable
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Target:
    """What a tweak touches; ``kind`` selects how it is read and written."""

    kind: str  # dword / dx_pair / compat_flag / mouse / power_scheme / power_overlay
    path: str = ""
    name: str = ""  # registry value name
    key: str = ""  # pair key inside DirectX strings, flag inside AppCompat values

    def to_json(self) -> dict:
        return {"kind": self.kind, "path": self.path, "name": self.name, "key": self.key}

    @classmethod
    def from_json(cls, data: dict) -> Target:
        return cls(data["kind"], data.get("path", ""), data.get("name", ""), data.get("key", ""))

    # ------------------------------------------------------------ read/write
    def read(self, backend: SystemBackend) -> State:
        if self.kind == "dword":
            got = backend.reg_get(HKCU, self.path, self.name)
            return None if got is None else int(got[0])  # type: ignore[call-overload]
        if self.kind == "dx_pair":
            return parse_dx_settings(_reg_text(backend, self.path, self.name)).get(self.key)
        if self.kind == "compat_flag":
            flags = _reg_text(backend, self.path, self.name).upper().split()
            return self.key.upper() in flags
        if self.kind == "mouse":
            return list(backend.mouse_get())
        if self.kind == "power_scheme":
            return backend.scheme_get().lower()
        if self.kind == "power_overlay":
            return backend.overlay_get().lower()
        raise TweakError(f"unknown target kind: {self.kind}")

    def write(self, backend: SystemBackend, state: State) -> None:
        if self.kind == "dword":
            if state is None:
                backend.reg_delete(HKCU, self.path, self.name)
            else:
                backend.reg_set(HKCU, self.path, self.name, int(state), REG_DWORD)  # type: ignore[call-overload]
        elif self.kind == "dx_pair":
            text = set_dx_pair(_reg_text(backend, self.path, self.name), self.key, state)
            _write_text(backend, self.path, self.name, text)
        elif self.kind == "compat_flag":
            text = set_compat_flag(_reg_text(backend, self.path, self.name), self.key, bool(state))
            _write_text(backend, self.path, self.name, text)
        elif self.kind == "mouse":
            backend.mouse_set(list(state))  # type: ignore[call-overload]
        elif self.kind == "power_scheme":
            backend.scheme_set(str(state))
        elif self.kind == "power_overlay":
            backend.overlay_set(str(state))
        else:
            raise TweakError(f"unknown target kind: {self.kind}")


def _reg_text(backend: SystemBackend, path: str, name: str) -> str:
    got = backend.reg_get(HKCU, path, name)
    return str(got[0]) if got else ""


def _write_text(backend: SystemBackend, path: str, name: str, text: str) -> None:
    if text:
        backend.reg_set(HKCU, path, name, text, REG_SZ)
    else:  # nothing left in the value: remove it, as Windows would
        backend.reg_delete(HKCU, path, name)


def set_dx_pair(text: str, key: str, value: object) -> str:
    """Set (or with ``None`` remove) one ``Key=Val`` pair, keeping the others and their order."""
    pairs = list(parse_dx_settings(text).items())
    found = False
    result = []
    for name, current in pairs:
        if name == key:
            found = True
            if value is not None:
                result.append((name, str(value)))
        else:
            result.append((name, current))
    if not found and value is not None:
        result.append((key, str(value)))
    return "".join(f"{name}={val};" for name, val in result)


def set_compat_flag(text: str, flag: str, present: bool) -> str:
    """Add/remove one flag in an AppCompat ``Layers`` value (``~ FLAG1 FLAG2``)."""
    parts = text.split()
    tilde = parts[:1] == ["~"]
    flags = [p for p in parts if p != "~" and p.upper() != flag.upper()]
    if present:
        flags.append(flag)
    if not flags:
        return ""
    return " ".join((["~"] if tilde or not parts else []) + flags) + " "


# ---------------------------------------------------------------------------
# Tweaks
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Tweak:
    id: str
    changes: tuple[tuple[Target, State], ...]


@dataclass(slots=True)
class AppliedTweak:
    """One journal entry: what was changed, from what, to what, when."""

    id: str  # unique entry id
    tweak: str
    when: str  # ISO timestamp
    targets: list[Target]
    before: list[State]
    after: list[State]

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "tweak": self.tweak,
            "when": self.when,
            "targets": [t.to_json() for t in self.targets],
            "before": self.before,
            "after": self.after,
        }

    @classmethod
    def from_json(cls, data: dict) -> AppliedTweak:
        return cls(
            id=data["id"],
            tweak=data["tweak"],
            when=data["when"],
            targets=[Target.from_json(t) for t in data["targets"]],
            before=list(data["before"]),
            after=list(data["after"]),
        )


def game_exe_value_name(backend: SystemBackend, info: SystemInfo) -> str | None:
    """Registry value name Windows uses for the game: the full path of cod.exe."""
    for path in (DX_KEY, LAYERS_KEY):
        for name in backend.reg_names(HKCU, path):
            if Path(name.replace("\\", "/")).name.lower() in GAME_PROCESS_NAMES:
                return name
    if info.game_install is not None:
        return str(Path(info.game_install.path) / "cod.exe")
    return None


def tweak_for(check: CheckResult, info: SystemInfo) -> str | None:
    """Id of the tweak that fixes this check row, or None (link / instructions only)."""
    if check.status not in (Status.WARN, Status.INFO):
        return None
    simple = {
        "game_mode": "game_mode_on",
        "recording": "recording_off",
        "auto_hdr": "auto_hdr_off",
        "fso": "fso_default",
        "mouse_acceleration": "mouse_accel_off",
    }
    if check.id in simple:
        return simple[check.id]
    if check.id == "gpu_preference" and check.variant in (None, "power_saving"):
        return "gpu_high_performance" if info.game_install is not None else None
    if check.id == "power_plan":
        return "power_balanced" if check.variant == "x3d" else "power_best_performance"
    return None


def build_tweak(tweak_id: str, backend: SystemBackend, info: SystemInfo) -> Tweak:
    if tweak_id == "game_mode_on":
        return Tweak(tweak_id, ((Target("dword", GAME_BAR_KEY, "AutoGameModeEnabled"), 1),))
    if tweak_id == "recording_off":
        return Tweak(tweak_id, ((Target("dword", GAME_DVR_KEY, "HistoricalCaptureEnabled"), 0),))
    if tweak_id == "auto_hdr_off":
        return Tweak(tweak_id, ((Target("dx_pair", DX_KEY, DX_GLOBAL, "AutoHDREnable"), "0"),))
    if tweak_id in ("gpu_high_performance", "fso_default"):
        exe = game_exe_value_name(backend, info)
        if exe is None:
            raise TweakError("the game's executable was not found")
        if tweak_id == "gpu_high_performance":
            return Tweak(tweak_id, ((Target("dx_pair", DX_KEY, exe, "GpuPreference"), "2"),))
        return Tweak(tweak_id, ((Target("compat_flag", LAYERS_KEY, exe, FSO_FLAG), False),))
    if tweak_id == "mouse_accel_off":
        return Tweak(tweak_id, ((Target("mouse"), [0, 0, 0]),))
    if tweak_id == "power_balanced":
        return Tweak(tweak_id, ((Target("power_scheme"), BALANCED_SCHEME),))
    if tweak_id == "power_best_performance":
        # Power modes only exist on top of the Balanced plan, so switch the plan first.
        return Tweak(
            tweak_id,
            (
                (Target("power_scheme"), BALANCED_SCHEME),
                (Target("power_overlay"), BEST_PERFORMANCE_OVERLAY),
            ),
        )
    raise TweakError(f"unknown tweak: {tweak_id}")


# ---------------------------------------------------------------------------
# Engine with journal
# ---------------------------------------------------------------------------


class WindowsTweaks:
    """Applies tweaks, keeps the journal and restores entries."""

    def __init__(
        self,
        backend: SystemBackend | None = None,
        journal: Path | None = None,
        game_running: Callable[[], bool] = is_game_running,
    ) -> None:
        self.backend = backend if backend is not None else WindowsBackend()
        self.journal = (
            journal if journal is not None else app_data_dir() / "windows" / "tweaks.json"
        )
        self._game_running = game_running

    # ---------------------------------------------------------------- journal
    def entries(self) -> list[AppliedTweak]:
        """Applied (not yet restored) tweaks, oldest first; a broken journal reads as empty."""
        try:
            data = json.loads(self.journal.read_text(encoding="utf-8"))
            return [AppliedTweak.from_json(e) for e in data.get("entries", [])]
        except (OSError, ValueError, KeyError, TypeError):
            return []

    def _save(self, entries: list[AppliedTweak]) -> None:
        self.journal.parent.mkdir(parents=True, exist_ok=True)
        data = {"format": JOURNAL_FORMAT, "version": 1, "entries": [e.to_json() for e in entries]}
        tmp = self.journal.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.journal)

    # ------------------------------------------------------------ operations
    def _refuse_while_game_runs(self) -> None:
        if self._game_running():
            raise GameRunningError("Close the game before changing Windows settings.")

    def apply(self, tweak_id: str, info: SystemInfo) -> AppliedTweak:
        """Change the settings; on any failure the targets written so far are rolled back."""
        self._refuse_while_game_runs()
        tweak = build_tweak(tweak_id, self.backend, info)
        targets = [target for target, _state in tweak.changes]
        before = [target.read(self.backend) for target in targets]
        entries = self.entries()
        entry = AppliedTweak(
            id=uuid.uuid4().hex[:12],
            tweak=tweak_id,
            when=datetime.now().isoformat(timespec="seconds"),
            targets=targets,
            before=before,
            after=[],
        )
        # Journal first: if the app dies halfway, the original values are still on disk.
        self._save([*entries, entry])
        written: list[int] = []
        try:
            for index, (target, state) in enumerate(tweak.changes):
                target.write(self.backend, state)
                written.append(index)
            entry.after = [target.read(self.backend) for target in targets]
            for (target, wanted), got in zip(tweak.changes, entry.after, strict=True):
                if _normalise(got) != _normalise(wanted):
                    raise TweakError(f"Windows did not accept the change ({target.kind})")
        except Exception as exc:
            for index in reversed(written):
                # Best effort; the journal entry is dropped below anyway.
                with contextlib.suppress(Exception):
                    targets[index].write(self.backend, before[index])
            self._save(entries)
            if isinstance(exc, WzceError):
                raise
            raise TweakError(str(exc)) from exc
        self._save([*entries, entry])
        return entry

    def restore(self, entry_id: str) -> AppliedTweak:
        """Put back the values recorded before the tweak and drop the journal entry."""
        self._refuse_while_game_runs()
        entries = self.entries()
        entry = next((e for e in entries if e.id == entry_id), None)
        if entry is None:
            raise TweakError("this change is no longer in the journal")
        try:
            for target, state in reversed(list(zip(entry.targets, entry.before, strict=True))):
                target.write(self.backend, state)
        except WzceError:
            raise
        except Exception as exc:
            raise TweakError(str(exc)) from exc
        self._save([e for e in entries if e.id != entry_id])
        return entry

    def restore_all(self) -> int:
        """Restore every entry, newest first; returns how many were restored."""
        entries = self.entries()
        for entry in reversed(entries):
            self.restore(entry.id)
        return len(entries)


def _normalise(state: State) -> State:
    return state.lower() if isinstance(state, str) else state


# ---------------------------------------------------------------------------
# Real backend (Windows only)
# ---------------------------------------------------------------------------


@dataclass
class WindowsBackend:
    """winreg + user32 + powrprof. Only HKCU is writable through this class."""

    _guid_type: type | None = field(default=None, init=False, repr=False)

    @staticmethod
    def _root(hive: str) -> int:
        import winreg

        if hive != HKCU:  # level A: per-user only, never HKLM
            raise TweakError(f"refusing to touch {hive}")
        return winreg.HKEY_CURRENT_USER

    def reg_get(self, hive: str, path: str, name: str) -> tuple[object, int] | None:
        import winreg

        try:
            with winreg.OpenKey(self._root(hive), path) as key:
                value, kind = winreg.QueryValueEx(key, name)
                return value, kind
        except FileNotFoundError:
            return None

    def reg_set(self, hive: str, path: str, name: str, value: object, kind: int) -> None:
        import winreg

        with winreg.CreateKeyEx(self._root(hive), path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, name, 0, kind, value)

    def reg_delete(self, hive: str, path: str, name: str) -> None:
        import winreg

        try:
            with winreg.OpenKey(self._root(hive), path, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, name)
        except FileNotFoundError:
            pass  # already absent

    def reg_names(self, hive: str, path: str) -> list[str]:
        import winreg

        names: list[str] = []
        try:
            with winreg.OpenKey(self._root(hive), path) as key:
                index = 0
                while True:
                    try:
                        names.append(winreg.EnumValue(key, index)[0])
                    except OSError:
                        break
                    index += 1
        except FileNotFoundError:
            pass
        return names

    def mouse_get(self) -> list[int]:
        import ctypes

        values = (ctypes.c_int * 3)()
        if not ctypes.WinDLL("user32").SystemParametersInfoW(0x0003, 0, values, 0):
            raise TweakError("could not read the mouse settings")
        return list(values)

    def mouse_set(self, values: list[int]) -> None:
        import ctypes

        array = (ctypes.c_int * 3)(*values)
        # SPI_SETMOUSE, persisted (SPIF_UPDATEINIFILE) and broadcast (SPIF_SENDCHANGE):
        # takes effect immediately, no sign-out needed.
        if not ctypes.WinDLL("user32").SystemParametersInfoW(0x0004, 0, array, 0x01 | 0x02):
            raise TweakError("could not change the mouse settings")

    def _guid(self, text: str):
        import ctypes

        from .windows_info import guid_struct

        if self._guid_type is None:
            self._guid_type = guid_struct()
        value = self._guid_type()
        ctypes.memmove(ctypes.byref(value), uuid.UUID(text).bytes_le, 16)
        return value

    def scheme_get(self) -> str:
        import ctypes

        from .windows_info import guid_struct

        powrprof = ctypes.WinDLL("powrprof")
        active = ctypes.POINTER(guid_struct())()
        if powrprof.PowerGetActiveScheme(None, ctypes.byref(active)) != 0:
            raise TweakError("could not read the power plan")
        try:
            return str(uuid.UUID(bytes_le=bytes(active.contents)))
        finally:
            ctypes.WinDLL("kernel32").LocalFree(active)

    def scheme_set(self, guid: str) -> None:
        import ctypes

        rc = ctypes.WinDLL("powrprof").PowerSetActiveScheme(None, ctypes.byref(self._guid(guid)))
        if rc != 0:
            raise TweakError(f"Windows refused to change the power plan (error {rc})")

    def overlay_get(self) -> str:
        import ctypes

        value = self._guid("00000000-0000-0000-0000-000000000000")
        if ctypes.WinDLL("powrprof").PowerGetEffectiveOverlayScheme(ctypes.byref(value)) != 0:
            raise TweakError("could not read the power mode")
        return str(uuid.UUID(bytes_le=bytes(value)))

    def overlay_set(self, guid: str) -> None:
        import ctypes

        # Undocumented but stable since Windows 10 1709: what Settings → Power mode calls.
        rc = ctypes.WinDLL("powrprof").PowerSetActiveOverlayScheme(self._guid(guid))
        if rc != 0:
            raise TweakError(f"Windows refused to change the power mode (error {rc})")
