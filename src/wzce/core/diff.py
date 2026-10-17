"""Compare two documents or value snapshots setting-by-setting.

Used by the "pending changes" panel (loaded file vs. edited document), the
history viewer (snapshot vs. snapshot) and to detect changes the game made
behind our back (backup vs. current file).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from .document import ConfigDocument


class ChangeKind(StrEnum):
    CHANGED = "changed"
    ADDED = "added"  # present only in the newer side (e.g. new setting after a game update)
    REMOVED = "removed"


@dataclass(frozen=True, slots=True)
class SettingChange:
    setting_id: str
    kind: ChangeKind
    old_raw: str | None
    new_raw: str | None


def diff_values(before: Mapping[str, str], after: Mapping[str, str]) -> list[SettingChange]:
    """Diff two ``{id: raw_value}`` snapshots. Order: ``after``'s order, then removed ids."""
    changes: list[SettingChange] = []
    for setting_id, new_raw in after.items():
        if setting_id not in before:
            changes.append(SettingChange(setting_id, ChangeKind.ADDED, None, new_raw))
        elif before[setting_id] != new_raw:
            changes.append(
                SettingChange(setting_id, ChangeKind.CHANGED, before[setting_id], new_raw)
            )
    for setting_id, old_raw in before.items():
        if setting_id not in after:
            changes.append(SettingChange(setting_id, ChangeKind.REMOVED, old_raw, None))
    return changes


def diff_documents(before: ConfigDocument, after: ConfigDocument) -> list[SettingChange]:
    return diff_values(before.values(), after.values())
