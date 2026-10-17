"""Dark "gaming" theme: color tokens, a Fusion palette and the application stylesheet.

All colors are defined once in ``COLORS``; widgets reference them through Qt
dynamic properties used as style selectors (e.g. ``card[changed="true"]``,
``QPushButton[variant="primary"]``) instead of hard-coding colors in code.
After changing such a property at runtime call ``repolish(widget)``.
"""

from __future__ import annotations

from importlib import resources

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication, QStyleFactory, QWidget

COLORS: dict[str, str] = {
    "bg": "#0e1014",
    "surface": "#161a21",
    "surface_alt": "#1c212a",
    "surface_hover": "#232934",
    "border": "#2a313d",
    "border_strong": "#3a4352",
    "text": "#e7e9ee",
    "text_muted": "#97a0b0",
    "text_faint": "#6b7484",
    "accent": "#f0a034",  # amber - changed values, primary actions
    "accent_hover": "#f5b65c",
    "accent_text": "#14100a",
    "success": "#3fb27f",
    "danger": "#e5534b",
    "info": "#5aa9f6",
    "nvidia": "#76b900",
    "amd": "#ed1c24",
    "intel": "#0a84d6",
}

FONT_FAMILY = "Segoe UI"
FONT_SIZE_PT = 10
MONO_FAMILY = "Cascadia Mono, Consolas, monospace"


def icon_path(name: str, suffix: str = "svg") -> str:
    """Absolute, forward-slash path of a bundled icon (Qt stylesheets need that form)."""
    return str(resources.files("wzce.data") / "icons" / f"{name}.{suffix}").replace("\\", "/")


def apply_theme(app: QApplication) -> None:
    app.setStyle(QStyleFactory.create("Fusion"))
    app.setFont(QFont(FONT_FAMILY, FONT_SIZE_PT))
    app.setPalette(_palette())
    app.setStyleSheet(stylesheet())


def repolish(widget: QWidget) -> None:
    """Re-evaluate the stylesheet after a dynamic property changed."""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def _palette() -> QPalette:
    c = {k: QColor(v) for k, v in COLORS.items()}
    p = QPalette()
    p.setColor(QPalette.ColorRole.Window, c["bg"])
    p.setColor(QPalette.ColorRole.WindowText, c["text"])
    p.setColor(QPalette.ColorRole.Base, c["surface_alt"])
    p.setColor(QPalette.ColorRole.AlternateBase, c["surface"])
    p.setColor(QPalette.ColorRole.Text, c["text"])
    p.setColor(QPalette.ColorRole.PlaceholderText, c["text_faint"])
    p.setColor(QPalette.ColorRole.Button, c["surface_alt"])
    p.setColor(QPalette.ColorRole.ButtonText, c["text"])
    p.setColor(QPalette.ColorRole.Highlight, c["accent"])
    p.setColor(QPalette.ColorRole.HighlightedText, c["accent_text"])
    p.setColor(QPalette.ColorRole.ToolTipBase, c["surface_alt"])
    p.setColor(QPalette.ColorRole.ToolTipText, c["text"])
    p.setColor(QPalette.ColorRole.Link, c["info"])
    for role in (
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
        QPalette.ColorRole.WindowText,
    ):
        p.setColor(QPalette.ColorGroup.Disabled, role, c["text_faint"])
    return p


def stylesheet() -> str:
    c = COLORS
    down, up, check = icon_path("chevron-down"), icon_path("chevron-up"), icon_path("check")
    return f"""
    QWidget {{ color: {c["text"]}; }}
    QMainWindow, QDialog {{ background: {c["bg"]}; }}
    QToolTip {{
        background: {c["surface_alt"]}; color: {c["text"]};
        border: 1px solid {c["border_strong"]}; padding: 6px; border-radius: 4px;
    }}

    /* ---------- header / panels ---------- */
    #header {{ background: {c["surface"]}; border-bottom: 1px solid {c["border"]}; }}
    #appTitle {{ font-size: 15pt; font-weight: 600; }}
    #appTitle[dirty="true"] {{ color: {c["accent"]}; }}
    #sidePanel {{ background: {c["surface"]}; border: none; }}
    #changesPanel {{ background: {c["surface"]}; border-left: 1px solid {c["border"]}; }}
    #panelTitle {{ font-size: 11pt; font-weight: 600; padding: 4px 2px; }}
    #content {{ background: {c["bg"]}; }}
    QSplitter::handle {{ background: {c["border"]}; }}

    /* ---------- status pill ---------- */
    #gamePill {{ border-radius: 10px; padding: 3px 10px; font-weight: 600; }}
    #gamePill[running="false"] {{ background: #173326; color: {c["success"]}; }}
    #gamePill[running="true"] {{ background: #3a1716; color: {c["danger"]}; }}

    /* ---------- buttons ---------- */
    QPushButton {{
        background: {c["surface_alt"]}; border: 1px solid {c["border"]};
        border-radius: 6px; padding: 5px 12px;
    }}
    QPushButton:hover {{ background: {c["surface_hover"]}; border-color: {c["border_strong"]}; }}
    QPushButton:pressed {{ background: {c["border"]}; }}
    QPushButton:disabled {{ color: {c["text_faint"]}; background: {c["surface"]}; }}
    QPushButton[variant="primary"] {{
        background: {c["accent"]}; color: {c["accent_text"]}; border: none; font-weight: 600;
    }}
    QPushButton[variant="primary"]:hover {{ background: {c["accent_hover"]}; }}
    QPushButton[variant="primary"]:disabled {{ background: {c["border"]}; color: {c["text_faint"]}; }}
    QPushButton[variant="ghost"] {{ background: transparent; border: none; color: {c["text_muted"]}; padding: 3px 6px; }}
    QPushButton[variant="ghost"]:hover {{ color: {c["text"]}; background: {c["surface_hover"]}; }}
    QPushButton[variant="link"] {{ background: transparent; border: none; color: {c["info"]}; padding: 0 4px; }}
    QPushButton[variant="link"]:hover {{ text-decoration: underline; }}

    /* segmented buttons (enum options, language switch) */
    QPushButton[segment="true"] {{ border-radius: 0; padding: 5px 12px; margin: 0; }}
    QPushButton[segment="true"][first="true"] {{ border-top-left-radius: 6px; border-bottom-left-radius: 6px; }}
    QPushButton[segment="true"][last="true"] {{ border-top-right-radius: 6px; border-bottom-right-radius: 6px; }}
    QPushButton[segment="true"]:checked {{
        background: {c["accent"]}; color: {c["accent_text"]}; border-color: {c["accent"]}; font-weight: 600;
    }}

    /* ---------- inputs ---------- */
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
        background: {c["surface_alt"]}; border: 1px solid {c["border"]};
        border-radius: 6px; padding: 4px 8px; selection-background-color: {c["accent"]};
        selection-color: {c["accent_text"]};
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {c["accent"]}; }}
    QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
        color: {c["text_faint"]}; background: {c["surface"]};
    }}
    QLineEdit[invalid="true"] {{ border-color: {c["danger"]}; }}
    #searchBox {{ padding: 6px 10px; min-width: 220px; }}
    QComboBox::drop-down {{ border: none; width: 24px; }}
    QComboBox::down-arrow {{ image: url("{down}"); width: 12px; height: 12px; }}
    QComboBox QAbstractItemView {{
        background: {c["surface_alt"]}; border: 1px solid {c["border_strong"]};
        selection-background-color: {c["surface_hover"]}; selection-color: {c["text"]}; outline: none;
    }}
    QSpinBox, QDoubleSpinBox {{ padding-right: 22px; }}
    QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
        width: 20px; border: none; background: transparent; subcontrol-origin: border;
    }}
    QSpinBox::up-button, QDoubleSpinBox::up-button {{ subcontrol-position: top right; }}
    QSpinBox::down-button, QDoubleSpinBox::down-button {{ subcontrol-position: bottom right; }}
    QSpinBox::up-button:hover, QSpinBox::down-button:hover,
    QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {{ background: {c["surface_hover"]}; }}
    QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url("{up}"); width: 10px; height: 10px; }}
    QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url("{down}"); width: 10px; height: 10px; }}
    QCheckBox {{ spacing: 6px; }}
    QCheckBox::indicator {{
        width: 16px; height: 16px; border-radius: 4px;
        border: 1px solid {c["border_strong"]}; background: {c["surface_alt"]};
    }}
    QCheckBox::indicator:checked {{ background: {c["accent"]}; border-color: {c["accent"]}; image: url("{check}"); }}

    QSlider::groove:horizontal {{ height: 4px; background: {c["border"]}; border-radius: 2px; }}
    QSlider::sub-page:horizontal {{ background: {c["accent"]}; border-radius: 2px; }}
    QSlider::handle:horizontal {{
        background: {c["text"]}; width: 14px; height: 14px; margin: -6px 0; border-radius: 7px;
    }}
    QSlider::handle:horizontal:hover {{ background: {c["accent_hover"]}; }}
    QSlider::sub-page:horizontal:disabled {{ background: {c["border_strong"]}; }}

    /* ---------- navigation ---------- */
    #navList {{ background: transparent; border: none; outline: none; font-size: 10.5pt; }}
    #navList::item {{ padding: 8px 10px; border-radius: 6px; margin: 1px 6px; color: {c["text_muted"]}; }}
    #navList::item:hover {{ background: {c["surface_hover"]}; color: {c["text"]}; }}
    #navList::item:selected {{ background: {c["surface_alt"]}; color: {c["text"]}; border-left: 3px solid {c["accent"]}; }}

    /* ---------- scroll ---------- */
    QScrollArea {{ border: none; background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {c["border_strong"]}; border-radius: 4px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: {c["text_faint"]}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}

    /* ---------- page / cards ---------- */
    #pageTitle {{ font-size: 18pt; font-weight: 600; }}
    #pageSubtitle {{ color: {c["text_muted"]}; }}
    #subgroupTitle {{
        font-size: 9pt; font-weight: 700; color: {c["text_faint"]};
        letter-spacing: 1px; padding-top: 14px; padding-bottom: 2px;
    }}
    #emptyState {{ color: {c["text_muted"]}; font-size: 11pt; padding: 40px; }}

    #card {{
        background: {c["surface"]}; border: 1px solid {c["border"]};
        border-left: 3px solid {c["border"]}; border-radius: 8px;
    }}
    #card:hover {{ border-color: {c["border_strong"]}; }}
    #card[changed="true"] {{ border-left: 3px solid {c["accent"]}; background: #1b1a17; }}
    #card[flash="true"] {{ border-color: {c["accent"]}; }}
    #cardTitle {{ font-size: 11pt; font-weight: 600; }}
    #cardDesc {{ color: {c["text_muted"]}; }}
    #cardKey {{ color: {c["text_faint"]}; font-family: {MONO_FAMILY}; font-size: 8.5pt; }}
    #cardRecommend {{ color: {c["text_muted"]}; font-size: 9pt; }}
    #cardRecommend[match="true"] {{ color: {c["success"]}; }}
    #cardOriginal {{ color: {c["accent"]}; font-size: 9pt; }}

    /* chips / badges */
    #chip {{
        background: {c["surface_alt"]}; border: 1px solid {c["border"]}; border-radius: 9px;
        padding: 1px 8px; font-size: 8.5pt; color: {c["text_muted"]};
    }}
    #chip[kind="new"] {{ background: #13283d; color: {c["info"]}; border-color: #1e4466; }}
    #chip[kind="lock"] {{ background: #2a2318; color: {c["accent"]}; border-color: #4a3b22; }}
    #chip[kind="nvidia"] {{ color: {c["nvidia"]}; border-color: #2f4a10; }}
    #chip[kind="amd"] {{ color: {c["amd"]}; border-color: #4a1416; }}
    #chip[kind="intel"] {{ color: {c["intel"]}; border-color: #13324d; }}
    #chip[kind="hw"] {{ color: {c["text_faint"]}; }}
    #navCount {{ color: {c["accent"]}; font-weight: 700; }}

    /* ---------- changes panel ---------- */
    #changeRow {{ background: {c["surface_alt"]}; border-radius: 6px; }}
    #changeRow:hover {{ background: {c["surface_hover"]}; }}
    #changeLabel {{ font-weight: 600; }}
    #changeValues {{ color: {c["text_muted"]}; font-size: 9pt; }}
    #slotWarning {{ color: {c["accent"]}; font-size: 9pt; }}

    /* ---------- game-change notice ---------- */
    #notice {{ background: #2a2216; border-bottom: 1px solid #4a3b22; }}
    #notice QLabel {{ color: {c["accent_hover"]}; }}

    /* ---------- hardware bar & system dialog ---------- */
    #hwBar {{ background: {c["surface"]}; border-bottom: 1px solid {c["border"]}; }}
    #hwTitle {{ color: {c["text_muted"]}; font-weight: 600; }}
    #hwSummary {{ color: {c["text"]}; }}
    #hwChecks {{ border-radius: 10px; padding: 3px 12px; font-weight: 600; }}
    #hwChecks[warn="true"] {{ background: #3a2a12; color: {c["accent"]}; border: 1px solid #5a4220; }}
    #hwChecks[warn="false"] {{ background: #173326; color: {c["success"]}; border: 1px solid #1f4a37; }}
    #checkRow {{ background: {c["surface"]}; border: 1px solid {c["border"]}; border-left: 3px solid {c["border"]}; border-radius: 8px; }}
    #checkRow[status="warn"][severity="high"] {{ border-left-color: {c["danger"]}; }}
    #checkRow[status="warn"] {{ border-left-color: {c["accent"]}; }}
    #checkRow[status="ok"] {{ border-left-color: {c["success"]}; }}
    #checkRow[status="info"] {{ border-left-color: {c["info"]}; }}
    #checkIcon {{ font-size: 15pt; min-width: 26px; }}
    #checkIcon[status="warn"] {{ color: {c["accent"]}; }}
    #checkIcon[status="ok"] {{ color: {c["success"]}; }}
    #checkIcon[status="info"] {{ color: {c["info"]}; }}
    #checkIcon[status="unknown"] {{ color: {c["text_faint"]}; }}
    #checkFix {{ color: {c["info"]}; }}
    QTabWidget::pane {{ border: 1px solid {c["border"]}; border-radius: 6px; top: -1px; }}
    QTabBar::tab {{ background: {c["surface"]}; color: {c["text_muted"]}; padding: 7px 16px; border: 1px solid {c["border"]}; border-bottom: none; border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 2px; }}
    QTabBar::tab:selected {{ background: {c["surface_alt"]}; color: {c["text"]}; border-top: 2px solid {c["accent"]}; }}

    /* ---------- tables (history) ---------- */
    QTableWidget {{
        background: {c["surface"]}; border: 1px solid {c["border"]}; border-radius: 6px;
        gridline-color: {c["border"]}; alternate-background-color: {c["surface_alt"]};
    }}
    QTableWidget::item {{ padding: 4px 8px; }}
    QTableView::indicator {{
        width: 15px; height: 15px; border-radius: 4px;
        border: 1px solid {c["border_strong"]}; background: {c["surface_alt"]};
    }}
    QTableView::indicator:checked {{ background: {c["accent"]}; border-color: {c["accent"]}; image: url("{check}"); }}
    QHeaderView::section {{
        background: {c["surface_alt"]}; color: {c["text_muted"]}; border: none;
        border-bottom: 1px solid {c["border"]}; padding: 6px 8px; font-weight: 600;
    }}

    /* toggle switch label */
    #toggleText {{ color: {c["text_muted"]}; }}

    QStatusBar {{ background: {c["surface"]}; border-top: 1px solid {c["border"]}; color: {c["text_muted"]}; }}
    QStatusBar QLabel {{ color: {c["text_muted"]}; padding: 0 8px; }}
    QMessageBox {{ background: {c["surface"]}; }}
    QMenu {{ background: {c["surface_alt"]}; border: 1px solid {c["border_strong"]}; }}
    QMenu::item:selected {{ background: {c["surface_hover"]}; }}
    """
