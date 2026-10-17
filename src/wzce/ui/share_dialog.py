"""'Share settings' dialog: pick categories and format, preview, copy or save.

The preview is regenerated on every change, so what you copy is exactly what you
see. Building the text is done in ``core/share_export.py``; this module is only
the form around it. File dialogs go through ``_get_save_path`` so tests can
replace them.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..core.document import ConfigDocument
from ..core.hardware import HardwareInfo
from ..core.i18n import Translator
from ..core.knowledge import KnowledgeBase, localized
from ..core.share_export import (
    DEFAULT_GROUPS,
    build_share,
    hardware_summary,
    to_json,
    to_markdown,
)
from ..core.system_info import SystemInfo
from .theme import MONO_FAMILY

APP_LABEL = f"Warzone Config Editor {__version__}"


class ShareDialog(QDialog):
    def __init__(
        self,
        document: ConfigDocument,
        knowledge: KnowledgeBase,
        tr: Translator,
        *,
        game: str,
        title_code: str | None,
        system_info: SystemInfo | None = None,
        hardware: HardwareInfo | None = None,
        has_unsaved_changes: bool = False,
        default_groups: Iterable[str] | None = None,
        gpu_vendor: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._document = document
        self._kb = knowledge
        self._tr = tr
        self._game = game
        self._title_code = title_code
        self._gpu_vendor = gpu_vendor
        self._hardware_lines = hardware_summary(system_info, hardware, tr)

        self.setWindowTitle(tr("share.title"))
        self.resize(980, 720)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        # --- categories (only those present in the open file) ----------------
        root.addWidget(self._section(tr("share.categories")))
        present = {knowledge.entry_for(s).group for s in document}
        grid = QGridLayout()
        self.group_checks: dict[str, QCheckBox] = {}
        groups = [g for g in knowledge.groups if g.id in present]
        # Default: the graphics-related categories (machine file). The caller passes
        # all groups for an account file (aim, audio...); fall back to everything if
        # none of the defaults exists in this file.
        present_ids = {g.id for g in groups}
        wanted = set(default_groups) if default_groups is not None else set(DEFAULT_GROUPS)
        defaults = present_ids & wanted or present_ids
        for index, group in enumerate(groups):
            check = QCheckBox(localized(group.label, tr.language))
            check.setChecked(group.id in defaults)
            check.toggled.connect(self.refresh)  # connected after the initial state
            self.group_checks[group.id] = check
            grid.addWidget(check, index // 4, index % 4)
        root.addLayout(grid)

        # --- options ------------------------------------------------------------
        options = QHBoxLayout()
        self.basic_only = QCheckBox(tr("share.basic_only"))
        self.basic_only.setChecked(True)
        self.basic_only.toggled.connect(self.refresh)
        options.addWidget(self.basic_only)
        self.include_hardware = QCheckBox(tr("share.include_hardware"))
        self.include_hardware.setChecked(bool(self._hardware_lines))
        self.include_hardware.setEnabled(bool(self._hardware_lines))
        self.include_hardware.toggled.connect(self.refresh)
        options.addWidget(self.include_hardware)
        options.addStretch()
        root.addLayout(options)

        formats = QHBoxLayout()
        formats.addWidget(QLabel(tr("share.format")))
        self.markdown_radio = QRadioButton(tr("share.markdown"))
        self.json_radio = QRadioButton(tr("share.json"))
        self.markdown_radio.setChecked(True)
        self._format_group = QButtonGroup(self)
        for radio in (self.markdown_radio, self.json_radio):
            self._format_group.addButton(radio)
            radio.toggled.connect(self.refresh)
            formats.addWidget(radio)
        formats.addStretch()
        root.addLayout(formats)

        # --- preview --------------------------------------------------------------
        self.summary = QLabel()
        self.summary.setObjectName("cardRecommend")
        root.addWidget(self.summary)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        font = QFont(MONO_FAMILY.split(",")[0])
        font.setPointSize(9)
        self.preview.setFont(font)
        root.addWidget(self.preview, 1)
        note = QLabel(tr("share.note"))
        note.setObjectName("cardDesc")
        note.setWordWrap(True)
        root.addWidget(note)
        if has_unsaved_changes:
            unsaved = QLabel(tr("share.unsaved"))
            unsaved.setObjectName("slotWarning")
            root.addWidget(unsaved)

        # --- buttons -------------------------------------------------------------
        buttons = QHBoxLayout()
        self.copy_button = QPushButton(tr("share.copy"))
        self.copy_button.setProperty("variant", "primary")
        self.copy_button.clicked.connect(self.copy)
        buttons.addWidget(self.copy_button)
        self.save_button = QPushButton(tr("share.save"))
        self.save_button.clicked.connect(self.save_dialog)
        buttons.addWidget(self.save_button)
        self.status = QLabel()
        self.status.setObjectName("cardRecommend")
        buttons.addWidget(self.status, 1)
        close = QPushButton(tr("dialog.close"))
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        root.addLayout(buttons)

        self.refresh()

    @staticmethod
    def _section(text: str) -> QLabel:
        label = QLabel(text.upper())
        label.setObjectName("subgroupTitle")
        return label

    # ------------------------------------------------------------------- text
    @property
    def is_json(self) -> bool:
        return self.json_radio.isChecked()

    def text(self) -> str:
        groups = [gid for gid, check in self.group_checks.items() if check.isChecked()]
        export = build_share(
            self._document,
            self._kb,
            self._tr,
            game=self._game,
            title_code=self._title_code,
            app=APP_LABEL,
            groups=groups,
            include_advanced=not self.basic_only.isChecked(),
            hardware=self._hardware_lines if self.include_hardware.isChecked() else None,
            gpu_vendor=self._gpu_vendor,
        )
        self._count = export.setting_count
        return to_json(export) if self.is_json else to_markdown(export, self._tr)

    def refresh(self) -> None:
        self.preview.setPlainText(self.text())
        self.summary.setText(self._tr("share.summary", count=self._count))
        enabled = self._count > 0
        self.copy_button.setEnabled(enabled)
        self.save_button.setEnabled(enabled)
        self.status.setText("")

    # ---------------------------------------------------------------- actions
    def copy(self) -> None:
        QGuiApplication.clipboard().setText(self.preview.toPlainText())
        self.status.setText(self._tr("share.copied"))

    def save_dialog(self) -> None:
        suffix = ".json" if self.is_json else ".md"
        name = f"{self._title_code or 'cod'}-settings{suffix}"
        path = self._get_save_path(name)
        if path:
            self.save_to(Path(path))

    def save_to(self, path: Path) -> Path:
        suffix = ".json" if self.is_json else ".md"
        if path.suffix.lower() != suffix:
            path = path.with_suffix(suffix)
        path.write_text(self.preview.toPlainText(), encoding="utf-8")
        self.status.setText(self._tr("share.saved", path=str(path)))
        return path

    def _get_save_path(self, suggested: str) -> str:
        file_filter = self._tr("share.filter_json" if self.is_json else "share.filter_md")
        path, _ = QFileDialog.getSaveFileName(
            self, self._tr("share.save_title"), suggested, file_filter
        )
        return path
