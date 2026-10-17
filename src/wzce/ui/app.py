"""GUI bootstrap: create the QApplication, theme, translator and main window."""

from __future__ import annotations

import contextlib
import ctypes
import os
import sys
import tempfile

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .. import __version__
from ..core.i18n import Translator
from ..core.knowledge import KnowledgeBase
from .app_settings import AppSettings
from .main_window import MainWindow
from .theme import apply_theme, icon_path

APP_NAME = "Warzone Config Editor"
# Lets Windows group our windows under our own taskbar icon instead of python.exe.
APP_USER_MODEL_ID = "WarzoneConfigEditor.App"


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
    app.setWindowIcon(QIcon(icon_path("app", "ico")))
    if sys.platform == "win32":
        with contextlib.suppress(AttributeError, OSError):  # cosmetic only
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    window = create_window(app)
    window.show()
    return app.exec()


def smoke_test() -> int:
    """Build the full UI without showing it, then exit. Used to check a frozen build.

    Exit codes: 0 OK, 2 Qt image plugins missing (SVG/ICO icons would not render),
    3 the main window could not be built, 4 the hardware probe (PowerShell/WMI) failed.
    Our own data goes to a temporary folder so the check never touches the user's
    settings, history or backups (game files are only read).
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ["WZCE_DATA_DIR"] = tempfile.mkdtemp(prefix="wzce-smoke-")
    from PySide6.QtGui import QImageReader

    app = QApplication.instance() or QApplication([sys.argv[0]])
    formats = {bytes(f).decode() for f in QImageReader.supportedImageFormats()}
    if not {"svg", "ico", "png"} <= formats:
        return 2
    try:
        window = create_window(app)
        window._timer.stop()
        app.processEvents()
        window._prompt_unsaved = lambda _count: "discard"
        window.close()
    except Exception:  # any failure means the build is broken
        return 3
    # The system probe runs PowerShell from the frozen exe - verify it really works.
    from ..core.system_info import collect_system_info

    info = collect_system_info()
    if any(error.startswith("cim") for error in info.errors) or not info.cpu_name:
        return 4
    return 0
