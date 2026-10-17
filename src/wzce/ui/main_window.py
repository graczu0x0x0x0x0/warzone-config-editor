"""Main window: header (file, filters, actions), category navigation, cards, changes panel.

Data flow
---------
* ``EditorSession`` (core) is the only state. Widgets read from it; edits go
  through ``_on_value_edited`` / ``_on_revert`` which update the session and then
  refresh the affected card, the navigation counters and the changes panel.
* The card page is rebuilt from scratch when the category, search, filters or
  language change (~170 cards max, fast enough). Rebuilds triggered from inside a
  card's own signal are deferred with ``QTimer.singleShot(0, ...)`` so the card is
  never deleted while its handler is still running.
* Every dialog goes through ``_ask`` / ``_prompt_unsaved`` / ``_show_message`` /
  ``_exec_dialog`` so tests can replace them.
* Undo/redo, discard and history restores all go through the session's undo stack;
  ``_after_changes(ids)`` is the one refresh path for any change to the working copy.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..core.backup import BackupManager
from ..core.discovery import (
    TITLE_NAMES,
    ConfigLocation,
    FileKind,
    Scope,
    classify_stem,
    discover,
)
from ..core.document import ConfigDocument
from ..core.errors import GameRunningError, ValidationError, WzceError
from ..core.hardware import HardwareInfo, detect_hardware
from ..core.history import HistoryEntry
from ..core.i18n import Translator, language_name
from ..core.knowledge import SUPPORTED_LANGUAGES, KnowledgeBase, KnowledgeEntry, localized
from ..core.model import Setting
from ..core.optimizer import Goal
from ..core.paths import app_data_dir
from ..core.process import GameRunningCheck, is_game_running
from ..core.session import EditorSession
from ..core.storage import SettingsFileSet
from ..core.system_checks import CheckResult, Severity, Status, evaluate_checks, warnings
from ..core.system_info import SystemInfo, collect_system_info
from ..core.templates import TemplateStore
from ..core.undo import CommandKind
from .app_settings import AppSettings
from .changes_panel import ChangesPanel
from .history_dialog import HistoryDialog
from .optimizer_dialog import OptimizerDialog
from .setting_card import SettingCard
from .share_dialog import ShareDialog
from .system_panel import HardwareBar, SystemDialog, SystemProbe, bar_items, check_title
from .templates_dialog import TemplatesDialog
from .theme import repolish

NAV_ALL = "__all__"
NAV_CHANGED = "__changed__"
OPEN_OTHER = "__open__"
GAME_POLL_MS = 2000
STATUS_TIMEOUT_MS = 8000


class MainWindow(QMainWindow):
    def __init__(
        self,
        knowledge: KnowledgeBase,
        tr: Translator,
        settings: AppSettings,
        *,
        locations: list[ConfigLocation] | None = None,
        backup_manager: BackupManager | None = None,
        game_running: GameRunningCheck = is_game_running,
        template_store: TemplateStore | None = None,
        hardware_provider: Callable[[ConfigDocument | None], HardwareInfo] = detect_hardware,
        system_info_provider: Callable[[], SystemInfo] | None = collect_system_info,
        async_system_info: bool = True,
        poll: bool = True,
    ) -> None:
        super().__init__()
        self.knowledge = knowledge
        self.tr = tr
        self.settings = settings
        self._backup_manager = backup_manager
        self.template_store = template_store if template_store is not None else TemplateStore()
        self._hardware_provider = hardware_provider
        self._hardware: HardwareInfo | None = None  # detected lazily, once
        # Detailed spec + checks arrive later from a background probe (2-4 s).
        self.system_info: SystemInfo | None = None
        self.system_checks: list[CheckResult] = []
        self._system_probe = SystemProbe(self)
        self._system_probe.ready.connect(self._on_system_info)
        self._game_running_check = game_running
        self._game_running = False
        self.session: EditorSession | None = None
        self.cards: dict[str, SettingCard] = {}
        self._nav_key = "display"
        self._disk_warning_shown = False

        # Machine settings first, then account files (sensitivity, FOV...) - discover()
        # already sorts them that way per title.
        self._locations = discover() if locations is None else list(locations)
        self._extra_files: list[SettingsFileSet] = []
        self._entry_order = {sid: i for i, sid in enumerate(knowledge.entries)}

        self.resize(1440, 900)
        self._build_ui()
        self._restore_window_state()
        self._apply_texts()
        self._populate_file_combo()
        self._open_initial_file()
        tr.add_listener(self._on_language_changed)

        self._timer = QTimer(self)
        self._timer.setInterval(GAME_POLL_MS)
        self._timer.timeout.connect(self._poll)
        self._poll()
        if poll:
            self._timer.start()
        if system_info_provider is not None:
            if async_system_info:
                self._system_probe.start(system_info_provider)
            else:
                self._on_system_info(system_info_provider())

    # =================================================================== UI
    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())
        self.hw_bar = HardwareBar(self.tr, collapsed=self.settings.hardware_bar_collapsed)
        self.hw_bar.details_requested.connect(lambda: self.open_system_dialog())
        self.hw_bar.checks_requested.connect(lambda: self.open_system_dialog(show_checks=True))
        self.hw_bar.collapsed_changed.connect(self._on_hw_bar_collapsed)
        root.addWidget(self.hw_bar)
        root.addWidget(self._build_notice())

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(1)

        nav_host = QFrame()
        nav_host.setObjectName("sidePanel")
        nav_layout = QVBoxLayout(nav_host)
        nav_layout.setContentsMargins(0, 12, 0, 12)
        self.nav = QListWidget()
        self.nav.setObjectName("navList")
        self.nav.currentItemChanged.connect(self._on_nav_changed)
        nav_layout.addWidget(self.nav)
        nav_host.setMinimumWidth(210)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("content")
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(QWidget())

        self.changes_panel = ChangesPanel(self.tr, self.knowledge)
        self.changes_panel.setMinimumWidth(260)
        self.changes_panel.revert_requested.connect(self._on_revert)
        self.changes_panel.jump_requested.connect(self.navigate_to)
        self.changes_panel.discard_all_requested.connect(self._discard_all)

        self.splitter.addWidget(nav_host)
        self.splitter.addWidget(self.scroll)
        self.splitter.addWidget(self.changes_panel)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([230, 900, 310])
        root.addWidget(self.splitter, 1)
        self.setCentralWidget(central)

        bar = self.statusBar()
        self.status_file = QLabel()
        self.status_count = QLabel()
        self.status_gpu = QLabel()
        bar.addPermanentWidget(self.status_count)
        bar.addPermanentWidget(self.status_gpu)
        bar.addPermanentWidget(self.status_file)

        QShortcut(QKeySequence.StandardKey.Save, self, activated=self.save)
        QShortcut(QKeySequence.StandardKey.Find, self, activated=self.search.setFocus)
        QShortcut(QKeySequence.StandardKey.Undo, self, activated=self.undo)
        QShortcut(QKeySequence.StandardKey.Redo, self, activated=self.redo)
        QShortcut(QKeySequence("Ctrl+Shift+Z"), self, activated=self.redo)

    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("header")
        outer = QVBoxLayout(header)
        outer.setContentsMargins(16, 10, 16, 10)
        outer.setSpacing(8)

        # Row 1: file + game state + editing actions (undo/redo/discard/save) + language.
        # Row 2: finding settings (search, filters, recommendations) + dialogs/tools.
        # Keep both rows roughly the same width: the wider one sets the window minimum.
        row1 = QHBoxLayout()
        row1.setSpacing(10)
        self.title_label = QLabel()
        self.title_label.setObjectName("appTitle")
        row1.addWidget(self.title_label)
        row1.addSpacing(12)
        self.file_label = QLabel()
        row1.addWidget(self.file_label)
        self.file_combo = QComboBox()
        self.file_combo.setMinimumWidth(300)
        self.file_combo.activated.connect(self._on_file_activated)
        row1.addWidget(self.file_combo)
        self.game_pill = QLabel()
        self.game_pill.setObjectName("gamePill")
        row1.addWidget(self.game_pill)
        row1.addStretch()
        # Plain text labels: the arrow glyphs are missing from many Windows UI fonts.
        self.undo_button = QPushButton()
        self.undo_button.clicked.connect(self.undo)
        self.redo_button = QPushButton()
        self.redo_button.clicked.connect(self.redo)
        self.discard_button = QPushButton()
        self.discard_button.clicked.connect(self._discard_all)
        self.save_button = QPushButton()
        self.save_button.setProperty("variant", "primary")
        self.save_button.setMinimumWidth(120)
        self.save_button.clicked.connect(self.save)
        for button in (self.undo_button, self.redo_button, self.discard_button, self.save_button):
            row1.addWidget(button)
        row1.addSpacing(12)
        self.language_group = QButtonGroup(self)
        for index, code in enumerate(SUPPORTED_LANGUAGES):
            button = QPushButton(code.upper())
            button.setCheckable(True)
            button.setProperty("segment", True)
            button.setProperty("first", index == 0)
            button.setProperty("last", index == len(SUPPORTED_LANGUAGES) - 1)
            button.setToolTip(language_name(code))
            button.setChecked(code == self.tr.language)
            button.clicked.connect(lambda _=False, c=code: self.set_language(c))
            self.language_group.addButton(button)
            row1.addWidget(button)
        outer.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(10)
        self.search = QLineEdit()
        self.search.setObjectName("searchBox")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _t: self._render_page())
        row2.addWidget(self.search)
        self.advanced_check = QCheckBox()
        self.advanced_check.setChecked(self.settings.advanced)
        self.advanced_check.toggled.connect(self._on_filter_changed)
        row2.addWidget(self.advanced_check)
        self.vendor_check = QCheckBox()
        self.vendor_check.setChecked(self.settings.hide_other_vendors)
        self.vendor_check.toggled.connect(self._on_filter_changed)
        row2.addWidget(self.vendor_check)
        row2.addSpacing(12)
        self.preset_label = QLabel()
        row2.addWidget(self.preset_label)
        self.preset_combo = QComboBox()
        self.preset_combo.setMinimumWidth(170)
        self.preset_combo.activated.connect(self._on_preset_changed)
        row2.addWidget(self.preset_combo)
        row2.addStretch()
        self.optimize_button = QPushButton()
        self.optimize_button.clicked.connect(self.open_optimizer)
        row2.addWidget(self.optimize_button)
        self.templates_button = QPushButton()
        self.templates_button.clicked.connect(self.open_templates)
        row2.addWidget(self.templates_button)
        self.history_button = QPushButton()
        self.history_button.clicked.connect(lambda: self.open_history())
        row2.addWidget(self.history_button)
        self.tools_button = QPushButton()
        self.tools_menu = QMenu(self)
        self.reload_action = QAction(self)
        self.reload_action.triggered.connect(self._reload)
        self.game_reset_action = QAction(self)
        self.game_reset_action.triggered.connect(self.request_game_reset)
        self.read_only_action = QAction(self)
        self.read_only_action.setCheckable(True)
        self.read_only_action.triggered.connect(self.set_files_read_only)
        self.open_folder_action = QAction(self)
        self.open_folder_action.triggered.connect(self._open_game_folder)
        self.open_backups_action = QAction(self)
        self.open_backups_action.triggered.connect(self._open_backup_folder)
        self.share_action = QAction(self)
        self.share_action.triggered.connect(self.open_share_dialog)
        self.tools_menu.addAction(self.share_action)
        self.tools_menu.addSeparator()
        self.tools_menu.addAction(self.reload_action)
        self.tools_menu.addSeparator()
        self.tools_menu.addAction(self.game_reset_action)
        self.tools_menu.addAction(self.read_only_action)
        self.tools_menu.addSeparator()
        self.tools_menu.addAction(self.open_folder_action)
        self.tools_menu.addAction(self.open_backups_action)
        self.tools_menu.addSeparator()
        self.about_action = QAction(self)
        self.about_action.triggered.connect(self.show_about)
        self.tools_menu.addAction(self.about_action)
        self.tools_button.setMenu(self.tools_menu)
        row2.addWidget(self.tools_button)
        outer.addLayout(row2)
        return header

    # ============================================================== texts
    def _apply_texts(self) -> None:
        """Set every static text; called at start and after a language change."""
        tr = self.tr
        self.title_label.setText(tr("app.title"))
        self.file_label.setText(tr("file.picker_label"))
        self.search.setPlaceholderText(tr("toolbar.search_placeholder"))
        self.advanced_check.setText(tr("filter.advanced_mode"))
        self.vendor_check.setText(tr("filter.hide_other_vendors"))
        self.preset_label.setText(tr("toolbar.recommend_for"))
        self.hw_bar.refresh_texts()
        self.tools_button.setText(tr("toolbar.tools"))
        self.optimize_button.setText(tr("toolbar.optimize"))
        self.reload_action.setText(tr("toolbar.reload"))
        self.share_action.setText(tr("tools.share"))
        self.game_reset_action.setText(tr("tools.game_reset"))
        self.read_only_action.setText(tr("readonly.toggle"))
        self.read_only_action.setToolTip(tr("readonly.explain"))
        self.open_folder_action.setText(tr("tools.open_game_folder"))
        self.open_backups_action.setText(tr("backup.open_folder"))
        self.about_action.setText(tr("tools.about"))
        self.discard_button.setText(tr("toolbar.discard"))
        self.history_button.setText(tr("toolbar.history"))
        self.templates_button.setText(tr("toolbar.templates"))
        self.undo_button.setText(tr("toolbar.undo"))
        self.redo_button.setText(tr("toolbar.redo"))
        self.notice_show.setText(tr("notice.show"))
        self.notice_undo.setText(tr("notice.undo_game"))
        self.notice_dismiss.setToolTip(tr("notice.dismiss"))

        self.preset_combo.clear()
        self.preset_combo.addItem(tr("toolbar.preset_none"), "")
        for preset in self.knowledge.presets:
            self.preset_combo.addItem(localized(preset.label, tr.language), preset.id)
            self.preset_combo.setItemData(
                self.preset_combo.count() - 1,
                localized(preset.desc, tr.language),
                Qt.ItemDataRole.ToolTipRole,
            )
        index = self.preset_combo.findData(self.settings.preset)
        self.preset_combo.setCurrentIndex(max(index, 0))
        self._update_game_pill()
        self._update_dirty_state()

    def set_language(self, language: str) -> None:
        self.settings.language = language
        self.tr.set_language(language)

    def _on_language_changed(self, language: str) -> None:
        for button in self.language_group.buttons():
            button.setChecked(button.text().lower() == language)
        self._apply_texts()
        self._populate_file_combo()
        self._render_all()

    # ============================================================== files
    def _file_items(self) -> list[tuple[str, SettingsFileSet, str]]:
        """(label, fileset, tooltip) for the file combo."""
        items = []
        for loc in self._locations:
            fs = loc.fileset
            items.append((self._file_label(loc), fs, str(fs.directory / fs.stem)))
        for fs in self._extra_files:
            items.append((fs.stem, fs, str(fs.directory / fs.stem)))
        return items

    def _file_label(self, loc: ConfigLocation) -> str:
        if loc.scope is Scope.MACHINE:
            kind = self.tr("file.machine")
        else:
            # Steam/Battle.net ids are long; the last digits are enough to tell accounts apart.
            account = f"…{loc.account_id[-4:]}" if loc.account_id else ""
            key = "file.account_pm" if loc.kind is FileKind.PROFILE_PM else "file.account"
            kind = self.tr(key, account=account)
        return f"{loc.title_name} · {kind}"

    def is_account_file(self) -> bool:
        """True when the open file is an account profile (sensitivity, FOV...)."""
        if self.session is None:
            return False
        info = classify_stem(self.session.fileset.stem)
        return info is not None and info[0] is Scope.ACCOUNT

    def _populate_file_combo(self) -> None:
        self.file_combo.blockSignals(True)
        self.file_combo.clear()
        for label, fileset, tooltip in self._file_items():
            self.file_combo.addItem(label, fileset)
            self.file_combo.setItemData(
                self.file_combo.count() - 1, tooltip, Qt.ItemDataRole.ToolTipRole
            )
        self.file_combo.addItem(self.tr("file.open_other"), OPEN_OTHER)
        self._select_current_file_in_combo()
        self.file_combo.blockSignals(False)

    def _select_current_file_in_combo(self) -> None:
        if self.session is None:
            self.file_combo.setCurrentIndex(-1)
            return
        for i in range(self.file_combo.count()):
            if self.file_combo.itemData(i) == self.session.fileset:
                self.file_combo.setCurrentIndex(i)
                return

    def _open_initial_file(self) -> None:
        candidates = [fs for _, fs, _ in self._file_items()]
        last = self.settings.last_file
        if last:
            try:
                last_set = SettingsFileSet.from_path(last)
                if last_set.exists():
                    if last_set not in candidates:
                        self._extra_files.append(last_set)
                        self._populate_file_combo()
                    candidates.insert(0, last_set)
            except WzceError:
                pass
        for fileset in candidates:
            if self.open_fileset(fileset):
                return
        self._render_all()

    def open_fileset(self, fileset: SettingsFileSet) -> bool:
        try:
            session = EditorSession(
                fileset, backup_manager=self._backup_manager, game_running=self._game_running_check
            )
        except (WzceError, OSError) as exc:
            self._show_message("error", self.tr("error.title"), self.tr("error.parse", error=exc))
            return False
        self.session = session
        self._disk_warning_shown = False
        self.settings.last_file = str(fileset.slots[0])
        self._select_current_file_in_combo()
        self._render_all()
        self.statusBar().showMessage(self.tr("status.loaded", file=fileset.stem), STATUS_TIMEOUT_MS)
        return True

    def _on_file_activated(self, index: int) -> None:
        data = self.file_combo.itemData(index)
        if self.session is not None and data == self.session.fileset:
            return
        if not self._confirm_leave():
            self._select_current_file_in_combo()
            return
        if data == OPEN_OTHER:
            path, _ = QFileDialog.getOpenFileName(
                self,
                self.tr("file.open_dialog_title"),
                str(self.session.fileset.directory) if self.session else "",
                self.tr("file.open_filter"),
            )
            if not path:
                self._select_current_file_in_combo()
                return
            try:
                fileset = SettingsFileSet.from_path(path)
            except WzceError as exc:
                self._show_message(
                    "error", self.tr("error.title"), self.tr("error.parse", error=exc)
                )
                self._select_current_file_in_combo()
                return
            if fileset not in [fs for _, fs, _ in self._file_items()]:
                self._extra_files.append(fileset)
            self.open_fileset(fileset)
            self._populate_file_combo()
            return
        if isinstance(data, SettingsFileSet) and not self.open_fileset(data):
            self._select_current_file_in_combo()

    def _confirm_leave(self) -> bool:
        """Before switching files / closing: handle unsaved changes. False = cancel."""
        if self.session is None or not self.session.is_dirty:
            return True
        choice = self._prompt_unsaved(len(self.session.pending_changes()))
        if choice == "save":
            return self.save(confirm=False)
        return choice == "discard"

    # ========================================================= navigation
    def _refresh_nav(self) -> None:
        tr = self.tr
        changed_by_group: dict[str, int] = {}
        groups_present: set[str] = set()
        if self.session is not None:
            changed = self.session.changed_ids()
            for setting in self.session.document:
                entry = self.knowledge.entry_for(setting)
                groups_present.add(entry.group)
                if setting.id in changed:
                    changed_by_group[entry.group] = changed_by_group.get(entry.group, 0) + 1

        def label(text: str, count: int) -> str:
            return f"{text}   ● {count}" if count else text

        self.nav.blockSignals(True)
        self.nav.clear()
        total_changed = sum(changed_by_group.values())
        entries = [
            (NAV_ALL, label(tr("nav.all"), 0)),
            (NAV_CHANGED, label(tr("nav.changed"), total_changed)),
        ]
        for group in self.knowledge.groups:
            if group.id in groups_present:
                entries.append(
                    (
                        group.id,
                        label(
                            localized(group.label, tr.language), changed_by_group.get(group.id, 0)
                        ),
                    )
                )
        for key, text in entries:
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.nav.addItem(item)
            if key == self._nav_key:
                self.nav.setCurrentItem(item)
        if self.nav.currentItem() is None and self.nav.count():
            self.nav.setCurrentRow(0)
            self._nav_key = self.nav.currentItem().data(Qt.ItemDataRole.UserRole)
        self.nav.blockSignals(False)

    def _on_nav_changed(self, current: QListWidgetItem | None, _previous: object) -> None:
        if current is None:
            return
        self._nav_key = current.data(Qt.ItemDataRole.UserRole)
        if self.search.text():
            self.search.blockSignals(True)
            self.search.clear()
            self.search.blockSignals(False)
        self._render_page()

    def _on_filter_changed(self) -> None:
        self.settings.advanced = self.advanced_check.isChecked()
        self.settings.hide_other_vendors = self.vendor_check.isChecked()
        self._render_page()

    def _on_preset_changed(self, _index: int) -> None:
        self.settings.preset = self.preset_combo.currentData() or ""
        self._render_page()

    # ============================================================== page
    def _visible_items(self) -> list[tuple[Setting, KnowledgeEntry]]:
        session = self.session
        assert session is not None
        changed = session.changed_ids()
        query = self.search.text().strip().lower()
        vendor = session.gpu_vendor if self.vendor_check.isChecked() else None
        advanced = self.advanced_check.isChecked()
        items: list[tuple[Setting, KnowledgeEntry]] = []
        for setting in session.document:
            entry = self.knowledge.entry_for(setting)
            if query:  # search looks everywhere, ignoring mode and vendor filters
                if self._matches(setting, entry, query):
                    items.append((setting, entry))
                continue
            if self._nav_key == NAV_CHANGED:
                if setting.id in changed:
                    items.append((setting, entry))
                continue
            if self._nav_key != NAV_ALL and entry.group != self._nav_key:
                continue
            hidden_by_mode = not advanced and (entry.advanced or "game_managed" in entry.flags)
            hidden_by_vendor = vendor is not None and entry.vendor not in (None, vendor)
            if (hidden_by_mode or hidden_by_vendor) and setting.id not in changed:
                continue
            items.append((setting, entry))
        items.sort(key=lambda it: self._sort_key(*it))
        return items

    def _matches(self, setting: Setting, entry: KnowledgeEntry, query: str) -> bool:
        haystack = " ".join(
            [setting.id, setting.description, *entry.label.values(), *entry.desc.values()]
        ).lower()
        return all(word in haystack for word in query.split())

    def _sort_key(self, setting: Setting, entry: KnowledgeEntry) -> tuple[int, int, int, int]:
        group_ids = [g.id for g in self.knowledge.groups]
        group_index = group_ids.index(entry.group) if entry.group in group_ids else len(group_ids)
        group = self.knowledge.group(entry.group) if entry.group in group_ids else None
        sub_ids = [s.id for s in group.subgroups] if group else []
        sub_index = sub_ids.index(entry.subgroup) if entry.subgroup in sub_ids else len(sub_ids)
        return (
            group_index,
            sub_index,
            self._entry_order.get(setting.id, 10**6),
            setting.line_index,
        )

    def _render_all(self) -> None:
        self._update_notice()
        self._refresh_system_checks()
        self._refresh_nav()
        self._render_page()
        self.changes_panel.refresh(self.session)
        self._update_status()
        self._update_dirty_state()

    def _render_page(self) -> None:
        tr = self.tr
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 20, 28, 28)
        layout.setSpacing(10)
        self.cards = {}

        if self.session is None:
            empty = QLabel(tr("file.none_found"))
            empty.setObjectName("emptyState")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(empty)
            open_button = QPushButton(tr("file.open_other"))
            open_button.clicked.connect(
                lambda: self._on_file_activated(self.file_combo.count() - 1)
            )
            layout.addWidget(open_button, 0, Qt.AlignmentFlag.AlignCenter)
            layout.addStretch()
            self._set_page(page)
            return

        query = self.search.text().strip()
        items = self._visible_items()
        if query:
            title_text = f"{tr('search.results')}: “{query}”"
        elif self._nav_key == NAV_ALL:
            title_text = tr("nav.all")
        elif self._nav_key == NAV_CHANGED:
            title_text = tr("nav.changed")
        else:
            title_text = localized(self.knowledge.group(self._nav_key).label, tr.language)
        title = QLabel(title_text)
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        subtitle = QLabel(tr("status.settings_count", count=len(items)))
        subtitle.setObjectName("pageSubtitle")
        layout.addWidget(subtitle)

        if not items:
            message = tr("filter.no_results", query=query) if query else tr("page.empty_filtered")
            empty = QLabel(message)
            empty.setObjectName("emptyState")
            layout.addWidget(empty)

        show_group_in_header = bool(query) or self._nav_key in (NAV_ALL, NAV_CHANGED)
        preset_id = self.preset_combo.currentData() or None
        preset_label = self.preset_combo.currentText() if preset_id else ""
        current_section: tuple[str, str | None] | None = None
        for setting, entry in items:
            section = (entry.group, entry.subgroup)
            if section != current_section:
                current_section = section
                layout.addWidget(self._section_header(entry, show_group_in_header))
            card = SettingCard(setting, entry, self.session, tr, preset_id, preset_label)
            card.value_edited.connect(self._on_value_edited)
            card.revert_requested.connect(self._on_revert)
            self.cards[setting.id] = card
            layout.addWidget(card)
        layout.addStretch()
        self._set_page(page)

    def _section_header(self, entry: KnowledgeEntry, with_group: bool) -> QLabel:
        lang = self.tr.language
        group = self.knowledge.group(entry.group)
        sub = group.subgroup(entry.subgroup) if entry.subgroup else None
        sub_text = localized(sub.label, lang) if sub else self.tr("nav.other")
        text = f"{localized(group.label, lang)} · {sub_text}" if with_group else sub_text
        header = QLabel(text.upper())
        header.setObjectName("subgroupTitle")
        return header

    def _page_key(self) -> tuple[object, ...]:
        """Identity of what the card page shows. Same key = same list of cards."""
        fileset = self.session.fileset if self.session else None
        return (
            fileset,
            self._nav_key,
            self.search.text().strip(),
            self.advanced_check.isChecked(),
            self.vendor_check.isChecked(),
        )

    def _set_page(self, page: QWidget) -> None:
        # Rebuilding the same view (after save, undo, reload, language switch...)
        # must not throw the user back to the top of a long list: keep the scroll
        # offset. A different view (other category, search, file) starts at the top.
        key = self._page_key()
        bar = self.scroll.verticalScrollBar()
        offset = bar.value() if key == getattr(self, "_shown_page_key", None) else 0
        self._shown_page_key = key

        old = self.scroll.takeWidget()
        self.scroll.setWidget(page)
        if old is not None:
            old.deleteLater()
        if offset:
            # The new page gets its final height only after the scroll area lays it
            # out, so apply now (usually enough) and once more after the event loop.
            page.layout().activate()
            bar.setValue(offset)
            QTimer.singleShot(0, page, lambda: bar.setValue(offset))

    # ============================================================ editing
    def _on_value_edited(self, setting_id: str, value: object) -> None:
        if self.session is None:
            return
        card = self.cards.get(setting_id)
        try:
            self.session.set_value(
                setting_id, value, allow_read_only=card.unlocked if card else False
            )
        except ValidationError as exc:
            if card is not None:
                card.refresh()
                card.show_error(str(exc))
            self.statusBar().showMessage(self.tr("error.validation", error=exc), STATUS_TIMEOUT_MS)
            return
        self._after_change(setting_id)

    def _on_revert(self, setting_id: str) -> None:
        if self.session is None:
            return
        self.session.revert(setting_id)
        self._after_change(setting_id)

    def _after_change(self, setting_id: str) -> None:
        self._after_changes([setting_id])

    def _after_changes(self, setting_ids: list[str]) -> None:
        """Refresh everything that depends on the working copy after values changed."""
        assert self.session is not None
        for setting_id in setting_ids:
            card = self.cards.get(setting_id)
            if card is not None:
                card.refresh()
        self._refresh_nav()
        self.changes_panel.refresh(self.session)
        self._update_dirty_state()
        if self._nav_key == NAV_CHANGED and not self.search.text():
            # A reverted setting must leave the "Changed" view; defer the rebuild
            # because we may be inside the card's own signal handler.
            QTimer.singleShot(0, self, self._render_page)

    def _discard_all(self) -> None:
        # No confirmation needed any more: discarding is a single undoable step.
        if self.session is None or not self.session.is_dirty:
            return
        touched = self.session.discard_all()
        self._after_changes(touched)
        self.statusBar().showMessage(self.tr("status.discarded"), STATUS_TIMEOUT_MS)

    # ========================================================== undo/redo
    def undo(self) -> None:
        if self.session is not None:
            self._show_undo_result(self.session.undo())

    def redo(self) -> None:
        if self.session is not None:
            self._show_undo_result(self.session.redo())

    def _show_undo_result(self, setting_ids: list[str]) -> None:
        if not setting_ids:
            return
        self._after_changes(setting_ids)
        if len(setting_ids) == 1 and setting_ids[0] not in self.cards:
            # Undoing something on another page: take the user there.
            self.navigate_to(setting_ids[0])

    def _command_text(self, setting_ids: list[str]) -> str:
        assert self.session is not None
        if len(setting_ids) == 1 and setting_ids[0] in self.session.document:
            setting = self.session.document.get(setting_ids[0])
            return localized(self.knowledge.entry_for(setting).label, self.tr.language)
        return self.tr("undo.many", count=len(setting_ids))

    # ============================================================ history
    def _user_values(self, values: dict[str, str]) -> dict[str, str]:
        """Drop settings the game manages itself before restoring old values.

        Putting back an old driver version, window position or detected-hardware
        value would only confuse the game, so history restores skip them.
        """
        assert self.session is not None
        document = self.session.document
        result = {}
        for setting_id, raw in values.items():
            if setting_id not in document:
                continue
            setting = document.get(setting_id)
            if setting.read_only or "game_managed" in self.knowledge.entry_for(setting).flags:
                continue
            result[setting_id] = raw
        return result

    def _apply_restored_values(self, values: dict[str, str]) -> None:
        assert self.session is not None
        touched = self.session.apply_raw_values(self._user_values(values))
        if touched:
            self._after_changes(touched)
            message = self.tr("history.applied", count=len(touched))
        else:
            message = self.tr("history.nothing_to_apply")
        self.statusBar().showMessage(message, STATUS_TIMEOUT_MS)

    def open_history(self, entry_id: str | None = None) -> None:
        if self.session is None:
            return
        dialog = HistoryDialog(
            self.session, self.knowledge, self.tr, select_entry_id=entry_id, parent=self
        )
        if self._exec_dialog(dialog) and dialog.result_values:
            self._apply_restored_values(dialog.result_values)

    # ========================================================== optimizer
    @property
    def hardware(self) -> HardwareInfo:
        """Detected once per window (takes a few ms); GPU name comes from the file."""
        if self._hardware is None:
            self._hardware = self._hardware_provider(
                self.session.original if self.session else None
            )
        return self._hardware

    def open_optimizer(self) -> None:
        if self.session is None:
            return
        preset = self.preset_combo.currentData() or Goal.COMPETITIVE.value
        dialog = OptimizerDialog(
            self.session,
            self.knowledge,
            self.tr,
            self.hardware,
            goal=Goal(preset),
            hints=self.system_hints(),
            parent=self,
        )
        if not self._exec_dialog(dialog) or not dialog.result_values:
            return
        touched = self.session.apply_raw_values(dialog.result_values, kind=CommandKind.BULK)
        if touched:
            self._after_changes(touched)
        self.statusBar().showMessage(
            self.tr("optimizer.applied", count=len(touched)), STATUS_TIMEOUT_MS
        )

    # ===================================================== system / checks
    def _on_system_info(self, info: SystemInfo) -> None:
        self.system_info = info
        if info.nvidia is not None and info.nvidia.rebar_enabled is not None:
            self._hardware = dataclasses.replace(self.hardware, rebar=info.nvidia.rebar_enabled)
        self._refresh_system_checks()

    def _machine_document(self) -> ConfigDocument | None:
        """Machine settings of the current title (checks need driver / GPU / ReBAR values)."""
        session = self.session
        if session is None:
            return None
        if not self.is_account_file():
            return session.original
        info = classify_stem(session.fileset.stem)
        title = info[2] if info else None
        for loc in self._locations:
            if loc.scope is Scope.MACHINE and loc.title_code == title:
                try:
                    return loc.fileset.load().document
                except (WzceError, OSError):
                    return None
        return None

    def _refresh_system_checks(self) -> None:
        if self.system_info is None:
            return
        self.system_checks = evaluate_checks(
            self.system_info, self.hardware, self._machine_document()
        )
        self.hw_bar.set_data(
            bar_items(self.system_info, self.hardware, self.tr), len(warnings(self.system_checks))
        )

    def _on_hw_bar_collapsed(self, collapsed: bool) -> None:
        self.settings.hardware_bar_collapsed = collapsed

    def system_hints(self) -> list[str]:
        """Titles of serious system problems, shown in the optimizer."""
        return [
            check_title(check, self.tr).split("  ·  ")[0]
            for check in self.system_checks
            if check.status is Status.WARN and check.severity is Severity.HIGH
        ]

    def open_system_dialog(self, show_checks: bool = False) -> None:
        if self.system_info is None:
            return
        dialog = SystemDialog(
            self.system_info,
            self.hardware,
            self.system_checks,
            self.tr,
            show_checks=show_checks,
            parent=self,
        )
        chosen: list[str] = []

        def on_action(action: str) -> None:
            if action.startswith("setting:"):
                chosen.append(action.removeprefix("setting:"))
                dialog.accept()
            else:
                self._open_external(action)

        dialog.action_requested.connect(on_action)
        self._exec_dialog(dialog)
        if chosen:
            self.navigate_to(chosen[0])

    def _open_external(self, target: str) -> None:
        """Open a Windows settings page (ms-settings:...) or a web page."""
        QDesktopServices.openUrl(QUrl(target))

    # ============================================================== share
    def open_share_dialog(self) -> None:
        """Readable summary of the current settings (Markdown/JSON) for sharing."""
        session = self.session
        if session is None:
            return
        code = session.fileset.title_code
        dialog = ShareDialog(
            session.document,
            self.knowledge,
            self.tr,
            game=TITLE_NAMES.get(code or "", code or session.fileset.stem),
            title_code=code,
            system_info=self.system_info,
            hardware=self.hardware,
            has_unsaved_changes=session.is_dirty,
            # Account files (sensitivity, FOV, audio) are shared as a whole.
            default_groups=[g.id for g in self.knowledge.groups]
            if self.is_account_file()
            else None,
            # Leave out other vendors' options (e.g. AMD Anti-Lag on an NVIDIA PC).
            gpu_vendor=session.gpu_vendor or self.hardware.gpu_vendor,
            parent=self,
        )
        self._exec_dialog(dialog)

    # ============================================================== tools
    def request_game_reset(self) -> None:
        """Set RecommendedSet=false: the game re-applies its own recommendations on start."""
        session = self.session
        if session is None:
            return
        if "RecommendedSet@0" not in session.document:
            self._show_message("warning", self.tr("error.title"), self.tr("reset.not_available"))
            return
        if not self._ask(self.tr("reset.recommended_title"), self.tr("reset.recommended_text")):
            return
        session.set_value("RecommendedSet@0", False)
        self._after_changes(["RecommendedSet@0"])
        self.statusBar().showMessage(self.tr("status.game_reset"), STATUS_TIMEOUT_MS)

    def set_files_read_only(self, read_only: bool) -> None:
        session = self.session
        if session is None:
            return
        if read_only and not self._ask(self.tr("readonly.toggle"), self.tr("readonly.explain")):
            self.read_only_action.setChecked(False)
            return
        try:
            session.fileset.set_read_only(read_only)
        except OSError as exc:
            self._show_message(
                "error", self.tr("error.title"), self.tr("error.readonly", error=exc)
            )
        self.read_only_action.setChecked(session.fileset.is_read_only())
        self._update_status()
        key = "status.readonly_on" if session.fileset.is_read_only() else "status.readonly_off"
        self.statusBar().showMessage(self.tr(key), STATUS_TIMEOUT_MS)

    def show_about(self) -> None:
        text = "\n\n".join(
            [
                self.tr("about.text", version=__version__, data_dir=str(app_data_dir())),
                self.tr("about.disclaimer"),
            ]
        )
        self._show_message("info", self.tr("tools.about"), text)

    def _open_game_folder(self) -> None:
        if self.session is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.session.fileset.directory)))

    def _open_backup_folder(self) -> None:
        folder = self.session.backup_manager.root if self.session else None
        if folder is not None:
            folder.mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    # ========================================================== templates
    def open_templates(self) -> None:
        if self.session is None:
            return
        dialog = TemplatesDialog(
            self.session, self.knowledge, self.tr, self.template_store, parent=self
        )
        if not self._exec_dialog(dialog) or not dialog.result_values:
            return
        # Values come from plan_template(): already validated for this file and free
        # of hardware/managed settings, so they can go straight into the session.
        touched = self.session.apply_raw_values(dialog.result_values, kind=CommandKind.BULK)
        if touched:
            self._after_changes(touched)
        self.statusBar().showMessage(
            self.tr("templates.applied", count=len(touched), name=dialog.result_name),
            STATUS_TIMEOUT_MS,
        )

    # ===================================================== game-change notice
    def _build_notice(self) -> QWidget:
        self.notice = QFrame()
        self.notice.setObjectName("notice")
        layout = QHBoxLayout(self.notice)
        layout.setContentsMargins(16, 8, 12, 8)
        self.notice_text = QLabel()
        self.notice_text.setWordWrap(True)
        layout.addWidget(self.notice_text, 1)
        self.notice_show = QPushButton()
        self.notice_show.clicked.connect(self._on_notice_show)
        layout.addWidget(self.notice_show)
        self.notice_undo = QPushButton()
        self.notice_undo.clicked.connect(self._on_notice_undo)
        layout.addWidget(self.notice_undo)
        self.notice_dismiss = QPushButton("✕")
        self.notice_dismiss.setProperty("variant", "ghost")
        self.notice_dismiss.clicked.connect(self._dismiss_notice)
        layout.addWidget(self.notice_dismiss)
        self.notice.hide()
        return self.notice

    def _notice_entry(self) -> HistoryEntry | None:
        return self.session.external_change if self.session is not None else None

    def _update_notice(self) -> None:
        """Show the banner when the game changed settings the user cares about."""
        entry = self._notice_entry()
        if entry is None:
            self.notice.hide()
            return
        meaningful = self._user_values(entry.old_values())
        if not meaningful:
            # Only game-managed values changed (driver version, window...): stay quiet;
            # the entry is still in the history.
            self.session.acknowledge_external_change()
            self.notice.hide()
            return
        names = [self._command_text([sid]) for sid in list(meaningful)[:3]]
        if len(meaningful) > 3:
            names.append("…")
        self.notice_text.setText(
            self.tr("notice.game_changed", count=len(meaningful), names=", ".join(names))
        )
        self.notice.show()

    def _on_notice_show(self) -> None:
        entry = self._notice_entry()
        if entry is not None:
            self.open_history(entry.id)

    def _on_notice_undo(self) -> None:
        entry = self._notice_entry()
        if entry is None:
            return
        self._apply_restored_values(entry.old_values())
        self._dismiss_notice()
        self.statusBar().showMessage(self.tr("notice.undone"), STATUS_TIMEOUT_MS)

    def _dismiss_notice(self) -> None:
        if self.session is not None:
            self.session.acknowledge_external_change()
        self.notice.hide()

    def _reload(self) -> None:
        if self.session is None or not self._confirm_leave():
            return
        try:
            self.session.reload()
        except (WzceError, OSError) as exc:
            self._show_message("error", self.tr("error.title"), self.tr("error.parse", error=exc))
            return
        self._disk_warning_shown = False
        self._render_all()
        self.statusBar().showMessage(self.tr("status.reloaded"), STATUS_TIMEOUT_MS)

    def navigate_to(self, setting_id: str) -> None:
        """Show the category containing ``setting_id`` and scroll its card into view."""
        if self.session is None or setting_id not in self.session.document:
            return
        entry = self.knowledge.entry_for(self.session.document.get(setting_id))
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self._nav_key = entry.group
        # The user explicitly asked for this setting: lift filters that would hide it.
        for check, hides, wanted in (
            (self.advanced_check, entry.advanced or "game_managed" in entry.flags, True),
            (self.vendor_check, entry.vendor not in (None, self.session.gpu_vendor), False),
        ):
            if hides and check.isChecked() != wanted:
                check.blockSignals(True)
                check.setChecked(wanted)
                check.blockSignals(False)
        self.settings.advanced = self.advanced_check.isChecked()
        self.settings.hide_other_vendors = self.vendor_check.isChecked()
        self._refresh_nav()
        self._render_page()
        # Look the card up again when the timer fires: the page may be rebuilt
        # in between, and a captured card reference would point to a deleted widget.
        QTimer.singleShot(30, self, lambda: self._flash(setting_id))

    def _flash(self, setting_id: str) -> None:
        card = self.cards.get(setting_id)
        if card is None:
            return
        self.scroll.ensureWidgetVisible(card, 0, 120)
        card.setProperty("flash", True)
        repolish(card)

        def clear() -> None:
            card.setProperty("flash", False)
            repolish(card)

        # Context-object form: Qt cancels the timer if the card is destroyed first.
        QTimer.singleShot(1200, card, clear)

    # =============================================================== save
    def save(self, confirm: bool = True) -> bool:
        """Save pending changes. Returns True when the files were written."""
        session = self.session
        if session is None:
            return False
        tr = self.tr
        count = len(session.pending_changes())
        if count == 0 and session.loaded.slots_in_sync:
            self.statusBar().showMessage(tr("save.nothing"), STATUS_TIMEOUT_MS)
            return False
        if session.game_running():
            self._show_message(
                "warning", tr("save.game_running_title"), tr("save.game_running_text")
            )
            return False
        # Asked even when ``confirm`` is False: overwriting the game's own changes
        # is a different decision than "save my edits".
        if session.disk_changed() and not self._ask(
            tr("save.confirm_title"), tr("save.disk_changed")
        ):
            return False
        if confirm and not self._ask(
            tr("save.confirm_title"), tr("save.confirm_text", count=count)
        ):
            return False
        try:
            result = session.save()
        except GameRunningError:
            self._show_message(
                "warning", tr("save.game_running_title"), tr("save.game_running_text")
            )
            return False
        except (WzceError, OSError) as exc:
            self._show_message("error", tr("error.title"), tr("save.failed", error=exc))
            return False
        message = tr("status.saved", count=count)
        if result.read_only_preserved:
            message += " " + tr("save.read_only_note")
        self._disk_warning_shown = False
        self._render_all()
        self.statusBar().showMessage(message, STATUS_TIMEOUT_MS)
        return True

    # ============================================================= status
    def _poll(self) -> None:
        """Periodic check: is the game running, did the file change on disk?"""
        try:
            running = bool(self._game_running_check())
        except Exception:  # psutil hiccups must never break the UI
            running = False
        if running != self._game_running:
            self._game_running = running
            self._update_game_pill()
            self._update_dirty_state()
        session = self.session
        if session is None or not session.disk_changed():
            return
        if not session.is_dirty:
            try:
                session.reload()
            except (WzceError, OSError):
                return  # the game may be mid-write; try again next tick
            self._render_all()
            self.statusBar().showMessage(self.tr("status.reloaded"), STATUS_TIMEOUT_MS)
        elif not self._disk_warning_shown:
            self._disk_warning_shown = True
            self.statusBar().showMessage(self.tr("status.changed_on_disk_dirty"), 0)

    def _update_game_pill(self) -> None:
        running = self._game_running
        self.game_pill.setText(self.tr("status.game_running" if running else "status.game_closed"))
        self.game_pill.setProperty("running", running)
        repolish(self.game_pill)

    def _update_status(self) -> None:
        session = self.session
        if session is None:
            for label in (self.status_file, self.status_count, self.status_gpu):
                label.setText("")
            return
        fs = session.fileset
        layout = self.tr("file.layout_ab" if fs.is_ab else "file.layout_single")
        read_only = f" · {self.tr('file.read_only')}" if fs.is_read_only() else ""
        self.status_file.setText(f"{fs.directory / fs.stem} · {layout}{read_only}")
        self.status_count.setText(self.tr("status.settings_count", count=len(session.document)))
        vendor = session.gpu_vendor
        self.status_gpu.setText(self.tr("status.gpu", vendor=vendor.upper()) if vendor else "")

    def _update_dirty_state(self) -> None:
        tr = self.tr
        session = self.session
        count = len(session.pending_changes()) if session else 0
        needs_sync = bool(session) and not session.loaded.slots_in_sync
        self.save_button.setText(
            tr("toolbar.save_count", count=count) if count else tr("toolbar.save")
        )
        self.save_button.setEnabled((count > 0 or needs_sync) and not self._game_running)
        self.save_button.setToolTip(tr("save.game_running_text") if self._game_running else "")
        self.discard_button.setEnabled(count > 0)
        for action in (
            self.share_action,
            self.reload_action,
            self.game_reset_action,
            self.read_only_action,
            self.open_folder_action,
        ):
            action.setEnabled(session is not None)
        self.optimize_button.setEnabled(session is not None)
        self.read_only_action.setChecked(bool(session) and session.fileset.is_read_only())
        self.history_button.setEnabled(session is not None)
        self.templates_button.setEnabled(session is not None)
        stack = session.undo_stack if session else None
        undo_cmd = stack.peek_undo() if stack else None
        redo_cmd = stack.peek_redo() if stack else None
        self.undo_button.setEnabled(undo_cmd is not None)
        self.redo_button.setEnabled(redo_cmd is not None)
        self.undo_button.setToolTip(
            tr("undo.tooltip", what=self._command_text(undo_cmd.setting_ids))
            if undo_cmd
            else tr("undo.nothing")
        )
        self.redo_button.setToolTip(
            tr("redo.tooltip", what=self._command_text(redo_cmd.setting_ids))
            if redo_cmd
            else tr("redo.nothing")
        )
        self.title_label.setProperty("dirty", count > 0)
        repolish(self.title_label)
        name = session.fileset.stem if session else ""
        self.setWindowTitle(
            f"{'● ' if count else ''}{name} — {tr('app.title')}" if name else tr("app.title")
        )

    # ============================================================ dialogs
    def _ask(self, title: str, text: str) -> bool:
        buttons = QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        box = QMessageBox(QMessageBox.Icon.Question, title, text, buttons, self)
        box.button(QMessageBox.StandardButton.Yes).setText(self.tr("dialog.yes"))
        box.button(QMessageBox.StandardButton.No).setText(self.tr("dialog.no"))
        return box.exec() == QMessageBox.StandardButton.Yes

    def _prompt_unsaved(self, count: int) -> str:
        """Returns "save", "discard" or "cancel"."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(self.tr("unsaved.title"))
        box.setText(self.tr("unsaved.text", count=count))
        save = box.addButton(self.tr("dialog.save"), QMessageBox.ButtonRole.AcceptRole)
        discard = box.addButton(self.tr("dialog.discard"), QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(self.tr("dialog.cancel"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        return "save" if clicked is save else "discard" if clicked is discard else "cancel"

    def _exec_dialog(self, dialog: QDialog) -> bool:
        """Run a modal dialog; True when accepted. Replaced in tests."""
        return dialog.exec() == QDialog.DialogCode.Accepted

    def _show_message(self, level: str, title: str, text: str) -> None:
        icon = {
            "error": QMessageBox.Icon.Critical,
            "warning": QMessageBox.Icon.Warning,
        }.get(level, QMessageBox.Icon.Information)
        QMessageBox(icon, title, text, QMessageBox.StandardButton.Ok, self).exec()

    # ======================================================= window state
    def _restore_window_state(self) -> None:
        geometry = self.settings.window_state("geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        splitter = self.settings.window_state("splitter")
        if splitter is not None:
            self.splitter.restoreState(splitter)

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._confirm_leave():
            event.ignore()
            return
        self.settings.set_window_state("geometry", self.saveGeometry())
        self.settings.set_window_state("splitter", self.splitter.saveState())
        self.settings.sync()
        self._timer.stop()
        self.tr.remove_listener(self._on_language_changed)
        event.accept()
