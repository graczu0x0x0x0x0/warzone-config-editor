"""Editing session: one opened settings file set, its unsaved changes and their undo history.

This is the UI's single source of truth, kept free of Qt so it can be unit
tested. It holds two documents:

* ``original`` - exactly what is on disk (as of load or last save)
* ``document`` - the working copy the user edits

Pending changes are simply ``diff(original, document)``. Every mutation goes
through a method here and is recorded on the ``UndoStack``; methods return the
ids of the settings they touched so the UI knows what to refresh.

Persistence side effects:
* ``reload()`` compares the file with what we last saw (``HistoryStore``) and
  records a GAME_CHANGE entry when something else wrote it -> ``external_change``.
* ``save()`` backs up, writes both slots and records a SAVE history entry.
"""

from __future__ import annotations

import contextlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .backup import BackupManager
from .diff import SettingChange, diff_documents, same_value
from .document import ConfigDocument, ValueChange
from .errors import WzceError
from .hardware import detect_gpu_vendor
from .history import EntryKind, HistoryEntry, HistoryStore
from .process import GameRunningCheck, is_game_running
from .storage import LoadedConfig, SaveResult, SettingsFileSet
from .undo import CommandKind, UndoCommand, UndoStack

# Retention per file set, applied after each save.
BACKUPS_TO_KEEP = 50
HISTORY_TO_KEEP = 200


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
        history: HistoryStore | None = None,
        game_running: GameRunningCheck = is_game_running,
    ) -> None:
        self.fileset = fileset
        self.backup_manager = backup_manager if backup_manager is not None else BackupManager()
        self.history = history if history is not None else HistoryStore()
        self.undo_stack = UndoStack()
        self._game_running = game_running
        self.loaded: LoadedConfig
        self.original: ConfigDocument
        self.document: ConfigDocument
        # GAME_CHANGE entry found by the most recent reload (None if the file was as
        # we left it). The UI shows a notice and then calls ``acknowledge_external_change``.
        self.external_change: HistoryEntry | None = None
        self._signature: _DiskSignature
        self.reload()

    @classmethod
    def open_path(cls, path: str | Path, **kwargs) -> EditorSession:
        return cls(SettingsFileSet.from_path(path), **kwargs)

    # ---------------------------------------------------------------- loading
    def reload(self, *, keep_undo: bool = False) -> None:
        """(Re)read from disk, dropping unsaved changes (and the undo history unless kept)."""
        self.loaded = self.fileset.load()
        self.original = self.loaded.document
        self.document = self.original.copy()
        self._signature = _DiskSignature.of(self.fileset)
        if not keep_undo:
            self.undo_stack.clear()
        entry = self.history.check_external_change(self.fileset, self.original)
        if entry is not None:
            self.external_change = entry

    def acknowledge_external_change(self) -> None:
        self.external_change = None

    def disk_changed(self) -> bool:
        """True when the slots changed on disk since load/save (e.g. the game wrote them)."""
        return _DiskSignature.of(self.fileset) != self._signature

    # ---------------------------------------------------------------- editing
    def set_value(
        self, setting_id: str, value: object, *, allow_read_only: bool = False
    ) -> ValueChange:
        change = self.document.set_value(setting_id, value, allow_read_only=allow_read_only)
        self.undo_stack.push(UndoCommand(CommandKind.EDIT, [change]))
        return change

    def revert(self, setting_id: str) -> ValueChange:
        """Undo the pending change of one setting (back to the value on disk)."""
        change = self.document.restore_raw(setting_id, self.original.get(setting_id).raw_value)
        self.undo_stack.push(UndoCommand(CommandKind.REVERT, [change]))
        return change

    def discard_all(self) -> list[str]:
        changes = [
            self.document.restore_raw(c.setting_id, c.old_raw)
            for c in self.pending_changes()
            if c.old_raw is not None
        ]
        self.undo_stack.push(UndoCommand(CommandKind.DISCARD, changes))
        return [c.setting_id for c in changes]

    def apply_raw_values(
        self, values: Mapping[str, str], kind: CommandKind = CommandKind.RESTORE
    ) -> list[str]:
        """Write raw values taken from an earlier version of this file (history restore).

        Ids missing from the current file are skipped silently - e.g. a setting the
        game removed in an update. One undo step undoes the whole operation.
        """
        changes = [
            self.document.restore_raw(setting_id, raw)
            for setting_id, raw in values.items()
            if setting_id in self.document
        ]
        changes = [c for c in changes if not c.is_noop]
        self.undo_stack.push(UndoCommand(kind, changes), allow_merge=False)
        return [c.setting_id for c in changes]

    def restore_snapshot(self, snapshot: ConfigDocument) -> list[str]:
        """Load a whole earlier state into the working copy (still needs saving)."""
        return self.apply_raw_values(snapshot.values())

    # ------------------------------------------------------------- undo/redo
    def undo(self) -> list[str]:
        command = self.undo_stack.take_undo()
        if command is None:
            return []
        for change in reversed(command.changes):
            self.document.restore_raw(change.setting_id, change.old_raw)
        return command.setting_ids

    def redo(self) -> list[str]:
        command = self.undo_stack.take_redo()
        if command is None:
            return []
        for change in command.changes:
            self.document.restore_raw(change.setting_id, change.new_raw)
        return command.setting_ids

    # ------------------------------------------------------------------ state
    def pending_changes(self) -> list[SettingChange]:
        return diff_documents(self.original, self.document)

    def changed_ids(self) -> set[str]:
        return {c.setting_id for c in self.pending_changes()}

    def is_changed(self, setting_id: str) -> bool:
        return not same_value(
            self.document.get(setting_id).raw_value, self.original.get(setting_id).raw_value
        )

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
    def save(self, note: str = "") -> SaveResult:
        """Back up, write both slots, record history, then reload the saved state.

        Saving with no pending changes is allowed on purpose: it re-syncs txt0
        and txt1 when they differ. The undo history survives a save, so Ctrl+Z
        right after saving brings the old values back as new pending changes.
        """
        if self.disk_changed():
            # Something (the game) wrote the file after we loaded it and we are about
            # to overwrite that. Record it first so it stays recoverable in History.
            # If it is unreadable (mid-write?), the backup made by save() still has it.
            with contextlib.suppress(WzceError):
                self.history.check_external_change(self.fileset, self.fileset.load().document)
        before = self.original
        result = self.fileset.save(
            self.document,
            backup_manager=self.backup_manager,
            game_running=self._game_running,
        )
        self.history.record(self.fileset, EntryKind.SAVE, before, self.document, note=note)
        # Mark our own write as "seen" so reload() does not report it as a game change.
        self.history.set_last_seen(self.fileset, self.document)
        self.backup_manager.prune(self.fileset, keep=BACKUPS_TO_KEEP)
        self.history.prune(self.fileset, keep=HISTORY_TO_KEEP)

        self.reload(keep_undo=True)
        return result
