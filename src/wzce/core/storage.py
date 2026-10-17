"""Read and write a settings file *set* safely.

The game stores each settings file as an A/B pair plus a 2-byte marker::

    s.1.0.cod25.txt0   slot 0
    s.1.0.cod25.txt1   slot 1
    s.1.0.cod25.m      b"\\x00\\x00" or b"\\x01\\x01" -> which slot is current

(Newer titles may use a single ``s.1.0.cod26.txt`` instead.) The game writes the
inactive slot and then flips the marker, so a crash mid-write never loses
settings. See docs/FILE_FORMAT.md section 4.

Our strategy is simpler and independent of the marker: write the *same* bytes to
both slots, atomically, and never touch the marker. Whatever slot the game picks,
it gets our content.
"""

from __future__ import annotations

import contextlib
import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from .diff import SettingChange, diff_documents
from .document import ConfigDocument
from .errors import GameRunningError, WriteVerificationError, WzceError
from .process import GameRunningCheck, is_game_running

if TYPE_CHECKING:  # avoid an import cycle at runtime (backup imports storage)
    from .backup import BackupInfo, BackupManager

AB_SUFFIXES = (".txt0", ".txt1")
SINGLE_SUFFIX = ".txt"
MARKER_SUFFIX = ".m"
_TITLE_RE = re.compile(r"\b(cod\d+)\b")


@dataclass(frozen=True, slots=True)
class LoadedConfig:
    """Result of ``SettingsFileSet.load``."""

    document: ConfigDocument
    source: Path  # slot the document was read from
    # Settings whose value differs between txt0 and txt1 (normally empty or tiny,
    # e.g. WindowMaximized). The UI shows this as a hint; saving re-syncs the slots.
    slot_differences: list[SettingChange] = field(default_factory=list)

    @property
    def slots_in_sync(self) -> bool:
        return not self.slot_differences


@dataclass(frozen=True, slots=True)
class SaveResult:
    written: list[Path]
    backup: BackupInfo | None
    read_only_preserved: list[Path]  # files that were read-only and were restored as such


@dataclass(frozen=True, slots=True)
class SettingsFileSet:
    """One logical settings file: an A/B pair (+ marker) or a single ``.txt`` file."""

    directory: Path
    stem: str  # file name without slot suffix, e.g. "s.1.0.cod25"
    is_ab: bool

    # ----------------------------------------------------------- construction
    @classmethod
    def from_path(cls, path: str | os.PathLike[str]) -> SettingsFileSet:
        """Build from any member of the set (``.txt0``, ``.txt1``, ``.m`` or ``.txt``)."""
        path = Path(path)
        name = path.name
        for suffix in (*AB_SUFFIXES, MARKER_SUFFIX):
            if name.endswith(suffix):
                return cls(path.parent, name[: -len(suffix)], is_ab=True)
        if name.endswith(SINGLE_SUFFIX):
            stem = name[: -len(SINGLE_SUFFIX)]
            # Prefer the A/B layout if its files exist next to the single file.
            is_ab = any((path.parent / f"{stem}{s}").exists() for s in AB_SUFFIXES)
            return cls(path.parent, stem, is_ab=is_ab)
        raise WzceError(f"not a settings file: {name}")

    # -------------------------------------------------------------- properties
    @property
    def slots(self) -> tuple[Path, ...]:
        if self.is_ab:
            return tuple(self.directory / f"{self.stem}{s}" for s in AB_SUFFIXES)
        return (self.directory / f"{self.stem}{SINGLE_SUFFIX}",)

    @property
    def marker(self) -> Path | None:
        return self.directory / f"{self.stem}{MARKER_SUFFIX}" if self.is_ab else None

    @property
    def title_code(self) -> str | None:
        """``"cod25"`` for ``s.1.0.cod25`` - identifies the game title."""
        match = _TITLE_RE.search(self.stem)
        return match.group(1) if match else None

    def existing_files(self) -> list[Path]:
        """All files of the set that exist on disk (slots and marker) - used for backups."""
        candidates = [*self.slots]
        if self.marker is not None:
            candidates.append(self.marker)
        return [p for p in candidates if p.exists()]

    def exists(self) -> bool:
        return any(p.exists() for p in self.slots)

    # ------------------------------------------------------------------- read
    def active_slot_index(self) -> int:
        """Slot the game considers current.

        Order of evidence: marker byte (0/1) -> newest modification time -> 0.
        A marker pointing at a missing slot is ignored.
        """
        if not self.is_ab:
            return 0
        slots = self.slots
        marker = self.marker
        if marker is not None and marker.exists():
            data = marker.read_bytes()
            if data[:1] in (b"\x00", b"\x01") and slots[data[0]].exists():
                return data[0]
        existing = [(p.stat().st_mtime, i) for i, p in enumerate(slots) if p.exists()]
        if not existing:
            raise WzceError(f"no settings file found for {self.stem}")
        return max(existing)[1]

    def load(self) -> LoadedConfig:
        source = self.slots[self.active_slot_index()]
        document = ConfigDocument.from_bytes(source.read_bytes())

        differences: list[SettingChange] = []
        for other in self.slots:
            if other != source and other.exists():
                try:
                    other_doc = ConfigDocument.from_bytes(other.read_bytes())
                except WzceError:
                    continue  # a broken inactive slot is exactly what A/B protects against
                differences = diff_documents(other_doc, document)
        return LoadedConfig(document, source, differences)

    # ------------------------------------------------------------------ write
    def save(
        self,
        document: ConfigDocument,
        *,
        backup_manager: BackupManager | None = None,
        game_running: GameRunningCheck = is_game_running,
        reason: str = "before save",
    ) -> SaveResult:
        """Write ``document`` to every slot. All-or-nothing.

        1. refuse while the game runs (it would overwrite us on exit),
        2. back up the current files (when a manager is given),
        3. write each slot atomically, keeping the read-only attribute,
        4. verify by reading back; on any failure restore what was there before.
        """
        if game_running():
            raise GameRunningError(
                "Close Call of Duty before saving - it rewrites settings on exit"
            )

        data = document.to_bytes()
        ConfigDocument.from_bytes(data)  # never write something we could not read back

        backup = backup_manager.create(self, reason=reason) if backup_manager else None

        originals = {p: (p.read_bytes() if p.exists() else None) for p in self.slots}
        written: list[Path] = []
        preserved: list[Path] = []
        try:
            for path in self.slots:
                if write_atomic(path, data):
                    preserved.append(path)
                written.append(path)
                if path.read_bytes() != data:
                    raise WriteVerificationError(f"verification failed for {path.name}")
        except Exception:
            _rollback(originals, written)
            raise
        return SaveResult(written, backup, preserved)

    # -------------------------------------------------------------- read-only
    def is_read_only(self) -> bool:
        """True when every existing slot has the read-only attribute."""
        existing = [p for p in self.slots if p.exists()]
        return bool(existing) and all(is_read_only(p) for p in existing)

    def set_read_only(self, read_only: bool) -> None:
        """Community trick: read-only slots stop updates from resetting settings.

        Side effect the UI must explain: the game can then no longer save changes
        made in its own menus.
        """
        for path in self.slots:
            if path.exists():
                set_read_only(path, read_only)


# ---------------------------------------------------------------------------
# Low-level file helpers
# ---------------------------------------------------------------------------


def is_read_only(path: Path) -> bool:
    return not (path.stat().st_mode & stat.S_IWRITE)


def set_read_only(path: Path, read_only: bool) -> None:
    # On Windows os.chmod only toggles the FILE_ATTRIBUTE_READONLY flag.
    os.chmod(path, stat.S_IREAD if read_only else stat.S_IREAD | stat.S_IWRITE)


def write_atomic(path: Path, data: bytes) -> bool:
    """Write ``data`` to ``path`` via a temp file + ``os.replace``.

    A crash leaves either the old or the new file, never a truncated one. If the
    target was read-only, the flag is cleared for the write and set again after.
    Returns True when the read-only flag was preserved this way.
    """
    was_read_only = path.exists() and is_read_only(path)
    if was_read_only:
        set_read_only(path, False)
    tmp = path.with_name(f".{path.name}.wzce-tmp")
    try:
        with open(tmp, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()
        if was_read_only and path.exists():
            set_read_only(path, True)
    return was_read_only


def _rollback(originals: dict[Path, bytes | None], written: list[Path]) -> None:
    """Best-effort restore of slots already overwritten during a failed save."""
    for path in written:
        original = originals.get(path)
        with contextlib.suppress(OSError):
            if original is None:
                path.unlink(missing_ok=True)
            else:
                write_atomic(path, original)
