"""GUI bootstrap: create the QApplication, theme, translator and main window."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .. import __version__
from ..core.i18n import Translator
from ..core.knowledge import KnowledgeBase
from .app_settings import AppSettings
from .main_window import MainWindow
from .theme import apply_theme

APP_NAME = "Warzone Config Editor"


def create_window(app: QApplication) -> MainWindow:
    """Build the main window with real data (used by ``run`` and handy for debugging)."""
    apply_theme(app)
    settings = AppSettings()
    tr = Translator(settings.language)
    return MainWindow(KnowledgeBase.load(), tr, settings)


def run(argv: list[str] | None = None) -> int:
    app = QApplication.instance() or QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    window = create_window(app)
    window.show()
    return app.exec()
