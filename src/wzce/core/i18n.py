"""UI string translations (English / Polish), independent of Qt.

Strings live in ``wzce/data/i18n/<lang>.json`` as a flat ``{"key": "text"}`` map
with ``str.format`` placeholders (``"Save ({count})"``). Setting labels and
descriptions are NOT here - they belong to the knowledge base.

Lookup order: current language -> English -> the key itself (so a missing
translation is visible but never crashes the UI). The Qt layer listens to
``Translator.add_listener`` to re-label widgets when the language changes,
which gives language switching without a restart.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from importlib import resources
from pathlib import Path
from typing import Any

from .knowledge import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES

LANGUAGE_META_KEY = "_language"  # {"code": "pl", "name": "Polski"} inside each file


def load_catalog(language: str, directory: Path | None = None) -> dict[str, str]:
    """Read one language file. Metadata keys (starting with ``_``) are dropped."""
    if directory is None:
        text = (resources.files("wzce.data") / "i18n" / f"{language}.json").read_text(
            encoding="utf-8"
        )
    else:
        text = (directory / f"{language}.json").read_text(encoding="utf-8")
    data: dict[str, Any] = json.loads(text)
    return {k: v for k, v in data.items() if not k.startswith("_")}


def language_name(language: str) -> str:
    """Native display name of a language ("English", "Polski")."""
    text = (resources.files("wzce.data") / "i18n" / f"{language}.json").read_text(encoding="utf-8")
    return json.loads(text)[LANGUAGE_META_KEY]["name"]


class Translator:
    def __init__(self, language: str = DEFAULT_LANGUAGE, directory: Path | None = None) -> None:
        self._directory = directory
        self._fallback = load_catalog(DEFAULT_LANGUAGE, directory)
        self._catalog: dict[str, str] = {}
        self._listeners: list[Callable[[str], None]] = []
        self._language = DEFAULT_LANGUAGE
        self.set_language(language)

    @property
    def language(self) -> str:
        return self._language

    def set_language(self, language: str) -> None:
        if language not in SUPPORTED_LANGUAGES:
            raise ValueError(f"unsupported language {language!r}")
        self._catalog = (
            self._fallback
            if language == DEFAULT_LANGUAGE
            else load_catalog(language, self._directory)
        )
        changed = language != self._language
        self._language = language
        if changed:
            for listener in list(self._listeners):
                listener(language)

    def add_listener(self, callback: Callable[[str], None]) -> None:
        """Call ``callback(language)`` after every language change."""
        self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[str], None]) -> None:
        self._listeners.remove(callback)

    def t(self, key: str, **params: object) -> str:
        """Translate ``key``; ``params`` fill ``{placeholders}``."""
        template = self._catalog.get(key) or self._fallback.get(key) or key
        if not params:
            return template
        try:
            return template.format(**params)
        except (KeyError, IndexError, ValueError):
            # A broken translation must not crash the UI - show it unformatted.
            return template

    __call__ = t
