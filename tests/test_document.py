"""Parser and serializer: structure, type inference, round-trip, editing."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import ALL_SAMPLE_FILES, COD26_SINGLE, PROFILE_TXT0
from wzce.core import ConfigDocument, ParseError, UnknownSettingError, ValidationError, ValueType

# ----------------------------------------------------------------- round-trip


@pytest.mark.parametrize("path", ALL_SAMPLE_FILES, ids=lambda p: p.name)
def test_round_trip_is_byte_exact(path: Path) -> None:
    data = path.read_bytes()
    assert ConfigDocument.from_bytes(data).to_bytes() == data


@pytest.mark.parametrize(
    "text",
    [
        "1\r\n\r\n// d\r\nA@0;1;2 = true\r\n",  # CRLF
        "1\n\n// d\nA@0;1;2 = true",  # no trailing newline
        "1\n// d\r\nA@0;1;2 = true\n",  # mixed endings
        "﻿1\n// d\nA@0;1;2 = true\n",  # BOM
    ],
)
def test_round_trip_preserves_line_endings_and_bom(text: str) -> None:
    data = text.encode("utf-8")
    assert ConfigDocument.from_bytes(data).to_bytes() == data


def test_round_trip_preserves_non_utf8_bytes() -> None:
    data = b"1\n// Monitor\nMonitor@0;2059;35888 = Caf\xe9 Display\n"  # cp1252 byte
    assert ConfigDocument.from_bytes(data).to_bytes() == data


# ------------------------------------------------------------------ structure


def test_cod25_structure(cod25_doc: ConfigDocument) -> None:
    assert cod25_doc.format_version == 1
    assert len(cod25_doc) == 147
    assert cod25_doc.sections == [
        "Audio",
        "Display",
        "Gameplay",
        "Graphics",
        "Interface",
        "Mouse and Gamepad",
        "System",
        None,
    ]
    assert cod25_doc.warnings == []


def test_trailing_settings_have_no_section(cod25_doc: ConfigDocument) -> None:
    # These three sit after "System" behind two blank lines, without a header.
    orphans = [s.id for s in cod25_doc if s.section is None]
    assert orphans == ["LicensedMusicVolume@0", "MouseUsesRawInput@0", "VRSValidationMask@0"]
    assert cod25_doc.get("RecommendedSet@0").section == "System"


def test_cod26_and_profile_files_parse() -> None:
    assert len(ConfigDocument.from_bytes(COD26_SINGLE.read_bytes())) == 163
    profile = ConfigDocument.from_bytes(PROFILE_TXT0.read_bytes())
    assert len(profile) == 67
    # Keys with spaces are legal in account files.
    assert profile.get("Handheld Fov@0").value == 80.0
    assert profile.get("TextChat background opacity@0").value == pytest.approx(0.2)


def test_variants_are_distinct_settings(cod25_doc: ConfigDocument) -> None:
    assert cod25_doc.get("DepthOfField@0").value_type is ValueType.BOOL
    assert cod25_doc.get("DepthOfField@1").value_type is ValueType.ENUM
    assert "DepthOfField" not in cod25_doc


def test_description_and_read_only(cod25_doc: ConfigDocument) -> None:
    reflex = cod25_doc.get("NvidiaReflex@0")
    assert reflex.description.startswith("Enable Nvidia low latency mode")
    assert reflex.section == "Display"
    assert not reflex.read_only
    assert cod25_doc.get("LastUsedGPU@0").read_only
    assert cod25_doc.get("DetectedMemoryAmountMB@0").read_only


def test_no_settings_is_a_parse_error() -> None:
    with pytest.raises(ParseError):
        ConfigDocument.parse("hello\nworld\n")


def test_unknown_line_is_kept_with_warning() -> None:
    text = "1\n// d\nA@0;1;2 = true\nsomething new\n"
    doc = ConfigDocument.parse(text)
    assert doc.to_text() == text
    assert len(doc.warnings) == 1


def test_duplicate_id_first_wins() -> None:
    doc = ConfigDocument.parse("1\nA@0;1;2 = true\nA@0;1;2 = false\n")
    assert doc.get("A@0").value is True
    assert any("duplicate" in w for w in doc.warnings)


# ------------------------------------------------------------- type inference


@pytest.mark.parametrize(
    ("setting_id", "value_type", "value"),
    [
        ("WindowsSonicEnable@0", ValueType.BOOL, False),
        ("ResolutionMultiplier@0", ValueType.INT, 100),
        ("WindowX@0", ValueType.INT, 0),
        ("VoiceVolume@0", ValueType.FLOAT, 0.8),
        ("NvidiaReflex@0", ValueType.ENUM, "Enabled + boost"),
        ("AspectRatio@0", ValueType.ENUM, "wide 16:9"),
        ("GPUName@0", ValueType.STRING, "NVIDIA GeForce RTX 5090"),
        ("SoundInputDevice@0", ValueType.STRING, ""),
        # Unconstrained version number must stay a string, not become 617.420000.
        ("DisplayDriverVersion@0", ValueType.STRING, "617.42"),
    ],
)
def test_value_types(cod25_doc: ConfigDocument, setting_id: str, value_type, value) -> None:
    setting = cod25_doc.get(setting_id)
    assert setting.value_type is value_type
    expected = pytest.approx(value) if isinstance(value, float) else value
    assert setting.value == expected


def test_enum_options_with_special_characters(cod25_doc: ConfigDocument) -> None:
    assert cod25_doc.get("NvidiaReflex@0").constraint.options == (
        "Disabled",
        "Enabled",
        "Enabled + boost",
    )
    assert "wide 19.5:9" in cod25_doc.get("AspectRatio@0").constraint.options
    assert "100%" in cod25_doc.get("VSync@0").constraint.options


def test_slider_friendliness(cod25_doc: ConfigDocument) -> None:
    assert cod25_doc.get("MaxFpsInGame@0").constraint.is_slider_friendly
    assert not cod25_doc.get("StaticSunshadowClipmapResolution@0").constraint.is_slider_friendly
    assert not cod25_doc.get("DetectedFrequencyGHz@0").constraint.is_slider_friendly


# -------------------------------------------------------------------- editing


def _changed_lines(before: ConfigDocument, after: ConfigDocument) -> list[int]:
    return [i for i, (a, b) in enumerate(zip(before.lines, after.lines, strict=True)) if a != b]


@pytest.mark.parametrize(
    ("setting_id", "value", "expected_line"),
    [
        ("WindowsSonicEnable@0", True, "WindowsSonicEnable@0;57752;48403 = true"),
        ("WindowsSonicEnable@0", "On", "WindowsSonicEnable@0;57752;48403 = true"),
        ("MaxFpsInGame@0", 237, "MaxFpsInGame@0;13305;58861 = 237 // 30 to 300"),
        ("MaxFpsInGame@0", "237", "MaxFpsInGame@0;13305;58861 = 237 // 30 to 300"),
        ("MaxFpsInGame@0", 200.0, "MaxFpsInGame@0;13305;58861 = 200 // 30 to 300"),
        (
            "VideoMemoryScaleMP@0",
            0.75,
            "VideoMemoryScaleMP@0;59710;7707 = 0.750000 // 0.000000 to 2.000000",
        ),
        (
            "VideoMemoryScaleMP@0",
            "0,8",  # Polish decimal comma
            "VideoMemoryScaleMP@0;59710;7707 = 0.800000 // 0.000000 to 2.000000",
        ),
        (
            "ShaderQuality@0",
            "medium",  # case-insensitive input, canonical output
            "ShaderQuality@0;19450;7764 = Medium // one of Default, Medium, Low",
        ),
        (
            "SoundInputDevice@0",
            "{0.0.1.00000000}.{abc}",
            "SoundInputDevice@0;2059;35888 = {0.0.1.00000000}.{abc}",
        ),
    ],
)
def test_set_value_rewrites_only_that_line(
    cod25_doc: ConfigDocument, setting_id: str, value: object, expected_line: str
) -> None:
    original = cod25_doc.copy()
    cod25_doc.set_value(setting_id, value)
    setting = cod25_doc.get(setting_id)
    assert cod25_doc.lines[setting.line_index] == expected_line
    assert _changed_lines(original, cod25_doc) == [setting.line_index]
    # The edited document must parse back to the same value.
    reparsed = ConfigDocument.from_bytes(cod25_doc.to_bytes())
    assert reparsed.get(setting_id).raw_value == setting.raw_value


def test_set_value_noop_returns_noop_change(cod25_doc: ConfigDocument) -> None:
    change = cod25_doc.set_value("MaxFpsInGame@0", 250)
    assert change.is_noop
    assert change.old_raw == change.new_raw == "250"


@pytest.mark.parametrize(
    ("setting_id", "value"),
    [
        ("MaxFpsInGame@0", 301),
        ("MaxFpsInGame@0", 29),
        ("MaxFpsInGame@0", 60.5),
        ("MaxFpsInGame@0", "fast"),
        ("MaxFpsInGame@0", True),
        ("VoiceVolume@0", 1.5),
        ("VoiceVolume@0", float("nan")),
        ("ShaderQuality@0", "Ultra"),
        ("WindowsSonicEnable@0", "maybe"),
        ("GPUName@0", "two\nlines"),
        ("GPUName@0", "a // b"),
        ("GPUName@0", " padded "),
    ],
)
def test_invalid_values_are_rejected(cod25_doc: ConfigDocument, setting_id: str, value) -> None:
    before = cod25_doc.to_bytes()
    with pytest.raises(ValidationError):
        cod25_doc.set_value(setting_id, value)
    assert cod25_doc.to_bytes() == before


def test_float_rounding_tolerance_at_range_edge(cod25_doc: ConfigDocument) -> None:
    cod25_doc.set_value("VoiceVolume@0", 1.0000004)
    assert cod25_doc.get("VoiceVolume@0").raw_value == "1.000000"


def test_read_only_requires_explicit_override(cod25_doc: ConfigDocument) -> None:
    with pytest.raises(ValidationError):
        cod25_doc.set_value("VRSValidationMask@0", 1)
    cod25_doc.set_value("VRSValidationMask@0", 1, allow_read_only=True)
    assert cod25_doc.get("VRSValidationMask@0").value == 1


def test_unknown_setting(cod25_doc: ConfigDocument) -> None:
    with pytest.raises(UnknownSettingError):
        cod25_doc.set_value("NoSuchThing@0", 1)


def test_empty_value_with_constraint_gets_spacing_back() -> None:
    doc = ConfigDocument.parse("1\nA@0;1;2 = // 0 to 10\nB@0;1;2 =// 0 to 10\n")
    assert doc.get("A@0").raw_value == ""
    assert doc.to_text() == "1\nA@0;1;2 = // 0 to 10\nB@0;1;2 =// 0 to 10\n"
    doc.set_value("A@0", 5)
    doc.set_value("B@0", 6)
    assert doc.lines[1:] == ["A@0;1;2 = 5 // 0 to 10", "B@0;1;2 = 6 // 0 to 10"]


def test_apply_values_collects_errors(cod25_doc: ConfigDocument) -> None:
    applied, errors = cod25_doc.apply_values(
        {
            "MaxFpsInGame@0": 144,  # applied
            "VSync@0": "disabled",  # no-op, not reported
            "MotionBlur@0": "true",  # cod26-only key
            "ShaderQuality@0": "Ultra",  # invalid option
            "LastUsedGPU@0": "x",  # read-only
        }
    )
    assert [c.setting_id for c in applied] == ["MaxFpsInGame@0"]
    assert set(errors) == {"MotionBlur@0", "ShaderQuality@0", "LastUsedGPU@0"}


def test_copy_is_independent(cod25_doc: ConfigDocument) -> None:
    clone = cod25_doc.copy()
    clone.set_value("MaxFpsInGame@0", 144)
    assert cod25_doc.get("MaxFpsInGame@0").value == 250
