"""UI translations: catalogs stay in sync and the translator never crashes."""

from __future__ import annotations

import re

import pytest

from wzce.core.i18n import Translator, language_name, load_catalog
from wzce.core.knowledge import SUPPORTED_LANGUAGES

_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def test_catalogs_have_identical_keys() -> None:
    en = load_catalog("en")
    for lang in SUPPORTED_LANGUAGES:
        assert set(load_catalog(lang)) == set(en), lang


def test_placeholders_match_between_languages() -> None:
    en = load_catalog("en")
    for lang in SUPPORTED_LANGUAGES:
        catalog = load_catalog(lang)
        for key, text in en.items():
            assert set(_PLACEHOLDER.findall(catalog[key])) == set(_PLACEHOLDER.findall(text)), (
                lang,
                key,
            )


def test_no_empty_translations() -> None:
    for lang in SUPPORTED_LANGUAGES:
        assert all(v.strip() for v in load_catalog(lang).values()), lang


def test_language_names() -> None:
    assert language_name("en") == "English"
    assert language_name("pl") == "Polski"


def test_translate_and_format() -> None:
    tr = Translator("pl")
    assert tr("toolbar.save") == "Zapisz"
    assert tr("toolbar.save_count", count=3) == "Zapisz (3)"
    tr.set_language("en")
    assert tr.t("toolbar.save_count", count=3) == "Save (3)"


def test_missing_key_falls_back_to_key() -> None:
    assert Translator("pl")("does.not.exist") == "does.not.exist"


def test_broken_placeholders_do_not_crash() -> None:
    tr = Translator("en")
    assert tr("toolbar.save_count") == "Save ({count})"  # no params -> raw template
    assert tr("toolbar.save_count", wrong=1) == "Save ({count})"


def test_listener_called_only_on_change() -> None:
    tr = Translator("en")
    calls: list[str] = []
    tr.add_listener(calls.append)
    tr.set_language("en")
    tr.set_language("pl")
    tr.set_language("pl")
    assert calls == ["pl"]
    tr.remove_listener(calls.append)
    tr.set_language("en")
    assert calls == ["pl"]


def test_unsupported_language() -> None:
    with pytest.raises(ValueError):
        Translator("de")
