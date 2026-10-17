"""Data model for one setting line and its value domain.

A setting line in the game file looks like::

    ShadowQuality@0;3981;58629 = Very_Low // one of Very_Low, Low, Medium, High, Very_High
    └─ key ─────┘ └┘ └──┘ └───┘   └ value ┘    └─ constraint ─────────────────────────┘
               variant type_id default_id

See ``docs/FILE_FORMAT.md`` for the full grammar. This module only knows about a
single setting; the whole file (ordering, comments, sections) is ``ConfigDocument``
in ``document.py``.

Design rule: we keep the *raw text* of everything and only regenerate the value
part of a line when the user changes it. That is what gives the byte-exact
round-trip guarantee.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum

from .errors import ValidationError

# Marker the developers put into descriptions of settings the game owns
# (detected hardware, driver versions...). The editor shows them read-only.
DO_NOT_MODIFY_MARKER = "DO NOT MODIFY"

# Ranges wider than this are "technically bounded" (e.g. 0 to 2147483647) and make
# no sense as a slider. The UI uses ``Constraint.is_slider_friendly`` to decide.
SLIDER_MAX_SPAN = 100_000

# Floats are always serialized with 6 decimals by the game ("0.850000").
FLOAT_DECIMALS = 6


class ValueType(StrEnum):
    """Kind of value a setting holds; drives validation and the UI widget choice."""

    BOOL = "bool"
    INT = "int"
    FLOAT = "float"
    ENUM = "enum"
    STRING = "string"  # free text: device GUIDs, GPU/monitor names, "Auto", versions...


@dataclass(frozen=True, slots=True)
class Constraint:
    """Value domain parsed from the trailing ``// ...`` comment of a setting line.

    Exactly one of the two shapes is used:
      * range:  ``min_value``/``max_value`` set, ``options`` empty
      * enum:   ``options`` non-empty, min/max are ``None``
    ``raw`` keeps the original comment text (without the leading ``// ``) so it can
    be written back untouched.
    """

    raw: str
    min_value: float | None = None
    max_value: float | None = None
    options: tuple[str, ...] = ()
    is_float_range: bool = False  # True when the bounds are written with decimals

    @property
    def is_enum(self) -> bool:
        return bool(self.options)

    @property
    def is_range(self) -> bool:
        return self.min_value is not None and self.max_value is not None

    @property
    def is_slider_friendly(self) -> bool:
        """True when the range is small enough for a slider (UI hint)."""
        if not self.is_range:
            return False
        assert self.min_value is not None and self.max_value is not None
        return (self.max_value - self.min_value) <= SLIDER_MAX_SPAN

    @classmethod
    def parse(cls, raw: str) -> Constraint | None:
        """Parse the comment after ``//``. Returns ``None`` for unrecognized text.

        Unknown comment shapes are not an error: the setting simply becomes
        unconstrained and the raw comment is still preserved by the document.
        """
        text = raw.strip()
        if text.startswith("one of "):
            # Options may contain spaces, '+', '%', ':' and '.' ("Enabled + boost",
            # "wide 19.5:9") but never ", " - so that is a safe separator.
            options = tuple(opt for opt in text[len("one of ") :].split(", "))
            if options and all(options):
                return cls(raw=raw, options=options)
            return None
        lo, sep, hi = text.partition(" to ")
        if sep:
            try:
                min_value, max_value = float(lo), float(hi)
            except ValueError:
                return None
            is_float = "." in lo or "." in hi
            return cls(raw=raw, min_value=min_value, max_value=max_value, is_float_range=is_float)
        return None


@dataclass(slots=True)
class Setting:
    """One ``Key@Variant;TypeId;DefaultId = Value // Constraint`` line.

    ``prefix`` is the exact text before the value (``"Key@0;1;2 = "``) and
    ``suffix`` the exact text after it (``" // 0 to 1"`` or ``""``). Rebuilding a
    line is therefore ``prefix + raw_value + suffix`` - nothing else changes.
    """

    key: str
    variant: int
    type_id: int
    default_id: int
    raw_value: str
    constraint: Constraint | None
    prefix: str
    suffix: str
    line_index: int  # 0-based index into ConfigDocument.lines
    description: str = ""
    section: str | None = None  # None for settings outside any "// Section" block
    value_type: ValueType = field(init=False)

    def __post_init__(self) -> None:
        self.value_type = infer_value_type(self.raw_value, self.constraint)

    # ----------------------------------------------------------------- identity
    @property
    def id(self) -> str:
        """Unique identity inside a file. ``Key`` alone is NOT unique (``DxrMode@0`` vs ``@1``)."""
        return f"{self.key}@{self.variant}"

    @property
    def read_only(self) -> bool:
        """The game marks some values it owns with "DO NOT MODIFY"."""
        return DO_NOT_MODIFY_MARKER in self.description

    @property
    def line(self) -> str:
        """The full line as it must appear in the file (without newline)."""
        return f"{self.prefix}{self.raw_value}{self.suffix}"

    # -------------------------------------------------------------------- value
    @property
    def value(self) -> bool | int | float | str:
        """Current value converted to a Python type matching ``value_type``."""
        return parse_raw_value(self.raw_value, self.value_type)

    def format_value(self, value: object) -> str:
        """Validate ``value`` for this setting and return its raw file representation.

        Accepts native Python values (``True``, ``120``, ``0.85``) as well as strings
        as typed by the user (``"true"``, ``"120"``). Raises ``ValidationError``.
        """
        return format_value(value, self.value_type, self.constraint, setting_id=self.id)


# ---------------------------------------------------------------------------
# Type inference and value conversion (module-level so they are easy to test).
# ---------------------------------------------------------------------------


def infer_value_type(raw_value: str, constraint: Constraint | None) -> ValueType:
    """Decide the value type from the constraint first, then from the value itself.

    Unconstrained numeric-looking values (``DisplayDriverVersion = 617.42``) are
    deliberately treated as STRING: they are versions/ids, and re-formatting them
    as floats ("617.420000") would corrupt them.
    """
    if constraint is not None:
        if constraint.is_enum:
            return ValueType.ENUM
        if constraint.is_range:
            return ValueType.FLOAT if constraint.is_float_range else ValueType.INT
    if raw_value in ("true", "false"):
        return ValueType.BOOL
    return ValueType.STRING


def parse_raw_value(raw: str, value_type: ValueType) -> bool | int | float | str:
    """Convert raw file text to a Python value. Falls back to the raw string on oddities."""
    try:
        match value_type:
            case ValueType.BOOL:
                return raw == "true"
            case ValueType.INT:
                return int(raw)
            case ValueType.FLOAT:
                return float(raw)
    except ValueError:
        # A value the game wrote but we cannot interpret - never crash on load.
        return raw
    return raw


_TRUE_WORDS = {"true", "1", "yes", "on"}
_FALSE_WORDS = {"false", "0", "no", "off"}


def format_value(
    value: object,
    value_type: ValueType,
    constraint: Constraint | None,
    *,
    setting_id: str = "",
) -> str:
    """Validate a value and serialize it exactly the way the game writes it."""
    where = f"{setting_id}: " if setting_id else ""

    match value_type:
        case ValueType.BOOL:
            if isinstance(value, bool):
                return "true" if value else "false"
            word = str(value).strip().lower()
            if word in _TRUE_WORDS:
                return "true"
            if word in _FALSE_WORDS:
                return "false"
            raise ValidationError(f"{where}expected true/false, got {value!r}")

        case ValueType.ENUM:
            assert constraint is not None
            text = str(value)
            if text in constraint.options:
                return text
            # Be forgiving about case ("very low" vs "Very Low") but write the
            # canonical spelling from the file - the game compares exactly.
            for option in constraint.options:
                if option.lower() == text.strip().lower():
                    return option
            raise ValidationError(f"{where}{text!r} is not one of: {', '.join(constraint.options)}")

        case ValueType.INT:
            number = _to_number(value, where)
            if not float(number).is_integer():
                raise ValidationError(f"{where}expected a whole number, got {value!r}")
            as_int = int(number)
            _check_range(as_int, constraint, where)
            return str(as_int)

        case ValueType.FLOAT:
            number = float(_to_number(value, where))
            if not math.isfinite(number):
                raise ValidationError(f"{where}value must be a finite number")
            # Round first so that e.g. 1.0000004 is accepted for a max of 1.0.
            number = round(number, FLOAT_DECIMALS)
            _check_range(number, constraint, where)
            return f"{number:.{FLOAT_DECIMALS}f}"

        case ValueType.STRING:
            text = str(value)
            # A newline would break the line-based format, and " // " would be
            # read back as the start of a constraint comment.
            if "\n" in text or "\r" in text:
                raise ValidationError(f"{where}text must be a single line")
            if " // " in text:
                raise ValidationError(f"{where}text must not contain ' // '")
            if text != text.strip():
                raise ValidationError(f"{where}text must not start or end with spaces")
            return text

    raise ValidationError(f"{where}unsupported value type {value_type}")  # pragma: no cover


def _to_number(value: object, where: str) -> float | int:
    if isinstance(value, bool):  # bool is an int subclass - reject it explicitly
        raise ValidationError(f"{where}expected a number, got {value!r}")
    if isinstance(value, int | float):
        return value
    text = str(value).strip().replace(",", ".")  # Polish users type "0,85"
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        raise ValidationError(f"{where}expected a number, got {value!r}") from None


def _check_range(number: float, constraint: Constraint | None, where: str) -> None:
    if constraint is None or not constraint.is_range:
        return
    assert constraint.min_value is not None and constraint.max_value is not None
    if not constraint.min_value <= number <= constraint.max_value:
        lo, hi = _pretty(constraint.min_value), _pretty(constraint.max_value)
        raise ValidationError(f"{where}{_pretty(number)} is outside the range {lo} to {hi}")


def _pretty(number: float) -> str:
    return str(int(number)) if float(number).is_integer() else f"{number:g}"
