"""Reusable preview of a ``TemplatePlan``: checkable rows "current -> new", skipped summary.

Used by the templates dialog and the optimizer wizard. Rows follow the same order
as the main window (category, subcategory, knowledge-base order). An optional
"why" column shows a reason per setting (the optimizer's explanations).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.document import ConfigDocument
from ..core.i18n import Translator
from ..core.knowledge import KnowledgeBase, localized
from ..core.model import Setting
from ..core.templates import SkipReason, TemplatePlan
from .editors import display_value


class PlanTable(QWidget):
    selection_changed = Signal(int)  # number of checked rows

    def __init__(
        self,
        tr: Translator,
        knowledge: KnowledgeBase,
        *,
        with_reasons: bool = False,
        template_header: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tr = tr
        self._kb = knowledge
        self._with_reasons = with_reasons
        self.plan: TemplatePlan | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        select_row = QHBoxLayout()
        self.select_all = QPushButton(tr("templates.select_all"))
        self.select_all.setProperty("variant", "link")
        self.select_all.clicked.connect(lambda: self.set_all_checked(True))
        self.select_none = QPushButton(tr("templates.select_none"))
        self.select_none.setProperty("variant", "link")
        self.select_none.clicked.connect(lambda: self.set_all_checked(False))
        select_row.addWidget(self.select_all)
        select_row.addWidget(self.select_none)
        select_row.addStretch()
        layout.addLayout(select_row)

        headers = [
            tr("history.col_setting"),
            tr("templates.col_current"),
            template_header or tr("templates.col_template"),
        ]
        if with_reasons:
            headers.append(tr("optimizer.col_reason"))
        self.table = QTableWidget(0, len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, len(headers)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemChanged.connect(
            lambda *_: self.selection_changed.emit(len(self.checked_ids()))
        )
        layout.addWidget(self.table, 1)

        self.skipped_label = QLabel()
        self.skipped_label.setObjectName("cardRecommend")
        self.skipped_label.setWordWrap(True)
        layout.addWidget(self.skipped_label)

    # ---------------------------------------------------------------- data
    def set_plan(
        self,
        plan: TemplatePlan | None,
        document: ConfigDocument,
        reasons: dict[str, str] | None = None,
    ) -> None:
        """Show ``plan``; ``reasons`` maps setting id -> already translated text."""
        tr = self._tr
        self.plan = plan
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        if plan is not None:
            plan.changes.sort(key=lambda c: self._display_order(document.get(c.setting_id)))
            self.table.setRowCount(len(plan.changes))
            for row, change in enumerate(plan.changes):
                setting = document.get(change.setting_id)
                entry = self._kb.entry_for(setting)
                name = QTableWidgetItem(localized(entry.label, tr.language))
                name.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
                name.setCheckState(Qt.CheckState.Checked)
                name.setData(Qt.ItemDataRole.UserRole, change.setting_id)
                name.setToolTip(change.setting_id)
                self.table.setItem(row, 0, name)
                old = display_value(change.old_raw, setting, entry, tr)
                new = display_value(change.new_raw, setting, entry, tr)
                self.table.setItem(row, 1, QTableWidgetItem(old))
                self.table.setItem(row, 2, QTableWidgetItem(new))
                if self._with_reasons:
                    reason = (reasons or {}).get(change.setting_id, "")
                    item = QTableWidgetItem(reason)
                    item.setToolTip(reason)
                    self.table.setItem(row, 3, item)
        self.skipped_label.setText(self._skipped_text(plan))
        self.skipped_label.setVisible(bool(plan and plan.skipped))
        self.table.blockSignals(False)
        self.selection_changed.emit(len(self.checked_ids()))

    def _display_order(self, setting: Setting) -> tuple[int, int, int]:
        """Same order as the main window: category, subcategory, knowledge-base order."""
        entry = self._kb.entry_for(setting)
        groups = {g.id: g for g in self._kb.groups}
        group_ids = list(groups)
        last = len(group_ids)
        group_index = group_ids.index(entry.group) if entry.group in groups else last
        subgroups = [s.id for s in groups[entry.group].subgroups] if entry.group in groups else []
        sub_index = subgroups.index(entry.subgroup) if entry.subgroup in subgroups else last
        entry_ids = list(self._kb.entries)
        entry_index = entry_ids.index(setting.id) if setting.id in entry_ids else len(entry_ids)
        return group_index, sub_index, entry_index

    def _skipped_text(self, plan: TemplatePlan | None) -> str:
        if plan is None or not plan.skipped:
            return ""
        tr = self._tr
        counts: dict[SkipReason, int] = {}
        for reason in plan.skipped.values():
            counts[reason] = counts.get(reason, 0) + 1
        parts = [f"{tr(f'templates.skip_{reason.value}')}: {n}" for reason, n in counts.items()]
        return f"{tr('templates.skipped_title')} " + " · ".join(parts)

    # ----------------------------------------------------------- selection
    def checked_ids(self) -> list[str]:
        ids = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                ids.append(item.data(Qt.ItemDataRole.UserRole))
        return ids

    def set_all_checked(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        self.table.blockSignals(True)
        for row in range(self.table.rowCount()):
            self.table.item(row, 0).setCheckState(state)
        self.table.blockSignals(False)
        self.selection_changed.emit(len(self.checked_ids()))

    def checked_values(self) -> dict[str, str]:
        return self.plan.values(only=self.checked_ids()) if self.plan else {}
