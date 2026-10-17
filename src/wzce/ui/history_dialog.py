"""History dialog: list of saves and game changes, per-entry diff, two restore actions.

Restoring never writes to disk directly. The dialog only *chooses* raw values;
the main window loads them into the working copy as one undoable step, and the
user saves as usual (with backup). Settings the game manages itself (driver
versions, window position, detected hardware...) are filtered out by the caller.

* "Undo these changes"      -> old values of just the settings in this entry
* "Restore this whole state" -> every value from the snapshot after this entry
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.history import EntryKind, HistoryEntry
from ..core.i18n import Translator
from ..core.knowledge import KnowledgeBase, localized
from ..core.session import EditorSession
from .editors import display_value


class HistoryDialog(QDialog):
    def __init__(
        self,
        session: EditorSession,
        knowledge: KnowledgeBase,
        tr: Translator,
        *,
        select_entry_id: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._session = session
        self._kb = knowledge
        self._tr = tr
        self.entries: list[HistoryEntry] = session.history.list(session.fileset)
        # Filled when the user picks an action; read by the main window after exec().
        self.result_values: dict[str, str] = {}

        self.setWindowTitle(tr("history.title"))
        self.resize(1000, 620)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        title = QLabel(f"{tr('history.title')} — {session.fileset.stem}")
        title.setObjectName("panelTitle")
        root.addWidget(title)

        splitter = QSplitter()
        self.entry_list = QListWidget()
        self.entry_list.setObjectName("navList")
        self.entry_list.setWordWrap(True)
        self.entry_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.entry_list.currentRowChanged.connect(self._show_entry)
        splitter.addWidget(self.entry_list)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(
            [tr("history.col_setting"), tr("history.col_before"), tr("history.col_after")]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2):
            self.table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )
        splitter.addWidget(self.table)
        splitter.setSizes([340, 660])
        root.addWidget(splitter, 1)

        self.empty_label = QLabel(tr("history.empty"))
        self.empty_label.setObjectName("emptyState")
        self.empty_label.setWordWrap(True)
        root.addWidget(self.empty_label)

        buttons = QHBoxLayout()
        self.open_backups = QPushButton(tr("backup.open_folder"))
        self.open_backups.clicked.connect(self._open_backup_folder)
        buttons.addWidget(self.open_backups)
        buttons.addStretch()
        self.undo_entry_button = QPushButton(tr("history.undo_entry"))
        self.undo_entry_button.setToolTip(tr("history.undo_entry_tip"))
        self.undo_entry_button.clicked.connect(self._choose_undo_entry)
        buttons.addWidget(self.undo_entry_button)
        self.restore_button = QPushButton(tr("history.restore_state"))
        self.restore_button.setToolTip(tr("history.restore_state_tip"))
        self.restore_button.setProperty("variant", "primary")
        self.restore_button.clicked.connect(self._choose_restore_state)
        buttons.addWidget(self.restore_button)
        close = QPushButton(tr("dialog.close"))
        close.clicked.connect(self.reject)
        buttons.addWidget(close)
        root.addLayout(buttons)

        self._fill_entries(select_entry_id)

    # ---------------------------------------------------------------- entries
    def entry_text(self, entry: HistoryEntry) -> str:
        tr = self._tr
        kind = tr(
            "history.kind_save" if entry.kind is EntryKind.SAVE else "history.kind_game_change"
        )
        when = entry.created.strftime("%Y-%m-%d %H:%M:%S")
        summary = tr("history.entry", kind=kind, count=len(entry.changes))
        return f"{when}\n{summary}"

    def _fill_entries(self, select_entry_id: str | None) -> None:
        has_entries = bool(self.entries)
        self.empty_label.setVisible(not has_entries)
        for button in (self.undo_entry_button, self.restore_button):
            button.setEnabled(has_entries)
        selected = 0
        for index, entry in enumerate(self.entries):
            item = QListWidgetItem(self.entry_text(entry))
            item.setData(Qt.ItemDataRole.UserRole, index)
            if entry.note:
                item.setToolTip(entry.note)
            self.entry_list.addItem(item)
            if entry.id == select_entry_id:
                selected = index
        if has_entries:
            self.entry_list.setCurrentRow(selected)

    @property
    def current_entry(self) -> HistoryEntry | None:
        row = self.entry_list.currentRow()
        return self.entries[row] if 0 <= row < len(self.entries) else None

    def _show_entry(self, row: int) -> None:
        tr = self._tr
        self.table.setRowCount(0)
        if not 0 <= row < len(self.entries):
            return
        entry = self.entries[row]
        document = self._session.document
        self.table.setRowCount(len(entry.changes))
        for r, change in enumerate(entry.changes):
            if change.setting_id in document:
                setting = document.get(change.setting_id)
                kb_entry = self._kb.entry_for(setting)
                label = localized(kb_entry.label, tr.language)
                before = display_value(change.old_raw or "", setting, kb_entry, tr)
                after = display_value(change.new_raw or "", setting, kb_entry, tr)
            else:
                label = f"{change.setting_id} {tr('history.missing_setting')}"
                before, after = change.old_raw or "—", change.new_raw or "—"
            name_item = QTableWidgetItem(label)
            name_item.setToolTip(change.setting_id)
            self.table.setItem(r, 0, name_item)
            self.table.setItem(
                r, 1, QTableWidgetItem(before if change.old_raw is not None else "—")
            )
            self.table.setItem(r, 2, QTableWidgetItem(after if change.new_raw is not None else "—"))

    # ---------------------------------------------------------------- actions
    def _choose_undo_entry(self) -> None:
        entry = self.current_entry
        if entry is not None:
            self.result_values = entry.old_values()
            self.accept()

    def _choose_restore_state(self) -> None:
        entry = self.current_entry
        if entry is not None:
            self.result_values = entry.load_snapshot().values()
            self.accept()

    def _open_backup_folder(self) -> None:
        folder = self._session.backup_manager.root
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
