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
from .i18n import Translator
from .knowledge import KnowledgeBase, KnowledgeEntry, KnowledgeError, localized
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
    "KnowledgeBase",
    "KnowledgeEntry",
    "KnowledgeError",
    "LoadedConfig",
    "ParseError",
    "SaveResult",
    "Scope",
    "Setting",
    "SettingChange",
    "SettingsFileSet",
    "Translator",
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
    "localized",
]
