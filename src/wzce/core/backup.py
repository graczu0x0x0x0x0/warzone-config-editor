"""Timestamped backups of settings file sets, with restore and pruning.

Layout under ``<app data>/backups``::

    20261017-114802-123456_s.1.0.cod25/
        manifest.json          # metadata + sha256 of every file
        s.1.0.cod25.txt0
        s.1.0.cod25.txt1
        s.1.0.cod25.m

A backup always contains the *whole* set (both slots and the marker), so a
restore puts the folder back exactly as the game left it.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .errors import BackupError, GameRunningError
from .paths import app_data_dir
from .process import GameRunningCheck, is_game_running
from .storage import SettingsFileSet, write_atomic

MANIFEST_NAME = "manifest.json"
MANIFEST_VERSION = 1
_TIMESTAMP_FORMAT = "%Y%m%d-%H%M%S-%f"


@dataclass(frozen=True, slots=True)
class BackupInfo:
    id: str  # folder name, unique and sortable by time
    path: Path
    created: datetime
    source_dir: Path
    stem: str
    files: dict[str, str]  # file name -> sha256
    reason: str

    def matches(self, fileset: SettingsFileSet) -> bool:
        return self.stem == fileset.stem and _same_dir(self.source_dir, fileset.directory)


class BackupManager:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root if root is not None else app_data_dir() / "backups"

    # ----------------------------------------------------------------- create
    def create(self, fileset: SettingsFileSet, *, reason: str = "") -> BackupInfo:
        files = fileset.existing_files()
        if not files:
            raise BackupError(f"nothing to back up for {fileset.stem}")

        created = datetime.now()
        folder = self._unique_folder(f"{created.strftime(_TIMESTAMP_FORMAT)}_{fileset.stem}")
        try:
            folder.mkdir(parents=True)
            hashes: dict[str, str] = {}
            for src in files:
                shutil.copy2(src, folder / src.name)
                hashes[src.name] = _sha256(folder / src.name)
            manifest = {
                "version": MANIFEST_VERSION,
                "created": created.isoformat(),
                "source_dir": str(fileset.directory),
                "stem": fileset.stem,
                "reason": reason,
                "files": hashes,
            }
            (folder / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        except OSError as exc:
            shutil.rmtree(folder, ignore_errors=True)
            raise BackupError(f"could not create backup: {exc}") from exc
        return self._read_manifest(folder)

    def _unique_folder(self, name: str) -> Path:
        candidate = self.root / name
        counter = 1
        while candidate.exists():
            candidate = self.root / f"{name}-{counter}"
            counter += 1
        return candidate

    # ------------------------------------------------------------------- list
    def list(self, fileset: SettingsFileSet | None = None) -> list[BackupInfo]:
        """Backups newest first, optionally only those belonging to ``fileset``."""
        if not self.root.is_dir():
            return []
        backups: list[BackupInfo] = []
        for folder in self.root.iterdir():
            if not (folder / MANIFEST_NAME).is_file():
                continue
            try:
                info = self._read_manifest(folder)
            except BackupError:
                continue  # skip damaged backups instead of hiding all of them
            if fileset is None or info.matches(fileset):
                backups.append(info)
        backups.sort(key=lambda b: (b.created, b.id), reverse=True)
        return backups

    def _read_manifest(self, folder: Path) -> BackupInfo:
        try:
            data = json.loads((folder / MANIFEST_NAME).read_text(encoding="utf-8"))
            return BackupInfo(
                id=folder.name,
                path=folder,
                created=datetime.fromisoformat(data["created"]),
                source_dir=Path(data["source_dir"]),
                stem=data["stem"],
                files=dict(data["files"]),
                reason=data.get("reason", ""),
            )
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise BackupError(f"damaged backup {folder.name}: {exc}") from exc

    # ---------------------------------------------------------------- restore
    def restore(
        self,
        backup: BackupInfo,
        fileset: SettingsFileSet,
        *,
        game_running: GameRunningCheck = is_game_running,
    ) -> BackupInfo:
        """Put the backed-up files back. Returns the safety backup of the replaced state.

        Integrity is checked (sha256) for every file *before* anything is written,
        and the current state is backed up first, so a restore is itself undoable.
        """
        if game_running():
            raise GameRunningError("Close Call of Duty before restoring a backup")
        if backup.stem != fileset.stem:
            raise BackupError(f"backup {backup.id} belongs to {backup.stem}, not {fileset.stem}")

        payload: dict[str, bytes] = {}
        for name, expected in backup.files.items():
            data = (backup.path / name).read_bytes()
            if hashlib.sha256(data).hexdigest() != expected:
                raise BackupError(f"backup {backup.id} is damaged ({name} checksum mismatch)")
            payload[name] = data

        safety = self.create(fileset, reason=f"before restoring {backup.id}")
        for name, data in payload.items():
            write_atomic(fileset.directory / name, data)
        return safety

    # ------------------------------------------------------------------ prune
    def prune(self, fileset: SettingsFileSet, keep: int = 50) -> list[BackupInfo]:
        """Delete the oldest backups of ``fileset`` beyond ``keep``. Returns the removed ones."""
        removed = self.list(fileset)[keep:]
        for info in removed:
            shutil.rmtree(info.path, ignore_errors=True)
        return removed


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _same_dir(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return str(a).lower() == str(b).lower()
