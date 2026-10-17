"""Core layer: file format, storage, backups, discovery. Must never import Qt.

Public API re-exported here so the UI (and tests) can ``from wzce.core import ...``.
"""

from .backup import BackupInfo, BackupManager
from .diff import ChangeKind, SettingChange, diff_documents, diff_values
from .discovery import ConfigLocation, FileKind, Scope, discover
from .document import ConfigDocument, ValueChange
from .errors import (
    BackupError,
    GameRunningError,
    ParseError,
    UnknownSettingError,
    ValidationError,
    WriteVerificationError,
    WzceError,
)
from .model import Constraint, Setting, ValueType
from .process import is_game_running
from .storage import LoadedConfig, SaveResult, SettingsFileSet

__all__ = [
    "BackupError",
    "BackupInfo",
    "BackupManager",
    "ChangeKind",
    "ConfigDocument",
    "ConfigLocation",
    "Constraint",
    "FileKind",
    "GameRunningError",
    "LoadedConfig",
    "ParseError",
    "SaveResult",
    "Scope",
    "Setting",
    "SettingChange",
    "SettingsFileSet",
    "UnknownSettingError",
    "ValidationError",
    "ValueChange",
    "ValueType",
    "WriteVerificationError",
    "WzceError",
    "diff_documents",
    "diff_values",
    "discover",
    "is_game_running",
]
