"""Right-hand panel listing pending changes ("before -> after") with per-row revert."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..core.i18n import Translator
from ..core.knowledge import KnowledgeBase, localized
from ..core.session import EditorSession
from .editors import display_value


class ChangesPanel(QFrame):
    revert_requested = Signal(str)  # setting id
    jump_requested = Signal(str)  # setting id
    discard_all_requested = Signal()

    def __init__(self, tr: Translator, kb: KnowledgeBase, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("changesPanel")
        self._tr = tr
        self._kb = kb

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)
        self.title = QLabel()
        self.title.setObjectName("panelTitle")
        root.addWidget(self.title)
        self.slot_warning = QLabel()
        self.slot_warning.setObjectName("slotWarning")
        self.slot_warning.setWordWrap(True)
        root.addWidget(self.slot_warning)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._list_host = QWidget()
        self._list_host.setObjectName("sidePanel")
        self._list = QVBoxLayout(self._list_host)
        self._list.setContentsMargins(0, 0, 0, 0)
        self._list.setSpacing(6)
        self._scroll.setWidget(self._list_host)
        root.addWidget(self._scroll, 1)

        self.discard_button = QPushButton()
        self.discard_button.clicked.connect(self.discard_all_requested)
        root.addWidget(self.discard_button)

    def refresh(self, session: EditorSession | None) -> None:
        tr = self._tr
        while self._list.count():
            item = self._list.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()

        changes = session.pending_changes() if session else []
        self.title.setText(f"{tr('changes.title')} ({len(changes)})")
        self.discard_button.setText(tr("changes.discard_all"))
        self.discard_button.setEnabled(bool(changes))

        differences = session.loaded.slot_differences if session else []
        self.slot_warning.setText(tr("file.slots_differ", count=len(differences)))
        self.slot_warning.setVisible(bool(differences))

        if not changes:
            empty = QLabel(tr("changes.empty"))
            empty.setObjectName("changeValues")
            self._list.addWidget(empty)
        assert session is not None or not changes
        for change in changes:
            setting = session.document.get(change.setting_id)
            entry = self._kb.entry_for(setting)
            old = display_value(change.old_raw or "", setting, entry, tr)
            new = display_value(change.new_raw or "", setting, entry, tr)
            self._list.addWidget(
                self._row(change.setting_id, localized(entry.label, tr.language), old, new)
            )
        self._list.addStretch()

    def _row(self, setting_id: str, label: str, old: str, new: str) -> QWidget:
        row = QFrame()
        row.setObjectName("changeRow")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(10, 6, 4, 6)
        texts = QVBoxLayout()
        texts.setSpacing(1)
        name = QPushButton(label)
        name.setObjectName("changeLabel")
        name.setProperty("variant", "ghost")
        name.setStyleSheet("text-align: left; padding: 0;")
        name.setCursor(Qt.CursorShape.PointingHandCursor)
        name.setToolTip(self._tr("changes.jump"))
        name.clicked.connect(lambda: self.jump_requested.emit(setting_id))
        texts.addWidget(name)
        values = QLabel(self._tr("changes.row", old=old, new=new))
        values.setObjectName("changeValues")
        values.setWordWrap(True)
        texts.addWidget(values)
        layout.addLayout(texts, 1)
        revert = QPushButton("↺")
        revert.setProperty("variant", "ghost")
        revert.setToolTip(self._tr("changes.revert"))
        revert.setCursor(Qt.CursorShape.PointingHandCursor)
        revert.clicked.connect(lambda: self.revert_requested.emit(setting_id))
        layout.addWidget(revert, 0, Qt.AlignmentFlag.AlignTop)
        return row
