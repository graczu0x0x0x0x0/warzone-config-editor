"""Templates: named sets of setting values that can be saved, shared and applied.

A template is ``{setting id: raw value}`` plus metadata. Sources:

* BUILTIN - generated on the fly from the knowledge base presets
  (competitive / balanced / quality / low_end)
* USER    - saved by the user from the current settings, or imported from a
  template ``.json`` or from someone else's game settings file

Hardware-specific values (GPU/monitor names, audio device ids, window geometry,
detected hardware, driver versions) are NEVER stored in a template - they would
be wrong on any other PC. ``plan_template`` enforces the same rules again when
applying, so a hand-edited template file cannot sneak them in either.

Applying is a two-step process so the UI can show a preview:
``plan_template()`` -> ``TemplatePlan`` (changes / unchanged / skipped with reasons),
then ``EditorSession.apply_raw_values`` with the changes the user kept.

File format (``*.json``)::

    {"format": "wzce-template", "version": 1, "name": "...", "description": "...",
     "created": "2026-10-17T12:00:00", "title_code": "cod25",
     "groups": ["display", "quality"], "values": {"VSync@0": "disabled", ...}}
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from .diff import same_value
from .document import ConfigDocument
from .errors import ValidationError, WzceError
from .knowledge import KnowledgeBase, KnowledgeEntry, localized
from .model import Setting
from .paths import app_data_dir

FORMAT_ID = "wzce-template"
FORMAT_VERSION = 1
TEMPLATE_SUFFIX = ".json"


class TemplateError(WzceError):
    """A template file is missing, malformed or not a template at all."""


class TemplateSource(StrEnum):
    BUILTIN = "builtin"
    USER = "user"


class SkipReason(StrEnum):
    MISSING = "missing"  # setting does not exist in this file (other title/version)
    MANAGED = "managed"  # read-only or written by the game itself
    HARDWARE = "hardware"  # hardware-specific value, never copied between PCs
    VENDOR = "vendor"  # only relevant for another GPU vendor
    INVALID = "invalid"  # value not accepted by this file (e.g. option removed)


@dataclass(slots=True)
class Template:
    name: str
    values: dict[str, str]
    description: str = ""
    groups: list[str] = field(default_factory=list)  # editor categories it covers
    title_code: str | None = None  # game title it was made from (informational)
    created: datetime = field(default_factory=datetime.now)
    source: TemplateSource = TemplateSource.USER
    path: Path | None = None  # file backing a USER template
    builtin_id: str | None = None  # preset id for BUILTIN templates

    # ------------------------------------------------------------- serialize
    def to_json(self) -> str:
        payload = {
            "format": FORMAT_ID,
            "version": FORMAT_VERSION,
            "name": self.name,
            "description": self.description,
            "created": self.created.isoformat(timespec="seconds"),
            "title_code": self.title_code,
            "groups": self.groups,
            "values": self.values,
        }
        return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"

    @classmethod
    def from_json(cls, text: str, *, path: Path | None = None) -> Template:
        where = path.name if path else "template"
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise TemplateError(f"{where}: invalid JSON ({exc})") from exc
        if not isinstance(data, dict) or data.get("format") != FORMAT_ID:
            raise TemplateError(f"{where}: not a Warzone Config Editor template")
        if int(data.get("version", 0)) > FORMAT_VERSION:
            raise TemplateError(f"{where}: made by a newer version of the editor")
        name = data.get("name")
        values = data.get("values")
        if not isinstance(name, str) or not name.strip():
            raise TemplateError(f"{where}: missing name")
        if not isinstance(values, dict) or not all(
            isinstance(k, str) and "@" in k and isinstance(v, str) for k, v in values.items()
        ):
            raise TemplateError(f"{where}: 'values' must map Key@Variant to text")
        groups = data.get("groups", [])
        if not isinstance(groups, list) or not all(isinstance(g, str) for g in groups):
            raise TemplateError(f"{where}: 'groups' must be a list of names")
        try:
            created = datetime.fromisoformat(data.get("created", ""))
        except (TypeError, ValueError):
            created = datetime.now()
        return cls(
            name=name.strip(),
            values=dict(values),
            description=str(data.get("description") or ""),
            groups=list(groups),
            title_code=data.get("title_code"),
            created=created,
            source=TemplateSource.USER,
            path=path,
        )


# ---------------------------------------------------------------------------
# What may go into / come out of a template
# ---------------------------------------------------------------------------


def exclusion_reason(setting: Setting, entry: KnowledgeEntry) -> SkipReason | None:
    """Why a setting must never be copied by a template (None = it may)."""
    if setting.read_only or "game_managed" in entry.flags:
        return SkipReason.MANAGED
    if entry.hardware_specific:
        return SkipReason.HARDWARE
    return None


def template_from_document(
    document: ConfigDocument,
    knowledge: KnowledgeBase,
    name: str,
    *,
    groups: Iterable[str] | None = None,
    description: str = "",
    title_code: str | None = None,
) -> Template:
    """Capture the current values of the chosen categories (all when ``groups`` is None)."""
    wanted = set(groups) if groups is not None else None
    values: dict[str, str] = {}
    used_groups: list[str] = []
    for setting in document:
        entry = knowledge.entry_for(setting)
        if wanted is not None and entry.group not in wanted:
            continue
        if exclusion_reason(setting, entry) is not None:
            continue
        values[setting.id] = setting.raw_value
        if entry.group not in used_groups:
            used_groups.append(entry.group)
    order = [g.id for g in knowledge.groups]
    used_groups.sort(key=lambda g: order.index(g) if g in order else len(order))
    return Template(
        name=name, values=values, description=description, groups=used_groups, title_code=title_code
    )


def builtin_templates(
    knowledge: KnowledgeBase, document: ConfigDocument, language: str
) -> list[Template]:
    """Knowledge-base presets as templates, values formatted for ``document``.

    Recommendations that do not fit this file (removed options, missing settings)
    are left out here; ``plan_template`` would report them anyway.
    """
    result = []
    for preset in knowledge.presets:
        values: dict[str, str] = {}
        groups: list[str] = []
        for setting_id, value in knowledge.preset_values(preset.id).items():
            if setting_id not in document:
                continue
            setting = document.get(setting_id)
            if exclusion_reason(setting, knowledge.entries[setting_id]) is not None:
                continue  # same rule as user templates: no hardware/managed values
            try:
                values[setting_id] = setting.format_value(value)
            except ValidationError:
                continue
            group = knowledge.entries[setting_id].group
            if group not in groups:
                groups.append(group)
        order = [g.id for g in knowledge.groups]
        groups.sort(key=lambda g: order.index(g) if g in order else len(order))
        result.append(
            Template(
                name=localized(preset.label, language),
                description=localized(preset.desc, language),
                values=values,
                groups=groups,
                source=TemplateSource.BUILTIN,
                builtin_id=preset.id,
            )
        )
    return result


# ---------------------------------------------------------------------------
# Applying: preview plan
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PlannedChange:
    setting_id: str
    old_raw: str
    new_raw: str


@dataclass(slots=True)
class TemplatePlan:
    changes: list[PlannedChange] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    skipped: dict[str, SkipReason] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)  # INVALID details per id

    def values(self, only: Iterable[str] | None = None) -> dict[str, str]:
        """``{id: new raw}`` of the planned changes (optionally just the ``only`` ids)."""
        keep = set(only) if only is not None else None
        return {
            c.setting_id: c.new_raw for c in self.changes if keep is None or c.setting_id in keep
        }


def plan_template(
    document: ConfigDocument,
    knowledge: KnowledgeBase,
    values: Mapping[str, object],
    *,
    gpu_vendor: str | None = None,
) -> TemplatePlan:
    """Work out what applying ``values`` to ``document`` would do, without changing it."""
    plan = TemplatePlan()
    for setting_id, value in values.items():
        if setting_id not in document:
            plan.skipped[setting_id] = SkipReason.MISSING
            continue
        setting = document.get(setting_id)
        entry = knowledge.entry_for(setting)
        reason = exclusion_reason(setting, entry)
        if reason is None and gpu_vendor and entry.vendor and entry.vendor != gpu_vendor:
            reason = SkipReason.VENDOR
        if reason is not None:
            plan.skipped[setting_id] = reason
            continue
        try:
            new_raw = setting.format_value(value)
        except ValidationError as exc:
            plan.skipped[setting_id] = SkipReason.INVALID
            plan.errors[setting_id] = str(exc)
            continue
        if same_value(new_raw, setting.raw_value):
            plan.unchanged.append(setting_id)
        else:
            plan.changes.append(PlannedChange(setting_id, setting.raw_value, new_raw))
    return plan


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:60] or "template"


class TemplateStore:
    """User templates as JSON files in ``<app data>/templates``."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root if root is not None else app_data_dir() / "templates"

    def list(self) -> list[Template]:
        """User templates sorted by name; unreadable files are skipped."""
        if not self.root.is_dir():
            return []
        templates = []
        for path in self.root.glob(f"*{TEMPLATE_SUFFIX}"):
            try:
                templates.append(load_template(path))
            except TemplateError:
                continue
        templates.sort(key=lambda t: t.name.lower())
        return templates

    def save(self, template: Template) -> Template:
        """Write a new file (or overwrite ``template.path`` if it lives in this store)."""
        self.root.mkdir(parents=True, exist_ok=True)
        path = template.path
        if path is None or path.parent != self.root:
            path = self._free_path(_slug(template.name))
        path.write_text(template.to_json(), encoding="utf-8")
        template.path = path
        template.source = TemplateSource.USER
        return template

    def _free_path(self, slug: str) -> Path:
        candidate, counter = self.root / f"{slug}{TEMPLATE_SUFFIX}", 2
        while candidate.exists():
            candidate = self.root / f"{slug}-{counter}{TEMPLATE_SUFFIX}"
            counter += 1
        return candidate

    def delete(self, template: Template) -> None:
        if template.source is not TemplateSource.USER or template.path is None:
            raise TemplateError("only your own templates can be deleted")
        if template.path.parent != self.root:
            raise TemplateError("template is not stored in the templates folder")
        template.path.unlink(missing_ok=True)

    def import_file(self, path: Path) -> Template:
        """Copy a template ``.json`` from anywhere into the store (as a new file)."""
        template = load_template(path)
        template.path = None
        return self.save(template)


def load_template(path: Path) -> Template:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise TemplateError(f"{path.name}: cannot read ({exc})") from exc
    return Template.from_json(text, path=path)


def export_template(template: Template, path: Path) -> Path:
    """Write a shareable copy (a built-in preset exports with its formatted values)."""
    path.write_text(template.to_json(), encoding="utf-8")
    return path
