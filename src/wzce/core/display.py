"""Human-readable rendering of raw setting values (shared by the UI and exports).

Kept Qt-free so the share export (Markdown/JSON) shows values exactly like the
cards, the changes panel and the history do.
"""

from __future__ import annotations

from .i18n import Translator
from .knowledge import KnowledgeEntry
from .model import Setting, ValueType, parse_raw_value

# The game stores floats via float32 (0.75 may come back as 0.750001); four decimals
# are plenty for every setting and hide that noise.
DISPLAY_DECIMALS = 4


def _number(value: float) -> str:
    return f"{round(value, DISPLAY_DECIMALS):g}"


def display_value(raw: str, setting: Setting, entry: KnowledgeEntry, tr: Translator) -> str:
    """Human-readable form of a raw value: translated booleans and options, units, %."""
    if raw == "":
        return tr("value.empty")
    match setting.value_type:
        case ValueType.BOOL:
            return tr("value.true" if raw == "true" else "value.false")
        case ValueType.ENUM:
            return entry.option_label(raw, tr.language)
        case ValueType.FLOAT:
            value = parse_raw_value(raw, ValueType.FLOAT)
            if isinstance(value, float):
                if entry.widget == "percent":
                    return f"{_number(value * 100)} %"
                return _number(value) + (f" {entry.unit}" if entry.unit else "")
        case ValueType.INT:
            return raw + (f" {entry.unit}" if entry.unit else "")
    return raw
