"""Knowledge base: human-friendly metadata for every known setting.

The game file only tells us *what* a value can be (type, range, options) and a
terse English comment. The knowledge base adds what the UI needs on top:

* editor category (group/subgroup) - the game's own 7 sections are too coarse
* label and full description in English and Polish
* estimated impact on FPS / input latency / enemy visibility / VRAM (0..3)
* recommended value per preset (competitive, balanced, quality, low_end)
* flags (advanced, hardware_specific...), GPU vendor, widget hints, units

Data lives in ``wzce/data/settings_db/``: ``_meta.json`` (groups, presets) plus
one JSON file per group. Schema: ``docs/KNOWLEDGE_BASE.md``.

Settings not in the knowledge base (e.g. added by a game update) still get a
synthesized entry from the file itself - see ``KnowledgeBase.entry_for``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

from .errors import WzceError
from .model import Setting

SUPPORTED_LANGUAGES: tuple[str, ...] = ("en", "pl")
DEFAULT_LANGUAGE = "en"
META_FILE = "_meta.json"

IMPACT_DIMENSIONS: tuple[str, ...] = ("fps", "latency", "visibility", "vram")
IMPACT_MAX = 3

# Closed vocabularies - the loader rejects anything else to catch typos early.
FLAGS = frozenset(
    {
        "advanced",  # hidden in "simple" mode
        "hardware_specific",  # never stored in shareable templates (GPU name, devices, window)
        "game_managed",  # written by the game itself; editable but rarely useful
        "new",  # synthesized: not in the knowledge base yet
    }
)
VENDORS = frozenset({"nvidia", "amd", "intel"})
WIDGETS = frozenset(
    {
        "percent",  # 0..1 float shown as 0..100 %
        "spin",  # force a spin box even when a slider would fit
        "device",  # audio device id (future: pick from Windows devices)
        "text",  # free text field
    }
)
# Hardware-dependent recommendations computed by the optimizer (PLAN stage 6).
RULES = frozenset({"physical_cores", "vram_fraction", "refresh_rate_cap"})

LocalizedText = Mapping[str, str]


class KnowledgeError(WzceError):
    """The knowledge base JSON is malformed (a developer error, caught by tests)."""


def localized(text: LocalizedText | None, language: str) -> str:
    """Pick ``language`` with English fallback; empty string when nothing is available."""
    if not text:
        return ""
    return text.get(language) or text.get(DEFAULT_LANGUAGE) or ""


def humanize_key(key: str) -> str:
    """``MaxFpsInGame`` -> ``Max Fps In Game`` (label for settings we know nothing about)."""
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", key)
    return spaced.replace("_", " ").strip()


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Subgroup:
    id: str
    label: LocalizedText


@dataclass(frozen=True, slots=True)
class Group:
    id: str
    icon: str
    label: LocalizedText
    subgroups: tuple[Subgroup, ...]

    def subgroup(self, subgroup_id: str) -> Subgroup | None:
        return next((s for s in self.subgroups if s.id == subgroup_id), None)


@dataclass(frozen=True, slots=True)
class Preset:
    id: str
    label: LocalizedText
    desc: LocalizedText


@dataclass(frozen=True, slots=True)
class Impact:
    fps: int = 0
    latency: int = 0
    visibility: int = 0
    vram: int = 0

    def as_dict(self) -> dict[str, int]:
        return {dim: getattr(self, dim) for dim in IMPACT_DIMENSIONS}

    @property
    def max(self) -> int:
        return max(self.as_dict().values())


@dataclass(frozen=True, slots=True)
class KnowledgeEntry:
    setting_id: str
    group: str
    subgroup: str | None
    label: LocalizedText
    desc: LocalizedText
    impact: Impact = field(default_factory=Impact)
    recommend: Mapping[str, Any] = field(default_factory=dict)  # preset id -> value
    tip: LocalizedText = field(default_factory=dict)  # why the recommendation
    flags: frozenset[str] = frozenset()
    vendor: str | None = None
    widget: str | None = None
    unit: str | None = None
    rule: str | None = None
    options: Mapping[str, LocalizedText] = field(default_factory=dict)  # enum option labels
    related: tuple[str, ...] = ()

    @property
    def known(self) -> bool:
        return "new" not in self.flags

    @property
    def advanced(self) -> bool:
        return "advanced" in self.flags

    @property
    def hardware_specific(self) -> bool:
        return "hardware_specific" in self.flags

    def option_label(self, option: str, language: str) -> str:
        """Display label of an enum option; falls back to the raw game spelling."""
        return localized(self.options.get(option), language) or option


# ---------------------------------------------------------------------------
# Knowledge base
# ---------------------------------------------------------------------------


class KnowledgeBase:
    def __init__(
        self,
        groups: list[Group],
        presets: list[Preset],
        entries: dict[str, KnowledgeEntry],
        section_fallback: dict[str, str],
    ) -> None:
        self.groups = groups
        self.presets = presets
        self.entries = entries
        self.section_fallback = section_fallback
        self._groups_by_id = {g.id: g for g in groups}

    # ---------------------------------------------------------------- loading
    @classmethod
    def load(cls, directory: Path | None = None) -> KnowledgeBase:
        """Load and validate the knowledge base (bundled data by default)."""
        if directory is None:
            root = resources.files("wzce.data") / "settings_db"
            files = {p.name: p.read_text(encoding="utf-8") for p in root.iterdir()}
        else:
            files = {p.name: p.read_text(encoding="utf-8") for p in directory.iterdir()}
        if META_FILE not in files:
            raise KnowledgeError(f"{META_FILE} is missing")

        meta = _load_json(META_FILE, files[META_FILE])
        presets = [
            Preset(p["id"], _text(p, "label", META_FILE), _text(p, "desc", META_FILE))
            for p in meta["presets"]
        ]
        groups = [
            Group(
                id=g["id"],
                icon=g.get("icon", ""),
                label=_text(g, "label", META_FILE),
                subgroups=tuple(
                    Subgroup(s["id"], _text(s, "label", META_FILE)) for s in g["subgroups"]
                ),
            )
            for g in meta["groups"]
        ]
        section_fallback = {k: v for k, v in meta["section_fallback"].items() if k != "comment"}

        kb = cls(groups, presets, {}, section_fallback)
        preset_ids = {p.id for p in presets}
        for name in sorted(files):
            if name == META_FILE or not name.endswith(".json"):
                continue
            data = _load_json(name, files[name])
            group_id = data.get("group")
            if group_id not in kb._groups_by_id:
                raise KnowledgeError(f"{name}: unknown group {group_id!r}")
            for setting_id, raw in data.get("settings", {}).items():
                if setting_id in kb.entries:
                    raise KnowledgeError(f"{name}: {setting_id} is defined twice")
                kb.entries[setting_id] = kb._build_entry(
                    name, group_id, setting_id, raw, preset_ids
                )
        for target in (s for e in kb.entries.values() for s in e.related):
            if target not in kb.entries:
                raise KnowledgeError(f"related setting {target} is not in the knowledge base")
        return kb

    def _build_entry(
        self,
        file_name: str,
        group_id: str,
        setting_id: str,
        raw: dict[str, Any],
        preset_ids: set[str],
    ) -> KnowledgeEntry:
        where = f"{file_name}: {setting_id}"
        if "@" not in setting_id:
            raise KnowledgeError(f"{where}: id must be Key@Variant")
        allowed = {
            "subgroup", "label", "desc", "impact", "recommend", "tip", "flags", "vendor",
            "widget", "unit", "rule", "options", "related",
        }  # fmt: skip
        unknown = set(raw) - allowed
        if unknown:
            raise KnowledgeError(f"{where}: unknown fields {sorted(unknown)}")

        group = self._groups_by_id[group_id]
        subgroup = raw.get("subgroup")
        if group.subgroup(subgroup) is None:
            raise KnowledgeError(f"{where}: unknown subgroup {subgroup!r} in group {group_id}")

        impact_raw = raw.get("impact", {})
        for dim, level in impact_raw.items():
            if dim not in IMPACT_DIMENSIONS or not (0 <= level <= IMPACT_MAX):
                raise KnowledgeError(f"{where}: bad impact {dim}={level}")

        recommend = raw.get("recommend", {})
        if set(recommend) - preset_ids:
            raise KnowledgeError(f"{where}: unknown presets {sorted(set(recommend) - preset_ids)}")

        flags = frozenset(raw.get("flags", []))
        checks = [
            (flags <= FLAGS and "new" not in flags, f"bad flags {sorted(flags)}"),
            (raw.get("vendor") in (None, *VENDORS), f"bad vendor {raw.get('vendor')!r}"),
            (raw.get("widget") in (None, *WIDGETS), f"bad widget {raw.get('widget')!r}"),
            (raw.get("rule") in (None, *RULES), f"bad rule {raw.get('rule')!r}"),
        ]
        for ok, message in checks:
            if not ok:
                raise KnowledgeError(f"{where}: {message}")

        options = raw.get("options", {})
        for option, text in options.items():
            _require_languages(text, f"{where}: option {option!r}", require_all=False)

        return KnowledgeEntry(
            setting_id=setting_id,
            group=group_id,
            subgroup=subgroup,
            label=_text(raw, "label", where),
            desc=_text(raw, "desc", where),
            impact=Impact(**impact_raw),
            recommend=recommend,
            tip=_text(raw, "tip", where) if "tip" in raw else {},
            flags=flags,
            vendor=raw.get("vendor"),
            widget=raw.get("widget"),
            unit=raw.get("unit"),
            rule=raw.get("rule"),
            options=options,
            related=tuple(raw.get("related", [])),
        )

    # ------------------------------------------------------------------ query
    def group(self, group_id: str) -> Group:
        return self._groups_by_id[group_id]

    def preset(self, preset_id: str) -> Preset:
        return next(p for p in self.presets if p.id == preset_id)

    def entry_for(self, setting: Setting) -> KnowledgeEntry:
        """Knowledge entry for a parsed setting; synthesized when unknown.

        The synthesized entry uses the file's English comment as description in
        every language and is flagged ``new`` so the UI can highlight it.
        """
        entry = self.entries.get(setting.id)
        if entry is not None:
            return entry
        group_id = self.section_fallback.get(setting.section or "", "system")
        description = {lang: setting.description for lang in SUPPORTED_LANGUAGES}
        return KnowledgeEntry(
            setting_id=setting.id,
            group=group_id,
            subgroup="unknown" if group_id == "system" else None,
            label={lang: humanize_key(setting.key) for lang in SUPPORTED_LANGUAGES},
            desc=description,
            flags=frozenset({"new", "advanced"}),
        )

    def recommendation(self, setting_id: str, preset_id: str) -> Any | None:
        entry = self.entries.get(setting_id)
        return None if entry is None else entry.recommend.get(preset_id)

    def preset_values(self, preset_id: str) -> dict[str, Any]:
        """``{setting_id: value}`` for one preset - feed to ``ConfigDocument.apply_values``."""
        return {
            sid: e.recommend[preset_id]
            for sid, e in self.entries.items()
            if preset_id in e.recommend
        }


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------


def _load_json(name: str, text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise KnowledgeError(f"{name}: invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise KnowledgeError(f"{name}: top level must be an object")
    return data


def _text(obj: Mapping[str, Any], key: str, where: str) -> dict[str, str]:
    value = obj.get(key)
    _require_languages(value, f"{where}: {key}", require_all=True)
    return dict(value)  # type: ignore[arg-type]


def _require_languages(value: Any, where: str, *, require_all: bool) -> None:
    if not isinstance(value, dict) or not value:
        raise KnowledgeError(f"{where} must be an object with language keys")
    missing = [lang for lang in SUPPORTED_LANGUAGES if not value.get(lang)]
    if require_all and missing:
        raise KnowledgeError(f"{where} is missing languages {missing}")
    if set(value) - set(SUPPORTED_LANGUAGES):
        raise KnowledgeError(f"{where} has unsupported languages {sorted(set(value))}")
