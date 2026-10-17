"""Persistent history of what happened to a settings file set.

Two kinds of entries:

* SAVE         - the editor wrote the files (changes = what the user changed)
* GAME_CHANGE  - the files differ from what we last saw, so something else wrote
                 them: almost always the game (in-game menu, update, autodetect)

Every entry stores the setting-level diff and a full snapshot of the file *after*
the event, so the UI can both "undo these changes" (write the old values of just
those settings) and "restore this state" (load the whole snapshot).

Layout under ``<app data>/history``::

    s.1.0.cod25-1a2b3c4d/                # stem + hash of the folder path
        last_seen.snapshot               # bytes we last saw on disk (change detection)
        20261017-114802-123456.json      # entry metadata + diff
        20261017-114802-123456.snapshot  # file contents after the event

Snapshots are raw bytes (not JSON text) so odd encodings survive exactly.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from .diff import ChangeKind, SettingChange, diff_documents
from .document import ConfigDocument
from .errors import WzceError
from .paths import app_data_dir
from .storage import SettingsFileSet

ENTRY_VERSION = 1
LAST_SEEN_NAME = "last_seen.snapshot"
DEFAULT_KEEP = 200
_TIMESTAMP_FORMAT = "%Y%m%d-%H%M%S-%f"


class EntryKind(StrEnum):
    SAVE = "save"
    GAME_CHANGE = "game_change"


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    id: str
    created: datetime
    kind: EntryKind
    changes: list[SettingChange]
    note: str
    directory: Path

    @property
    def snapshot_path(self) -> Path:
        return self.directory / f"{self.id}.snapshot"

    def load_snapshot(self) -> ConfigDocument:
        return ConfigDocument.from_bytes(self.snapshot_path.read_bytes())

    def old_values(self) -> dict[str, str]:
        """``{id: raw}`` that undoes this entry (settings that existed before it)."""
        return {c.setting_id: c.old_raw for c in self.changes if c.old_raw is not None}


class HistoryStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root if root is not None else app_data_dir() / "history"

    def folder(self, fileset: SettingsFileSet) -> Path:
        # Several installs/accounts can share a stem; the path hash keeps them apart.
        digest = hashlib.sha1(str(fileset.directory).lower().encode("utf-8")).hexdigest()[:8]
        return self.root / f"{fileset.stem}-{digest}"

    # ------------------------------------------------------------- recording
    def record(
        self,
        fileset: SettingsFileSet,
        kind: EntryKind,
        before: ConfigDocument,
        after: ConfigDocument,
        *,
        note: str = "",
    ) -> HistoryEntry | None:
        """Store an entry for ``before -> after``. Returns None when nothing changed."""
        changes = diff_documents(before, after)
        if not changes:
            return None
        folder = self.folder(fileset)
        folder.mkdir(parents=True, exist_ok=True)
        created = datetime.now()
        entry_id = self._unique_id(folder, created.strftime(_TIMESTAMP_FORMAT))
        (folder / f"{entry_id}.snapshot").write_bytes(after.to_bytes())
        payload = {
            "version": ENTRY_VERSION,
            "created": created.isoformat(),
            "kind": kind.value,
            "note": note,
            "changes": [
                {"id": c.setting_id, "kind": c.kind.value, "old": c.old_raw, "new": c.new_raw}
                for c in changes
            ],
        }
        (folder / f"{entry_id}.json").write_text(json.dumps(payload, indent=1), encoding="utf-8")
        return HistoryEntry(entry_id, created, kind, changes, note, folder)

    @staticmethod
    def _unique_id(folder: Path, base: str) -> str:
        candidate, counter = base, 1
        while (folder / f"{candidate}.json").exists():
            candidate = f"{base}-{counter}"
            counter += 1
        return candidate

    # ----------------------------------------------------- change detection
    def last_seen(self, fileset: SettingsFileSet) -> ConfigDocument | None:
        path = self.folder(fileset) / LAST_SEEN_NAME
        if not path.exists():
            return None
        try:
            return ConfigDocument.from_bytes(path.read_bytes())
        except WzceError:
            return None  # corrupted marker: behave like a first run

    def set_last_seen(self, fileset: SettingsFileSet, document: ConfigDocument) -> None:
        folder = self.folder(fileset)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / LAST_SEEN_NAME).write_bytes(document.to_bytes())

    def check_external_change(
        self, fileset: SettingsFileSet, current: ConfigDocument
    ) -> HistoryEntry | None:
        """Compare ``current`` with what we last saw; record a GAME_CHANGE if they differ.

        Always updates ``last_seen`` afterwards. The first time a file is seen there is
        nothing to compare with, so no entry is created.
        """
        previous = self.last_seen(fileset)
        entry = None
        if previous is not None:
            entry = self.record(fileset, EntryKind.GAME_CHANGE, previous, current)
        self.set_last_seen(fileset, current)
        return entry

    # ------------------------------------------------------------- reading
    def list(self, fileset: SettingsFileSet) -> list[HistoryEntry]:
        """Entries newest first; damaged entries are skipped."""
        folder = self.folder(fileset)
        if not folder.is_dir():
            return []
        entries = []
        for meta in folder.glob("*.json"):
            entry = self._read(meta)
            if entry is not None and entry.snapshot_path.exists():
                entries.append(entry)
        entries.sort(key=lambda e: (e.created, e.id), reverse=True)
        return entries

    @staticmethod
    def _read(meta: Path) -> HistoryEntry | None:
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
            changes = [
                SettingChange(c["id"], ChangeKind(c["kind"]), c["old"], c["new"])
                for c in data["changes"]
            ]
            return HistoryEntry(
                id=meta.stem,
                created=datetime.fromisoformat(data["created"]),
                kind=EntryKind(data["kind"]),
                changes=changes,
                note=data.get("note", ""),
                directory=meta.parent,
            )
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def prune(self, fileset: SettingsFileSet, keep: int = DEFAULT_KEEP) -> int:
        """Delete the oldest entries beyond ``keep``. Returns how many were removed."""
        removed = self.list(fileset)[keep:]
        for entry in removed:
            (entry.directory / f"{entry.id}.json").unlink(missing_ok=True)
            entry.snapshot_path.unlink(missing_ok=True)
        return len(removed)
