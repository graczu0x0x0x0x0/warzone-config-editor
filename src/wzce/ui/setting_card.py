"""One card per setting: title, badges, description, editor, recommendation, revert.

The card never writes to the session itself. It emits ``value_edited`` /
``revert_requested`` and the main window applies them (central error handling,
one place that refreshes the changes panel). After every change the window
calls ``refresh()`` so the card re-reads its state from the session.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..core.diff import same_value
from ..core.display import display_value
from ..core.errors import ValidationError
from ..core.i18n import Translator
from ..core.knowledge import IMPACT_DIMENSIONS, IMPACT_MAX, KnowledgeEntry, localized
from ..core.model import Setting
from ..core.session import EditorSession
from .editors import ValueEditor, create_editor
from .theme import repolish


def make_chip(text: str, kind: str = "", tooltip: str = "") -> QLabel:
    chip = QLabel(text)
    chip.setObjectName("chip")
    if kind:
        chip.setProperty("kind", kind)
    if tooltip:
        chip.setToolTip(tooltip)
    return chip


class SettingCard(QFrame):
    value_edited = Signal(str, object)  # setting id, new value
    revert_requested = Signal(str)  # setting id

    def __init__(
        self,
        setting: Setting,
        entry: KnowledgeEntry,
        session: EditorSession,
        tr: Translator,
        preset_id: str | None,
        preset_label: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.setting_id = setting.id
        self.entry = entry
        self._session = session
        self._tr = tr
        self._preset_id = preset_id
        self._preset_label = preset_label
        self._unlocked = False
        lang = tr.language

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 14, 12)
        root.setSpacing(6)

        # --- title row ----------------------------------------------------
        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        title = QLabel(localized(entry.label, lang))
        title.setObjectName("cardTitle")
        title_row.addWidget(title)
        # The original name from the game file, so users can match it with guides,
        # forum posts or the file itself. Selectable to allow copying.
        self.key_label = QLabel(f"({setting.id})")
        self.key_label.setObjectName("cardKey")
        self.key_label.setToolTip(tr("card.technical_key"))
        self.key_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        title_row.addWidget(self.key_label, 0, Qt.AlignmentFlag.AlignBaseline)
        title_row.addStretch()
        for chip in self._chips(setting):
            title_row.addWidget(chip)
        root.addLayout(title_row)

        # --- description ----------------------------------------------------
        desc_text = localized(entry.desc, lang)
        if desc_text:
            desc = QLabel(desc_text)
            desc.setObjectName("cardDesc")
            desc.setWordWrap(True)
            desc.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            root.addWidget(desc)

        # --- editor row -------------------------------------------------------
        editor_row = QHBoxLayout()
        editor_row.setSpacing(8)
        self.editor: ValueEditor = create_editor(setting, entry, tr)
        self.editor.edited.connect(lambda value: self.value_edited.emit(self.setting_id, value))
        editor_row.addWidget(self.editor, 1)
        self.unlock_button = QPushButton(tr("card.unlock"))
        self.unlock_button.setProperty("variant", "link")
        self.unlock_button.clicked.connect(self._unlock)
        editor_row.addWidget(self.unlock_button)
        self.revert_button = QPushButton("↺")
        self.revert_button.setProperty("variant", "ghost")
        self.revert_button.setToolTip(tr("card.reset"))
        self.revert_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.revert_button.clicked.connect(lambda: self.revert_requested.emit(self.setting_id))
        editor_row.addWidget(self.revert_button)
        root.addLayout(editor_row)

        # --- footer: recommendation and the value before the change -----------
        footer = QHBoxLayout()
        footer.setSpacing(8)
        self.recommend_label = QLabel()
        self.recommend_label.setObjectName("cardRecommend")
        if entry.tip:
            self.recommend_label.setToolTip(localized(entry.tip, lang))
        footer.addWidget(self.recommend_label)
        self.apply_recommended = QPushButton(tr("card.apply_recommended"))
        self.apply_recommended.setProperty("variant", "link")
        self.apply_recommended.setCursor(Qt.CursorShape.PointingHandCursor)
        self.apply_recommended.clicked.connect(self._apply_recommended)
        footer.addWidget(self.apply_recommended)
        footer.addStretch()
        self.original_label = QLabel()
        self.original_label.setObjectName("cardOriginal")
        footer.addWidget(self.original_label)
        root.addLayout(footer)

        self._recommended_raw = self._compute_recommended_raw(setting)
        self.refresh()

    # ------------------------------------------------------------------ chips
    def _chips(self, setting: Setting) -> list[QLabel]:
        tr, entry = self._tr, self.entry
        chips: list[QLabel] = []
        if not entry.known:
            chips.append(make_chip(tr("card.new_badge"), "new", tr("card.new_tooltip")))
        if setting.read_only:
            chips.append(make_chip("🔒", "lock", tr("card.read_only")))
        if entry.vendor:
            chips.append(
                make_chip(entry.vendor.upper(), entry.vendor, tr(f"card.vendor_{entry.vendor}"))
            )
        if entry.hardware_specific:
            chips.append(make_chip("PC", "hw", tr("card.hardware_specific")))
        for dim, level in entry.impact.as_dict().items():
            if level <= 0:
                continue
            dots = "●" * level + "○" * (IMPACT_MAX - level)
            name = tr(f"impact.{dim}")
            tip = f"{tr('impact.title')} - {name}: {tr(f'impact.level_{level}')}"
            chips.append(make_chip(f"{name} {dots}", "", tip))
        assert set(entry.impact.as_dict()) <= set(IMPACT_DIMENSIONS)
        return chips

    # -------------------------------------------------------- recommendation
    def _compute_recommended_raw(self, setting: Setting) -> str | None:
        if self._preset_id is None:
            return None
        value = self.entry.recommend.get(self._preset_id)
        if value is None:
            return None
        try:
            return setting.format_value(value)
        except ValidationError:
            return None  # recommendation not valid for this title (e.g. DLAA in cod26)

    def _apply_recommended(self) -> None:
        if self._recommended_raw is not None:
            self.value_edited.emit(self.setting_id, self._recommended_raw)

    def _unlock(self) -> None:
        self._unlocked = True
        self.refresh()

    @property
    def unlocked(self) -> bool:
        return self._unlocked

    # ---------------------------------------------------------------- refresh
    def refresh(self) -> None:
        """Re-read value and changed state from the session."""
        tr = self._tr
        setting = self._session.document.get(self.setting_id)
        self.editor.set_raw(setting.raw_value)
        self.editor.set_error(None)

        locked = setting.read_only and not self._unlocked
        self.editor.setEnabled(not locked)
        self.unlock_button.setVisible(locked)

        changed = self._session.is_changed(self.setting_id)
        self.setProperty("changed", changed)
        repolish(self)
        self.revert_button.setVisible(changed)
        if changed:
            before = display_value(
                self._session.original_raw(self.setting_id), setting, self.entry, tr
            )
            self.original_label.setText(tr("card.original", value=before))
        self.original_label.setVisible(changed)

        if self._recommended_raw is not None:
            shown = display_value(self._recommended_raw, setting, self.entry, tr)
            matches = same_value(self._recommended_raw, setting.raw_value)
            prefix = "✓ " if matches else ""
            self.recommend_label.setText(
                prefix + tr("card.recommended", preset=self._preset_label, value=shown)
            )
            self.recommend_label.setProperty("match", matches)
            self.recommend_label.setVisible(True)
            self.apply_recommended.setVisible(not matches and not locked)
        elif self._preset_id and self.entry.rule:
            self.recommend_label.setText(tr("card.recommended_rule"))
            self.recommend_label.setProperty("match", False)
            self.recommend_label.setVisible(True)
            self.apply_recommended.setVisible(False)
        else:
            self.recommend_label.setVisible(False)
            self.apply_recommended.setVisible(False)
        repolish(self.recommend_label)

    def show_error(self, message: str) -> None:
        self.editor.set_error(message)
