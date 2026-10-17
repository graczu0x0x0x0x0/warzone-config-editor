"""Templates dialog: built-in presets and user templates, preview with checkboxes, apply.

Left: built-in presets and "my templates". Right: what applying the selected
template would change *in the current working copy* (``plan_template``), one
checkbox per change, plus a summary of skipped settings and why.

The dialog never touches the session: "Apply" stores the chosen raw values in
``result_values`` and the main window applies them as one undoable step.

Every file dialog / prompt goes through a small overridable method
(``_edit_template_info``, ``_get_open_path``, ``_get_save_path``, ``_ask``,
``_show_error``) so tests can drive the dialog without modal windows.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.document import ConfigDocument
from ..core.errors import WzceError
from ..core.i18n import Translator
from ..core.knowledge import KnowledgeBase, localized
from ..core.session import EditorSession
from ..core.templates import (
    SkipReason,
    Template,
    TemplatePlan,
    TemplateSource,
    TemplateStore,
    builtin_templates,
    export_template,
    plan_template,
    template_from_document,
)
from .editors import display_value

SETTINGS_SUFFIXES = (".txt0", ".txt1", ".txt")
_TITLE_RE = re.compile(r"\b(cod\d+)\b")


class TemplateInfoDialog(QDialog):
    """Asks for name, description and categories when saving/importing a template."""

    def __init__(
        self,
        tr: Translator,
        knowledge: KnowledgeBase,
        group_ids: list[str],
        default_name: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tr = tr
        self.setWindowTitle(tr("templates.info_title"))
        self.setMinimumWidth(480)
        root = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit(default_name)
        self.description = QLineEdit()
        form.addRow(tr("templates.info_name"), self.name)
        form.addRow(tr("templates.info_description"), self.description)
        root.addLayout(form)

        root.addWidget(QLabel(tr("templates.info_groups")))
        self.group_checks: dict[str, QCheckBox] = {}
        for group in knowledge.groups:
            if group.id in group_ids:
                check = QCheckBox(localized(group.label, tr.language))
                check.setChecked(True)
                self.group_checks[group.id] = check
                root.addWidget(check)

        note = QLabel(tr("templates.info_hardware_note"))
        note.setObjectName("cardDesc")
        note.setWordWrap(True)
        root.addWidget(note)
        self.error = QLabel()
        self.error.setObjectName("slotWarning")
        root.addWidget(self.error)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("dialog.save"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("dialog.cancel"))
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _accept(self) -> None:
        if not self.name.text().strip():
            self.error.setText(self._tr("templates.info_name_required"))
            return
        if not self.selected_groups():
            self.error.setText(self._tr("templates.info_groups_required"))
            return
        self.accept()

    def selected_groups(self) -> list[str]:
        return [gid for gid, check in self.group_checks.items() if check.isChecked()]


class TemplatesDialog(QDialog):
    def __init__(
        self,
        session: EditorSession,
        knowledge: KnowledgeBase,
        tr: Translator,
        store: TemplateStore,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._session = session
        self._kb = knowledge
        self._tr = tr
        self.store = store
        self.templates: list[Template] = []
        self.plan: TemplatePlan | None = None
        self.result_values: dict[str, str] = {}
        self.result_name = ""

        self.setWindowTitle(tr("templates.title"))
        self.resize(1100, 680)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        splitter = QSplitter()
        # --- left: template list ------------------------------------------------
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        self.list.setObjectName("navList")
        self.list.setWordWrap(True)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.currentItemChanged.connect(lambda *_: self._show_selected())
        left_layout.addWidget(self.list, 1)
        self.new_button = QPushButton(tr("templates.new"))
        self.new_button.clicked.connect(self.create_from_current)
        left_layout.addWidget(self.new_button)
        self.import_button = QPushButton(tr("templates.import"))
        self.import_button.clicked.connect(self.import_dialog)
        left_layout.addWidget(self.import_button)
        splitter.addWidget(left)

        # --- right: details and preview -------------------------------------
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 0, 0, 0)
        self.name_label = QLabel()
        self.name_label.setObjectName("pageTitle")
        right_layout.addWidget(self.name_label)
        self.description_label = QLabel()
        self.description_label.setObjectName("cardDesc")
        self.description_label.setWordWrap(True)
        right_layout.addWidget(self.description_label)
        self.meta_label = QLabel()
        self.meta_label.setObjectName("cardRecommend")
        self.meta_label.setWordWrap(True)
        right_layout.addWidget(self.meta_label)
        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        right_layout.addWidget(self.summary_label)

        select_row = QHBoxLayout()
        self.select_all = QPushButton(tr("templates.select_all"))
        self.select_all.setProperty("variant", "link")
        self.select_all.clicked.connect(lambda: self._set_all_checked(True))
        self.select_none = QPushButton(tr("templates.select_none"))
        self.select_none.setProperty("variant", "link")
        self.select_none.clicked.connect(lambda: self._set_all_checked(False))
        select_row.addWidget(self.select_all)
        select_row.addWidget(self.select_none)
        select_row.addStretch()
        right_layout.addLayout(select_row)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(
            [tr("history.col_setting"), tr("templates.col_current"), tr("templates.col_template")]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemChanged.connect(lambda *_: self._update_apply_button())
        right_layout.addWidget(self.table, 1)
        self.skipped_label = QLabel()
        self.skipped_label.setObjectName("cardRecommend")
        self.skipped_label.setWordWrap(True)
        right_layout.addWidget(self.skipped_label)
        splitter.addWidget(right)
        splitter.setSizes([300, 800])
        root.addWidget(splitter, 1)

        # --- bottom buttons --------------------------------------------------
        buttons = QHBoxLayout()
        self.export_button = QPushButton(tr("templates.export"))
        self.export_button.clicked.connect(self.export_dialog)
        buttons.addWidget(self.export_button)
        self.delete_button = QPushButton(tr("templates.delete"))
        self.delete_button.clicked.connect(self.delete_selected)
        buttons.addWidget(self.delete_button)
        buttons.addStretch()
        close = QPushButton(tr("dialog.close"))
        close.clicked.connect(self.reject)
        buttons.addWidget(close)
        self.apply_button = QPushButton()
        self.apply_button.setProperty("variant", "primary")
        self.apply_button.clicked.connect(self.apply_selected)
        buttons.addWidget(self.apply_button)
        root.addLayout(buttons)

        self.reload_templates()

    # ================================================================ list
    def reload_templates(self, select: Template | None = None) -> None:
        tr = self._tr
        builtins = builtin_templates(self._kb, self._session.document, tr.language)
        users = self.store.list()
        self.templates = builtins + users
        self.list.blockSignals(True)
        self.list.clear()
        self._add_header(tr("templates.section_builtin"))
        for template in builtins:
            self._add_template_item(template)
        self._add_header(tr("templates.section_user"))
        if not users:
            hint = QListWidgetItem(tr("templates.user_empty"))
            hint.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(hint)
        for template in users:
            self._add_template_item(template)
        self.list.blockSignals(False)

        # Select the template just saved/imported (matched by file), else the first one.
        rows = [
            (row, self.list.item(row).data(Qt.ItemDataRole.UserRole))
            for row in range(self.list.count())
        ]
        rows = [(row, t) for row, t in rows if t is not None]
        wanted = [
            row for row, t in rows if select is not None and select.path and t.path == select.path
        ]
        target = wanted[0] if wanted else (rows[0][0] if rows else -1)
        self.list.setCurrentRow(target)
        self._show_selected()

    def _add_header(self, text: str) -> None:
        item = QListWidgetItem(text)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        font = item.font()
        font.setBold(True)
        item.setFont(font)
        self.list.addItem(item)

    def _add_template_item(self, template: Template) -> None:
        item = QListWidgetItem(template.name)
        item.setData(Qt.ItemDataRole.UserRole, template)
        if template.description:
            item.setToolTip(template.description)
        self.list.addItem(item)

    def select_template(self, predicate) -> bool:
        """Select the first template matching ``predicate`` (used by tests and callers)."""
        for row in range(self.list.count()):
            template = self.list.item(row).data(Qt.ItemDataRole.UserRole)
            if template is not None and predicate(template):
                self.list.setCurrentRow(row)
                return True
        return False

    @property
    def current_template(self) -> Template | None:
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    # ============================================================= preview
    def _show_selected(self) -> None:
        tr = self._tr
        template = self.current_template
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        self.plan = None
        is_user = template is not None and template.source is TemplateSource.USER
        self.delete_button.setEnabled(is_user)
        self.export_button.setEnabled(template is not None)
        if template is None:
            for label in (self.name_label, self.description_label, self.meta_label):
                label.setText("")
            self.summary_label.setText("")
            self.skipped_label.setText("")
            self.table.blockSignals(False)
            self._update_apply_button()
            return

        self.name_label.setText(template.name)
        self.description_label.setText(template.description)
        self.description_label.setVisible(bool(template.description))
        group_names = [
            localized(self._kb.group(g).label, tr.language)
            for g in template.groups
            if g in {grp.id for grp in self._kb.groups}
        ]
        meta = [tr("templates.meta", groups=", ".join(group_names), count=len(template.values))]
        if template.title_code:
            meta.append(tr("templates.meta_source", title=template.title_code))
        if template.source is TemplateSource.USER:
            meta.append(tr("templates.meta_created", date=template.created.strftime("%Y-%m-%d")))
        self.meta_label.setText(" · ".join(meta))

        document = self._session.document
        plan = plan_template(
            document, self._kb, template.values, gpu_vendor=self._session.gpu_vendor
        )
        self.plan = plan
        plan.changes.sort(key=lambda c: self._display_order(document.get(c.setting_id)))
        self.summary_label.setText(
            tr(
                "templates.summary",
                changes=len(plan.changes),
                unchanged=len(plan.unchanged),
                skipped=len(plan.skipped),
            )
            if plan.changes
            else tr("templates.nothing_to_change")
        )
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
            self.table.setItem(
                row, 1, QTableWidgetItem(display_value(change.old_raw, setting, entry, tr))
            )
            self.table.setItem(
                row, 2, QTableWidgetItem(display_value(change.new_raw, setting, entry, tr))
            )
        self.skipped_label.setText(self._skipped_text(plan))
        self.skipped_label.setVisible(bool(plan.skipped))
        self.table.blockSignals(False)
        self._update_apply_button()

    def _display_order(self, setting) -> tuple[int, int, int]:
        """Same order as the main window: category, subcategory, knowledge-base order."""
        entry = self._kb.entry_for(setting)
        group_ids = [g.id for g in self._kb.groups]
        group_index = group_ids.index(entry.group) if entry.group in group_ids else len(group_ids)
        subgroups = (
            [s.id for s in self._kb.group(entry.group).subgroups]
            if entry.group in group_ids
            else []
        )
        sub_index = (
            subgroups.index(entry.subgroup) if entry.subgroup in subgroups else len(subgroups)
        )
        entry_ids = list(self._kb.entries)
        entry_index = entry_ids.index(setting.id) if setting.id in entry_ids else len(entry_ids)
        return group_index, sub_index, entry_index

    def _skipped_text(self, plan: TemplatePlan) -> str:
        if not plan.skipped:
            return ""
        tr = self._tr
        counts: dict[SkipReason, int] = {}
        for reason in plan.skipped.values():
            counts[reason] = counts.get(reason, 0) + 1
        parts = [f"{tr(f'templates.skip_{reason.value}')}: {n}" for reason, n in counts.items()]
        return f"{tr('templates.skipped_title')} " + " · ".join(parts)

    def checked_ids(self) -> list[str]:
        ids = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                ids.append(item.data(Qt.ItemDataRole.UserRole))
        return ids

    def _set_all_checked(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        self.table.blockSignals(True)
        for row in range(self.table.rowCount()):
            self.table.item(row, 0).setCheckState(state)
        self.table.blockSignals(False)
        self._update_apply_button()

    def _update_apply_button(self) -> None:
        count = len(self.checked_ids())
        self.apply_button.setText(self._tr("templates.apply", count=count))
        self.apply_button.setEnabled(count > 0)

    # ============================================================== actions
    def apply_selected(self) -> None:
        template = self.current_template
        if self.plan is None or template is None:
            return
        self.result_values = self.plan.values(only=self.checked_ids())
        self.result_name = template.name
        if self.result_values:
            self.accept()

    def create_from_current(self) -> Template | None:
        """Save the editor's current values (incl. unsaved edits) as a new template."""
        document = self._session.document
        default = self._tr("templates.default_name", date=datetime.now().strftime("%Y-%m-%d"))
        return self._create_from_document(document, default, self._session.fileset.title_code)

    def _create_from_document(
        self, document: ConfigDocument, default_name: str, title_code: str | None
    ) -> Template | None:
        group_ids = []
        for setting in document:
            group = self._kb.entry_for(setting).group
            if group not in group_ids:
                group_ids.append(group)
        info = self._edit_template_info(default_name, group_ids)
        if info is None:
            return None
        name, description, groups = info
        template = template_from_document(
            document,
            self._kb,
            name,
            groups=groups,
            description=description,
            title_code=title_code,
        )
        self.store.save(template)
        self.reload_templates(select=template)
        return template

    def import_dialog(self) -> None:
        path = self._get_open_path()
        if path:
            self.import_path(Path(path))

    def import_path(self, path: Path) -> Template | None:
        """Import a template ``.json`` or build a template from a game settings file."""
        tr = self._tr
        try:
            if path.suffix.lower() in SETTINGS_SUFFIXES:
                document = ConfigDocument.from_bytes(path.read_bytes())
                match = _TITLE_RE.search(path.name)
                template = self._create_from_document(
                    document, path.stem, match.group(1) if match else None
                )
            else:
                template = self.store.import_file(path)
                self.reload_templates(select=template)
        except (WzceError, OSError) as exc:
            self._show_error(tr("templates.error", error=exc))
            return None
        return template

    def export_dialog(self) -> None:
        template = self.current_template
        if template is None:
            return
        path = self._get_save_path(f"{template.name}.json")
        if path:
            self.export_to(Path(path))

    def export_to(self, path: Path) -> Path | None:
        template = self.current_template
        if template is None:
            return None
        if path.suffix.lower() != ".json":
            path = path.with_suffix(".json")
        try:
            return export_template(template, path)
        except OSError as exc:
            self._show_error(self._tr("templates.error", error=exc))
            return None

    def delete_selected(self) -> None:
        template = self.current_template
        if template is None or template.source is not TemplateSource.USER:
            return
        if not self._ask(
            self._tr("templates.delete"), self._tr("templates.delete_confirm", name=template.name)
        ):
            return
        try:
            self.store.delete(template)
        except WzceError as exc:
            self._show_error(self._tr("templates.error", error=exc))
            return
        self.reload_templates()

    # ============================================================ hooks
    def _edit_template_info(
        self, default_name: str, group_ids: list[str]
    ) -> tuple[str, str, list[str]] | None:
        dialog = TemplateInfoDialog(self._tr, self._kb, group_ids, default_name, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return (
            dialog.name.text().strip(),
            dialog.description.text().strip(),
            dialog.selected_groups(),
        )

    def _get_open_path(self) -> str:
        path, _ = QFileDialog.getOpenFileName(
            self, self._tr("templates.import_title"), "", self._tr("templates.import_filter")
        )
        return path

    def _get_save_path(self, suggested: str) -> str:
        path, _ = QFileDialog.getSaveFileName(
            self, self._tr("templates.export_title"), suggested, self._tr("templates.export_filter")
        )
        return path

    def _ask(self, title: str, text: str) -> bool:
        buttons = QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        box = QMessageBox(QMessageBox.Icon.Question, title, text, buttons, self)
        box.button(QMessageBox.StandardButton.Yes).setText(self._tr("dialog.yes"))
        box.button(QMessageBox.StandardButton.No).setText(self._tr("dialog.no"))
        return box.exec() == QMessageBox.StandardButton.Yes

    def _show_error(self, text: str) -> None:
        QMessageBox(
            QMessageBox.Icon.Critical,
            self._tr("error.title"),
            text,
            QMessageBox.StandardButton.Ok,
            self,
        ).exec()
