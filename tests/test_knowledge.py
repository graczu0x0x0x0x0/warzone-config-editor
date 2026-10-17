"""Knowledge base: loader validation and consistency with the real game files.

These tests are the safety net for hand-edited JSON: every setting in the
sample files must be described, every recommendation must be a value the game
accepts, and both languages must be filled in.
"""

from __future__ import annotations

import json
import shutil
from importlib import resources
from pathlib import Path

import pytest

from conftest import COD25_TXT0, COD26_SINGLE, SNAPSHOT
from wzce.core import ConfigDocument, ValidationError, ValueType
from wzce.core.knowledge import (
    SUPPORTED_LANGUAGES,
    KnowledgeBase,
    KnowledgeError,
    humanize_key,
    localized,
)
from wzce.core.model import format_value

PROFILE = SNAPSHOT / "profile"
TITLE_DOCS = {
    "cod25": ConfigDocument.from_bytes(COD25_TXT0.read_bytes()),
    "cod26": ConfigDocument.from_bytes(COD26_SINGLE.read_bytes()),
    # Account-level files (sensitivity, FOV, audio mix, HDR...).
    "cod25-account": ConfigDocument.from_bytes((PROFILE / "g.cod25.1.0.l.txt0").read_bytes()),
    "cod25-pm": ConfigDocument.from_bytes((PROFILE / "g.cod25.pm.1.0.l.txt0").read_bytes()),
    "cod26-account": ConfigDocument.from_bytes((PROFILE / "g.cod26.1.0.l.txt").read_bytes()),
    "cod26-pm": ConfigDocument.from_bytes((PROFILE / "g.cod26.pm.1.0.l.txt").read_bytes()),
}

# Recommendations that are valid for one title but not another. Listed explicitly
# so a new mismatch (e.g. after a game update) fails loudly instead of slipping by.
KNOWN_TITLE_DIFFERENCES = {
    ("cod26", "DLSSModeMP@0", "quality"),  # cod26 removed DLAA from this variant
}


@pytest.fixture(scope="module")
def kb() -> KnowledgeBase:
    return KnowledgeBase.load()


# --------------------------------------------------------------- structure


def test_groups_and_presets(kb: KnowledgeBase) -> None:
    assert [g.id for g in kb.groups] == [
        "display", "performance", "upscaling", "quality", "aim", "gameplay",
        "audio", "interface", "controls", "power", "system",
    ]  # fmt: skip
    assert [p.id for p in kb.presets] == ["competitive", "balanced", "quality", "low_end"]


@pytest.mark.parametrize("title", TITLE_DOCS)
def test_every_machine_setting_is_described(kb: KnowledgeBase, title: str) -> None:
    missing = [s.id for s in TITLE_DOCS[title] if s.id not in kb.entries]
    assert missing == []


def test_no_orphan_entries(kb: KnowledgeBase) -> None:
    known_ids = set().union(*(doc.ids for doc in TITLE_DOCS.values()))
    assert sorted(set(kb.entries) - known_ids) == []


def test_every_subgroup_is_used(kb: KnowledgeBase) -> None:
    used = {(e.group, e.subgroup) for e in kb.entries.values()}
    for group in kb.groups:
        for sub in group.subgroups:
            if sub.id != "unknown":  # reserved for synthesized entries
                assert (group.id, sub.id) in used, f"empty subgroup {group.id}/{sub.id}"


def test_both_languages_are_real_translations(kb: KnowledgeBase) -> None:
    for entry in kb.entries.values():
        for lang in SUPPORTED_LANGUAGES:
            assert entry.label.get(lang) and entry.desc.get(lang), entry.setting_id
        # Copy-pasted English in the Polish field is a typical mistake.
        assert entry.desc["pl"] != entry.desc["en"], entry.setting_id


# ------------------------------------------------------- values vs. game files


def _settings_for(setting_id: str):
    return [(t, doc.get(setting_id)) for t, doc in TITLE_DOCS.items() if setting_id in doc]


def test_recommendations_are_valid_and_canonical(kb: KnowledgeBase) -> None:
    problems = []
    for entry in kb.entries.values():
        for title, setting in _settings_for(entry.setting_id):
            for preset, value in entry.recommend.items():
                if (title, entry.setting_id, preset) in KNOWN_TITLE_DIFFERENCES:
                    continue
                try:
                    raw = format_value(value, setting.value_type, setting.constraint)
                except Exception as exc:
                    problems.append(f"{title} {entry.setting_id} [{preset}]: {exc}")
                    continue
                if isinstance(value, str) and raw != value:
                    problems.append(f"{title} {entry.setting_id} [{preset}]: write {raw!r}")
                if setting.value_type is ValueType.BOOL and not isinstance(value, bool):
                    problems.append(f"{title} {entry.setting_id} [{preset}]: use JSON true/false")
    assert problems == []


def test_known_title_differences_are_still_real(kb: KnowledgeBase) -> None:
    for title, setting_id, preset in KNOWN_TITLE_DIFFERENCES:
        setting = TITLE_DOCS[title].get(setting_id)
        with pytest.raises(ValidationError):
            format_value(
                kb.recommendation(setting_id, preset), setting.value_type, setting.constraint
            )


def test_option_labels_refer_to_real_options(kb: KnowledgeBase) -> None:
    for entry in kb.entries.values():
        if not entry.options:
            continue
        all_options = set()
        for _, setting in _settings_for(entry.setting_id):
            assert setting.value_type is ValueType.ENUM, entry.setting_id
            all_options |= set(setting.constraint.options)
        assert set(entry.options) <= all_options, entry.setting_id


def test_do_not_modify_settings_are_game_managed(kb: KnowledgeBase) -> None:
    for title, doc in TITLE_DOCS.items():
        for setting in doc:
            if setting.read_only:
                assert "game_managed" in kb.entries[setting.id].flags, (title, setting.id)


def test_percent_widget_only_on_floats(kb: KnowledgeBase) -> None:
    for entry in kb.entries.values():
        if entry.widget == "percent":
            for _, setting in _settings_for(entry.setting_id):
                assert setting.value_type is ValueType.FLOAT, entry.setting_id


def test_competitive_preset_applies_cleanly_to_cod25(kb: KnowledgeBase) -> None:
    doc = TITLE_DOCS["cod25"].copy()
    applied, errors = doc.apply_values(kb.preset_values("competitive"))
    assert applied, "competitive preset should change something in the sample"
    # Only settings that do not exist in cod25 may fail.
    assert all(sid not in TITLE_DOCS["cod25"] for sid in errors), errors
    assert ConfigDocument.from_bytes(doc.to_bytes()).values() == doc.values()


# ------------------------------------------------------------- fallback


def test_unknown_setting_gets_synthesized_entry(kb: KnowledgeBase) -> None:
    doc = ConfigDocument.parse(
        "1\n\n\n//\n// Graphics\n\n// Brand new upscaler\nSuperUpscalerXL@0;1;2 = true\n"
    )
    entry = kb.entry_for(doc.get("SuperUpscalerXL@0"))
    assert not entry.known
    assert entry.group == "quality"  # from the file's "Graphics" section
    assert entry.subgroup is None
    assert localized(entry.label, "pl") == "Super Upscaler XL"
    assert localized(entry.desc, "pl") == "Brand new upscaler"
    assert entry.advanced


def test_unknown_setting_without_section_goes_to_system(kb: KnowledgeBase) -> None:
    doc = ConfigDocument.parse("1\n// Mystery\nMystery@0;1;2 = 5\n")
    entry = kb.entry_for(doc.get("Mystery@0"))
    assert (entry.group, entry.subgroup) == ("system", "unknown")


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("MaxFpsInGame", "Max Fps In Game"),
        ("DLSSModeMP", "DLSS Mode MP"),
        ("VRS", "VRS"),
        ("Handheld Fov", "Handheld Fov"),
        ("Very_Low", "Very Low"),
    ],
)
def test_humanize_key(key: str, expected: str) -> None:
    assert humanize_key(key) == expected


def test_option_label_fallback(kb: KnowledgeBase) -> None:
    entry = kb.entries["DisplayMode@0"]
    assert entry.option_label("Fullscreen", "pl") == "Pełny ekran"
    assert entry.option_label("Fullscreen", "en") == "Fullscreen"  # raw spelling
    assert entry.option_label("Windowed", "en") == "Windowed"


# ------------------------------------------------------ loader validation


@pytest.fixture
def db_copy(tmp_path: Path) -> Path:
    src = resources.files("wzce.data") / "settings_db"
    dst = tmp_path / "settings_db"
    dst.mkdir()
    for item in src.iterdir():
        (dst / item.name).write_text(item.read_text(encoding="utf-8"), encoding="utf-8")
    return dst


def _mutate(db: Path, file_name: str, setting_id: str, **changes) -> None:
    path = db / file_name
    data = json.loads(path.read_text(encoding="utf-8"))
    entry = data["settings"][setting_id]
    for key, value in changes.items():
        if value is None:
            entry.pop(key, None)
        else:
            entry[key] = value
    path.write_text(json.dumps(data), encoding="utf-8")


def test_copy_loads(db_copy: Path) -> None:
    assert len(KnowledgeBase.load(db_copy).entries) == len(KnowledgeBase.load().entries)


@pytest.mark.parametrize(
    "changes",
    [
        {"subgroup": "nope"},
        {"label": {"en": "Only English"}},
        {"desc": None},
        {"impact": {"fps": 7}},
        {"impact": {"beauty": 1}},
        {"recommend": {"ultra_mega": "On"}},
        {"flags": ["shiny"]},
        {"flags": ["new"]},
        {"vendor": "3dfx"},
        {"widget": "knob"},
        {"rule": "magic"},
        {"related": ["DoesNotExist@0"]},
        {"step": 0},
        {"step": "1"},
        {"colour": "red"},
    ],
    ids=lambda c: next(iter(c)),
)
def test_loader_rejects_bad_entries(db_copy: Path, changes: dict) -> None:
    _mutate(db_copy, "display.json", "HDR@0", **changes)
    with pytest.raises(KnowledgeError):
        KnowledgeBase.load(db_copy)


def test_loader_rejects_duplicates_and_bad_json(db_copy: Path) -> None:
    shutil.copy(db_copy / "display.json", db_copy / "display_copy.json")
    with pytest.raises(KnowledgeError, match="twice"):
        KnowledgeBase.load(db_copy)
    (db_copy / "display_copy.json").write_text("{oops", encoding="utf-8")
    with pytest.raises(KnowledgeError, match="invalid JSON"):
        KnowledgeBase.load(db_copy)
