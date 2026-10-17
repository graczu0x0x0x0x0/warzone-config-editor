"""Parse and serialize a whole settings file with a byte-exact round-trip guarantee.

The document keeps every original line. Settings are views onto specific lines;
changing a value rewrites only that one line, so comments, blank lines, ordering,
line endings, BOM and the trailing newline all survive untouched.

File layout recap (see docs/FILE_FORMAT.md)::

    1                       <- format version (line 1)
                            <- two blank lines end a section
    //                      <- bare "//" announces a section header
    // Audio                <- section name
                            <- one blank line between entries
    // Adjusts ...          <- description of the next setting
    Volume@0;14317;21371 = 1.000000 // 0.000000 to 1.000000
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass

from .errors import ParseError, UnknownSettingError, ValidationError
from .model import Constraint, Setting

# Key may contain spaces ("Handheld Fov") but never '@'. The three numbers are
# copied verbatim on write - see FILE_FORMAT.md section "Meaning of the two numbers".
_SETTING_RE = re.compile(
    r"^(?P<key>[^@]+)@(?P<variant>\d+);(?P<type_id>\d+);(?P<default_id>\d+) =(?P<rest>.*)$"
)
_CONSTRAINT_SEP = " // "
_UTF8_BOM = b"\xef\xbb\xbf"


@dataclass(frozen=True, slots=True)
class ValueChange:
    """Result of a single successful ``set_value`` call (used by undo/history)."""

    setting_id: str
    old_raw: str
    new_raw: str

    @property
    def is_noop(self) -> bool:
        return self.old_raw == self.new_raw


class ConfigDocument:
    """In-memory representation of one ``s.1.0.codNN.txtX`` (or account ``g.codNN...``) file."""

    def __init__(
        self,
        lines: list[str],
        line_has_cr: list[bool],
        trailing_newline: bool,
        has_bom: bool,
    ) -> None:
        # Use ConfigDocument.parse / from_bytes instead of calling this directly.
        self.lines = lines
        self._line_has_cr = line_has_cr
        self.trailing_newline = trailing_newline
        self.has_bom = has_bom
        self.format_version: int | None = None
        self.settings: list[Setting] = []
        self._by_id: dict[str, Setting] = {}
        # Non-fatal oddities found while parsing (unknown lines, duplicate ids).
        # Shown to the user as diagnostics; the lines themselves are preserved.
        self.warnings: list[str] = []

    # ------------------------------------------------------------------ parsing
    @classmethod
    def from_bytes(cls, data: bytes) -> ConfigDocument:
        has_bom = data.startswith(_UTF8_BOM)
        if has_bom:
            data = data[len(_UTF8_BOM) :]
        # surrogateescape keeps any non-UTF-8 byte (e.g. an odd monitor name in a
        # legacy code page) intact through decode -> encode.
        return cls.parse(data.decode("utf-8", errors="surrogateescape"), _has_bom=has_bom)

    @classmethod
    def parse(cls, text: str, *, _has_bom: bool = False) -> ConfigDocument:
        """Parse file text. Raises ``ParseError`` if no setting line is found at all."""
        if text.startswith("﻿"):  # BOM passed in as text
            text = text[1:]
            _has_bom = True

        # Split on "\n" only and remember a trailing "\r" per line: this preserves
        # LF, CRLF and even mixed files exactly.
        parts = text.split("\n")
        trailing_newline = parts[-1] == ""
        if trailing_newline:
            parts.pop()
        line_has_cr = [p.endswith("\r") for p in parts]
        lines = [p[:-1] if cr else p for p, cr in zip(parts, line_has_cr, strict=True)]

        doc = cls(lines, line_has_cr, trailing_newline, _has_bom)
        doc._index_lines()
        if not doc.settings:
            raise ParseError("no settings found - this does not look like a Call of Duty config")
        return doc

    def _index_lines(self) -> None:
        """Walk the lines once and build Setting objects with section/description context."""
        section: str | None = None
        expecting_section_name = False
        description_parts: list[str] = []
        blank_run = 0

        for index, line in enumerate(self.lines):
            stripped = line.strip()

            if index == 0 and stripped.isdigit():
                self.format_version = int(stripped)
                continue

            if not stripped:
                blank_run += 1
                description_parts.clear()
                if blank_run >= 2:
                    # Two blank lines close a section. The game puts a few settings
                    # after "System" without a header - they must not be filed
                    # under System, so they get section None ("Other").
                    section = None
                continue
            blank_run = 0

            if stripped == "//":
                expecting_section_name = True
                description_parts.clear()
                continue

            if stripped.startswith("//"):
                comment = stripped[2:].strip()
                if expecting_section_name:
                    section = comment
                    expecting_section_name = False
                else:
                    description_parts.append(comment)
                continue

            expecting_section_name = False
            setting = self._parse_setting_line(line, index)
            if setting is None:
                self.warnings.append(f"line {index + 1}: unrecognized line kept as-is: {line!r}")
                description_parts.clear()
                continue

            setting.section = section
            setting.description = " ".join(description_parts)
            description_parts.clear()
            self.settings.append(setting)
            if setting.id in self._by_id:
                self.warnings.append(
                    f"line {index + 1}: duplicate setting {setting.id}; first occurrence wins"
                )
            else:
                self._by_id[setting.id] = setting

    @staticmethod
    def _parse_setting_line(line: str, index: int) -> Setting | None:
        match = _SETTING_RE.match(line)
        if match is None:
            return None
        rest = match["rest"]
        prefix = line[: match.start("rest")]  # "Key@0;1;2 ="
        had_space = rest.startswith(" ")
        body = rest[1:] if had_space else rest

        if body.startswith("// "):
            # Empty value followed directly by a constraint ("Key@0;1;2 = // 0 to 1").
            # Keep the separator inside the suffix; set_value re-adds spacing.
            raw_value, suffix = "", rest
        else:
            if had_space:
                prefix += " "
            raw_value, sep, comment = body.partition(_CONSTRAINT_SEP)
            suffix = sep + comment
        constraint = Constraint.parse(suffix.lstrip()[len("// ") :]) if suffix else None

        return Setting(
            key=match["key"],
            variant=int(match["variant"]),
            type_id=int(match["type_id"]),
            default_id=int(match["default_id"]),
            raw_value=raw_value,
            constraint=constraint,
            prefix=prefix,
            suffix=suffix,
            line_index=index,
        )

    # ------------------------------------------------------------ serializing
    def to_text(self) -> str:
        body = "\n".join(
            line + ("\r" if cr else "")
            for line, cr in zip(self.lines, self._line_has_cr, strict=True)
        )
        if self.trailing_newline:
            body += "\n"
        return body

    def to_bytes(self) -> bytes:
        data = self.to_text().encode("utf-8", errors="surrogateescape")
        return (_UTF8_BOM + data) if self.has_bom else data

    def copy(self) -> ConfigDocument:
        """Independent deep copy (cheap: files are ~16 KB)."""
        return ConfigDocument.from_bytes(self.to_bytes())

    # ----------------------------------------------------------------- access
    def __iter__(self) -> Iterator[Setting]:
        return iter(self.settings)

    def __len__(self) -> int:
        return len(self.settings)

    def __contains__(self, setting_id: object) -> bool:
        return setting_id in self._by_id

    def get(self, setting_id: str) -> Setting:
        try:
            return self._by_id[setting_id]
        except KeyError:
            raise UnknownSettingError(f"unknown setting {setting_id}") from None

    @property
    def ids(self) -> list[str]:
        return list(self._by_id)

    @property
    def sections(self) -> list[str | None]:
        """Section names in file order (``None`` = settings outside any section)."""
        seen: dict[str | None, None] = {}
        for setting in self.settings:
            seen.setdefault(setting.section, None)
        return list(seen)

    def values(self) -> dict[str, str]:
        """Snapshot ``{id: raw_value}`` - the format used by templates and history."""
        return {s.id: s.raw_value for s in self._by_id.values()}

    # --------------------------------------------------------------- mutation
    def set_value(
        self, setting_id: str, value: object, *, allow_read_only: bool = False
    ) -> ValueChange:
        """Validate and apply one value; only the setting's own line is rewritten.

        ``value`` may be a Python value or user-typed text; it is normalized to the
        game's exact spelling (``0.85`` -> ``"0.850000"``, ``"very low"`` -> ``"Very Low"``).
        """
        setting = self.get(setting_id)
        if setting.read_only and not allow_read_only:
            raise ValidationError(f"{setting_id} is managed by the game (DO NOT MODIFY)")
        new_raw = setting.format_value(value)
        change = ValueChange(setting_id, setting.raw_value, new_raw)
        if change.is_noop:
            return change

        if new_raw:
            # The line had an empty value ("Key =" / "Key = // c"); restore the
            # canonical "Key = value // c" spacing around the new value.
            if not setting.prefix.endswith(" "):
                setting.prefix += " "
            if setting.suffix and not setting.suffix.startswith(" "):
                setting.suffix = " " + setting.suffix
        setting.raw_value = new_raw
        self.lines[setting.line_index] = setting.line
        return change

    def apply_values(
        self,
        values: Mapping[str, object],
        *,
        allow_read_only: bool = False,
    ) -> tuple[list[ValueChange], dict[str, str]]:
        """Apply many values (template / history restore) without stopping on errors.

        Returns ``(applied_changes, errors)`` where ``errors`` maps setting id to a
        human-readable reason (unknown in this file, invalid value, read-only).
        Unknown ids are normal: a template made for cod25 may be applied to cod26.
        """
        applied: list[ValueChange] = []
        errors: dict[str, str] = {}
        for setting_id, value in values.items():
            try:
                change = self.set_value(setting_id, value, allow_read_only=allow_read_only)
            except (UnknownSettingError, ValidationError) as exc:
                errors[setting_id] = str(exc)
                continue
            if not change.is_noop:
                applied.append(change)
        return applied, errors
