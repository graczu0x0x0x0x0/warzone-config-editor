"""Persistent preferences of the editor itself (not the game).

Stored as an INI file next to our other data (``<app data>/settings.ini``) so a
portable install or ``WZCE_DATA_DIR`` keeps everything in one folder.
"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QSettings

from ..core.knowledge import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES
from ..core.paths import app_data_dir


class AppSettings:
    def __init__(self, settings: QSettings | None = None) -> None:
        if settings is None:
            path = app_data_dir() / "settings.ini"
            path.parent.mkdir(parents=True, exist_ok=True)
            settings = QSettings(str(path), QSettings.Format.IniFormat)
        self._s = settings

    def _get_bool(self, key: str, default: bool) -> bool:
        value = self._s.value(key, default)
        if isinstance(value, str):  # INI stores booleans as text
            return value.lower() == "true"
        return bool(value)

    # --- language ---------------------------------------------------------
    @property
    def language(self) -> str:
        value = str(self._s.value("ui/language", DEFAULT_LANGUAGE))
        return value if value in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE

    @language.setter
    def language(self, value: str) -> None:
        self._s.setValue("ui/language", value)

    # --- filters ----------------------------------------------------------
    @property
    def advanced(self) -> bool:
        return self._get_bool("ui/advanced", False)

    @advanced.setter
    def advanced(self, value: bool) -> None:
        self._s.setValue("ui/advanced", value)

    @property
    def hide_other_vendors(self) -> bool:
        return self._get_bool("ui/hide_other_vendors", True)

    @hide_other_vendors.setter
    def hide_other_vendors(self, value: bool) -> None:
        self._s.setValue("ui/hide_other_vendors", value)

    @property
    def preset(self) -> str:
        return str(self._s.value("ui/preset", "competitive"))

    @preset.setter
    def preset(self, value: str) -> None:
        self._s.setValue("ui/preset", value)

    @property
    def hardware_bar_collapsed(self) -> bool:
        return self._get_bool("ui/hardware_bar_collapsed", False)

    @hardware_bar_collapsed.setter
    def hardware_bar_collapsed(self, value: bool) -> None:
        self._s.setValue("ui/hardware_bar_collapsed", value)

    # --- files and window -----------------------------------------------------
    @property
    def last_file(self) -> str:
        return str(self._s.value("files/last", ""))

    @last_file.setter
    def last_file(self, value: str) -> None:
        self._s.setValue("files/last", value)

    def window_state(self, key: str) -> QByteArray | None:
        value = self._s.value(f"window/{key}")
        return value if isinstance(value, QByteArray) else None

    def set_window_state(self, key: str, value: QByteArray) -> None:
        self._s.setValue(f"window/{key}", value)

    def sync(self) -> None:
        self._s.sync()
