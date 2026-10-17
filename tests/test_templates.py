"""Templates: creation without hardware data, preview plans, built-ins, storage, import/export."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import COD26_SINGLE, not_running
from wzce.core import ConfigDocument, KnowledgeBase, SettingsFileSet
from wzce.core.session import EditorSession
from wzce.core.templates import (
    SkipReason,
    Template,
    TemplateError,
    TemplateSource,
    TemplateStore,
    builtin_templates,
    export_template,
    load_template,
    plan_template,
    template_from_document,
)
from wzce.core.undo import CommandKind

HARDWARE_IDS = {
    "GPUName@0", "Monitor@0", "SoundOutputDevice@0", "VoiceOutputDevice@0",
    "SoundInputDevice@0", "WindowWidth@0", "WindowX@0", "Resolution@0", "RefreshRate@0",
}  # fmt: skip
MANAGED_IDS = {
    "LastUsedGPU@0",
    "DetectedMemoryAmountMB@0",
    "GPUDriverVersion@0",
    "RecommendedSet@0",
}


@pytest.fixture(scope="module")
def kb() -> KnowledgeBase:
    return KnowledgeBase.load()


@pytest.fixture
def doc(cod25_doc: ConfigDocument) -> ConfigDocument:
    return cod25_doc


# ---------------------------------------------------------------- creation


def test_template_never_contains_hardware_or_managed_values(doc, kb) -> None:
    template = template_from_document(doc, kb, "All")
    assert not (set(template.values) & (HARDWARE_IDS | MANAGED_IDS))
    assert "VSync@0" in template.values
    assert template.groups[0] == "display"  # knowledge-base order


def test_template_for_selected_groups(doc, kb) -> None:
    template = template_from_document(doc, kb, "Gfx", groups=["quality", "upscaling"])
    groups = {kb.entries[sid].group for sid in template.values}
    assert groups == {"quality", "upscaling"}
    assert template.groups == ["upscaling", "quality"]


def test_json_round_trip(doc, kb) -> None:
    template = template_from_document(
        doc, kb, "Mój szablon", description="opis", title_code="cod25"
    )
    loaded = Template.from_json(template.to_json())
    assert (loaded.name, loaded.description, loaded.title_code) == ("Mój szablon", "opis", "cod25")
    assert loaded.values == template.values
    assert loaded.groups == template.groups


@pytest.mark.parametrize(
    "payload",
    [
        "{broken",
        json.dumps({"format": "something-else", "name": "x", "values": {}}),
        json.dumps({"format": "wzce-template", "version": 99, "name": "x", "values": {}}),
        json.dumps({"format": "wzce-template", "name": "", "values": {}}),
        json.dumps({"format": "wzce-template", "name": "x", "values": {"NoVariant": "1"}}),
        json.dumps({"format": "wzce-template", "name": "x", "values": {"A@0": 1}}),
        json.dumps({"format": "wzce-template", "name": "x", "values": {}, "groups": "display"}),
    ],
)
def test_invalid_template_files_are_rejected(payload: str) -> None:
    with pytest.raises(TemplateError):
        Template.from_json(payload)


# --------------------------------------------------------------------- plan


def test_plan_reports_changes_unchanged_and_skips(doc, kb) -> None:
    plan = plan_template(
        doc,
        kb,
        {
            "ShaderQuality@0": "Medium",  # change
            "VSync@0": "disabled",  # already so
            "MotionBlur@0": "Off",  # cod26-only
            "GPUName@0": "Some GPU",  # hardware
            "LastUsedGPU@0": "x",  # managed
            "AmdAntilag2@0": "true",  # other vendor (sample has NVIDIA)
            "TextureFilter@0": "aniso 32x",  # invalid option
        },
        gpu_vendor="nvidia",
    )
    assert [(c.setting_id, c.old_raw, c.new_raw) for c in plan.changes] == [
        ("ShaderQuality@0", "Low", "Medium")
    ]
    assert plan.unchanged == ["VSync@0"]
    assert plan.skipped == {
        "MotionBlur@0": SkipReason.MISSING,
        "GPUName@0": SkipReason.HARDWARE,
        "LastUsedGPU@0": SkipReason.MANAGED,
        "AmdAntilag2@0": SkipReason.VENDOR,
        "TextureFilter@0": SkipReason.INVALID,
    }
    assert "aniso 32x" in plan.errors["TextureFilter@0"]
    assert plan.values() == {"ShaderQuality@0": "Medium"}
    assert plan.values(only=[]) == {}


def test_plan_without_vendor_keeps_vendor_settings(doc, kb) -> None:
    plan = plan_template(doc, kb, {"AmdAntilag2@0": "true"})
    assert [c.setting_id for c in plan.changes] == ["AmdAntilag2@0"]


def test_plan_normalizes_values(doc, kb) -> None:
    plan = plan_template(doc, kb, {"VideoMemoryScaleMP@0": "0.7", "ShaderQuality@0": "medium"})
    assert plan.values() == {"VideoMemoryScaleMP@0": "0.700000", "ShaderQuality@0": "Medium"}


def test_cross_title_template(doc, kb) -> None:
    cod26 = ConfigDocument.from_bytes(COD26_SINGLE.read_bytes())
    template = template_from_document(cod26, kb, "From cod26")
    plan = plan_template(doc, kb, template.values)
    assert plan.skipped.get("MotionBlur@0") is SkipReason.MISSING  # not in cod25
    assert plan.changes or plan.unchanged


# ---------------------------------------------------------------- built-ins


def test_builtin_templates(doc, kb) -> None:
    templates = builtin_templates(kb, doc, "pl")
    assert [t.builtin_id for t in templates] == ["competitive", "balanced", "quality", "low_end"]
    competitive = templates[0]
    assert competitive.source is TemplateSource.BUILTIN
    assert competitive.name == "Competitive"
    assert competitive.values["ShaderQuality@0"] == "Medium"
    assert competitive.values["VideoMemoryScaleMP@0"] == "0.700000"  # formatted for the file
    assert "MotionBlur@0" not in competitive.values  # cod26-only, left out for cod25
    assert not (set(competitive.values) & HARDWARE_IDS)


def test_builtin_quality_skips_dlaa_on_cod26(kb) -> None:
    cod26 = ConfigDocument.from_bytes(COD26_SINGLE.read_bytes())
    quality = next(t for t in builtin_templates(kb, cod26, "en") if t.builtin_id == "quality")
    assert "DLSSModeMP@0" not in quality.values  # DLAA does not exist in cod26


# ---------------------------------------------------------------- storage


def test_store_save_list_delete(doc, kb, tmp_path: Path) -> None:
    store = TemplateStore(tmp_path / "templates")
    first = store.save(template_from_document(doc, kb, "Mój Competitive!"))
    second = store.save(template_from_document(doc, kb, "Mój Competitive!"))
    assert first.path.name == "m-j-competitive.json"
    assert second.path.name == "m-j-competitive-2.json"
    assert [t.name for t in store.list()] == ["Mój Competitive!", "Mój Competitive!"]

    store.delete(first)
    assert len(store.list()) == 1
    with pytest.raises(TemplateError):
        store.delete(builtin_templates(kb, doc, "en")[0])


def test_store_overwrites_its_own_file(doc, kb, tmp_path: Path) -> None:
    store = TemplateStore(tmp_path / "templates")
    template = store.save(template_from_document(doc, kb, "A"))
    template.description = "changed"
    store.save(template)
    assert [t.description for t in store.list()] == ["changed"]


def test_store_skips_broken_files(tmp_path: Path) -> None:
    store = TemplateStore(tmp_path / "templates")
    store.root.mkdir(parents=True)
    (store.root / "broken.json").write_text("{nope", encoding="utf-8")
    assert store.list() == []


def test_export_and_import(doc, kb, tmp_path: Path) -> None:
    store = TemplateStore(tmp_path / "templates")
    preset = builtin_templates(kb, doc, "en")[0]
    exported = export_template(preset, tmp_path / "share.json")
    imported = store.import_file(exported)
    assert imported.source is TemplateSource.USER
    assert imported.path.parent == store.root
    assert imported.values == preset.values
    assert load_template(imported.path).name == "Competitive"


def test_import_rejects_non_template(tmp_path: Path) -> None:
    path = tmp_path / "x.json"
    path.write_text('{"hello": 1}', encoding="utf-8")
    with pytest.raises(TemplateError):
        TemplateStore(tmp_path / "templates").import_file(path)


# ------------------------------------------------------- applying in a session


def test_apply_plan_is_one_undo_step(cod25_set: SettingsFileSet, kb) -> None:
    session = EditorSession(cod25_set, game_running=not_running)
    preset = builtin_templates(kb, session.document, "en")[0]
    plan = plan_template(session.document, kb, preset.values, gpu_vendor=session.gpu_vendor)
    touched = session.apply_raw_values(plan.values(), kind=CommandKind.BULK)
    assert set(touched) == {c.setting_id for c in plan.changes}
    assert session.changed_ids() == set(touched)
    session.undo()
    assert not session.is_dirty
