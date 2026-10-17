"""Compare two documents or value snapshots setting-by-setting.

Used by the "pending changes" panel (loaded file vs. edited document), the
history viewer (snapshot vs. snapshot) and to detect changes the game made
behind our back (backup vs. current file).
"""

from __future__ import annotations

import math
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


# The game keeps floats as 32-bit internally and writes them back with 6 decimals,
# so a value we saved as "119.900000" comes back as "119.900002" (observed in the
# account-file test, 2026-10-17). Such differences are not real changes.
FLOAT_REL_TOLERANCE = 1e-6
FLOAT_ABS_TOLERANCE = 1e-5


def same_value(a: str, b: str) -> bool:
    """Raw values equal, or both decimal numbers equal up to float32 round-off."""
    if a == b:
        return True
    if "." not in a and "." not in b:
        return False  # integers / words: exact comparison only
    try:
        x, y = float(a), float(b)
    except ValueError:
        return False
    return math.isclose(x, y, rel_tol=FLOAT_REL_TOLERANCE, abs_tol=FLOAT_ABS_TOLERANCE)


def diff_values(before: Mapping[str, str], after: Mapping[str, str]) -> list[SettingChange]:
    """Diff two ``{id: raw_value}`` snapshots. Order: ``after``'s order, then removed ids."""
    changes: list[SettingChange] = []
    for setting_id, new_raw in after.items():
        if setting_id not in before:
            changes.append(SettingChange(setting_id, ChangeKind.ADDED, None, new_raw))
        elif not same_value(before[setting_id], new_raw):
            changes.append(
                SettingChange(setting_id, ChangeKind.CHANGED, before[setting_id], new_raw)
            )
    for setting_id, old_raw in before.items():
        if setting_id not in after:
            changes.append(SettingChange(setting_id, ChangeKind.REMOVED, old_raw, None))
    return changes


def diff_documents(before: ConfigDocument, after: ConfigDocument) -> list[SettingChange]:
    return diff_values(before.values(), after.values())
