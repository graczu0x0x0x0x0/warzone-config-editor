"""Well-known filesystem locations (game folders and our own data folder).

Everything that depends on environment variables lives here so tests can
redirect it (``WZCE_DATA_DIR`` or monkeypatching these functions).
"""

from __future__ import annotations

import os
from pathlib import Path

APP_DIR_NAME = "WarzoneConfigEditor"


def app_data_dir() -> Path:
    """Our own data root: backups, history, templates, app settings.

    ``%APPDATA%\\WarzoneConfigEditor`` by default; override with ``WZCE_DATA_DIR``
    (used by tests and for a portable install).
    """
    override = os.environ.get("WZCE_DATA_DIR")
    if override:
        return Path(override)
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(base) / APP_DIR_NAME


def game_players_dirs() -> list[Path]:
    """Candidate ``players`` folders, newest location first.

    * BO7 (cod25) and newer: ``%LOCALAPPDATA%\\Activision\\Call of Duty\\players``
    * BO6 (cod24) and older: ``Documents\\Call of Duty\\players`` (also the
      OneDrive-redirected Documents folder, which is common on Windows 11).
    Only existing folders are returned.
    """
    candidates: list[Path] = []
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(Path(local) / "Activision" / "Call of Duty" / "players")
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    candidates.append(home / "Documents" / "Call of Duty" / "players")
    candidates.append(home / "OneDrive" / "Documents" / "Call of Duty" / "players")

    seen: set[Path] = set()
    result: list[Path] = []
    for path in candidates:
        resolved = path.resolve()
        if path.is_dir() and resolved not in seen:
            seen.add(resolved)
            result.append(path)
    return result
