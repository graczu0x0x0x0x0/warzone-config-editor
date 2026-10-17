"""Editing session: one opened settings file set and its unsaved changes.

This is the UI's single source of truth, kept free of Qt so it can be unit
tested. It holds two documents:

* ``original`` - exactly what is on disk (as of load or last save)
* ``document`` - the working copy the user edits

Pending changes are simply ``diff(original, document)``; reverting one setting
copies its raw value back from ``original``. Stage 4 (undo/redo) builds on
``ValueChange`` objects returned by ``set_value``/``revert``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .backup import BackupManager
from .diff import SettingChange, diff_documents
from .document import ConfigDocument, ValueChange
from .hardware import detect_gpu_vendor
from .process import GameRunningCheck, is_game_running
from .storage import LoadedConfig, SaveResult, SettingsFileSet

# How many backups to keep per file set after each save.
BACKUPS_TO_KEEP = 50


@dataclass(frozen=True, slots=True)
class _DiskSignature:
    """Cheap fingerprint of the slots on disk, to notice writes by the game."""

    entries: tuple[tuple[str, int, int], ...]  # (name, size, mtime_ns)

    @classmethod
    def of(cls, fileset: SettingsFileSet) -> _DiskSignature:
        entries = []
        for path in fileset.slots:
            if path.exists():
                st = path.stat()
                entries.append((path.name, st.st_size, st.st_mtime_ns))
        return cls(tuple(entries))


class EditorSession:
    def __init__(
        self,
        fileset: SettingsFileSet,
        *,
        backup_manager: BackupManager | None = None,
        game_running: GameRunningCheck = is_game_running,
    ) -> None:
        self.fileset = fileset
        self.backup_manager = backup_manager if backup_manager is not None else BackupManager()
        self._game_running = game_running
        self.loaded: LoadedConfig
        self.original: ConfigDocument
        self.document: ConfigDocument
        self._signature: _DiskSignature
        self.reload()

    @classmethod
    def open_path(cls, path: str | Path, **kwargs) -> EditorSession:
        return cls(SettingsFileSet.from_path(path), **kwargs)

    # ---------------------------------------------------------------- loading
    def reload(self) -> None:
        """(Re)read from disk, dropping all unsaved changes."""
        self.loaded = self.fileset.load()
        self.original = self.loaded.document
        self.document = self.original.copy()
        self._signature = _DiskSignature.of(self.fileset)

    def disk_changed(self) -> bool:
        """True when the slots changed on disk since load/save (e.g. the game wrote them)."""
        return _DiskSignature.of(self.fileset) != self._signature

    # ---------------------------------------------------------------- editing
    def set_value(
        self, setting_id: str, value: object, *, allow_read_only: bool = False
    ) -> ValueChange:
        return self.document.set_value(setting_id, value, allow_read_only=allow_read_only)

    def revert(self, setting_id: str) -> ValueChange:
        """Undo the pending change of one setting (back to the value on disk)."""
        return self.document.restore_raw(setting_id, self.original.get(setting_id).raw_value)

    def discard_all(self) -> None:
        self.document = self.original.copy()

    # ------------------------------------------------------------------ state
    def pending_changes(self) -> list[SettingChange]:
        return diff_documents(self.original, self.document)

    def changed_ids(self) -> set[str]:
        return {c.setting_id for c in self.pending_changes()}

    def is_changed(self, setting_id: str) -> bool:
        return self.document.get(setting_id).raw_value != self.original.get(setting_id).raw_value

    @property
    def is_dirty(self) -> bool:
        return bool(self.pending_changes())

    def original_raw(self, setting_id: str) -> str:
        return self.original.get(setting_id).raw_value

    @property
    def gpu_vendor(self) -> str | None:
        return detect_gpu_vendor(self.original)

    def game_running(self) -> bool:
        return self._game_running()

    # ------------------------------------------------------------------- save
    def save(self) -> SaveResult:
        """Back up, write both slots, then treat the saved state as the new original.

        Saving with no pending changes is allowed on purpose: it re-syncs txt0
        and txt1 when they differ.
        """
        result = self.fileset.save(
            self.document,
            backup_manager=self.backup_manager,
            game_running=self._game_running,
        )
        self.backup_manager.prune(self.fileset, keep=BACKUPS_TO_KEEP)
        self.reload()
        return result
